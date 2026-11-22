#!/usr/bin/perl
use strict;
use warnings;
use Test::More;
use Socket qw(getaddrinfo AF_INET SOCK_STREAM);

my $host   = 'www.instagram.com';
my $errfile = "$ENV{HOME}/.cache/dl_wm_net_stderr.$$";

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

my ($err, @res) = getaddrinfo($host, 'https', { socktype => SOCK_STREAM });
my $dns_ok = (!$err && @res) ? 1 : 0;
ok($dns_ok, "DNS resolves $host") or diag('getaddrinfo: ' . ($err // 'no results'));

my ($rc, $out, $code) = (127, '', '000');
if ($dns_ok) {
    unlink $errfile;
    ($rc, $out) = capture_cmd($errfile, 'curl', '-sS', '--max-time', '30',
                              '-o', '/dev/null', '-w', '%{http_code}',
                              'https://www.instagram.com/');
    $out = '' unless defined $out;
    $out =~ s/\s+//g;
    $code = $out if $rc == 0 && $out ne '';
}
ok($dns_ok && $rc == 0 && $code =~ /^[23]\d\d$/,
   'HTTPS GET returns a 2xx/3xx status within 30 s');
diag("curl exit=$rc status=$code");

my $errtext = '';
if (-f $errfile) {
    open(my $ef, '<', $errfile) or die "open $errfile: $!";
    local $/;
    $errtext = <$ef> // '';
    close $ef;
}
my $proxy_cert = ($errtext =~ /(proxy|certificate|SSL|TLS)/i) ? 1 : 0;
ok($rc == 0 && !$proxy_cert, 'no proxy or certificate error');
diag('curl stderr indicates a proxy/certificate problem') if $proxy_cert;
unlink $errfile;

done_testing();
