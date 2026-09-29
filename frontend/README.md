# Admin page frontend (React + Vite)

A React SPA connected to a Python WebSocket server, built as vertical
slices (#178). See `src/nhl_scoreboard/ws_server.py`'s own docstring for
exactly what's been ported over so far and what hasn't -- local-dev only,
not wired into the actual admin page or the device image yet.

So far: the installed version (read-only), the Scoreboard section (16
fields), the Audio section (`enabled`/`device`/`horn_dir`), the Status
page section (`enabled`/`port`), the Panel section (17 fields, grouped
into Geometry/Driver-PWM/Brightness, with a "restart required" badge on
the 12 fields that need `nhl-scoreboard.service` to restart before they
take effect), the Night mode section (6 fields: enabled, the dim window's
start/end time, dimmed brightness, suppress scope, cooldown), the idle
rotation list (`[[rotation]]`), and Reboot / Software update -- all with
no page reload, which was the actual point of moving off
`status_server.py`'s HTML-form-POST model. The rotation editor does real
add/remove/reorder in the browser (↑/↓ buttons, a row cap of 8) -- the old
HTML version needed a numeric "order" field and a full-page round trip
per click specifically because it had no JS to do this with; this one
just does it. Software update is the first thing that actually *pushes*:
a check/apply runs out of process on its own schedule, and the page
updates itself the moment it finishes -- no click, no manual refresh,
which is the literal problem the whole rebuild started from. Scoreboard
also exposes two fields (`goal_detail_seconds`, `three_stars_seconds`)
that were never actually in `status_server.py`'s own HTML form -- fixed
in passing, not carried forward. Styled with plain Bootstrap CSS (the
`bootstrap` npm package, not `react-bootstrap`) -- hand-applied classes on
plain JSX, no component library, since nothing here needs JS-driven
components (modals, dropdowns) yet. Dark by default
(`data-bs-theme="dark"` on `<html>`, `index.html`), matching
`status_server.py`'s existing theme.

**Reboot and Software update call real `systemctl` commands.** Harmless
on the real board (the same commands `status_server.py` already runs),
but if you're testing these locally, shadow `systemctl` with a fake
binary on `PATH` first (log its args, exit 0) rather than let a dev
machine actually try to reboot itself or start a systemd unit that
doesn't exist there.

## Running it locally

Two processes, in separate terminals, from the repo root:

```bash
source .venv/bin/activate
python -m nhl_scoreboard.ws_server        # ws://localhost:8765/
```

```bash
cd frontend
npm install                               # first time only
npm run dev                               # http://localhost:5173/
```

By default the WebSocket server reads/writes `scoreboard.local.toml` in the
repo root (same git-ignored dev config every other local-dev command uses)
-- override with `NHL_SCOREBOARD_CONFIG` to point at a different file.
Similarly, `NHL_SCOREBOARD_UPDATE_STATE` overrides where it watches for the
update-check/apply state file (real default: `/var/lib/nhl-scoreboard/
update-state.json`, root-only, not writable as yourself) and
`NHL_SCOREBOARD_WS_UPDATE_POLL` overrides how often it checks (default 1s)
-- point the first at a scratch path and write JSON to it by hand to see
the Software update card update itself with zero clicks.

Open `http://localhost:5173/` -- it should show `WebSocket: open`, the
installed version (`unknown (factory image)` unless something has written
`/opt/nhl-scoreboard/VERSION`, e.g. via `NHL_SCOREBOARD_APP_DIR` pointed at
a directory that has one), and the Audio section pre-filled from the config
file -- editable, with a "Saved." confirmation on submit and no navigation.

## Commands

```bash
npm run dev      # dev server with HMR
npm run build    # type-check (tsc) + production build to dist/
npm run lint     # oxlint
npm run preview  # serve the dist/ build locally
```

`dist/` and `node_modules/` are git-ignored -- nothing here is built or
committed as static output yet. A later #178 story wires the production
build into the image the same way team logos and fonts already are: built
at CI/image-build time, shipped as static files, no Node runtime on the
device.
