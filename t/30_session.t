#!/usr/bin/perl
use strict;
use warnings;
use Test::More;
use POSIX qw(strftime);

my $home   = $ENV{HOME};
my $repo   = "$home/repos/dl_wm";
my $cookie = "$repo/conf/instagram.cookies.haddamgoel.txt";
my $outdir = "$home/dl_wm_outputs/ghost_soldier";
my $report = "$outdir/report.txt";
my $errfile = "$home/.cache/dl_wm_session_stderr.$$";
my $url    = 'https://www.instagram.com/accounts/edit/';

sub capture_cmd {
    my ($errpath, @cmd) = @_;
    pipe(my $rd, my $wr) or die "pipe: $!";
    my $pid = fork();
    die "fork: $!" unless defined $pid;
    if ($pid == 0) {
        close $rd;
        open STDOUT, '>&', $wr or exit 126;
        open STDERR, '>', $errpath or exit 126;
        close $wr;
        exec { $cmd[0] } @cmd;
        exit 127;
    }
    close $wr;
    local $/;
    my $out = <$rd>;
    close $rd;
    waitpid($pid, 0);
    return ($? >> 8, defined $out ? $out : '');
}

unlink $errfile;
my ($rc, $out) = capture_cmd($errfile, 'curl', '-sS', '-L', '--max-time', '30',
                            '-o', '/dev/null', '-b', $cookie,
                            '-w', '%{http_code}\t%{url_effective}', $url);
my $raw = defined $out ? $out : '';
chomp $raw;
my ($code, $final) = split /\t/, $raw, 2;
$code  = '000' unless defined $code && $code ne '';
$final = ''    unless defined $final;

ok($rc == 0, 'session GET completed');
diag("curl exit=$rc") unless $rc == 0;

ok($code eq '200' && $final !~ m{/accounts/login/?},
   'HTTP 200 and final URL is not /accounts/login/');
diag("status=$code final=$final");

mkdir $outdir unless -d $outdir;
my $line = sprintf("%s GET %s -> HTTP %s final=%s\n",
                   strftime('%Y-%m-%d %H:%M:%S', localtime), $url, $code,
                   ($final eq '' ? 'unknown' : $final));
my $written = 0;
if (open(my $rf, '>>', $report)) {
    $written = (print $rf $line) ? 1 : 0;
    close $rf;
}
ok($written, 'status line written to report');
diag("status line: $line") if $written;

unlink $errfile;

done_testing();
