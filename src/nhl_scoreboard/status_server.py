"""Web status page for headless debugging, plus a config editor (#48, #110).

Stdlib-only (`http.server`), matching the project's "no heavy dependencies on
the device" stance. Serves a status snapshot it has no knowledge of (handed
to it as a callable -- see ``ScoreboardApp.status_snapshot``) alongside a
form-per-section editor for ``scoreboard.toml``, built from the ``Settings``
dataclasses and the raw ``[wifi]`` table (which isn't part of ``Settings``
at all -- see ``config.py``).

No auth, bound to 0.0.0.0 by default: this is a status/config page for a
device already trusted on the local network, not something to port-forward.
A submitted form is checked against the request's own Host header (see
``_is_same_origin``) to close the classic CSRF vector -- a malicious page
elsewhere on the LAN auto-submitting a form against the board's IP -- without
adding a login flow.

``do_POST`` never mutates the live, shared ``Settings`` object directly: it
loads a throwaway copy of the config file, saves the update into *that*, and
lets ``ScoreboardApp.reload_config_if_changed()`` -- already polled every
main-loop tick -- pick the change up from disk. ``Settings.save()``
(``config.py``) mutates ``self`` synchronously as part of writing the file;
doing that to ``ScoreboardApp.settings`` from this request-handling thread
while the main loop thread is mid-iteration reading it would be an undefined
interleaving, not just a stale read.
"""

from __future__ import annotations

import html
import logging
import subprocess
import threading
import tomllib
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import ConfigWriteError, Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Field:
    section: str
    key: str
    kind: str  # "bool", "int", "float", "str", "password", "select", "country"
    label: str
    choices: tuple[str, ...] = ()
    #: [panel]'s geometry/electrical fields are baked into the already-
    #: constructed RGBMatrix and need a process restart to take effect
    #: (see config.py's Settings.reload_config_if_changed docstring). Still
    #: shown and saved -- just labelled, per #48/#51's explicit decision not
    #: to omit them.
    restart_required: bool = False


