# Admin page frontend (React + Vite)

A React SPA connected to a Python admin server, built as vertical slices
(#178). See `src/nhl_scoreboard/admin_server.py`'s own docstring for
exactly what's been built and the decisions behind it. As of story 10,
this is the admin page that ships: `admin_server.py` serves this page's
production build *and* its WebSocket on one port, started by
`ScoreboardApp` itself the same way `status_server.py` (the HTML-forms
page this replaces) used to be. `frontend/dist/` is a CI build product
(`build-image.yml`'s own "Build admin frontend" step), copied into the
image at `/usr/share/nhl-scoreboard/admin` -- Node never touches the
device itself.

Every config section `status_server.py` had is here: the Scoreboard
section (16 fields), the Audio section (`enabled`/`device`/`horn_dir`),
the Status page section (`enabled`/`port` -- still named `[status]` in
`scoreboard.toml`, now controlling this server instead of the old one),
the Panel section (17 fields, grouped into Geometry/Driver-PWM/
Brightness, with a "restart required" badge on the 12 fields that need
`nhl-scoreboard.service` to restart before they take effect), the Night
mode section (6 fields: enabled, the dim window's start/end time, dimmed
brightness, suppress scope, cooldown), the Wi-Fi section (just
`connect_timeout_seconds` -- SSID/password/country editing did **not**
carry over, dropped deliberately: the AP/captive-portal flow, #131-#133,
is now the one way to (re)join a network), the idle rotation list
(`[[rotation]]`), Reboot / Software update, and a read-only Board status
box (scene, current game, last poll, last error -- `ScoreboardApp.
status_snapshot()`, the other thing `status_server.py` used to serve
alongside its forms). All with no page reload, which was the actual point
of moving off `status_server.py`'s HTML-form-POST model. The rotation
editor does real add/remove/reorder in the browser (↑/↓ buttons, a row
cap of 8) -- the old HTML version needed a numeric "order" field and a
full-page round trip per click specifically because it had no JS to do
this with; this one just does it. Software update is the first thing
that actually *pushes*: a check/apply runs out of process on its own
schedule, and the page updates itself the moment it finishes -- no
click, no manual refresh, which is the literal problem the whole rebuild
started from. Scoreboard also exposes two fields (`goal_detail_seconds`,
`three_stars_seconds`) that were never actually in `status_server.py`'s
own HTML form -- fixed in passing, not carried forward. Styled with plain
Bootstrap CSS (the `bootstrap` npm package, not `react-bootstrap`) --
hand-applied classes on plain JSX, no component library, since nothing
here needs JS-driven components (modals, dropdowns) yet. Dark by default
(`data-bs-theme="dark"` on `<html>`, `index.html`), matching
`status_server.py`'s old theme. Laid out as two columns on a wide viewport
(Bootstrap's grid, `col-lg-6`), stacking to one on anything narrower.

**Reboot and Software update call real `systemctl` commands.** Harmless
on the real board (the same commands `status_server.py` used to run), but
if you're testing these locally, shadow `systemctl` with a fake binary on
`PATH` first (log its args, exit 0) rather than let a dev machine actually
try to reboot itself or start a systemd unit that doesn't exist there.

## Running it locally (dev mode, with HMR)

Two processes, in separate terminals, from the repo root:

```bash
source .venv/bin/activate
python -m nhl_scoreboard.admin_server        # ws://localhost:8765/
```

```bash
cd frontend
npm install                               # first time only
npm run dev                               # http://localhost:5173/
```

By default the admin server reads/writes `scoreboard.local.toml` in the
repo root (same git-ignored dev config every other local-dev command uses)
-- override with `NHL_SCOREBOARD_CONFIG` to point at a different file.
Similarly, `NHL_SCOREBOARD_UPDATE_STATE` overrides where it watches for the
update-check/apply state file (real default: `/var/lib/nhl-scoreboard/
update-state.json`, root-only, not writable as yourself) and
`NHL_SCOREBOARD_ADMIN_UPDATE_POLL` overrides how often it checks (default
1s) -- point the first at a scratch path and write JSON to it by hand to
see the Software update card update itself with zero clicks.
`NHL_SCOREBOARD_ADMIN_SNAPSHOT_POLL` is the equivalent for the Board
status box (default 2s), fed by `SNAPSHOT_PROVIDER` -- `None` outside a
real `ScoreboardApp` (dev mode included), which the Board status box shows
as "no live app to report on" rather than blank/broken.

Open `http://localhost:5173/` -- it should show `WebSocket: open`, the
installed version (`unknown (factory image)` unless something has written
`/opt/nhl-scoreboard/VERSION`, e.g. via `NHL_SCOREBOARD_APP_DIR` pointed at
a directory that has one), and the Audio section pre-filled from the config
file -- editable, with a "Saved." confirmation on submit and no navigation.

## Running it against a production build (no Vite, no HMR)

The same way it runs on the real device: one process, serving the built
static files and the WebSocket on the same port.

```bash
npm run build                                        # -> dist/
NHL_SCOREBOARD_ADMIN_DIR="$PWD/dist" \
  NHL_SCOREBOARD_CONFIG=../scoreboard.local.toml \
  python -m nhl_scoreboard.admin_server                # http://localhost:8765/
```

Open `http://localhost:8765/` directly -- no separate frontend server this
time. Useful for checking a change survives the real build (minification,
`tsc`'s stricter checking) before it ships, and for verifying the static-
file half of `admin_server.py` (`_static_response`/`_process_request`)
against real built output rather than Vite's dev server.

## Commands

```bash
npm run dev      # dev server with HMR
npm run build    # type-check (tsc) + production build to dist/
npm run lint     # oxlint
npm run preview  # serve the dist/ build locally (Vite's own preview server, not admin_server.py)
```

`dist/` and `node_modules/` are git-ignored -- built fresh by
`build-image.yml`'s "Build admin frontend" step on every image build, never
committed.
