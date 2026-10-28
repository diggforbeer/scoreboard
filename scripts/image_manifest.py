#!/usr/bin/env python3
"""Fingerprint of what the image build installs outside the app tree (#284).

The in-app updater only swaps ``/opt/nhl-scoreboard`` and the admin page, so
anything installed elsewhere (scripts in /usr/local/sbin, systemd units, apt
packages) only changes by reflashing. This records a sha256 per file under
``image/files/scripts`` and ``image/files/systemd`` plus the layer's apt
package list. ``build-app-bundle.py`` puts it in each release's manifest, and
the image build writes the same thing onto the board, so the updater can tell
when a release changes something it cannot deliver.

    python scripts/image_manifest.py > image-manifest.json
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE_DIRS = ("scripts", "systemd")


def package_list(layer: Path) -> list[str]:
    # Same regex-not-YAML approach as tests/test_image_deps.py: the block is
    # a flat list, and a YAML parse would add a dependency to the image build.
    pattern = r"^  packages:\n(?P<body>(?:.*\n)*?)\n  customize-hooks:"
    match = re.search(pattern, layer.read_text(), re.M)
    if not match:
        raise SystemExit(f"could not find the packages: block in {layer}")
    names = {
        line.split("#", 1)[0].strip().removeprefix("- ").strip()
        for line in match.group("body").splitlines()
        if line.strip().startswith("-")
    }
    return sorted(names)


def build(root: Path = ROOT) -> dict[str, object]:
    files: dict[str, str] = {}
    for directory in FILE_DIRS:
        for path in sorted((root / "image/files" / directory).iterdir()):
            if path.is_file():
                files[f"{directory}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files, "packages": package_list(root / "image/layer/nhl-scoreboard.yaml")}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
