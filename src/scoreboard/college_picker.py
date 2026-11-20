"""The FBS team list the admin page's college picker offers (#543).

The page must not hardcode 134 teams (the hockey and football pickers take theirs from the board),
so the admin server sends the table as conferences with their teams. The table is ESPN's, two
requests and ~1.9 MB, so it is fetched once on first need (a page visit), kept for a day, and
served from memory after that: with no network, a cached list still works, and a failed fetch is
retried only every few minutes so an offline board never hammers ESPN. Nothing here touches the
live football feed; it asks ESPN with a client of its own.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .football.college_teams import CollegeTable

log = logging.getLogger(__name__)

#: A fetched table is good for a day (conference moves happen once a year).
TTL_SECONDS = 24 * 3600.0
#: After a failed fetch, wait this long before the next try.
RETRY_SECONDS = 300.0


def fetch_table() -> CollegeTable | None:
    """The real source: ESPN's FBS table via a throwaway college client (``None`` on failure)."""
    from .football.api import LEAGUE_COLLEGE, FootballClient

    return FootballClient(league=LEAGUE_COLLEGE).college_teams()


def payload_from_table(table: CollegeTable) -> dict[str, Any]:
    """Conferences A-Z (independents last), each with its teams A-Z, as plain JSON data."""
    return {
        "ready": True,
        "conferences": [
            {
                "name": name,
                "short": short,
                "teams": [
                    {
                        "id": team.espn_id,
                        "abbrev": team.abbrev,
                        "name": f"{team.location} {team.nickname}".strip(),
                        "short_name": team.short_name,
                        "color": list(team.color),
                    }
                    for team in teams
                ],
            }
            for name, short, teams in table.conferences()
        ],
    }


NOT_READY: dict[str, Any] = {"ready": False, "conferences": []}


class CollegeTeamList:
    """The cached picker payload and when to fetch it again. Thread-safe: the admin loop reads it
    while a worker thread refreshes it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None
        self._fetched_at = 0.0
        self._retry_after = 0.0
        self._busy = False

    @property
    def payload(self) -> dict[str, Any]:
        """What to send: the cached list, or ``NOT_READY`` until one has been fetched."""
        with self._lock:
            return self._payload if self._payload is not None else NOT_READY

    def due(self, source: Callable[[], CollegeTable | None] | None) -> bool:
        """Whether a fetch should start now: there is a source, none is running, the cache is
        absent or a day old, and a recent failure is not still being waited out."""
        if source is None:
            return False
        now = self._clock()
        with self._lock:
            if self._busy or now < self._retry_after:
                return False
            return self._payload is None or now - self._fetched_at >= TTL_SECONDS

    def refresh(self, source: Callable[[], CollegeTable | None]) -> bool:
        """Fetch (blocking; run it off the event loop). ``True`` if a new list was stored; on a
        failure the old list, if any, stays and the next try waits ``RETRY_SECONDS``."""
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        table = None
        try:
            table = source()
        except Exception:
            log.exception("Fetching the college team list failed")
        finally:
            now = self._clock()
            with self._lock:
                self._busy = False
                if table is not None and len(table):
                    self._payload = payload_from_table(table)
                    self._fetched_at = now
                    self._retry_after = 0.0
                else:
                    self._retry_after = now + RETRY_SECONDS
                stored = self._payload is not None and self._fetched_at == now
        if not stored:
            log.warning("College team list unavailable; retrying in %ds", int(RETRY_SECONDS))
        return stored
