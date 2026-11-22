#!/usr/bin/perl
use strict;
use warnings;
use FindBin qw($Bin);
use IO::Handle;

my @tests = qw(00_env.t 10_network.t 20_cookie_file.t 30_session.t 40_download.t);

my $outdir  = "$ENV{HOME}/dl_wm_outputs/ghost_soldier";
my $logfile = "$outdir/test_run.log";
my $state   = "$Bin/.suite_state";
mkdir $outdir unless -d $outdir;

my $force_all   = grep { $_ eq '--all' } @ARGV;
my $show_status = grep { $_ eq '--status' } @ARGV;
my $dry_run     = grep { $_ eq '--dry-run' || $_ eq '-n' } @ARGV;

my $repo = $Bin;
$repo =~ s{/+t$}{};

sub run_capture_quiet {
    my @cmd = @_;
    open(my $fh, '-|', @cmd) or return (127, '');
    local $/;
    my $out = <$fh>;
    close $fh;
    return ($? >> 8, defined $out ? $out : '');
}

sub fingerprint {
    my ($rc, $head) = run_capture_quiet('git', '-C', $repo, 'rev-parse', 'HEAD');
    chomp $head;
    $head = 'unknown' unless $rc == 0 && defined $head && $head ne '';
    my ($prc, $pyv) = run_capture_quiet("$ENV{HOME}/micromamba/envs/dl_wm/bin/python", '-V');
    chomp $pyv;
    $pyv = 'unknown' unless $prc == 0 && defined $pyv && $pyv ne '';
    $pyv =~ s/\s+/_/g;
    my $mt = -f "$repo/environment.yml" ? (stat(_))[9] : 0;
    return "HEAD=$head envyml=$mt py=$pyv";
}

sub read_state {
    my (%done, $fp);
    return (\%done, undef) unless -f $state;
    open(my $fh, '<', $state) or return (\%done, undef);
    while (my $l = <$fh>) {
        chomp $l;
        $l =~ s/\s+$//;
        next if $l eq '';
        if ($l =~ /^#\s*fingerprint\s+(.*)$/) { $fp = $1; next; }
        next if $l =~ /^#/;
        $done{$l} = 1;
    }
    close $fh;
    return (\%done, $fp);
}

sub write_header {
    my ($fp) = @_;
    open(my $fh, '>', $state) or die "open $state: $!";
    print $fh "# fingerprint $fp\n";
    close $fh;
}

sub mark_done {
    my ($file) = @_;
    open(my $fh, '>>', $state) or die "open $state: $!";
    print $fh "$file\n";
    close $fh;
}

my $logmode = ($show_status || $dry_run) ? '>>' : '>';
open(my $LOG, $logmode, $logfile) or die "open $logfile: $!";
$LOG->autoflush(1);

sub emit {
    my ($text) = @_;
    print $text;
    print $LOG $text;
}

sub run_test {
    my ($path) = @_;
    pipe(my $rd, my $wr) or die "pipe: $!";
    my $pid = fork();
    die "fork: $!" unless defined $pid;
    if ($pid == 0) {
        close $rd;
        open STDOUT, '>&', $wr or exit 126;
        open STDERR, '>&', \*STDOUT or exit 126;
        close $wr;
        exec $^X, $path;
        exit 127;
    }
    close $wr;
    while (my $line = <$rd>) {
        emit($line);
    }
    close $rd;
    waitpid($pid, 0);
    return $? >> 8;
}

my $fp = fingerprint();
my ($done, $oldfp) = read_state();

if ($show_status) {
    emit("# state file: $state\n");
    emit("# stored fingerprint: " . (defined $oldfp ? $oldfp : '(none)') . "\n");
    emit("# current fingerprint: $fp\n");
    emit("# stages recorded passed: " . (join(' ', map { "t/$_" } sort keys %$done) || '(none)') . "\n");
    emit("# all stages passed: " . (keys(%$done) == @tests ? 'yes' : 'no') . "\n");
    close $LOG;
    exit 0;
}

my %usable;
if ($force_all) {
    unlink $state if -f $state && !$dry_run;
    emit("# --all: state cleared, running the full suite\n");
}
elsif (defined $oldfp && $oldfp eq $fp) {
    %usable = %$done;
    my @cached = grep { $usable{$_} } @tests;
    if (@cached) {
        emit("# resuming: " . scalar(@cached) . " stage(s) already passed (use --all to force)\n");
    }
}
elsif (defined $oldfp) {
    emit("# state fingerprint changed (env or repo moved); starting fresh\n");
    unlink $state if -f $state && !$dry_run;
}

unless ($dry_run || $force_all || (defined $oldfp && $oldfp eq $fp)) {
    write_header($fp);
}

if ($dry_run) {
    emit("# ---- dry run: plan ----\n");
    for my $file (@tests) {
        my $name = "t/$file";
        if ($usable{$file}) {
            emit("# would SKIP  $name (already passed)\n");
        }
        else {
            emit("# would RUN   $name\n");
        }
    }
    emit("# ---- dry run: nothing executed ----\n");
    close $LOG;
    exit 0;
}

my ($failed, @summary);
for my $i (0 .. $#tests) {
    my $file = $tests[$i];
    my $name = "t/$file";

    if ($usable{$file}) {
        emit("# SKIP $name (passed in an earlier run; --all to force)\n");
        push @summary, "# PASS (cached) $name\n";
        next;
    }

    my $path = "$Bin/$file";
    emit("# ==== $name ====\n");
    my $rc = run_test($path);
    if ($rc == 0) {
        mark_done($file);
        push @summary, "# PASS $name\n";
    }
    else {
        $failed = $name;
        push @summary, "# FAIL $name (exit $rc)\n";
        for my $j ($i + 1 .. $#tests) {
            push @summary, "# SKIP t/$tests[$j] (earlier stage $name failed)\n";
        }
        last;
    }
}

emit("\n# ---- summary ----\n");
emit($_) for @summary;
if ($failed) {
    emit("SUITE FAIL (first failing file: $failed)\n");
    emit("# resume state kept; a rerun continues from the first unpassed stage\n");
}
else {
    unlink $state if -f $state;
    emit("SUITE PASS\n");
    emit("# state cleared (suite green)\n");
}

close $LOG;
exit($failed ? 1 : 0);
