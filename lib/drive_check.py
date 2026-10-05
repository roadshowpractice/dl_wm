"""Check that dl_wm's outputs/ (a symlink onto the UBUNTU 26_0 USB drive) is really there and writable.

USB drives are not reliable: the drive can be unplugged, fail to automount, or be remounted
read-only by the kernel after an error (the fstab line has errors=remount-ro). A path that
merely exists proves nothing, so this writes a small file, reads it back and deletes it.

    from lib.drive_check import assert_outputs_writable
    assert_outputs_writable()          # raises OutputsDriveError with a plain explanation

    python -m lib.drive_check          # same check from the shell; exit 0 = ok, 1 = not ok
"""
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class OutputsDriveError(RuntimeError):
    pass


def _mount_for(path):
    """(mount point, options) of the real filesystem holding path, from /proc/mounts (skips autofs)."""
    best = ("", "")
    with open("/proc/mounts") as fh:
        for line in fh:
            dev, mnt, fstype, opts = line.split()[:4]
            mnt = mnt.replace("\\040", " ")
            if fstype == "autofs":
                continue
            if (str(path) + "/").startswith(mnt.rstrip("/") + "/") and len(mnt) >= len(best[0]):
                best = (mnt, opts)
    return best


def assert_outputs_writable(outputs=None):
    """Return the resolved outputs path if a real write works there; raise OutputsDriveError otherwise."""
    link = Path(outputs or REPO / "outputs")
    target = link.resolve()
    if not target.is_dir():
        raise OutputsDriveError(
            f"{link} -> {target} is not there. Is the UBUNTU 26_0 USB drive plugged in? "
            f"(it automounts at /mnt/ubuntu26)")
    mnt, opts = _mount_for(target)
    if "ro" in opts.split(","):
        raise OutputsDriveError(
            f"{target} is on {mnt}, which is mounted READ-ONLY (the kernel does that after a drive error). "
            f"Unplug/replug the drive, or check it, before running anything that saves files.")
    probe = target / f".write_test_{uuid.uuid4().hex}"
    data = b"dl_wm drive check\n"
    try:
        with open(probe, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if probe.read_bytes() != data:
            raise OutputsDriveError(f"wrote a test file on {target} but read back something different")
    except OSError as e:
        raise OutputsDriveError(f"can't write to {target}: {e}") from e
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return target


if __name__ == "__main__":
    try:
        print(f"ok: {assert_outputs_writable()} is writable")
    except OutputsDriveError as e:
        print(f"NOT OK: {e}", file=sys.stderr)
        sys.exit(1)