#: Declarative field list, one entry per editable value. Deliberately not
#: derived from the dataclasses themselves (via `dataclasses.fields()`):
#: that would only give names/types, not the human labels, valid-value
#: sets, or the live/restart-required split, which live nowhere else.
#: Grouped contiguously by section -- `_FIELDS_BY_SECTION` relies on that.
_FIELDS: tuple[_Field, ...] = (
    _Field(
        "scoreboard", "favourite_team", "str", "Favourite team (3-letter abbrev, blank for none)"
    ),
    _Field("scoreboard", "timezone", "str", "Timezone (IANA name, e.g. America/Chicago)"),
    _Field("scoreboard", "rotation", "select", "Rotation", choices=("favourite", "all")),
    _Field("scoreboard", "rotate_seconds", "float", "Seconds per game in rotation"),
    _Field("scoreboard", "poll_seconds", "float", "Score poll interval (seconds)"),
    _Field("scoreboard", "live_poll_seconds", "float", "Live score poll interval (seconds)"),
    _Field("scoreboard", "countdown_hours", "float", "Countdown window before puck drop (hours)"),
    _Field("scoreboard", "final_hold_minutes", "float", "Final score hold time (minutes)"),
    _Field("scoreboard", "goal_flash_seconds", "float", "Goal celebration duration (seconds)"),
    _Field("scoreboard", "show_clock_when_idle", "bool", "Show clock when there are no games"),
    _Field(
        "scoreboard", "show_clock_between_games", "bool", "Show clock between favourite's games"
    ),
    _Field("scoreboard", "show_logos", "bool", "Show team logos"),
    _Field("scoreboard", "logo_variant", "select", "Logo variant", choices=("dark", "light")),
    _Field("scoreboard", "show_standings", "bool", "Show favourite's playoff standings"),
    _Field("scoreboard", "prefer_favourite", "bool", "Prefer favourite when choosing a game"),
    _Field("audio", "enabled", "bool", "Goal horn enabled"),
    _Field("audio", "device", "str", "ALSA device (blank for default)"),
    _Field("audio", "horn_dir", "str", "Horn directory override (blank for default)"),
    _Field("status", "enabled", "bool", "Status page enabled"),
    _Field("status", "port", "int", "Status page port"),
    _Field("night_mode", "enabled", "bool", "Night mode enabled"),
    _Field("night_mode", "start_time", "str", "Dim window start (24-hour HH:MM)"),
    _Field("night_mode", "end_time", "str", "Dim window end (24-hour HH:MM)"),
    _Field("night_mode", "dim_brightness", "int", "Dimmed brightness (0-100)"),
    _Field("night_mode", "suppress_scope", "select", "Suppress scope", choices=("tracked", "all")),
    _Field("night_mode", "cooldown_minutes", "float", "Cooldown after game ends (minutes)"),
    _Field("panel", "brightness", "int", "Brightness (0-100)"),
    _Field("panel", "auto_brightness", "bool", "Auto brightness from ambient sensor"),
    _Field("panel", "min_brightness", "int", "Auto-brightness minimum"),
    _Field("panel", "max_brightness", "int", "Auto-brightness maximum"),
    _Field(
        "panel", "brightness_poll_seconds", "float", "Brightness sensor poll interval (seconds)"
    ),
    _Field("panel", "rows", "int", "Rows per panel", restart_required=True),
    _Field("panel", "cols", "int", "Columns per panel", restart_required=True),
    _Field("panel", "chain_length", "int", "Chain length", restart_required=True),
    _Field("panel", "parallel", "int", "Parallel chains", restart_required=True),
    _Field(
        "panel",
        "hardware_mapping",
        "select",
        "Hardware mapping",
        choices=("regular", "adafruit-hat", "adafruit-hat-pwm"),
        restart_required=True,
    ),
    _Field("panel", "gpio_slowdown", "int", "GPIO slowdown", restart_required=True),
    _Field("panel", "pwm_bits", "int", "PWM bits", restart_required=True),
    _Field("panel", "pwm_lsb_nanoseconds", "int", "PWM LSB nanoseconds", restart_required=True),
    _Field(
        "panel",
        "disable_hardware_pulsing",
        "bool",
        "Disable hardware pulsing",
        restart_required=True,
    ),
    _Field("panel", "pixel_mapper", "str", "Pixel mapper", restart_required=True),
    _Field(
        "panel",
        "limit_refresh_rate_hz",
        "int",
        "Refresh rate limit (Hz, 0 = unlimited)",
        restart_required=True,
    ),
    # [wifi] isn't part of Settings at all (see config.py) -- scoreboard-
    # provision reads it straight out of the raw TOML. Saving still goes
    # through Settings.save(), which writes any {section: {key: value}}
    # regardless of whether that section is one of its own dataclass fields.
    _Field("wifi", "ssid", "str", "Wi-Fi SSID (blank to use ethernet)"),
    _Field("wifi", "password", "password", "Wi-Fi password"),
    _Field("wifi", "country", "country", "Regulatory country code (2 letters, e.g. US)"),
)

_SECTIONS: tuple[tuple[str, str], ...] = (
    ("scoreboard", "Scoreboard"),
    ("audio", "Audio"),
    ("status", "Status page"),
    ("night_mode", "Night mode"),
    ("panel", "Panel"),
    ("wifi", "Wi-Fi"),
)
_SECTION_TITLES: dict[str, str] = dict(_SECTIONS)

_FIELDS_BY_SECTION: dict[str, tuple[_Field, ...]] = {
    section: tuple(f for f in _FIELDS if f.section == section) for section, _ in _SECTIONS
}


def _current_value(settings: Settings, wifi_raw: dict[str, Any], field: _Field) -> Any:
    if field.section == "wifi":
        return wifi_raw.get(field.key, "")
    return getattr(getattr(settings, field.section), field.key)


def _read_wifi_raw(source_path: Path | None) -> dict[str, Any]:
    """The raw ``[wifi]`` table, straight from disk -- Settings has no model for it."""
    if source_path is None:
        return {}
    try:
        with source_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    wifi = raw.get("wifi", {})
    return wifi if isinstance(wifi, dict) else {}


