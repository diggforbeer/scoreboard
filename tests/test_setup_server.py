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
