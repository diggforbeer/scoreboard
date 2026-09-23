"""Parity between pyproject.toml's runtime deps and the image's apt packages (#77).

The image installs Python deps from apt (`image/layer/nhl-scoreboard.yaml`),
not pip -- the app ships as a plain source tree on PYTHONPATH, never
`pip install`ed on the board. That list is kept in sync with
pyproject.toml's `[project] dependencies` entirely by hand: nothing else
catches drift between the two.

If a runtime dependency lands in pyproject.toml without a matching apt
package, `pip install -e '.[dev]'` still satisfies the CI test job and
nothing in the image build imports the new module either, so the gap ships
silently and only shows up as an ImportError on first boot -- the same
failure class as #21's libpython3.13 (see CLAUDE.md). This test is the
cheap, always-runs half of the fix; the image build's own post-purge
import check (image/layer/nhl-scoreboard.yaml) is the other half and
catches anything this name map gets wrong.

Deliberately regex-based rather than a YAML parse: the packages list is a
flat, comment-laden block and pulling in PyYAML as a new dev dependency
just to read it isn't worth it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
IMAGE_LAYER = REPO_ROOT / "image" / "layer" / "nhl-scoreboard.yaml"

# Runtime (PyPI distribution name) -> apt package providing the same import
# in image/layer/nhl-scoreboard.yaml. Update this alongside any change to
# pyproject.toml's [project] dependencies or the image layer's apt list.
DEP_TO_APT_PACKAGE = {
    "requests": "python3-requests",
    "pillow": "python3-pil",
    "tomlkit": "python3-tomlkit",
}


def _runtime_dependency_names() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    deps = data["project"]["dependencies"]
    # "requests>=2.31" -> "requests"
    return [re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0] for dep in deps]


def _apt_packages() -> set[str]:
    text = IMAGE_LAYER.read_text()
    match = re.search(r"^  packages:\n(?P<body>(?:.*\n)*?)\n  customize-hooks:", text, re.M)
    assert match, "could not find the mmdebstrap packages: block in the image layer"
    return {
        line.split("#", 1)[0].strip().removeprefix("- ").strip()
        for line in match.group("body").splitlines()
        if line.strip().startswith("-")
    }


def test_every_runtime_dependency_has_an_apt_package():
    apt_packages = _apt_packages()
    for name in _runtime_dependency_names():
        assert name in DEP_TO_APT_PACKAGE, (
            f"pyproject.toml depends on {name!r} but there is no entry for it in "
            "DEP_TO_APT_PACKAGE (tests/test_image_deps.py) -- add one, and make sure "
            "the image installs it from apt, or the board will ImportError on first boot"
        )
        apt_package = DEP_TO_APT_PACKAGE[name]
        assert apt_package in apt_packages, (
            f"pyproject.toml depends on {name!r}, mapped to apt package "
            f"{apt_package!r}, but that package is missing from the packages: list in "
            f"{IMAGE_LAYER.relative_to(REPO_ROOT)}"
        )


def test_dep_to_apt_package_map_has_no_stale_entries():
    runtime_names = set(_runtime_dependency_names())
    stale = set(DEP_TO_APT_PACKAGE) - runtime_names
    assert not stale, (
        f"DEP_TO_APT_PACKAGE has entries for {stale!r}, which are no longer in "
        "pyproject.toml's runtime dependencies -- remove them"
    )
