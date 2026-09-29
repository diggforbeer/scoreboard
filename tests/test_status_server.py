"""Tests for the stdlib status page and config editor (#48, #110)."""

from __future__ import annotations

import http.client
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

from nhl_scoreboard.config import Settings
from nhl_scoreboard.status_server import (
    _FIELDS_BY_SECTION,
    StatusServer,
    _reboot_board,
    _render_html,
    _restart_wifi_provisioning,
)


def _form_for(settings: Settings, section: str, **overrides: object) -> dict[str, str]:
    """A full form submission for ``section``: every field, current value unless overridden.

    Mirrors what the real HTML form always submits -- every field in the
    section, not just the one being changed -- since ``do_POST`` treats an
    absent checkbox key as False rather than "leave it alone".
    """
    data: dict[str, str] = {"section": section}
    for field in _FIELDS_BY_SECTION[section]:
        value = (
            overrides[field.key]
            if field.key in overrides
            else getattr(getattr(settings, section), field.key)
        )
        if field.kind == "bool":
            if value:
                data[field.key] = "true"
        else:
            data[field.key] = str(value)
    return data


def _wifi_form(**overrides: str) -> dict[str, str]:
    """ssid/password/country aren't part of Settings, so they have no
    ``settings``-derived defaults; connect_timeout_seconds is a real
    WifiConfig field but round-trips through this same raw section."""
    data = {
        "section": "wifi",
        "ssid": "",
        "password": "",
        "country": "",
        "connect_timeout_seconds": "90",
    }
    data.update(overrides)
    return data


def _post(port: int, data: dict[str, str], origin: bool = True) -> tuple[int, dict, str]:
    body = urllib.parse.urlencode(data)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{port}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", "/save", body=body, headers=headers)
        resp = conn.getresponse()
        resp_body = resp.read().decode("utf-8")
        return resp.status, dict(resp.getheaders()), resp_body
    finally:
        conn.close()


def test_render_html_escapes_and_includes_values():
    body = _render_html({"scene": "game", "favourite team": "<script>"}).decode("utf-8")
    assert "game" in body
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_status_server_serves_snapshot_over_http():
    snapshot = {"scene": "preview", "favourite team": "NSH"}
    server = StatusServer(snapshot=lambda: snapshot, port=0, settings=Settings, host="127.0.0.1")
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "preview" in body
        assert "NSH" in body
    finally:
        server.stop()


def test_status_server_404s_on_unknown_paths():
    server = StatusServer(snapshot=dict, port=0, settings=Settings, host="127.0.0.1")
    server.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/nope", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("expected a 404")
    finally:
        server.stop()


