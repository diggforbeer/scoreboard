#!/usr/bin/env bash
# One-shot local dev environment setup, so a fresh clone is ready to run in
# a couple of commands instead of retyping README's "Development" section
# by hand every time. Safe to re-run -- every step here is idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VENV="${REPO_ROOT}/.venv"

if [ ! -d "${VENV}" ]; then
    echo "==> Creating .venv"
    python3 -m venv "${VENV}"
else
    echo "==> .venv already exists"
fi

echo "==> Installing nhl-scoreboard in editable mode with dev extras"
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet -e '.[dev]'

LOCAL_CONFIG="${REPO_ROOT}/scoreboard.local.toml"
if [ ! -f "${LOCAL_CONFIG}" ]; then
    echo "==> Creating scoreboard.local.toml from the shipped boot-partition template"
    cp "${REPO_ROOT}/image/files/boot/scoreboard.toml" "${LOCAL_CONFIG}"
else
    echo "==> scoreboard.local.toml already exists; leaving it as-is"
fi

echo "==> Fetching team logos (best-effort: needs network + libcairo2)"
if "${VENV}/bin/python" "${REPO_ROOT}/scripts/fetch-logos.py"; then
    echo "==> Logos fetched"
else
    echo "==> Logo fetch failed -- not fatal, the board falls back to text" \
        "abbreviations without them. Re-run scripts/fetch-logos.py once" \
        "libcairo2/network are available if you want real crests."
fi

cat <<'EOF'

==> Ready. Activate the venv, then:

    source .venv/bin/activate

    nhl-scoreboard --dump                                              # today's scores, no display
    nhl-scoreboard --backend RGBMatrixEmulator -c scoreboard.local.toml    # live board: http://localhost:8888
                                                                        #   admin page: http://localhost:8080
    python scripts/preview.py --fixture                                # frames as ASCII, offline
    pytest                                                             # 199+ tests, ~1s, fully offline
EOF
