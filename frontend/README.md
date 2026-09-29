# Admin page frontend (React + Vite)

A React SPA connected to a Python WebSocket server, built as vertical
slices (#178). See `src/nhl_scoreboard/ws_server.py`'s own docstring for
exactly what's been ported over so far and what hasn't -- local-dev only,
not wired into the actual admin page or the device image yet.

So far: the installed version (read-only), and the Audio section
(`enabled`/`device`/`horn_dir`) -- read, edit, and save, with no page
reload, which was the actual point of moving off `status_server.py`'s
HTML-form-POST model. Styled with plain Bootstrap CSS (the `bootstrap`
npm package, not `react-bootstrap`) -- hand-applied classes on plain JSX,
no component library, since nothing here needs JS-driven components
(modals, dropdowns) yet. Dark by default (`data-bs-theme="dark"` on
`<html>`, `index.html`), matching `status_server.py`'s existing theme.

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