def _coerce_section(
    fields: tuple[_Field, ...], form: dict[str, list[str]]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Turn posted form strings into typed values, or per-field error messages.

    A checkbox left unchecked simply isn't present in ``form`` at all -- that
    means False, not "leave the old value alone" (#110 explicitly calls this
    out: a naive pass-through would let `bool("false")` silently stay True).
    """
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for field in fields:
        raw = form.get(field.key)
        if field.kind == "bool":
            values[field.key] = raw is not None
            continue
        text = (raw[0] if raw else "").strip()
        if field.kind == "int":
            try:
                values[field.key] = int(text)
            except ValueError:
                errors[field.key] = f"{field.label} must be a whole number"
        elif field.kind == "float":
            try:
                values[field.key] = float(text)
            except ValueError:
                errors[field.key] = f"{field.label} must be a number"
        elif field.kind == "select":
            if text not in field.choices:
                errors[field.key] = f"{field.label} must be one of: {', '.join(field.choices)}"
            else:
                values[field.key] = text
        elif field.kind == "country":
            if text and not (len(text) == 2 and text.isalpha()):
                errors[field.key] = f"{field.label} must be a two-letter code, e.g. US"
            else:
                values[field.key] = text.upper()
        else:  # str, password
            values[field.key] = text
    return values, errors


# -- rendering ---------------------------------------------------------------


def _render_html(snapshot: dict[str, str]) -> bytes:
    """The read-only snapshot table alone, as its own page.

    Kept separate from `_render_page` (which adds the config editor) so a
    caller that only has a snapshot -- no `Settings` -- still gets a working
    page; also what the existing snapshot-rendering tests exercise directly.
    """
    rows = _snapshot_rows(snapshot)
    return _PAGE_TEMPLATE.format(banner="", rows=rows, sections="").encode("utf-8")


def _snapshot_rows(snapshot: dict[str, str]) -> str:
    return "".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>"
        for key, value in snapshot.items()
    )


_PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>NHL Scoreboard status</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #eee; padding: 2rem; max-width: 40rem; }}
h1 {{ font-size: 1.2rem; }}
h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
h3 {{ font-size: 1rem; margin-bottom: 0.25rem; }}
table {{ border-collapse: collapse; margin-bottom: 1rem; }}
th, td {{ text-align: left; padding: 0.25rem 1.5rem 0.25rem 0; }}
th {{ color: #888; font-weight: normal; white-space: nowrap; }}
form.section {{
  border: 1px solid #333; border-radius: 4px; padding: 0.75rem 1rem; margin-bottom: 1rem;
}}
.field {{ margin: 0.5rem 0; }}
.field input[type=text], .field input[type=password], .field input[type=number], .field select {{
  width: 100%; max-width: 20rem; box-sizing: border-box;
}}
.hint {{ color: #aaa; font-size: 0.85rem; }}
.restart-note {{ color: #d9a441; font-size: 0.8rem; }}
.field-error {{ color: #e06c6c; font-size: 0.85rem; }}
.banner-ok {{ color: #6cbf6c; }}
.banner-error {{ color: #e06c6c; }}
button {{ margin-top: 0.5rem; }}
</style>
</head>
<body>
<h1>NHL Scoreboard status</h1>
{banner}
<table>{rows}</table>
{sections}
</body>
</html>
"""


def _render_field(
    field: _Field,
    settings: Settings,
    wifi_raw: dict[str, Any],
    error: str | None,
    submitted_raw: str | None,
) -> str:
    current = _current_value(settings, wifi_raw, field)
    restart_note = (
        ' <span class="restart-note">(applies after restart)</span>'
        if field.restart_required
        else ""
    )
    error_html = f'<div class="field-error">{html.escape(error)}</div>' if error else ""

    if field.kind == "bool":
        checked = submitted_raw == "true" if submitted_raw is not None else bool(current)
        input_html = (
            f'<input type="checkbox" name="{field.key}" value="true"'
            f"{' checked' if checked else ''}>"
        )
        return (
            f'<div class="field"><label>{input_html} {html.escape(field.label)}'
            f"{restart_note}</label>{error_html}</div>"
        )

    value = submitted_raw if submitted_raw is not None else str(current)
    if field.kind == "select":
        options = "".join(
            f'<option value="{html.escape(choice)}"'
            f"{' selected' if choice == value else ''}>{html.escape(choice)}</option>"
            for choice in field.choices
        )
        input_html = f'<select name="{field.key}">{options}</select>'
    elif field.kind == "password":
        # Prefilled in cleartext, same as every other field: the password
        # is already stored in cleartext in scoreboard.toml (config.py has
        # no encryption story for it), and this page already has no login
        # -- see the module docstring. type="password" here is just so a
        # shoulder-surfer glancing at the screen doesn't read it off, not a
        # confidentiality boundary against anyone who can reach this page.
        input_html = f'<input type="password" name="{field.key}" value="{html.escape(value)}">'
    elif field.kind in ("int", "float"):
        step = "1" if field.kind == "int" else "any"
        input_html = (
            f'<input type="number" step="{step}" name="{field.key}" value="{html.escape(value)}">'
        )
    else:  # str, country
        input_html = f'<input type="text" name="{field.key}" value="{html.escape(value)}">'

    return (
        f'<div class="field"><label>{html.escape(field.label)}{restart_note}<br>'
        f"{input_html}</label>{error_html}</div>"
    )


def _render_section(
    section: str,
    title: str,
    settings: Settings,
    wifi_raw: dict[str, Any],
    errors: dict[str, str],
    submitted: dict[str, str],
    form_error: str | None,
) -> str:
    note = ""
    if section == "wifi":
        note = (
            '<p class="hint">Saving this restarts the board\'s Wi-Fi connection. '
            "If the new network doesn't come up, the previous settings are "
            "restored automatically.</p>"
        )
    error_html = f'<p class="banner-error">{html.escape(form_error)}</p>' if form_error else ""
    fields_html = "".join(
        _render_field(field, settings, wifi_raw, errors.get(field.key), submitted.get(field.key))
        for field in _FIELDS_BY_SECTION[section]
    )
    return (
        f'<form method="post" action="/save" class="section">'
        f'<input type="hidden" name="section" value="{section}">'
        f"<h3>{html.escape(title)}</h3>{note}{error_html}{fields_html}"
        f'<button type="submit">Save {html.escape(title)}</button>'
        f"</form>"
    )


def _render_page(
    snapshot: dict[str, str],
    settings: Settings,
    wifi_raw: dict[str, Any],
    *,
    banner_section: str | None = None,
    error_section: str | None = None,
    form_error: str | None = None,
    errors: dict[str, str] | None = None,
    submitted: dict[str, str] | None = None,
) -> bytes:
    errors = errors or {}
    submitted = submitted or {}

    banner = ""
    if banner_section:
        title = _SECTION_TITLES.get(banner_section, banner_section)
        message = f"{html.escape(title)} settings saved."
        if banner_section == "wifi":
            message += (
                " Applying the new Wi-Fi settings now -- the board's network "
                "connection may drop briefly."
            )
        banner = f'<p class="banner-ok">{message}</p>'

    sections = "".join(
        _render_section(
            section,
            title,
            settings,
            wifi_raw,
            errors if section == error_section else {},
            submitted if section == error_section else {},
            form_error if section == error_section else None,
        )
        for section, title in _SECTIONS
    )
    rows = _snapshot_rows(snapshot)
    return _PAGE_TEMPLATE.format(
        banner=banner, rows=rows, sections=f"<h2>Settings</h2>{sections}"
    ).encode("utf-8")


# -- Wi-Fi live trigger (#51, #110) ------------------------------------------


def _restart_wifi_provisioning() -> None:
    """Live-trigger the boot-time Wi-Fi apply/rollback path without a reboot.

    ``scoreboard-provision.service`` is ``Type=oneshot``/``RemainAfterExit=yes``,
    so `systemctl restart` re-runs ``apply_wifi()`` (and its rollback) on
    demand -- checked before relying on it (#110), not assumed. Fire-and-
    forget on a background thread: the new network can take up to that
    script's own WIFI_CONNECT_TIMEOUT (90s default) to fail over and roll
    back, and the HTTP response to the request that triggered this must not
    block on that.
    """

    def _run() -> None:
        try:
            subprocess.run(
                ["systemctl", "restart", "scoreboard-provision.service"],
                check=False,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("Could not restart scoreboard-provision.service: %s", exc)

    threading.Thread(target=_run, daemon=True, name="wifi-restart").start()


# -- HTTP handler --------------------------------------------------------


def _make_handler(
    snapshot: Callable[[], dict[str, str]],
    settings: Callable[[], Settings],
    wifi_restart: Callable[[], None],
) -> type[BaseHTTPRequestHandler]:
    class StatusRequestHandler(BaseHTTPRequestHandler):
        server_version = "nhl-scoreboard-status/1.0"

        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path not in ("/", "/index.html"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            query = urllib.parse.parse_qs(parsed.query)
            banner_section = (query.get("saved") or [None])[0]
            current = settings()
            body = _render_page(
                snapshot(),
                current,
                _read_wifi_raw(current.source_path),
                banner_section=banner_section,
            )
            self._write_html(HTTPStatus.OK, body)

        def do_POST(self) -> None:
            if self.path not in ("/", "/save"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._is_same_origin():
                self.send_error(HTTPStatus.FORBIDDEN, "Cross-site POST rejected")
                return

            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
            section = (form.get("section") or [""])[0]
            fields = _FIELDS_BY_SECTION.get(section)
            if not fields:
                self.send_error(HTTPStatus.BAD_REQUEST, "Unknown config section")
                return

            values, errors = _coerce_section(fields, form)
            current = settings()
            form_error: str | None = None
            if not errors and current.source_path is None:
                form_error = "No config file is loaded; nothing to save."
            elif not errors:
                try:
                    # A throwaway Settings instance, not `current` -- saving
                    # into the live app's own Settings from this thread
                    # would mutate it out from under the main loop. The main
                    # loop's reload_config_if_changed() picks this up from
                    # disk on its own next tick instead.
                    Settings.from_toml(current.source_path).save({section: values})
                except (OSError, tomllib.TOMLDecodeError) as exc:
                    # from_toml() itself doesn't guard its read (by design --
                    # see reload_config_if_changed(), which wraps every one
                    # of its own calls the same way); the file can still
                    # vanish or go bad between settings() and here.
                    form_error = f"Could not read {current.source_path}: {exc}"
                except ConfigWriteError as exc:
                    form_error = str(exc)

            if errors or form_error:
                submitted = {f.key: (form.get(f.key) or [""])[0] for f in fields}
                body = _render_page(
                    snapshot(),
                    current,
                    _read_wifi_raw(current.source_path),
                    error_section=section,
                    form_error=form_error,
                    errors=errors,
                    submitted=submitted,
                )
                # form_error only fires once field-level errors are already
                # empty (see the elif above), so this is unambiguous.
                status = HTTPStatus.INTERNAL_SERVER_ERROR if form_error else HTTPStatus.BAD_REQUEST
                self._write_html(status, body)
                return

            if section == "wifi":
                wifi_restart()

            self.send_response(HTTPStatus.SEE_OTHER)
            redirect_section = section if section in _FIELDS_BY_SECTION else ""
            safe_section = urllib.parse.quote(redirect_section, safe="")
            self.send_header("Location", f"/?saved={safe_section}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _is_same_origin(self) -> bool:
            """Origin/Referer must match this request's own Host -- CSRF mitigation (#110)."""
            host = self.headers.get("Host", "")
            candidate = self.headers.get("Origin") or self.headers.get("Referer")
            if not host or not candidate:
                return False
            return urllib.parse.urlsplit(candidate).netloc == host

        def _write_html(self, status: HTTPStatus, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("status server: %s", format % args)

    return StatusRequestHandler


class StatusServer:
    """Serves the status/config page on a background thread until ``stop()``."""

    def __init__(
        self,
        snapshot: Callable[[], dict[str, str]],
        port: int,
        settings: Callable[[], Settings],
        host: str = "0.0.0.0",  # intentional: a LAN status page, see module docstring
        wifi_restart: Callable[[], None] | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._settings = settings
        self._host = host
        self._port = port
        self._wifi_restart = wifi_restart or _restart_wifi_provisioning
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port -- resolves a requested port of 0 to the one actually picked."""
        if self._httpd is not None:
            return self._httpd.server_address[1]
        return self._port

    def start(self) -> None:
        handler = _make_handler(self._snapshot, self._settings, self._wifi_restart)
        self._httpd = ThreadingHTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="status-server", daemon=True
        )
        self._thread.start()
        log.info("Status page listening on http://%s:%d/", self._host, self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