def test_get_renders_editable_form_fields_and_restart_note(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "TOR"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert 'name="favourite_team" value="TOR"' in body
        assert "applies after restart" in body
    finally:
        server.stop()


def test_get_shows_saved_banner():
    settings = Settings()
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/?saved=scoreboard"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "Scoreboard settings saved" in body
    finally:
        server.stop()


def test_post_round_trip_writes_config(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, headers, _ = _post(
            server.port, _form_for(settings, "scoreboard", favourite_team="tor")
        )
        assert status == 303
        assert headers["Location"] == "/?saved=scoreboard"
    finally:
        server.stop()
    # A fresh load (standing in for reload_config_if_changed() picking it up)
    # sees the write, normalised the same way any other load is (#110).
    assert Settings.load(path).scoreboard.favourite_team == "TOR"


def test_post_unchecked_checkbox_saves_false_not_missing(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[audio]\nenabled = true\n")
    settings = Settings.load(path)
    assert settings.audio.enabled is True
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, _ = _post(server.port, _form_for(settings, "audio", enabled=False))
        assert status == 303
    finally:
        server.stop()
    assert Settings.load(path).audio.enabled is False


def test_post_rejects_unknown_select_and_non_numeric_seconds(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\nlogo_variant = "dark"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        data = _form_for(settings, "scoreboard", logo_variant="bogus", rotate_seconds="soon")
        status, _, body = _post(server.port, data)
        assert status == 400
        assert "must be one of" in body
        assert "must be a number" in body
    finally:
        server.stop()
    # Nothing was written -- the file is untouched.
    assert 'logo_variant = "dark"' in path.read_text()


def test_post_rejects_non_numeric_int_field(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\nport = 8080\n")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        data = _form_for(settings, "status", port="not-a-port")
        status, _, body = _post(server.port, data)
        assert status == 400
        assert "must be a whole number" in body
    finally:
        server.stop()
    assert Settings.load(path).status.port == 8080


def test_post_never_mutates_the_live_settings_object(tmp_path):
    """do_POST must save into a throwaway Settings, never the shared live one (#110 SS1).

    A genuine concurrent-access race is inherently timing-dependent to
    prove reliably; this instead proves the structural guarantee that makes
    such a race impossible in the first place -- the live object simply
    never changes from this code path, so there is nothing for the main
    loop thread to race against.
    """
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    live_settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: live_settings, host="127.0.0.1")
    server.start()
    try:
        status, _, _ = _post(
            server.port, _form_for(live_settings, "scoreboard", favourite_team="tor")
        )
        assert status == 303
    finally:
        server.stop()
    assert live_settings.scoreboard.favourite_team == "NSH"
    assert Settings.load(path).scoreboard.favourite_team == "TOR"


def test_post_rejects_cross_origin(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        body = urllib.parse.urlencode(_form_for(settings, "scoreboard", favourite_team="tor"))
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request(
            "POST",
            "/save",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "http://evil.example",
            },
        )
        resp = conn.getresponse()
        resp.read()
        status = resp.status
        conn.close()
        assert status == 403
    finally:
        server.stop()
    assert Settings.load(path).scoreboard.favourite_team == "NSH"


def test_post_rejects_missing_origin_and_referer(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, _ = _post(
            server.port,
            _form_for(settings, "scoreboard", favourite_team="tor"),
            origin=False,
        )
        assert status == 403
    finally:
        server.stop()
    assert Settings.load(path).scoreboard.favourite_team == "NSH"


def test_post_wifi_section_triggers_restart_but_others_do_not(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n[wifi]\nssid = ""\n')
    settings = Settings.load(path)
    calls: list[int] = []
    server = StatusServer(
        snapshot=dict,
        port=0,
        settings=lambda: settings,
        host="127.0.0.1",
        wifi_restart=lambda: calls.append(1),
    )
    server.start()
    try:
        status, _, _ = _post(server.port, _form_for(settings, "scoreboard", favourite_team="tor"))
        assert status == 303
        assert calls == []

        status, _, _ = _post(
            server.port, _wifi_form(ssid="HomeNet", password="hunter2", country="us")
        )
        assert status == 303
        assert calls == [1]
    finally:
        server.stop()
    raw = tomllib.loads(path.read_text())
    assert raw["wifi"] == {
        "ssid": "HomeNet",
        "password": "hunter2",
        "country": "US",
        "connect_timeout_seconds": 90.0,
    }


def test_post_wifi_setup_section_round_trips_and_does_not_restart_wifi(tmp_path):
    """[wifi_setup] (#132) is a real Settings section, unlike [wifi]'s raw
    ssid/password/country -- round-trips through _form_for like any other
    section, and isn't the network-join section wifi_restart is scoped to."""
    path = tmp_path / "scoreboard.toml"
    path.write_text("[wifi_setup]\nenabled = true\nport = 80\n")
    settings = Settings.load(path)
    calls: list[int] = []
    server = StatusServer(
        snapshot=dict,
        port=0,
        settings=lambda: settings,
        host="127.0.0.1",
        wifi_restart=lambda: calls.append(1),
    )
    server.start()
    try:
        status, _, _ = _post(
            server.port, _form_for(settings, "wifi_setup", enabled=False, port="8090")
        )
        assert status == 303
        assert calls == []
    finally:
        server.stop()
    reloaded = Settings.load(path)
    assert reloaded.wifi_setup.enabled is False
    assert reloaded.wifi_setup.port == 8090


def test_post_wifi_rejects_bad_country_code(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[wifi]\nssid = ""\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, body = _post(server.port, _wifi_form(ssid="HomeNet", country="USA"))
        assert status == 400
        assert "two-letter code" in body
    finally:
        server.stop()
    assert tomllib.loads(path.read_text()).get("wifi", {}).get("ssid", "") == ""


def test_post_unknown_section_is_rejected(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, _ = _post(server.port, {"section": "nonsense"})
        assert status == 400
    finally:
        server.stop()


def test_post_unknown_path_404s(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request(
            "POST",
            "/nope",
            body="",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": f"http://127.0.0.1:{server.port}",
            },
        )
        resp = conn.getresponse()
        resp.read()
        status = resp.status
        conn.close()
        assert status == 404
    finally:
        server.stop()


def test_post_with_no_config_file_loaded_explains_rather_than_crashes():
    settings = Settings()
    assert settings.source_path is None
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, body = _post(server.port, _form_for(settings, "scoreboard"))
        assert status == 500
        assert "No config file" in body
    finally:
        server.stop()


def test_post_reports_write_failure_instead_of_500_traceback(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    path.unlink()
    path.mkdir()  # any write to `path` now fails with IsADirectoryError
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, body = _post(
            server.port, _form_for(settings, "scoreboard", favourite_team="tor")
        )
        assert status == 500
        assert "could not" in body.lower()
    finally:
        server.stop()


def test_get_wifi_saved_banner_warns_about_network_interruption():
    settings = Settings()
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/?saved=wifi"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "Wi-Fi settings saved" in body
        assert "network" in body.lower()
    finally:
        server.stop()


def _rotation_form(action: str, rows: list[dict[str, str]]) -> dict[str, str]:
    data = {"section": "rotation", "rotation_action": action}
    for i, row in enumerate(rows):
        data[f"rotation_screen_{i}"] = row["screen"]
        data[f"rotation_seconds_{i}"] = row["seconds"]
        data[f"rotation_order_{i}"] = row["order"]
    return data


def test_get_renders_rotation_rows_from_settings(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text(
        '[[rotation]]\nscreen = "standings"\nseconds = 20\n'
        '[[rotation]]\nscreen = "clock"\nseconds = 10\n'
    )
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert 'name="rotation_screen_0"' in body
        assert 'value="standings" selected' in body
        assert 'name="rotation_seconds_0" value="20.0"' in body
        assert 'name="rotation_screen_1"' in body
        assert 'value="clock" selected' in body
    finally:
        server.stop()


def test_post_rotation_add_row_does_not_save(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, body = _post(server.port, _rotation_form("add_row", []))
        assert status == 200
        assert 'name="rotation_screen_0"' in body
    finally:
        server.stop()
    assert Settings.load(path).rotation == []


def test_post_rotation_add_row_respects_max_rows(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    rows = [{"screen": "clock", "seconds": "5", "order": str(i + 1)} for i in range(8)]
    try:
        status, _, body = _post(server.port, _rotation_form("add_row", rows))
        assert status == 200
        assert "Maximum 8 rows" in body
    finally:
        server.stop()


def test_post_rotation_remove_row(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    rows = [
        {"screen": "standings", "seconds": "20", "order": "1"},
        {"screen": "clock", "seconds": "10", "order": "2"},
    ]
    try:
        status, _, body = _post(server.port, _rotation_form("remove_row_0", rows))
        assert status == 200
        assert body.count('name="rotation_screen_') == 1
        assert 'name="rotation_screen_0"' in body
        assert 'value="clock" selected' in body
        assert 'name="rotation_seconds_0" value="10"' in body
    finally:
        server.stop()
    assert Settings.load(path).rotation == []


def test_post_rotation_save_writes_sorted_by_order(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    rows = [
        {"screen": "clock", "seconds": "10", "order": "2"},
        {"screen": "standings", "seconds": "20", "order": "1"},
    ]
    try:
        status, headers, _ = _post(server.port, _rotation_form("save", rows))
        assert status == 303
        assert headers["Location"] == "/?saved=rotation"
    finally:
        server.stop()
    reloaded = Settings.load(path)
    assert [e.screen for e in reloaded.rotation] == ["standings", "clock"]
    assert [e.seconds for e in reloaded.rotation] == [20.0, 10.0]


def test_post_rotation_save_rejects_bad_screen_and_seconds(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    rows = [
        {"screen": "bogus", "seconds": "notanumber", "order": "1"},
    ]
    try:
        status, _, body = _post(server.port, _rotation_form("save", rows))
        assert status == 400
        assert "unknown screen" in body
    finally:
        server.stop()
    assert Settings.load(path).rotation == []


def test_get_shows_rotation_saved_banner():
    settings = Settings()
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/?saved=rotation"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "Idle rotation settings saved" in body
    finally:
        server.stop()


def test_default_wifi_restart_invokes_systemctl(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "nhl_scoreboard.status_server.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    _restart_wifi_provisioning()
    # Fire-and-forget on a background thread -- give it a moment to run.
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls
    (cmd,), kwargs = calls[0]
    assert cmd == ["systemctl", "restart", "scoreboard-provision.service"]
    assert kwargs["check"] is False


def test_post_reboot_triggers_reboot_and_requires_same_origin(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    calls: list[int] = []
    server = StatusServer(
        snapshot=dict,
        port=0,
        settings=lambda: settings,
        host="127.0.0.1",
        reboot=lambda: calls.append(1),
    )
    server.start()
    try:

        def post_reboot(origin: bool) -> int:
            headers = {"Origin": f"http://127.0.0.1:{server.port}"} if origin else {}
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            try:
                conn.request("POST", "/reboot", body="", headers=headers)
                resp = conn.getresponse()
                resp.read()
                return resp.status
            finally:
                conn.close()

        assert post_reboot(origin=False) == 403
        assert calls == []
        assert post_reboot(origin=True) == 200
        assert calls == [1]
    finally:
        server.stop()


def test_panel_rgb_sequence_is_restart_required_select_with_six_permutations(tmp_path):
    field = next(f for f in _FIELDS_BY_SECTION["panel"] if f.key == "rgb_sequence")
    assert field.kind == "select"
    assert field.restart_required
    assert sorted(field.choices) == sorted(["RGB", "RBG", "GRB", "GBR", "BRG", "BGR"])
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    settings = Settings.load(path)
    server = StatusServer(snapshot=dict, port=0, settings=lambda: settings, host="127.0.0.1")
    server.start()
    try:
        status, _, _ = _post(server.port, _form_for(settings, "panel", rgb_sequence="RBG"))
        assert status == 303
        status, _, _ = _post(server.port, _form_for(settings, "panel", rgb_sequence="XYZ"))
        assert status == 400
    finally:
        server.stop()
    assert Settings.load(path).panel.rgb_sequence == "RBG"


def test_default_reboot_invokes_systemctl(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "nhl_scoreboard.status_server.subprocess.run",
        lambda *args, **kwargs: calls.append(args),
    )
    _reboot_board()
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls == [(["systemctl", "reboot"],)]
