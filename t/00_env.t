#!/usr/bin/perl
use strict;
use warnings;
use Test::More;

my $home  = $ENV{HOME};
my $py    = "$home/micromamba/envs/dl_wm/bin/python";
my $ytdlp = "$home/micromamba/envs/dl_wm/bin/yt-dlp";
my $repo  = "$home/repos/dl_wm";

sub run_capture {
    my @cmd = @_;
    open(my $fh, '-|', @cmd) or return (127, '');
    local $/;
    my $out = <$fh>;
    close $fh;
    return ($? >> 8, defined $out ? $out : '');
}

ok(-f $py && -x $py, 'python exists and is executable');

my ($rc, $out) = run_capture($py, '-V');
my $ver = ($out =~ /Python\s+(\S+)/) ? $1 : '';
ok($rc == 0 && $ver =~ /^3\.10\./,
   'python version is 3.10.x');
diag("python version: " . ($ver eq '' ? 'unknown' : $ver));

($rc, $out) = run_capture($py, '-c', 'import yt_dlp; print(yt_dlp.version.__version__)');
chomp $out;
ok($rc == 0, 'import yt_dlp works');
diag("yt_dlp module version: $out") if $rc == 0;

($rc, $out) = run_capture($ytdlp, '--version');
chomp $out;
ok($rc == 0 && $out ne '', 'yt-dlp --version works');
diag("yt-dlp binary version: $out") if $out ne '';

my ($grc, $head) = run_capture('git', '-C', $repo, 'rev-parse', 'HEAD');
chomp $head;
my ($arc) = run_capture('git', '-C', $repo, 'merge-base', '--is-ancestor', '651563f', 'HEAD');
ok($grc == 0 && $arc == 0,
   'repo HEAD contains 651563f (environment.yml pin)');
diag("HEAD: $head") unless $grc == 0 && $arc == 0;

done_testing();
