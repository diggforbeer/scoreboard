#!/usr/bin/env python3
"""Build the app-update bundle + manifest attached to each release (#32).

    python scripts/build-app-bundle.py --version v2026.09.29 --out dist
    gh release upload v2026.09.29 dist/nhl-scoreboard-app.tar.gz dist/manifest.json

The bundle is the ``nhl_scoreboard`` package plus, when ``frontend/dist`` has
been built, the admin page as a top-level ``admin/``; nhl_scoreboard.updater
unpacks the package over /opt/nhl-scoreboard and ``admin/`` into the admin
page's directory (#185). The manifest carries the HUB75 driver
pin (from fetch-vendor.sh) so a board can refuse a release that needs a
rebuilt ``rgbmatrix``, the bundle's sha256, and an ``image`` fingerprint of the
scripts, units and apt packages the updater can't deliver (#284).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import image_manifest  # noqa: E402  (sibling script; needs the path line above)


def driver_pin() -> str:
    match = re.search(r"MATRIX_REF:-([0-9a-f]+)", (ROOT / "scripts/fetch-vendor.sh").read_text())
    if not match:
        raise SystemExit("could not find MATRIX_REF in scripts/fetch-vendor.sh")
    return match.group(1)


def build(version: str, out: Path, admin_dist: Path = ROOT / "frontend/dist") -> None:
    out.mkdir(parents=True, exist_ok=True)
    bundle = out / "nhl-scoreboard-app.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        tar.add(
            ROOT / "src/nhl_scoreboard",
            arcname="nhl_scoreboard",
            filter=lambda t: None if "__pycache__" in t.name else t,
        )
        if (admin_dist / "index.html").is_file():
            tar.add(admin_dist, arcname="admin")
    manifest = {
        "version": version,
        "driver_commit": driver_pin(),
        # What the updater can't install (#284); the board compares it with its own record.
        "image": image_manifest.build(),
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, default=Path("dist"))
    args = parser.parse_args()
    build(args.version, args.out)
