"""WiFi setup page served while the board's own first-boot AP is up (#132).

Sub-issue of #116, depending on the AP/DHCP/DNS infrastructure #131 already
built. Stdlib-only (`http.server`) -- this page genuinely must work with
zero network connectivity (it's the mechanism for getting the board online
at all), unlike `admin_server.py`, which only needs to work once the board
already has real connectivity. Scope is strictly the page and
captive-portal probe handling -- collecting a network choice and a
password and handing it off to a submission file. Actually joining that
network is #133's job, not this module's: this only ever writes the
submission, never touches `iwctl`/iwd itself.

No live network scan here: `nhl-scoreboard-setup-ap` already established
(#132's issue discussion, corroborated against real-hardware reports on
this exact brcmfmac chip family) that this chip cannot scan for networks
while its own AP is active -- concurrent AP+STA needs a module parameter
this image doesn't set, and is reported to crash this chip's firmware
under concurrent use even when it is set. So the picker renders whatever
`networks()` returns -- a snapshot cached by the setup-ap script from a
scan taken moments before the AP came up, not a live list -- and a plain
text SSID field is always shown alongside it, never hidden behind the
picker, so a network missing from that stale snapshot (out of range at
that exact moment, hidden/non-broadcasting, or one that only appeared
afterward) still has a way in.
"""

from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

log = logging.getLogger(__name__)

#: Paths real devices probe to decide whether a network is "captive" (behind
#: a login/consent page) before treating it as having real internet access.
#: dnsmasq's wildcard DNS (see nhl-scoreboard-setup-ap) already resolves
#: every hostname a probe might use -- apple.com, gstatic.com,
#: msftconnecttest.com, whatever -- to this board, so a probe's *path* is
#: the only thing left to match on; the Host header it arrives with is
#: irrelevant and never checked. Answering any of these with the real
#: fixed content/204 the OS expects would make it conclude there is no
#: portal and never show the "Sign in to network" prompt at all -- the
#: entire point here is to fail that check on purpose, the same technique
#: countless public-WiFi captive portals already use.
_CAPTIVE_PROBE_PATHS = frozenset(
    {
        "/hotspot-detect.html",  # Apple (captive.apple.com)
        "/library/test/success.html",  # Apple, older/alternate path
        "/generate_204",  # Android (connectivitycheck.gstatic.com)
        "/gen_204",  # Android, seen on some OEM builds
        "/connecttest.txt",  # Windows NCSI (msftconnecttest.com)
        "/ncsi.txt",  # Windows NCSI, older path
    }
)


def _render_page(networks: list[str], *, error: str | None = None) -> bytes:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    picker_html = "".join(
        f'<label><input type="radio" name="ssid_choice" value="{html.escape(n)}"> '
        f"{html.escape(n)}</label><br>"
        for n in networks
    )
    if not networks:
        picker_html = "<p>No nearby networks were seen before setup mode started.</p>"
    page = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NHL Scoreboard setup</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #eee; padding: 1.5rem; max-width: 28rem }}
h1 {{ font-size: 1.2rem; }}
fieldset {{ border: 1px solid #444; margin-bottom: 1rem; }}
label {{ display: inline-block; margin: 0.25rem 0; }}
input[type=text], input[type=password] {{ width: 100%; box-sizing: border-box; padding: .4rem }}
button {{ padding: 0.5rem 1.5rem; }}
.error {{ color: #f66; }}
</style>
</head>
<body>
<h1>Join a WiFi network</h1>
{error_html}
<form method="POST" action="/">
<fieldset>
<legend>Nearby networks</legend>
{picker_html}
</fieldset>
<label>Or enter a network name manually:<br>
<input type="text" name="ssid_other" placeholder="Network name"></label>
<p><label>Password (leave blank for an open network):<br>
<input type="password" name="password"></label></p>
<button type="submit">Join</button>
</form>
</body>
</html>
"""
    return page.encode("utf-8")


def _render_confirmation(ssid: str) -> bytes:
    page = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>NHL Scoreboard setup</title></head>
<body style="font-family: sans-serif; background: #111; color: #eee; padding: 1.5rem;">
<h1>Saved</h1>
<p>Recorded &ldquo;{html.escape(ssid)}&rdquo;. The board will use it the next time it looks
for a network to join.</p>
</body>
</html>
"""
    return page.encode("utf-8")


def _choose_ssid(form: dict[str, list[str]]) -> str:
    """The manual text field wins whenever it's non-empty, else the picked radio.

    A person who typed a name clearly means to override whatever they may
    have also left selected in the picker (browsers keep an old radio
    selection around even after text is typed elsewhere in the same form).
    """
    manual = form.get("ssid_other", [""])[0].strip()
    if manual:
        return manual
    return form.get("ssid_choice", [""])[0].strip()


def _make_handler(
    networks: Callable[[], list[str]],
    on_submit: Callable[[str, str | None], None],
) -> type[BaseHTTPRequestHandler]:
    class SetupRequestHandler(BaseHTTPRequestHandler):
        server_version = "nhl-scoreboard-setup/1.0"

        def _send_html(self, body: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect_to_setup_page(self) -> None:
            # A relative Location resolves against whatever host the client
            # thinks it just asked (captive.apple.com, gstatic.com, ...) --
            # which is fine, since dnsmasq's wildcard DNS already points
            # every one of those back at this board.
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send_html(_render_page(networks()))
                return
            if self.path in _CAPTIVE_PROBE_PATHS:
                log.debug("Captive-portal probe on %s; redirecting to the setup page", self.path)
            self._redirect_to_setup_page()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(body, keep_blank_values=True)
            ssid = _choose_ssid(form)
            if not ssid:
                self._send_html(
                    _render_page(networks(), error="Enter or choose a network name."),
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            password = form.get("password", [""])[0]
            on_submit(ssid, password or None)
            self._send_html(_render_confirmation(ssid))

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("setup server: %s", format % args)

    return SetupRequestHandler


class SetupServer:
    """Serves the WiFi setup page on a background thread until ``stop()``."""

    def __init__(
        self,
        networks: Callable[[], list[str]],
        on_submit: Callable[[str, str | None], None],
        port: int,
        host: str = "0.0.0.0",  # intentional: reachable only from the board's own AP anyway
    ) -> None:
        self._networks = networks
        self._on_submit = on_submit
        self._host = host
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._httpd is not None:
            return self._httpd.server_address[1]
        return self._port

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer(
            (self._host, self._port), _make_handler(self._networks, self._on_submit)
        )
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="setup-server", daemon=True
        )
        self._thread.start()
        log.info("WiFi setup page listening on http://%s:%d/", self._host, self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
