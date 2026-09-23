"""nhl-scoreboard-grow-rootfs: the shell script, run for real.

Every system tool it touches (findmnt, lsblk, parted, sfdisk, resize2fs,
systemctl, logger) is faked -- a tiny script on a PATH prepended in front
of the real one, recording its invocation and returning canned output or
exit codes the test controls. This runs the actual script byte-for-byte,
so it catches shell bugs a description of the logic would not, without
touching a real disk or needing root.

What this does NOT verify: that sfdisk/resize2fs correctly resize a real
partition on real hardware. That's out of reach without a Pi and an SD
card (see issue #4); what's verified here is that the script asks for the
right thing, in the right order, and never touches the disk when its own
safety checks say not to.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "image"
    / "files"
    / "scripts"
    / "nhl-scoreboard-grow-rootfs"
)

# A two-partition MBR disk (boot, root) in `parted -ms unit s p` machine
# output: partition;start;end;size;filesystem;name;flags. Root (2) is last.
TWO_PART_DISK = (
    "BYT;\n"
    "/dev/mmcblk0:31000000s:sd/mmc::512:512:msdos:SD card:;\n"
    "1:2048s:526335s:524288s:fat32::lba;\n"
    "2:526336s:5500000s:4973665s:ext4::;\n"
)
# A third partition after root: root is no longer last.
THREE_PART_DISK = TWO_PART_DISK + "3:5500001s:6000000s:499999s:ext4::;\n"


def write_fake(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text(f'#!/bin/sh\necho "$0 $*" >> "$FAKE_CALL_LOG"\n{body}')
    path.chmod(0o755)


class Rig:
    """One fake first-boot environment. Each .run() call is one boot
    attempt: the call log is truncated first, so result.calls reflects
    only that invocation, not ones before it in the same test."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.bindir = tmp_path / "bin"
        self.bindir.mkdir()
        self.state_dir = tmp_path / "state"
        self.call_log = tmp_path / "calls.log"
        self.sfdisk_stdin = tmp_path / "sfdisk_stdin"
        # Stands in for /proc/sys/kernel/random/boot_id: same value across
        # runs = no reboot in between, a different one = a real reboot.
        self.boot_id_file = tmp_path / "boot_id"
        self.set_boot_id("boot-a")

        write_fake(self.bindir, "findmnt", 'echo "${FAKE_ROOT_PART:-/dev/mmcblk0p2}"')
        write_fake(self.bindir, "lsblk", 'echo "${FAKE_ROOT_DISK:-mmcblk0}"')
        write_fake(self.bindir, "parted", 'printf "%s" "$FAKE_PARTED_OUT"')
        write_fake(
            self.bindir, "sfdisk", 'cat > "$FAKE_SFDISK_STDIN"; exit "${FAKE_SFDISK_EXIT:-0}"'
        )
        write_fake(self.bindir, "resize2fs", 'exit "${FAKE_RESIZE2FS_EXIT:-0}"')
        write_fake(self.bindir, "systemctl", "exit 0")
        write_fake(self.bindir, "logger", "exit 0")

    def set_boot_id(self, value: str) -> None:
        self.boot_id_file.write_text(f"{value}\n")

    def write_grown_marker(self, boot_id: str) -> None:
        """Put the rig in stage 2, as if stage 1 ran during boot `boot_id`."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        grown_marker(self.state_dir).write_text(f"{boot_id}\n")

    def run(self, *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        import os

        self.call_log.write_text("")
        env = {
            "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "FAKE_CALL_LOG": str(self.call_log),
            "FAKE_PARTED_OUT": TWO_PART_DISK,
            "FAKE_SFDISK_STDIN": str(self.sfdisk_stdin),
            "NHL_SCOREBOARD_STATE_DIR": str(self.state_dir),
            "NHL_SCOREBOARD_BOOT_ID_FILE": str(self.boot_id_file),
            **(env_extra or {}),
        }
        result = subprocess.run(
            ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10
        )
        result.calls = self.call_log.read_text()
        return result


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


def grown_marker(state_dir: Path) -> Path:
    return state_dir / "rootfs-partition-grown"


def done_marker(state_dir: Path) -> Path:
    return state_dir / "rootfs-grown"


# --------------------------------------------------------------------------
# stage 1: grow the partition table
# --------------------------------------------------------------------------


def test_stage1_grows_the_last_partition_and_requests_a_reboot(rig):
    result = rig.run()
    assert result.returncode == 0, result.stderr

    assert "sfdisk" in result.calls
    assert "--no-reread" in result.calls
    assert "-N 2" in result.calls or "-N" in result.calls  # partition number passed
    assert "systemctl" in result.calls and "reboot" in result.calls

    assert grown_marker(rig.state_dir).is_file()
    # Records which boot grew the table, so stage 2 can tell whether a
    # reboot has actually happened since (#69).
    assert grown_marker(rig.state_dir).read_text().strip() == "boot-a"
    assert not done_marker(rig.state_dir).is_file()


def test_stage1_passes_the_exact_start_sector_unchanged(rig):
    """The single most safety-critical line: start must never move."""
    rig.run()
    assert rig.sfdisk_stdin.read_text().strip() == "526336,+"


def test_stage1_refuses_when_root_is_not_the_last_partition(rig):
    result = rig.run(env_extra={"FAKE_PARTED_OUT": THREE_PART_DISK})
    assert result.returncode == 0, result.stderr
    assert "sfdisk" not in result.calls
    assert "systemctl" not in result.calls
    assert not grown_marker(rig.state_dir).is_file()
    # Refusal is permanent, not retried forever: stops the unit from
    # trying (and logging about it) on every future boot.
    assert done_marker(rig.state_dir).is_file()


def test_stage1_sfdisk_failure_is_retryable_not_permanent(rig):
    result = rig.run(env_extra={"FAKE_SFDISK_EXIT": "1"})
    assert result.returncode == 1
    assert not grown_marker(rig.state_dir).is_file()
    assert not done_marker(rig.state_dir).is_file()  # must retry next boot
    assert "systemctl" not in result.calls  # never reboot on a failed grow


# --------------------------------------------------------------------------
# stage 2: grow the filesystem into the (now larger) partition
# --------------------------------------------------------------------------


def test_stage2_runs_resize2fs_and_finishes(rig):
    rig.write_grown_marker("boot-a")
    rig.set_boot_id("boot-b")  # rebooted since stage 1

    result = rig.run()
    assert result.returncode == 0, result.stderr
    assert "resize2fs" in result.calls
    assert "sfdisk" not in result.calls, "must not try to grow the table again"
    assert done_marker(rig.state_dir).is_file()
    assert not grown_marker(rig.state_dir).is_file(), "stage-1 marker is cleared"


def test_stage2_resize2fs_failure_is_retryable(rig):
    rig.write_grown_marker("boot-a")
    rig.set_boot_id("boot-b")

    result = rig.run(env_extra={"FAKE_RESIZE2FS_EXIT": "1"})
    assert result.returncode == 1
    assert not done_marker(rig.state_dir).is_file()
    assert grown_marker(rig.state_dir).is_file(), "stays in stage 2 for next boot"


def test_stage2_refuses_until_a_reboot_has_actually_happened(rig):
    """#69: the reboot request is non-blocking and can fail or be skipped.
    Re-run in the same boot, the kernel still has the old, smaller table
    cached; resize2fs would no-op and DONE_MARKER would end it for good."""
    rig.write_grown_marker("boot-a")  # same boot id as the rig's current one

    result = rig.run()
    assert result.returncode == 1, "retryable, like every other failure here"
    assert "resize2fs" not in result.calls
    assert "sfdisk" not in result.calls
    assert "systemctl" in result.calls and "reboot" in result.calls, "asks again"
    assert not done_marker(rig.state_dir).is_file()
    assert grown_marker(rig.state_dir).read_text().strip() == "boot-a", "left untouched"


def test_full_cycle_across_a_failed_reboot_then_a_real_one(rig):
    rig.run()  # stage 1 during boot-a
    rig.run()  # reboot never happened: still boot-a
    assert not done_marker(rig.state_dir).is_file()

    rig.set_boot_id("boot-b")
    result = rig.run()
    assert result.returncode == 0, result.stderr
    assert "resize2fs" in result.calls
    assert done_marker(rig.state_dir).is_file()


def test_unreadable_boot_id_falls_back_to_trusting_the_marker(rig):
    """No boot id available must never be worse than before the check
    existed: stage 1 still records its marker, and stage 2 still runs
    resize2fs rather than waiting forever for a reboot it can't detect."""
    missing = {"NHL_SCOREBOARD_BOOT_ID_FILE": str(rig.tmp_path / "no-such-file")}

    result = rig.run(env_extra=missing)
    assert result.returncode == 0, result.stderr
    assert grown_marker(rig.state_dir).read_text().strip() == ""

    result = rig.run(env_extra=missing)
    assert result.returncode == 0, result.stderr
    assert "resize2fs" in result.calls
    assert done_marker(rig.state_dir).is_file()


# --------------------------------------------------------------------------
# idempotency
# --------------------------------------------------------------------------


def test_done_marker_short_circuits_before_touching_anything(rig):
    rig.state_dir.mkdir(parents=True, exist_ok=True)
    done_marker(rig.state_dir).touch()

    result = rig.run()
    assert result.returncode == 0
    assert result.calls == "", "must not invoke findmnt/lsblk/parted/sfdisk once done"
