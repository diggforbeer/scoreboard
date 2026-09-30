"""Admin page server: static React build + WebSocket, one port (#178).

Named ``admin_server`` (not ``ws_server``, its name through story 9) since
story 10 made it serve the built frontend too, not just a WebSocket --
started by ``ScoreboardApp`` on the real device now, same as
``StatusServer`` (the page this replaces) was.

Scope, deliberately narrow -- built as vertical slices, not the finished
thing:

* Local-dev only *through story 9*. Not started by ``ScoreboardApp``, not
  wired into ``image/layer/nhl-scoreboard.yaml`` or any systemd unit -- run
  it by hand (``python -m nhl_scoreboard.admin_server``) alongside the
  React dev server. Story 10 changed this -- see below.
* Story 1: prove the pipeline. On connect, sends the installed version once
  (the same value the admin page's status grid already shows, via
  ``updater.installed_version()``).
* Story 2: the first real config section, Audio (``enabled``/``device``/
  ``horn_dir`` -- the smallest section, chosen to prove the read/edit/save
  round trip before a bigger one). Also sends the current ``[audio]``
  values on connect, and handles a ``save`` message the same way
  ``status_server.py``'s ``/save`` POST does: write into a throwaway
  ``Settings`` instance (never the live app's, which this process doesn't
  even have -- it always loads fresh from disk), never mutate anything in
  memory. Deliberately hardcoded per-section rather than generalised over
  every section the way ``status_server.py``'s ``_Field``/
  ``_coerce_section`` machinery is -- one or two sections isn't enough
  evidence yet for what the right shared shape is; that generalisation is
  a later story's job once more sections show the actual pattern.
* Story 3: the idle-rotation screen list (``[[rotation]]``, #150/#151).
  Unlike Audio (a fixed set of scalar fields), this is an ordered,
  variable-length list -- ``config.py``'s ``Settings.save()`` already
  special-cases ``"rotation"`` to replace the whole list rather than patch
  individual keys (see its own docstring), so this just validates the
  incoming list the same way ``config.py``'s own ``_parse_rotation`` does
  (unknown screen, non-positive seconds) and passes it straight through.
  Row order is now just the list's own order -- the numeric "order" field
  and the full-page-round-trip add/remove buttons in
  ``status_server.py``'s HTML version existed *specifically* to work
  around having no client-side JS (#151); now that there's a real one,
  neither is needed, and the frontend does real add/remove/reorder in
  local state before a single Save sends the whole list.
* Story 4: Reboot and Software update -- the first things that are
  actions on the real system, not config file edits, and the first
  place this server actually *pushes* something instead of only
  answering a request. ``updater.check()``/``apply()`` run out of
  process (the same ``systemctl start --no-block
  nhl-scoreboard-update-{now,apply}.service`` units
  ``status_server.py`` already triggers, not reimplemented here) and
  write their result to ``updater.STATE_FILE`` on their own schedule --
  this process has no way to know when that happens except by watching
  for it, which is exactly the "click Check, refresh manually to see if
  anything changed" gap the whole rebuild started from (see CLAUDE.md).
  ``_watch_update_state`` polls that file's mtime every
  ``UPDATE_POLL_SECONDS`` and broadcasts a fresh ``config``/``update``
  message to *every* connected client the moment it changes -- the
  first real use of a client set here, not just request/response on one
  connection. Reboot has no equivalent watch: the board going down *is*
  the confirmation, and there's nothing left running to report back.
* Story 5: Scoreboard -- 16 scalar fields (bool/str/float, one select),
  the biggest section yet. Every earlier docstring here said hardcoding
  each section was deliberate because one or two sections wasn't enough
  evidence for the right shared shape; Scoreboard is that third data
  point, and it's the same bool/str/float/select shape Audio already
  had, just five times the field count -- copy-pasting
  ``_coerce_audio`` into a 16-field version would be exactly the
  needless duplication that guidance was postponing, not avoiding.
  ``_coerce_scalar_fields`` + the ``_AUDIO_FIELDS``/
  ``_SCOREBOARD_FIELDS`` specs below replace ``_coerce_audio``, and are
  what a third scalar-field section reaches for too -- ``[[rotation]]``
  stays its own thing, since a variable-length list was never the same
  shape to begin with. Also exposes ``goal_detail_seconds`` and
  ``three_stars_seconds`` (#122, #156), which were never actually added
  to ``status_server.py``'s own HTML form -- a real, small gap in the
  page this is replacing, fixed in passing rather than carried forward.
* Story 6: Status page (``enabled``/``port``) -- the smallest section
  after Audio, and the first ``"int"`` field (``_FieldSpec`` gains that
  kind: ``port`` must be a whole number, not ``8080.5``; everything so
  far had been bool/str/float). Otherwise nothing new -- exactly the
  ``_coerce_scalar_fields`` pattern Scoreboard's story already proved
  out, applied to a two-field section this time.
* Story 7: Panel -- 17 fields (everything ``PanelConfig`` has except
  ``pitch_mm``, which ``status_server.py``'s own form has never exposed
  either: it's informational only, the driver never reads it). The
  biggest section yet, and the first real use of ``_FieldSpec.
  restart_required`` -- 12 of the 17 fields are baked into the
  constructed ``RGBMatrix`` and only take effect after
  ``nhl-scoreboard.service`` restarts (see CLAUDE.md's "wrong
  hardware_mapping is a silent failure" hardware note); only the five
  brightness-related fields hot-apply. The flag is informational for the
  frontend to badge, same as ``status_server.py``'s own per-field
  ``restart_required`` -- it doesn't change validation. Also the second
  real use of the ``"select"`` kind (``hardware_mapping``,
  ``rgb_sequence``), after ``logo_variant`` in Scoreboard.
* Story 8: Night mode (``[night_mode]``, #92) -- 6 fields, none
  ``restart_required`` (night mode is polled live, nothing here is baked
  into a constructed object the way Panel's fields are). The first
  section whose payload can't be a blind ``dataclasses.asdict()`` of the
  settings dataclass: ``NightModeConfig`` carries derived ``start``/
  ``end`` fields (``datetime.time``, ``field(init=False)``, parsed once
  from ``start_time``/``end_time`` in ``__post_init__`` so the app never
  re-parses the strings itself) that aren't JSON-serialisable and were
  never a value a person sets directly -- ``_night_mode_payload`` builds
  the dict by hand instead, naming only the 6 editable fields.
* Story 9: Wi-Fi (``[wifi]``) -- the smallest section yet, one field
  (``connect_timeout_seconds``). ``ssid``/``password``/``country`` live
  in the same TOML table but are deliberately not modelled by
  ``WifiConfig`` at all (``config.py``'s own ``_wifi_config`` filters
  them out before ``_build()`` sees them) -- actually joining a network
  is ``setup_server.py``'s job, the offline-first captive-portal page,
  out of scope for this whole rebuild (see the note right after story
  1). This section only tunes how long a join attempt waits before
  deciding it failed.
* Story 10: deploy to the real device, retire ``status_server.py``. Three
  things landed together, all driven by the same decision (the owner: "we
  can delete the old site, and make this the one that starts on boot"):

  1. **One port serves the built React page and the WebSocket.**
     ``websockets``' own ``process_request`` hook (confirmed present in the
     pinned ``websockets>=13``, tested directly against 17.1 before relying
     on it) intercepts every incoming request; a genuine WebSocket upgrade
     (``Upgrade: websocket`` header -- what a real browser's
     ``new WebSocket(...)`` always sends, checked directly rather than
     assumed) is let through to ``_handle`` as before, anything else is
     served as a static file out of ``ADMIN_DIR`` (``_static_response``),
     falling back to ``index.html`` for this single-page app's one route.
     No reverse proxy, no second port.
  2. **``AdminServer`` wraps ``run()`` on a background thread**, exposing
     the same ``start()``/``stop()``/``port`` shape ``StatusServer`` (the
     class this replaces) had, so ``app.py``'s integration is a small diff
     at the same three call sites ``StatusServer`` was built/started/
     stopped/rebuilt from, not a rewrite of ``ScoreboardApp`` itself.
     ``StatusServer`` ran a blocking ``http.server`` loop in a plain
     thread; this runs its own ``asyncio`` loop in the thread instead,
     since ``run()`` is a coroutine -- ``stop()`` signals it via
     ``asyncio.run_coroutine_threadsafe`` rather than an OS-level shutdown
     call, since there's no ``httpd.shutdown()`` equivalent for a bare
     ``serve()`` context manager.
  3. **The status snapshot moved over too**, not just the config editor:
     ``status_server.py`` served two genuinely different things --
     ``ScoreboardApp.status_snapshot()`` (scene, current game, last poll,
     last error -- read-only "headless debugging" state) alongside the
     HTML-forms editor. Only the editor had a home in the new page through
     story 9; dropping the snapshot too would have been a real regression
     for anyone debugging a board with no HDMI output, so it's ported
     here first. ``SNAPSHOT_PROVIDER`` is the same "handed to it as a
     callable" relationship ``StatusServer``'s own ``snapshot`` parameter
     had -- this module still has no model of what a scene or a game is,
     it just forwards whatever dict it's given. Broadcast on change
     (``_watch_snapshot``), same proven shape as ``_watch_update_state``.

  ``[status]``'s ``enabled``/``port`` fields are reused as-is for this
  server -- same TOML section, same meaning ("is the web admin page on,
  and where"), just a different implementation underneath; an existing
  board's boot-partition config needed no migration. Wi-Fi ``ssid``/
  ``password``/``country`` editing, which ``status_server.py``'s own Wi-Fi
  section had (raw TOML fields, unrelated to ``WifiConfig``, restarting
  ``scoreboard-provision.service`` on save) did **not** carry over --
  explicitly dropped, not an oversight: the AP/captive-portal flow (#131-
  #133) is now the one way to (re)join a network, covering the far more
  common "board has no network yet" case with a real retry/rollback state
  machine; changing an already-online board's Wi-Fi now means walking it
  through that flow (e.g. by disconnecting it) rather than editing a
  field here.

No auth, same trust model ``status_server.py`` (the page this replaces)
had: a LAN-only admin tool, not something to port-forward.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path

import websockets
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from . import updater
from .config import VALID_ROTATION_SCREENS, ConfigWriteError, Settings
from .updater import installed_version

log = logging.getLogger(__name__)

#: Overridable so a second instance (or a test) doesn't collide with one
#: already running locally -- same convention as StatusServer's port.
HOST = os.environ.get("NHL_SCOREBOARD_ADMIN_HOST", "localhost")
PORT = int(os.environ.get("NHL_SCOREBOARD_ADMIN_PORT", "8765"))
#: scoreboard.toml to read/write. Defaults to the same git-ignored dev
#: config every other local-dev command uses (`nhl-scoreboard -c
#: scoreboard.local.toml`); DEFAULT_CONFIG_PATHS (config.py) are real
#: device-only paths that don't exist on a dev machine. Rebound at runtime
#: by AdminServer.start() to the real board's resolved config path (#178
#: story 10) -- same "just assign the module global" convention the test
#: suite already uses (monkeypatch.setattr(admin_server, "CONFIG_PATH", ...)).
CONFIG_PATH = os.environ.get("NHL_SCOREBOARD_CONFIG", "scoreboard.local.toml")
#: The built frontend (`frontend/dist`, a CI build product -- see
#: build-image.yml) -- served for any plain HTTP GET, same directory
#: pattern as NHL_SCOREBOARD_FONT_DIR for fonts.py. Local dev doesn't use
#: this at all (frontend/README.md's `npm run dev` / Vite is the real dev
#: workflow); it matters for `npm run build` + a manual verification pass,
#: and for the real device.
ADMIN_DIR = Path(os.environ.get("NHL_SCOREBOARD_ADMIN_DIR", "/usr/share/nhl-scoreboard/admin"))
#: Same recommendation as status_server.py's rotation editor (#151) --
#: generous but finite, so an unbounded list doesn't need its own
#: pagination story. Enforced server-side here too, not just by the
#: frontend disabling its own "Add row" button at this count.
ROTATION_MAX_ROWS = 8
#: How often to check updater.STATE_FILE for a change while a check/apply
#: might be running. Overridable so tests don't wait a real second.
UPDATE_POLL_SECONDS = float(os.environ.get("NHL_SCOREBOARD_ADMIN_UPDATE_POLL", "1"))
#: How often to check the live snapshot for a change (#178 story 10) --
#: much chattier than UPDATE_POLL_SECONDS since scene/game state changes
#: far more often than an update check does, but still just a poll, not
#: pushed straight off the main loop -- this process has no other way to
#: know ScoreboardApp's state changed except asking again.
SNAPSHOT_POLL_SECONDS = float(os.environ.get("NHL_SCOREBOARD_ADMIN_SNAPSHOT_POLL", "2"))

#: Every currently-open connection -- the update-state/snapshot watchers
#: broadcast to all of them, unlike everything else here, which only ever
#: replies to whoever sent the request.
_clients: set[ServerConnection] = set()

#: ScoreboardApp.status_snapshot, injected by AdminServer.start() (#178
#: story 10) -- None in every other context (local dev, tests, the plain
#: CLI entry point via main()), which have no live app to ask. Same
#: "handed to it as a callable" relationship status_server.py's own
#: snapshot parameter had -- this module still has no idea what a scene or
#: a game is.
SNAPSHOT_PROVIDER: Callable[[], dict[str, str]] | None = None


@dataclasses.dataclass(frozen=True)
class _FieldSpec:
    kind: str  # "bool" | "str" | "float" | "int" | "select"
    choices: tuple[str, ...] = ()
    #: Mirrors status_server.py's own per-field flag (#178 story 7) -- a
    #: value that only takes effect after nhl-scoreboard.service restarts,
    #: because it's baked into the constructed RGBMatrix (see CLAUDE.md's
    #: "wrong hardware_mapping is a silent failure" hardware note). Purely
    #: informational for the frontend to badge; doesn't change validation.
    restart_required: bool = False


#: Mirrors AudioConfig's own fields (config.py) -- kept as an explicit spec
#: rather than introspected via dataclasses.fields() so a field's *type*
#: (bool vs. float, say) is checked, not just its name; a dataclass field
#: alone doesn't carry enough for that.
_AUDIO_FIELDS: dict[str, _FieldSpec] = {
    "enabled": _FieldSpec("bool"),
    "device": _FieldSpec("str"),
    "horn_dir": _FieldSpec("str"),
}

#: Mirrors ScoreboardConfig's own fields (config.py), same convention.
_SCOREBOARD_FIELDS: dict[str, _FieldSpec] = {
    "favourite_team": _FieldSpec("str"),
    "timezone": _FieldSpec("str"),
    "rotate_seconds": _FieldSpec("float"),
    "poll_seconds": _FieldSpec("float"),
    "live_poll_seconds": _FieldSpec("float"),
    "show_clock_when_idle": _FieldSpec("bool"),
    "prefer_favourite": _FieldSpec("bool"),
    "show_logos": _FieldSpec("bool"),
    "logo_variant": _FieldSpec("select", choices=("dark", "light")),
    "goal_flash_seconds": _FieldSpec("float"),
    "goal_detail_seconds": _FieldSpec("float"),
    "three_stars_seconds": _FieldSpec("float"),
    "countdown_hours": _FieldSpec("float"),
    "final_hold_minutes": _FieldSpec("float"),
    "show_standings": _FieldSpec("bool"),
    "show_clock_between_games": _FieldSpec("bool"),
}

#: Mirrors StatusServerConfig's own fields (config.py), same convention.
#: The first "int" field here -- port must be a whole number, not
#: 8080.5 -- everything else so far has been bool/str/float.
_STATUS_FIELDS: dict[str, _FieldSpec] = {
    "enabled": _FieldSpec("bool"),
    "port": _FieldSpec("int"),
}

#: Mirrors PanelConfig's own fields (config.py), same convention -- except
#: pitch_mm, which status_server.py's own form has never exposed either:
#: it's informational only, the driver never reads it (CLAUDE.md). The
#: five brightness-related fields hot-apply; every other field here is
#: restart_required, since it's baked into the constructed RGBMatrix.
_PANEL_FIELDS: dict[str, _FieldSpec] = {
    "brightness": _FieldSpec("int"),
    "auto_brightness": _FieldSpec("bool"),
    "min_brightness": _FieldSpec("int"),
    "max_brightness": _FieldSpec("int"),
    "brightness_poll_seconds": _FieldSpec("float"),
    "rows": _FieldSpec("int", restart_required=True),
    "cols": _FieldSpec("int", restart_required=True),
    "chain_length": _FieldSpec("int", restart_required=True),
    "parallel": _FieldSpec("int", restart_required=True),
    "hardware_mapping": _FieldSpec(
        "select", choices=("regular", "adafruit-hat", "adafruit-hat-pwm"), restart_required=True
    ),
    "rgb_sequence": _FieldSpec(
        "select", choices=("RGB", "RBG", "GRB", "GBR", "BRG", "BGR"), restart_required=True
    ),
    "gpio_slowdown": _FieldSpec("int", restart_required=True),
    "pwm_bits": _FieldSpec("int", restart_required=True),
    "pwm_lsb_nanoseconds": _FieldSpec("int", restart_required=True),
    "disable_hardware_pulsing": _FieldSpec("bool", restart_required=True),
    "pixel_mapper": _FieldSpec("str", restart_required=True),
    "limit_refresh_rate_hz": _FieldSpec("int", restart_required=True),
}

#: Mirrors NightModeConfig's own *editable* fields (config.py) -- not all
#: of them: `start`/`end` are derived `datetime.time` objects
#: (`field(init=False)`), computed by `__post_init__` from `start_time`/
#: `end_time` purely so the app never re-parses the strings itself. They
#: aren't JSON-serialisable and aren't a config value a person sets
#: directly, so unlike every other section here, this one can't just
#: `dataclasses.asdict()` the whole dataclass for its payload (see
#: _night_mode_payload). None of these are restart_required -- night mode
#: is polled live, nothing here is baked into a constructed object the
#: way panel's fields are.
_NIGHT_MODE_FIELDS: dict[str, _FieldSpec] = {
    "enabled": _FieldSpec("bool"),
    "start_time": _FieldSpec("str"),
    "end_time": _FieldSpec("str"),
    "dim_brightness": _FieldSpec("int"),
    "suppress_scope": _FieldSpec("select", choices=("tracked", "all")),
    "cooldown_minutes": _FieldSpec("float"),
}

#: WifiConfig only models one field -- ssid/password/country live in the
#: same [wifi] TOML table but are read directly out of the raw dict by
#: scoreboard-provision (predates this dataclass, #133) and deliberately
#: NOT exposed here: actually setting up a network is setup_server.py's
#: job (the offline-first captive-portal page, #132), not this one. This
#: only tunes how long a join attempt (boot-time or live, #133) waits
#: before deciding it failed.
_WIFI_FIELDS: dict[str, _FieldSpec] = {
    "connect_timeout_seconds": _FieldSpec("float"),
}


def _audio_payload(settings: Settings) -> dict[str, object]:
    return {"type": "config", "section": "audio", "data": dataclasses.asdict(settings.audio)}


def _scoreboard_payload(settings: Settings) -> dict[str, object]:
    return {
        "type": "config",
        "section": "scoreboard",
        "data": dataclasses.asdict(settings.scoreboard),
    }


def _status_payload(settings: Settings) -> dict[str, object]:
    return {"type": "config", "section": "status", "data": dataclasses.asdict(settings.status)}


def _panel_payload(settings: Settings) -> dict[str, object]:
    return {"type": "config", "section": "panel", "data": dataclasses.asdict(settings.panel)}


def _night_mode_payload(settings: Settings) -> dict[str, object]:
    nm = settings.night_mode
    return {
        "type": "config",
        "section": "night_mode",
        "data": {
            "enabled": nm.enabled,
            "start_time": nm.start_time,
            "end_time": nm.end_time,
            "dim_brightness": nm.dim_brightness,
            "suppress_scope": nm.suppress_scope,
            "cooldown_minutes": nm.cooldown_minutes,
        },
    }


def _wifi_payload(settings: Settings) -> dict[str, object]:
    return {"type": "config", "section": "wifi", "data": dataclasses.asdict(settings.wifi)}


def _rotation_payload(settings: Settings) -> dict[str, object]:
    return {
        "type": "config",
        "section": "rotation",
        "data": [dataclasses.asdict(entry) for entry in settings.rotation],
    }


def _update_payload() -> dict[str, object]:
    state = updater.read_state()
    return {
        "type": "config",
        "section": "update",
        "data": {
            "installed": state.get("installed") or "unknown (factory image)",
            "latest": state.get("latest") or "",
            "checked_at": state.get("checked_at") or "",
            "error": state.get("error") or "",
            "reason": state.get("reason") or "",
            "available": bool(state.get("available")),
            "applicable": bool(state.get("applicable")),
            "last_apply": (state.get("last_apply") or {}).get("detail") or "",
        },
    }


def _snapshot_payload() -> dict[str, object]:
    """ScoreboardApp.status_snapshot()'s dict, handed straight through --
    same "this module has no idea what a scene or a game is" relationship
    status_server.py's own snapshot parameter had. An empty dict (no
    provider configured -- local dev, tests, or the plain `main()` CLI
    entry point) is a valid, harmless payload; the frontend just shows
    nothing rather than "waiting..." forever.
    """
    return {
        "type": "snapshot",
        "data": SNAPSHOT_PROVIDER() if SNAPSHOT_PROVIDER is not None else {},
    }


async def _broadcast(payload: dict[str, object]) -> None:
    raw = json.dumps(payload)
    # A snapshot, not a live iteration over _clients -- a connection can
    # close (and remove itself, see _handle's finally) while this awaits,
    # which would otherwise be mutating the set mid-loop.
    for client in list(_clients):
        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            await client.send(raw)


async def _send_version(connection: ServerConnection) -> None:
    value = installed_version() or "unknown (factory image)"
    await connection.send(json.dumps({"type": "version", "value": value}))


async def _send_audio_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_audio_payload(settings)))


async def _send_rotation_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_rotation_payload(settings)))


async def _send_scoreboard_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_scoreboard_payload(settings)))


async def _send_status_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_status_payload(settings)))


async def _send_panel_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_panel_payload(settings)))


async def _send_night_mode_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_night_mode_payload(settings)))


async def _send_wifi_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_wifi_payload(settings)))


async def _send_snapshot(connection: ServerConnection) -> None:
    await connection.send(json.dumps(_snapshot_payload()))


async def _send_update_config(connection: ServerConnection) -> None:
    await connection.send(json.dumps(_update_payload()))


def _start_update_unit(action: str) -> None:
    """Same mechanism as status_server.py's own ``_start_update_unit`` --
    duplicated rather than imported, same "hardcoded per-thing, not shared
    yet" call as every other section here. Fire-and-forget: the actual
    check/apply happens in the unit's own process, on its own schedule;
    ``_watch_update_state`` is what notices and reports the result, not
    this call returning.
    """
    unit = {
        "check": "nhl-scoreboard-update-now.service",
        "apply": "nhl-scoreboard-update-apply.service",
    }[action]
    try:
        subprocess.run(
            ["systemctl", "start", "--no-block", unit], check=False, capture_output=True, timeout=30
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Could not start %s: %s", unit, exc)


def _reboot() -> None:
    """Same mechanism as status_server.py's own ``_reboot_board``."""
    try:
        subprocess.run(["systemctl", "reboot"], check=False, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Could not reboot: %s", exc)


async def _watch_update_state() -> None:
    """Broadcast a fresh update config to every client whenever
    updater.STATE_FILE changes -- the actual point of story 4. check()/
    apply() run out of process and write that file on their own schedule;
    this is what turns "the file changed" into "the page updated itself",
    without the admin page (or a person) ever having to ask again.
    """
    last_mtime: float | None = None
    while True:
        try:
            mtime = updater.STATE_FILE.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != last_mtime:
            last_mtime = mtime
            if _clients:
                await _broadcast(_update_payload())
        await asyncio.sleep(UPDATE_POLL_SECONDS)


async def _watch_snapshot() -> None:
    """Broadcast a fresh snapshot to every client whenever it changes (#178
    story 10) -- same shape as _watch_update_state, the proven pattern for
    "this process has no other way to know something changed except
    polling for it". A no-op loop (SNAPSHOT_PROVIDER stays None) in every
    context but a real device: local dev, tests, and the plain `main()`
    CLI entry point have no live ScoreboardApp to ask.
    """
    last: dict[str, str] | None = None
    while True:
        current = SNAPSHOT_PROVIDER() if SNAPSHOT_PROVIDER is not None else None
        if current != last:
            last = current
            if _clients and current is not None:
                await _broadcast(_snapshot_payload())
        await asyncio.sleep(SNAPSHOT_POLL_SECONDS)


def _coerce_scalar_fields(data: object, fields: dict[str, _FieldSpec]) -> dict[str, object]:
    """Validate an incoming save's ``data`` against a section's field specs.
    JSON already carries real types (unlike an HTML form's fields, which
    are always strings) -- there's no `bool("false") == True` trap to guard
    against here the way status_server.py's _coerce_section has to; this
    only ever checks the type (or, for "select", the choice) actually
    received is the right one.
    """
    if not isinstance(data, dict):
        raise ValueError(json.dumps({"data": "must be an object"}))
    errors: dict[str, str] = {}
    for key in data:
        if key not in fields:
            errors[key] = f"unknown field {key!r}"
    for key, spec in fields.items():
        if key not in data:
            continue
        value = data[key]
        if spec.kind == "bool" and not isinstance(value, bool):
            errors[key] = "must be a boolean"
        elif spec.kind == "str" and not isinstance(value, str):
            errors[key] = "must be a string"
        elif spec.kind == "float" and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            errors[key] = "must be a number"
        elif spec.kind == "int" and (not isinstance(value, int) or isinstance(value, bool)):
            errors[key] = "must be a whole number"
        elif spec.kind == "select" and value not in spec.choices:
            errors[key] = f"must be one of {', '.join(spec.choices)}"
    if errors:
        raise ValueError(json.dumps(errors))
    return data


def _coerce_rotation(data: object) -> list[dict[str, object]]:
    """Validate an incoming save's ``data`` the same way config.py's own
    ``_parse_rotation`` validates a freshly-loaded ``[[rotation]]`` table --
    unknown screen, non-numeric/non-positive seconds -- except a save
    rejects the *whole* list on the first bad row instead of silently
    dropping just that one. ``_parse_rotation`` is right to be forgiving
    about a hand-edited TOML file (a typo there must not stop the board
    booting), but a live edit from this page is different: the person
    editing it should see exactly what's wrong and fix it, not have a row
    silently vanish.
    """
    if not isinstance(data, list):
        raise ValueError(json.dumps({"rotation": "must be a list"}))
    if len(data) > ROTATION_MAX_ROWS:
        raise ValueError(json.dumps({"rotation": f"at most {ROTATION_MAX_ROWS} rows"}))
    entries: list[dict[str, object]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(json.dumps({f"row {i + 1}": "must be an object"}))
        screen = item.get("screen")
        if screen not in VALID_ROTATION_SCREENS:
            choices = ", ".join(VALID_ROTATION_SCREENS)
            raise ValueError(json.dumps({f"row {i + 1}": f"screen must be one of {choices}"}))
        seconds = item.get("seconds")
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError(json.dumps({f"row {i + 1}": "seconds must be a positive number"}))
        entries.append({"screen": screen, "seconds": float(seconds)})
    return entries


#: Which _send_*_config to call after a save, keyed by section -- fresh
#: from disk each time, same discipline as status_server.py: never assume
#: the in-memory values just validated are exactly what landed.
_SEND_AFTER_SAVE = {
    "audio": _send_audio_config,
    "scoreboard": _send_scoreboard_config,
    "status": _send_status_config,
    "panel": _send_panel_config,
    "night_mode": _send_night_mode_config,
    "wifi": _send_wifi_config,
    "rotation": _send_rotation_config,
}


async def _handle_save(connection: ServerConnection, message: dict[str, object]) -> None:
    section = message.get("section")
    try:
        if section == "audio":
            values: object = _coerce_scalar_fields(message.get("data"), _AUDIO_FIELDS)
        elif section == "scoreboard":
            values = _coerce_scalar_fields(message.get("data"), _SCOREBOARD_FIELDS)
        elif section == "status":
            values = _coerce_scalar_fields(message.get("data"), _STATUS_FIELDS)
        elif section == "panel":
            values = _coerce_scalar_fields(message.get("data"), _PANEL_FIELDS)
        elif section == "night_mode":
            values = _coerce_scalar_fields(message.get("data"), _NIGHT_MODE_FIELDS)
        elif section == "wifi":
            values = _coerce_scalar_fields(message.get("data"), _WIFI_FIELDS)
        elif section == "rotation":
            values = _coerce_rotation(message.get("data"))
        else:
            error = {"type": "error", "message": f"unknown section {section!r}"}
            await connection.send(json.dumps(error))
            return
        Settings.load(CONFIG_PATH).save({section: values})
    except (ValueError, ConfigWriteError) as exc:
        error = {"type": "error", "section": section, "message": str(exc)}
        await connection.send(json.dumps(error))
        return
    await connection.send(json.dumps({"type": "saved", "section": section}))
    await _SEND_AFTER_SAVE[section](connection)


async def _handle(connection: ServerConnection) -> None:
    _clients.add(connection)
    try:
        await _send_version(connection)
        await _send_audio_config(connection)
        await _send_scoreboard_config(connection)
        await _send_status_config(connection)
        await _send_panel_config(connection)
        await _send_night_mode_config(connection)
        await _send_wifi_config(connection)
        await _send_rotation_config(connection)
        await _send_update_config(connection)
        await _send_snapshot(connection)
        log.info("Sent initial state to %s", connection.remote_address)
        async for raw in connection:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await connection.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue
            msg_type = message.get("type")
            if msg_type == "save":
                await _handle_save(connection, message)
            elif msg_type == "update_check":
                await connection.send(json.dumps({"type": "checking"}))
                _start_update_unit("check")
            elif msg_type == "update_apply":
                await connection.send(json.dumps({"type": "applying"}))
                _start_update_unit("apply")
            elif msg_type == "reboot":
                await connection.send(json.dumps({"type": "rebooting"}))
                _reboot()
            else:
                error = {"type": "error", "message": "unknown message type"}
                await connection.send(json.dumps(error))
    finally:
        _clients.discard(connection)


# -- static file serving (#178 story 10) -------------------------------------
#
# One port serves both the page and the WebSocket -- websockets' own
# process_request hook (confirmed present in the pinned websockets>=13,
# tested against 17.1) fires for every incoming request, upgrade or not.
# The frontend connects its WebSocket at the same path ("/") the page is
# served from, so requests are told apart by the Upgrade header, not the
# path -- a real browser's `new WebSocket(...)` always sends a genuine
# `Upgrade: websocket` header; a plain page-load GET never does. Verified
# directly against a running server before relying on it, not assumed from
# the library's docs alone.

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


def _static_response(request_path: str) -> Response:
    """Serve a file out of ADMIN_DIR, falling back to index.html.

    This is a single-page app with exactly one client-side route ("/"),
    so any path that isn't a real file under ADMIN_DIR -- including "/"
    itself -- gets index.html, same as any other SPA's server-side
    fallback. ``.resolve()`` + a containment check guards against a
    path-traversal request (``/../../etc/passwd``) escaping ADMIN_DIR.
    """
    admin_dir = ADMIN_DIR.resolve()
    rel = request_path.split("?", 1)[0].lstrip("/") or "index.html"
    candidate = (admin_dir / rel).resolve()
    outside_admin_dir = candidate != admin_dir and admin_dir not in candidate.parents
    if outside_admin_dir or not candidate.is_file():
        candidate = admin_dir / "index.html"
    try:
        body = candidate.read_bytes()
    except OSError:
        return Response(HTTPStatus.NOT_FOUND, "Not Found", Headers(), b"")
    content_type = _CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
    headers = Headers([("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return Response(HTTPStatus.OK, "OK", headers, body)


async def _process_request(connection: ServerConnection, request: Request) -> Response | None:
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None  # let the WebSocket handshake proceed as normal
    return _static_response(request.path)


async def run(host: str = HOST, port: int = PORT) -> None:
    watcher = asyncio.create_task(_watch_update_state())
    snapshot_watcher = asyncio.create_task(_watch_snapshot())
    try:
        async with serve(_handle, host, port, process_request=_process_request) as server:
            log.info("Admin server listening on http://%s:%d/ (page + WebSocket)", host, port)
            await server.serve_forever()
    finally:
        watcher.cancel()
        snapshot_watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        with contextlib.suppress(asyncio.CancelledError):
            await snapshot_watcher


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("websockets %s", websockets.__version__)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


# -- thread lifecycle (#178 story 10) -----------------------------------------


class AdminServer:
    """Runs `run()` on a background thread with its own asyncio loop, until
    `stop()` -- the same start/stop/port shape `StatusServer` (the page
    this replaces) had, so `app.py`'s integration is a small diff, not a
    rewrite. `StatusServer` ran a blocking `http.server` loop in a plain
    `threading.Thread`; this does the asyncio equivalent, since `run()`
    itself is a coroutine.
    """

    def __init__(
        self,
        config_path: str,
        port: int,
        snapshot: Callable[[], dict[str, str]] | None = None,
        host: str = "0.0.0.0",  # intentional: a LAN admin page, see module docstring
    ) -> None:
        self._config_path = config_path
        self._port = port
        self._snapshot = snapshot
        self._host = host
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: asyncio.Event | None = None
        self._bound_port: int | None = None

    @property
    def port(self) -> int:
        """The bound port -- resolves a requested port of 0 to the one actually picked."""
        return self._bound_port if self._bound_port is not None else self._port

    def start(self) -> None:
        global CONFIG_PATH, SNAPSHOT_PROVIDER
        CONFIG_PATH = self._config_path
        SNAPSHOT_PROVIDER = self._snapshot
        ready = threading.Event()
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._serve(ready)), name="admin-server", daemon=True
        )
        self._thread.start()
        if not ready.wait(timeout=5):
            log.warning("Admin server did not confirm startup within 5s")

    async def _serve(self, ready: threading.Event) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        watcher = asyncio.create_task(_watch_update_state())
        snapshot_watcher = asyncio.create_task(_watch_snapshot())
        try:
            async with serve(
                _handle, self._host, self._port, process_request=_process_request
            ) as server:
                self._bound_port = server.sockets[0].getsockname()[1]
                log.info(
                    "Admin server listening on http://%s:%d/ (page + WebSocket)",
                    self._host,
                    self.port,
                )
                ready.set()
                await self._stop_event.wait()
        finally:
            watcher.cancel()
            snapshot_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            with contextlib.suppress(asyncio.CancelledError):
                await snapshot_watcher

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            stop_event = self._stop_event
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(
                    self._set_stop_event(stop_event), self._loop
                ).result(timeout=5)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._stop_event = None
        self._bound_port = None

    @staticmethod
    async def _set_stop_event(stop_event: asyncio.Event) -> None:
        stop_event.set()


if __name__ == "__main__":
    main()
