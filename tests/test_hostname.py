"""The board's name (#292): label validation, applying it, the scoreboard.local alias."""

from __future__ import annotations

import pytest

from scoreboard.hostname import (
    AliasPublisher,
    apply_hostname,
    normalise_hostname,
    valid_hostname_label,
)


@pytest.mark.parametrize("name", ["kitchen", "scoreboard-a1b2", "a", "a1", "x" * 63])
def test_valid_labels(name):
    assert valid_hostname_label(name)


@pytest.mark.parametrize("name", ["", "-a", "a-", "has space", "under_score", "x" * 64, "a.b"])
def test_invalid_labels(name):
    assert not valid_hostname_label(name)


def test_normalise_lowercases_and_drops_dot_local():
    assert normalise_hostname("  Kitchen.LOCAL ") == "kitchen"


def test_apply_hostname_writes_files_and_restarts_avahi(tmp_path):
    hostname, hosts, state = tmp_path / "hostname", tmp_path / "hosts", tmp_path / "s" / "chosen"
    hosts.write_text("127.0.0.1\tlocalhost\n127.0.1.1\told\n")
    calls, live = [], []
    ok = apply_hostname(
        "kitchen",
        hostname_file=hostname,
        hosts_file=hosts,
        state_file=state,
        run=lambda cmd, **kw: calls.append(cmd),
        set_hostname=live.append,
    )
    assert ok
    assert live == ["kitchen"], "the kernel's name is set by syscall"
    assert calls == [["systemctl", "restart", "avahi-daemon.service"]], "no command takes the name"
    assert hostname.read_text() == "kitchen\n"
    assert "127.0.1.1\tkitchen" in hosts.read_text()
    assert "old" not in hosts.read_text()
    assert state.read_text() == "kitchen\n"


def test_apply_hostname_failure_is_not_fatal(tmp_path):
    ok = apply_hostname(
        "kitchen",
        hostname_file=tmp_path / "missing-dir" / "hostname",
        hosts_file=tmp_path / "hosts",
        state_file=tmp_path / "state",
        run=lambda cmd, **kw: None,
        set_hostname=lambda name: None,
    )
    assert not ok


@pytest.mark.parametrize(
    "name",
    ["", "-h", "--version", "a b", "kitchen\n127.0.0.1\tevil", "a\tb", "x" * 64, "a;reboot", "a.b"],
)
def test_apply_hostname_refuses_anything_but_a_single_label(tmp_path, name):
    """The name goes into /etc/hostname and /etc/hosts, so a bad one must touch nothing."""
    hostname, hosts, state = tmp_path / "hostname", tmp_path / "hosts", tmp_path / "state"
    hosts.write_text("127.0.0.1\tlocalhost\n")
    calls, live = [], []
    ok = apply_hostname(
        name,
        hostname_file=hostname,
        hosts_file=hosts,
        state_file=state,
        run=lambda cmd, **kw: calls.append(cmd),
        set_hostname=live.append,
    )
    assert not ok
    assert calls == [] and live == []
    assert not hostname.exists() and not state.exists()
    assert hosts.read_text() == "127.0.0.1\tlocalhost\n"


def test_a_failed_live_rename_still_announces_the_name(tmp_path):
    """Setting the kernel name needs root; without it the files and avahi still update."""

    def denied(name):
        raise PermissionError("not root")

    calls = []
    ok = apply_hostname(
        "kitchen",
        hostname_file=tmp_path / "hostname",
        hosts_file=tmp_path / "hosts",
        state_file=tmp_path / "state",
        run=lambda cmd, **kw: calls.append(cmd),
        set_hostname=denied,
    )
    assert ok
    assert calls == [["systemctl", "restart", "avahi-daemon.service"]]


class FakeProc:
    def __init__(self, alive=True):
        self.alive = alive
        self.terminated = False

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated = True
        self.alive = False


def test_alias_publishes_once_per_ip_and_moves_with_it():
    procs = []

    def popen(cmd, **kw):
        procs.append((cmd, FakeProc()))
        return procs[-1][1]

    pub = AliasPublisher(popen=popen)
    pub.sync(True, "10.0.0.7")
    pub.sync(True, "10.0.0.7")
    assert [c for c, _ in procs] == [["avahi-publish-address", "scoreboard.local", "10.0.0.7"]]
    pub.sync(True, "10.0.0.8")
    assert len(procs) == 2 and procs[0][1].terminated
    pub.sync(False, "10.0.0.8")
    assert not pub.active


def test_alias_taken_by_another_board_is_not_retried_every_tick():
    count = []

    def popen(cmd, **kw):
        count.append(1)
        return FakeProc(alive=False)  # avahi-publish-address exited: name taken

    pub = AliasPublisher(popen=popen)
    for _ in range(5):
        pub.sync(True, "10.0.0.7")
    assert len(count) == 1
    assert not pub.active


def test_alias_without_avahi_utils_is_not_fatal():
    def popen(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    pub = AliasPublisher(popen=popen)
    pub.sync(True, "10.0.0.7")
    assert not pub.active
