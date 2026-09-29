# Admin page frontend (React + Vite)

Story 1 of #178: a React SPA connected to a Python WebSocket server, proving
the pipeline end to end before building anything real on top of it. See
`src/nhl_scoreboard/ws_server.py`'s own docstring for exactly what this
story does and doesn't cover -- local-dev only, one piece of data
(the installed version), no reconnect logic, not wired into the actual
admin page or the device image yet.

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

Open `http://localhost:5173/` -- it should show `WebSocket: open` and the
installed version (`unknown (factory image)` unless something has written
`/opt/nhl-scoreboard/VERSION`, e.g. via `NHL_SCOREBOARD_APP_DIR` pointed at
a directory that has one).

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
