"""Tests for the WiFi setup page (#132)."""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request

from nhl_scoreboard.setup_server import SetupServer


def _post(url: str, data: str) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data.encode("utf-8"), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _get_without_following_redirects(port: int, path: str) -> http.client.HTTPResponse:
    """A GET whose 3xx response is not auto-followed -- urlopen's default
    opener would silently chase a redirect to "/" and hide the very
    behaviour these captive-portal-probe tests exist to check."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    return conn.getresponse()


def test_setup_page_lists_cached_networks():
    server = SetupServer(
        networks=lambda: ["Home Wifi", "Guest Network"],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert "Home Wifi" in body
        assert "Guest Network" in body
        assert 'name="ssid_other"' in body
        assert 'name="password"' in body
        # Show-password toggle: unnamed so it is never submitted, and the
        # field stays masked by default (also when JS is unavailable).
        assert 'id="show-password"' in body
        assert 'name="show' not in body
        assert 'type="password" name="password"' in body
    finally:
        server.stop()


def test_setup_page_with_no_cached_networks_still_offers_manual_entry():
    server = SetupServer(
        networks=lambda: [], on_submit=lambda ssid, password: None, port=0, host="127.0.0.1"
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert 'name="ssid_other"' in body
    finally:
        server.stop()


def test_setup_page_escapes_network_names():
    server = SetupServer(
        networks=lambda: ["<script>alert(1)</script>"],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body
    finally:
        server.stop()


def test_submitting_a_picked_network_calls_on_submit():
    submitted = []
    server = SetupServer(
        networks=lambda: ["Home Wifi"],
        on_submit=lambda ssid, password: submitted.append((ssid, password)),
        port=0,
        host="127.0.0.1",
    )
    server.start()
    try:
        status, body = _post(
            f"http://127.0.0.1:{server.port}/", "ssid_choice=Home+Wifi&password=hunter2"
        )
        assert status == 200
        assert "Home Wifi" in body
        assert submitted == [("Home Wifi", "hunter2")]
    finally:
        server.stop()


def test_submitting_a_manual_ssid_calls_on_submit():
    submitted = []
    server = SetupServer(
        networks=lambda: ["Home Wifi"],
        on_submit=lambda ssid, password: submitted.append((ssid, password)),
        port=0,
        host="127.0.0.1",
    )
    server.start()
    try:
        status, _ = _post(
            f"http://127.0.0.1:{server.port}/", "ssid_choice=Home+Wifi&ssid_other=Hidden+Net"
        )
        assert status == 200
        assert submitted == [("Hidden Net", None)]
    finally:
        server.stop()


def test_open_network_password_is_none_not_empty_string():
    submitted = []
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: submitted.append((ssid, password)),
        port=0,
        host="127.0.0.1",
    )
    server.start()
    try:
        _post(f"http://127.0.0.1:{server.port}/", "ssid_other=OpenNet&password=")
        assert submitted == [("OpenNet", None)]
    finally:
        server.stop()


def test_submitting_with_no_ssid_at_all_is_rejected_without_calling_on_submit():
    submitted = []
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: submitted.append((ssid, password)),
        port=0,
        host="127.0.0.1",
    )
    server.start()
    try:
        status, body = _post(f"http://127.0.0.1:{server.port}/", "password=hunter2")
        assert status == 400
        assert "network name" in body.lower()
        assert submitted == []
    finally:
        server.stop()


# --------------------------------------------------------------------------
# captive-portal probes: must never get the OS's expected "no portal here"
# response, or the "sign in to network" prompt never fires.
# --------------------------------------------------------------------------


def test_apple_probe_is_redirected_to_setup_page():
    server = SetupServer(
        networks=lambda: [], on_submit=lambda ssid, password: None, port=0, host="127.0.0.1"
    )
    server.start()
    try:
        resp = _get_without_following_redirects(server.port, "/hotspot-detect.html")
        assert resp.status == 302
        assert resp.getheader("Location") == "/"
    finally:
        server.stop()


def test_android_probe_is_redirected_to_setup_page():
    server = SetupServer(
        networks=lambda: [], on_submit=lambda ssid, password: None, port=0, host="127.0.0.1"
    )
    server.start()
    try:
        resp = _get_without_following_redirects(server.port, "/generate_204")
        assert resp.status == 302
        assert resp.getheader("Location") == "/"
    finally:
        server.stop()


def test_windows_ncsi_probe_is_redirected_to_setup_page():
    server = SetupServer(
        networks=lambda: [], on_submit=lambda ssid, password: None, port=0, host="127.0.0.1"
    )
    server.start()
    try:
        resp = _get_without_following_redirects(server.port, "/connecttest.txt")
        assert resp.status == 302
        assert resp.getheader("Location") == "/"
    finally:
        server.stop()


def test_unknown_path_is_also_redirected_since_dns_is_wildcarded():
    """Any hostname a phone probes resolves here (dnsmasq's wildcard DNS) --
    an unrecognised path still needs to land on the setup page, not a 404."""
    server = SetupServer(
        networks=lambda: [], on_submit=lambda ssid, password: None, port=0, host="127.0.0.1"
    )
    server.start()
    try:
        resp = _get_without_following_redirects(server.port, "/whatever")
        assert resp.status == 302
        assert resp.getheader("Location") == "/"
    finally:
        server.stop()


# --------------------------------------------------------------------------
# display check (#172): confirm the panel is actually showing something
# before assuming a wrong hardware_mapping isn't the problem.
# --------------------------------------------------------------------------


def test_page_shows_current_mapping_when_not_in_a_trial():
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
        panel_state=lambda: ("regular", False, False),
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "regular" in body
        assert "try a different display type" in body
        # Not gated: the WiFi form is present and usable.
        assert 'name="ssid_other"' in body
        assert "Yes, it&#x27;s working" not in body and "Yes, it's working" not in body
    finally:
        server.stop()


def test_page_gates_the_wifi_form_while_a_trial_is_in_progress():
    server = SetupServer(
        networks=lambda: ["Home Wifi"],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
        panel_state=lambda: ("adafruit-hat", True, False),
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "adafruit-hat" in body
        assert "Yes, it&#39;s working" in body or "Yes, it's working" in body
        assert 'name="ssid_other"' not in body
        assert "Confirm the display" in body
    finally:
        server.stop()


def test_posting_wifi_form_while_gated_is_rejected_and_does_not_call_on_submit():
    submitted = []
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: submitted.append((ssid, password)),
        port=0,
        host="127.0.0.1",
        panel_state=lambda: ("adafruit-hat", True, False),
    )
    server.start()
    try:
        status, _ = _post(f"http://127.0.0.1:{server.port}/", "ssid_other=Home&password=")
        assert status == 409
        assert submitted == []
    finally:
        server.stop()


def test_panel_next_calls_the_callback_and_shows_the_restarting_page():
    calls = []
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
        on_panel_next=lambda chosen: calls.append(chosen) or "adafruit-hat",
    )
    server.start()
    try:
        status, body = _post(f"http://127.0.0.1:{server.port}/panel/next", "")
        assert status == 200
        assert calls == [None], "the plain button names no board: try the next one"
        assert "Adafruit RGB Matrix Bonnet or HAT" in body, "the board's name, not the driver's"
        assert "Restarting" in body
    finally:
        server.stop()


def test_panel_next_failure_is_reported_without_a_restarting_page():
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
        on_panel_next=lambda chosen: None,
    )
    server.start()
    try:
        status, body = _post(f"http://127.0.0.1:{server.port}/panel/next", "")
        assert status == 500
        assert "Could not save" in body
    finally:
        server.stop()


def test_panel_confirm_calls_the_callback_and_redirects_home():
    calls = []
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
        on_panel_confirm=lambda: calls.append(1),
    )
    server.start()
    try:
        resp = _get_without_following_redirects(server.port, "/")  # sanity: page loads
        assert resp.status == 200
        status, _ = _post(f"http://127.0.0.1:{server.port}/panel/confirm", "")
        assert status == 200  # urlopen follows the redirect to "/"
        assert calls == [1]
    finally:
        server.stop()


def test_panel_card_after_a_full_lap_points_at_the_wiring():
    from nhl_scoreboard.setup_server import _render_page

    page = _render_page(
        [], panel_mapping="adafruit-hat-pwm", panel_in_trial=True, panel_tried_all=True
    ).decode()
    assert "ribbon cable" in page
    assert "Yes, it&#x27;s working" in page or "Yes, it's working" in page
    assert "/panel/next" in page, "still free to go round again"


def test_panel_card_mid_lap_does_not_blame_the_wiring():
    from nhl_scoreboard.setup_server import _render_page

    page = _render_page([], panel_mapping="adafruit-hat", panel_in_trial=True).decode()
    assert "ribbon cable" not in page


def test_picking_a_board_passes_it_to_the_callback():
    """#172's original ask: jump straight to the board you know you have."""
    calls = []
    server = SetupServer(
        networks=lambda: [],
        on_submit=lambda ssid, password: None,
        port=0,
        host="127.0.0.1",
        on_panel_next=lambda chosen: calls.append(chosen) or chosen,
    )
    server.start()
    try:
        status, body = _post(
            f"http://127.0.0.1:{server.port}/panel/next", "mapping=adafruit-hat-pwm"
        )
        assert status == 200
        assert calls == ["adafruit-hat-pwm"]
        assert "solder mod" in body
    finally:
        server.stop()


def test_page_names_boards_not_driver_settings():
    from nhl_scoreboard.config import PANEL_HARDWARE_MAPPING_CHOICES
    from nhl_scoreboard.setup_server import _render_page

    page = _render_page([], panel_mapping="adafruit-hat").decode()
    assert "Display type is set to <b>Adafruit RGB Matrix Bonnet or HAT</b>" in page
    for mapping in PANEL_HARDWARE_MAPPING_CHOICES:
        assert f'<option value="{mapping}"' in page, f"{mapping} missing from the picker"
    assert '<option value="adafruit-hat" selected>' in page, "current board preselected"


def test_a_hand_edited_mapping_still_shows_as_is():
    from nhl_scoreboard.setup_server import _render_page

    page = _render_page([], panel_mapping="compute-module").decode()
    assert "<b>compute-module</b>" in page
