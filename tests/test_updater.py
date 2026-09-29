"""Tests for the app self-update flow (#32): check, apply, rollback."""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

from nhl_scoreboard import updater
from nhl_scoreboard.config import Settings
from nhl_scoreboard.status_server import StatusServer


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = tmp_path / "opt" / "nhl-scoreboard"
    (app / "nhl_scoreboard").mkdir(parents=True)
    (app / "nhl_scoreboard" / "__init__.py").write_text("OLD")
    (app / "VERSION").write_text("v2026.09.01\n")
    monkeypatch.setattr(updater, "APP_DIR", app)
    monkeypatch.setattr(updater, "STATE_FILE", tmp_path / "state" / "update-state.json")
    monkeypatch.setattr(updater, "DRIVER_COMMIT_FILE", tmp_path / "driver-commit")
    monkeypatch.setattr(updater, "HEALTH_SECONDS", 0)
    return app


def _bundle(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_release(monkeypatch, *, tag="v2026.09.29", driver="abc1234", assets=True):
    manifest = {"driver_commit": driver, "sha256": "x"}

    def fetch(url):
        if url.endswith("manifest.json"):
            return manifest
        return {
            "tag_name": tag,
            "assets": (
                [
                    {"name": updater.BUNDLE_ASSET, "browser_download_url": "http://b/bundle"},
                    {
                        "name": updater.MANIFEST_ASSET,
                        "browser_download_url": "http://b/manifest.json",
                    },
                ]
                if assets
                else []
            ),
        }

    monkeypatch.setattr(updater, "_fetch_json", fetch)


def test_is_newer_orders_calver_including_same_day_suffix():
    assert updater.is_newer("v2026.09.29", "v2026.09.28")
    assert updater.is_newer("v2026.09.29.1", "v2026.09.29")
    assert updater.is_newer("v2026.09.29.10", "v2026.09.29.2")
    assert not updater.is_newer("v2026.09.29", "v2026.09.29")
    assert not updater.is_newer("v2026.09.28", "v2026.09.29")
    assert updater.is_newer("v2026.09.29", "")


def test_check_records_available_update(env, monkeypatch):
    _fake_release(monkeypatch)
    state = updater.check()
    assert state["available"] and state["applicable"]
    assert state["latest"] == "v2026.09.29"
    assert updater.read_state()["bundle_url"] == "http://b/bundle"


def test_check_up_to_date(env, monkeypatch):
    _fake_release(monkeypatch, tag="v2026.09.01")
    state = updater.check()
    assert not state["available"]
    assert state["reason"] == "Up to date"


def test_check_refuses_when_driver_changed(env, monkeypatch, tmp_path):
    (tmp_path / "driver-commit").write_text("51d3231deadbeef\n")
    _fake_release(monkeypatch, driver="ffff000")
    state = updater.check()
    assert state["available"] and not state["applicable"]
    assert "reflash" in state["reason"]


def test_check_accepts_driver_prefix_match(env, monkeypatch, tmp_path):
    (tmp_path / "driver-commit").write_text("51d3231deadbeef\n")
    _fake_release(monkeypatch, driver="51d3231")
    assert updater.check()["applicable"]


def test_check_release_without_bundle_needs_reflash(env, monkeypatch):
    _fake_release(monkeypatch, assets=False)
    state = updater.check()
    assert not state["applicable"]
    assert "reflash" in state["reason"]


def test_check_network_failure_is_recorded_not_raised(env, monkeypatch):
    def boom(url):
        raise OSError("no route")

    monkeypatch.setattr(updater, "_fetch_json", boom)
    assert "no route" in updater.check()["error"]


def _prepared(env, monkeypatch, bundle: bytes, *, healthy: bool):
    updater._write_state(
        {
            "latest": "v2026.09.29",
            "available": True,
            "applicable": True,
            "bundle_url": "http://b/bundle",
            "sha256": hashlib.sha256(bundle).hexdigest(),
        }
    )
    monkeypatch.setattr(updater, "_download", lambda url, dest: dest.write_bytes(bundle))
    calls: list[tuple[str, ...]] = []
    # The service only "comes up" if the new tree is in place *and* healthy.
    monkeypatch.setattr(updater, "_systemctl", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(
        updater,
        "_service_active",
        lambda: healthy or (env / "nhl_scoreboard" / "__init__.py").read_text() == "OLD",
    )
    return calls


GOOD = {"nhl_scoreboard/__init__.py": "NEW"}


def test_apply_swaps_in_new_tree_when_service_comes_up(env, monkeypatch):
    calls = _prepared(env, monkeypatch, _bundle(GOOD), healthy=True)
    assert updater.apply() is True
    assert (env / "nhl_scoreboard" / "__init__.py").read_text() == "NEW"
    assert updater.installed_version() == "v2026.09.29"
    assert not env.with_name("nhl-scoreboard.prev").exists()
    assert calls == [("restart", updater.SERVICE)]
    state = updater.read_state()
    assert state["last_apply"]["outcome"] == "success"
    assert not state["available"]


def test_apply_rolls_back_when_service_does_not_come_up(env, monkeypatch):
    calls = _prepared(env, monkeypatch, _bundle(GOOD), healthy=False)
    # New tree (contents "NEW") makes the service report inactive.
    monkeypatch.setattr(
        updater,
        "_service_active",
        lambda: (env / "nhl_scoreboard" / "__init__.py").read_text() == "OLD",
    )
    assert updater.apply() is False
    assert (env / "nhl_scoreboard" / "__init__.py").read_text() == "OLD"
    assert updater.installed_version() == "v2026.09.01"
    assert calls == [("restart", updater.SERVICE)] * 2  # once on new, once on restore
    assert updater.read_state()["last_apply"]["outcome"] == "rolled_back"
    assert not env.with_name("nhl-scoreboard.prev").exists()
    assert not env.with_name("nhl-scoreboard.failed").exists()


def test_apply_rolls_back_when_restart_command_fails(env, monkeypatch):
    _prepared(env, monkeypatch, _bundle(GOOD), healthy=True)
    monkeypatch.setattr(updater, "_systemctl", lambda *a: False)
    assert updater.apply() is False
    assert (env / "nhl_scoreboard" / "__init__.py").read_text() == "OLD"


def test_apply_rejects_checksum_mismatch_without_touching_live_tree(env, monkeypatch):
    calls = _prepared(env, monkeypatch, _bundle(GOOD), healthy=True)
    state = updater.read_state()
    state["sha256"] = "0" * 64
    updater._write_state(state)
    assert updater.apply() is False
    assert (env / "nhl_scoreboard" / "__init__.py").read_text() == "OLD"
    assert calls == []
    assert updater.read_state()["last_apply"]["outcome"] == "failed"


def test_apply_rejects_path_traversal(env, monkeypatch):
    calls = _prepared(env, monkeypatch, _bundle({"../evil": "x", **GOOD}), healthy=True)
    assert updater.apply() is False
    assert not (env.parent / "evil").exists()
    assert calls == []


def test_apply_rejects_bundle_without_package(env, monkeypatch):
    calls = _prepared(env, monkeypatch, _bundle({"README": "x"}), healthy=True)
    assert updater.apply() is False
    assert calls == []


def test_apply_without_recorded_update_fails(env):
    assert updater.apply() is False


def test_wait_until_healthy_fails_on_first_inactive_poll(monkeypatch):
    monkeypatch.setattr(updater, "_service_active", lambda: False)
    assert updater.wait_until_healthy(5, 0) is False


def test_cli_check_honours_disabled_setting(env, monkeypatch, tmp_path):
    cfg = tmp_path / "scoreboard.toml"
    cfg.write_text("[update]\nenabled = false\n")
    monkeypatch.setattr(updater, "check", lambda: pytest.fail("should not check"))
    assert updater.main(["check", "--config", str(cfg)]) == 0


def test_cli_check_force_ignores_disabled_setting(env, monkeypatch):
    called = []
    monkeypatch.setattr(updater, "check", lambda: called.append(1) or {})
    assert updater.main(["check", "--force"]) == 0
    assert called


def test_update_config_defaults_on():
    assert Settings().update.enabled is True
    assert Settings.from_dict({"update": {"enabled": False}}).update.enabled is False


# -- admin page ---------------------------------------------------------


def _request(port, method, path, origin=True):
    headers = {"Origin": f"http://127.0.0.1:{port}"} if origin else {}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read().decode()
    finally:
        conn.close()


def test_admin_page_buttons_trigger_units(env):
    updater._write_state(
        {
            "latest": "v2026.09.29",
            "available": True,
            "applicable": True,
            "checked_at": "now",
        }
    )
    triggered: list[str] = []
    server = StatusServer(
        snapshot=dict,
        port=0,
        settings=Settings,
        host="127.0.0.1",
        update_trigger=triggered.append,
    )
    server.start()
    try:
        _, _, body = _request(server.port, "GET", "/")
        assert "Check for updates now" in body
        assert "Install v2026.09.29" in body

        status, headers, _ = _request(server.port, "POST", "/update/check")
        assert status == 303 and headers["Location"] == "/?update=check"
        assert _request(server.port, "POST", "/update/apply")[0] == 303
        assert triggered == ["check", "apply"]

        assert _request(server.port, "POST", "/update/apply", origin=False)[0] == 403
        assert triggered == ["check", "apply"]
    finally:
        server.stop()


def test_admin_page_hides_install_when_not_applicable(env):
    updater._write_state({"latest": "v2026.09.29", "available": True, "applicable": False})
    server = StatusServer(snapshot=dict, port=0, settings=Settings, host="127.0.0.1")
    server.start()
    try:
        _, _, body = _request(server.port, "GET", "/")
        assert "Install v" not in body
        assert "Check for updates now" in body
    finally:
        server.stop()


# -- bundle builder -----------------------------------------------------


def test_build_app_bundle_matches_what_the_updater_expects(tmp_path):
    path = Path(__file__).resolve().parent.parent / "scripts" / "build-app-bundle.py"
    spec = importlib.util.spec_from_file_location("build_app_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build("v2026.09.29", tmp_path)

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    bundle = tmp_path / updater.BUNDLE_ASSET
    assert manifest["sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert manifest["driver_commit"]
    dest = tmp_path / "out"
    updater._extract(bundle, dest)
    assert (dest / "nhl_scoreboard" / "updater.py").is_file()
    assert not list(dest.rglob("__pycache__"))
