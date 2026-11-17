"""The static marketing site (``site/``): every local link and image exists, and the wait-list
button points at a real form, not the placeholder the page is first written with."""

from __future__ import annotations

import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
PAGES = sorted(SITE.glob("*.html"))


def test_the_waitlist_link_is_a_real_url_not_the_placeholder():
    text = (SITE / "parts.html").read_text()
    link = re.search(
        r'id="waitlist-link"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*id="waitlist-link"', text
    )
    assert link, "the wait-list button is missing"
    url = link.group(1) or link.group(2)
    assert url.startswith("https://"), (
        f"set the wait-list form URL in site/parts.html (got {url!r})"
    )


def test_every_local_link_and_image_on_the_site_exists():
    missing = []
    for page in PAGES:
        for ref in re.findall(r'(?:src|href)="([^"#:?]+)', page.read_text()):
            if ref.startswith(("http", "mailto")):
                continue
            if not (SITE / ref).exists():
                missing.append(f"{page.name}: {ref}")
    assert not missing, missing
