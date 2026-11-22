#!/usr/bin/perl
use strict;
use warnings;
use Test::More;
use Digest::SHA;
use POSIX qw(strftime);

my $home   = $ENV{HOME};
my $ytdlp  = "$home/micromamba/envs/dl_wm/bin/yt-dlp";
my $cookie = "$home/repos/dl_wm/conf/instagram.cookies.haddamgoel.txt";
my $outdir = "$home/dl_wm_outputs/ghost_soldier";
my $url    = 'https://www.instagram.com/p/DfnnH-uF5Aj/';
my $id     = 'DfnnH-uF5Aj';
my $log    = "$outdir/yt_dlp_download.log";
my $report = "$outdir/report.txt";

mkdir $outdir unless -d $outdir;

my @args = ('--cookies', $cookie,
            '-o', "$outdir/%(id)s.%(ext)s",
            $url);

my $rc;
{
    my $pid = fork();
    die "fork: $!" unless defined $pid;
    if ($pid == 0) {
        open STDOUT, '>', $log or exit 126;
        open STDERR, '>&', \*STDOUT or exit 126;
        exec { $ytdlp } $ytdlp, @args;
        exit 127;
    }
    waitpid($pid, 0);
    $rc = $? >> 8;
}
ok($rc == 0, 'yt-dlp download exit 0');
diag("exit=$rc; see $log") unless $rc == 0;

my @files = grep { -f $_ && -s $_ } glob("$outdir/$id*");
my $file  = @files ? $files[0] : undef;
ok(@files && -s $file, 'non-empty output file exists');
diag("no non-empty $id* file in $outdir") unless @files;

my ($fname, $bytes, $sha, $sha_ok) = ('N/A', 'N/A', 'N/A', 0);
if ($file) {
    ($fname) = $file =~ m{([^/]+)$};
    $bytes   = -s $file;
    $sha     = Digest::SHA->new(256)->addfile($file)->hexdigest;
    $sha_ok  = ($sha =~ /^[0-9a-f]{64}$/) ? 1 : 0;
}
ok($sha_ok, 'sha256 computed');
diag("filename=$fname bytes=$bytes sha256=$sha") if $sha_ok;

my $date = strftime('%Y-%m-%d %H:%M:%S', localtime);
my $r_ok = 0;
if (open(my $rf, '>', $report)) {
    print $rf "URL: $url\n";
    print $rf "date: $date\n";
    print $rf "exit_code: $rc\n";
    print $rf "filename: $fname\n";
    print $rf "bytes: $bytes\n";
    print $rf "sha256: $sha\n";
    close $rf;
    $r_ok = (-s $report) ? 1 : 0;
}
ok($r_ok, 'report.txt written');

done_testing();
