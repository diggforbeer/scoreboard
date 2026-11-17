"""What the board has cached, for the admin page's Cache tab: a readable view and a way to clear it.

Pure helpers. The app builds the item list (``ScoreboardApp.cache_items``) from its own state and
the football mode's, and each item is shown with how old it is, a one-line summary and the data
itself (turned into plain JSON and cut to ``MAX_DATA_CHARS`` so a 300 KB schedule cannot flood the
page). Clearing is by *scope*: ``all``, a sport (``hockey``, ``football``) or one item
(``hockey:standings``). The data refetches by itself on the next pass, as it does after a restart.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

#: How much of an item's data is sent to the page.
MAX_DATA_CHARS = 8000
SCOPES_OF_SPORT = ("hockey", "football")


def jsonable(value: Any, depth: int = 0) -> Any:
    """``value`` as plain JSON types: dataclasses (slotted too), mappings, sequences and dates."""
    if depth > 8:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: jsonable(getattr(value, f.name, None), depth + 1)
            for f in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(k): jsonable(v, depth + 1) for k, v in list(value.items())}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v, depth + 1) for v in list(value)]
    return str(value)


def item(
    key: str, sport: str, label: str, age: float | None, summary: str, value: Any, *, clear=True
) -> dict[str, Any]:
    """One cached thing as the page shows it. ``age`` is seconds since it was fetched (``None``
    when unknown); ``clear`` says whether the page may offer to clear it on its own."""
    text = json.dumps(jsonable(value), indent=1, default=str)
    truncated = len(text) > MAX_DATA_CHARS
    return {
        "key": key,
        "sport": sport,
        "label": label,
        "age_seconds": None if age is None else round(max(age, 0.0), 1),
        "summary": summary,
        "data": text[:MAX_DATA_CHARS],
        "truncated": truncated,
        "clearable": clear,
    }


def matches(scope: str, key: str) -> bool:
    """Whether clearing ``scope`` includes the item ``key`` (``sport:name``)."""
    return scope == "all" or scope == key or key.startswith(f"{scope}:")


def valid_scope(scope: object, keys: list[str]) -> bool:
    return isinstance(scope, str) and (scope == "all" or scope in SCOPES_OF_SPORT or scope in keys)
