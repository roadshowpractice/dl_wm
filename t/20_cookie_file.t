#!/usr/bin/perl
use strict;
use warnings;
use Test::More;

my $home   = $ENV{HOME};
my $repo   = "$home/repos/dl_wm";
my $rel    = 'conf/instagram.cookies.haddamgoel.txt';
my $cookie = "$repo/$rel";

plan skip_all => "no local cookie file; refresh with: bin/refresh_cookies.py instagram.com $rel (never committed)"
    unless -f $cookie;

sub capture_cmd {
    my @cmd = @_;
    open(my $fh, '-|', @cmd) or return (127, '');
    local $/;
    my $out = <$fh>;
    close $fh;
    return ($? >> 8, defined $out ? $out : '');
}

ok(-f $cookie, 'cookie file exists');

my @st   = stat($cookie);
my $mode = @st ? ($st[2] & 07777) : -1;
ok($mode == 0600, 'cookie file mode is 0600')
    or diag(sprintf('mode is %04o', $mode));

my ($grc, $rule) = capture_cmd('git', '-C', $repo, 'check-ignore', '-v', $rel);
chomp $rule;
ok($grc == 0 && $rule ne '', 'cookie file is git-ignored');
diag("ignore rule: $rule") if $rule ne '';

open(my $fh, '<', $cookie) or die "open cookie file: $!";
my @lines = <$fh>;
close $fh;

my $header = (@lines && $lines[0] =~ /^# Netscape HTTP Cookie File/) ? 1 : 0;
ok($header, 'Netscape cookie header present');

my (@bad, @cookies);
for my $i (0 .. $#lines) {
    my $l = $lines[$i];
    chomp $l;
    $l =~ s/\r$//;
    next if $l =~ /^#/ || $l =~ /^\s*$/;
    my @f = split /\t/, $l, -1;
    push @bad, $i + 1 if @f != 7;
    push @cookies, \@f if @f == 7;
}
ok(!@bad, 'each non-comment line has 7 tab-separated fields')
    or diag('bad lines: ' . join(',', @bad));

my %names;
for my $f (@cookies) {
    $names{ $f->[5] } = 1 if $f->[0] =~ /instagram\.com$/;
}
my @missing = grep { !$names{$_} } qw(sessionid ds_user_id csrftoken);
ok(!@missing, 'required cookies present for instagram.com')
    or diag('missing: ' . join(',', @missing));

my ($sess) = grep { $_->[5] eq 'sessionid' && $_->[0] =~ /instagram\.com$/ } @cookies;
my $exp = $sess ? $sess->[4] : 0;
ok($sess && $exp =~ /^\d+$/ && $exp > time(),
   'sessionid is not expired');
diag('sessionid missing or expiry not in the future')
    unless ($sess && $exp =~ /^\d+$/ && $exp > time());

my $count = scalar @cookies;
ok(defined $count, 'cookie count printed');
diag("cookie count: $count");

done_testing();
