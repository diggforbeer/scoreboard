"""The FBS team list the admin page's college picker offers (#543).

The page must not hardcode 134 teams (the hockey and football pickers take theirs from the board),
so the admin server sends the table as conferences with their teams. The table is ESPN's, two
requests and ~1.9 MB, so it is fetched once on first need (a page visit), kept for a day, and
served from memory after that: with no network, a cached list still works, and a failed fetch is
retried only every few minutes so an offline board never hammers ESPN. Nothing here touches the
live football feed; it asks ESPN with a client of its own.

The list is also **kept on disk** (``CACHE_FILE``, beside the other persistent state in
``/var/lib/scoreboard``), so a board that restarts with no network still has the picker's teams.
The file holds the payload the page is sent and the wall-clock time it was fetched, so its age
carries across a restart (a stale one is served at once and refreshed in the background). A file
that is missing, unreadable or the wrong shape is ignored, and one that cannot be written is only
logged: the disk is a convenience, never a reason for the page to fail.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .football.college_teams import CollegeTable

log = logging.getLogger(__name__)

#: A fetched table is good for a day (conference moves happen once a year).
TTL_SECONDS = 24 * 3600.0
#: After a failed fetch, wait this long before the next try.
RETRY_SECONDS = 300.0
#: Where the fetched list is kept (persistent across reflash and in-app updates).
CACHE_FILE = Path(
    os.environ.get("SCOREBOARD_COLLEGE_TEAMS_FILE", "/var/lib/scoreboard/college-teams.json")
)


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


def _valid_team(team: Any) -> bool:
    color = team.get("color") if isinstance(team, dict) else None
    return (
        isinstance(team, dict)
        and isinstance(team.get("id"), int)
        and not isinstance(team.get("id"), bool)
        and all(isinstance(team.get(k), str) and team[k] for k in ("abbrev", "name", "short_name"))
        and isinstance(color, list)
        and len(color) == 3
        and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)
    )


def valid_payload(data: Any) -> bool:
    """Whether ``data`` is exactly the shape the page reads: a ready payload with at least one
    conference and team, every team complete. A cache file is only trusted if this is true."""
    if not isinstance(data, dict) or data.get("ready") is not True:
        return False
    conferences = data.get("conferences")
    if not isinstance(conferences, list) or not conferences:
        return False
    for conference in conferences:
        if not isinstance(conference, dict):
            return False
        if not all(isinstance(conference.get(k), str) and conference[k] for k in ("name", "short")):
            return False
        teams = conference.get("teams")
        if not isinstance(teams, list) or not teams or not all(_valid_team(t) for t in teams):
            return False
    return True


class CollegeTeamList:
    """The cached picker payload and when to fetch it again. Thread-safe: the admin loop reads it
    while a worker thread refreshes it."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._wall = wall
        self._path: Path | None = None
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None
        self._fetched_at = 0.0
        self._retry_after = 0.0
        self._busy = False

    def use_file(self, path: Path | None) -> None:
        """Keep the list in ``path`` from now on, and take what is already there if nothing newer
        is in memory. ``None`` (tests, bare dev runs) keeps it in memory only."""
        with self._lock:
            self._path = path
            if path is None or self._payload is not None:
                return
            loaded = self._read(path)
            if loaded is None:
                return
            payload, saved_at = loaded
            # The age carries over a restart through the wall clock; a clock that jumped back
            # makes the file look new rather than from the future.
            self._payload = payload
            self._fetched_at = self._clock() - max(0.0, self._wall() - saved_at)

    @staticmethod
    def _read(path: Path) -> tuple[dict[str, Any], float] | None:
        try:
            raw = json.loads(path.read_text())
            payload, saved_at = raw["payload"], float(raw["saved_at"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("Ignoring the unreadable college team list %s", path)
            return None
        if not valid_payload(payload):
            log.warning("Ignoring the college team list %s: not the expected shape", path)
            return None
        return payload, saved_at

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        """Store ``payload`` atomically (write a neighbour, then rename). Never raises."""
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"saved_at": self._wall(), "payload": payload}))
            os.replace(tmp, path)
        except OSError:
            log.warning("Could not save the college team list to %s", path, exc_info=True)
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)

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
        path: Path | None = None
        fresh: dict[str, Any] = {}
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
                    path, fresh = self._path, self._payload
                else:
                    self._retry_after = now + RETRY_SECONDS
                stored = self._payload is not None and self._fetched_at == now
        if stored and path is not None:
            self._write(path, fresh)
        if not stored:
            log.warning("College team list unavailable; retrying in %ds", int(RETRY_SECONDS))
        return stored
