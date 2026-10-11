"""Client for the public NHL web API (api-web.nhle.com).

This is the same undocumented-but-public API the NHL's own site uses. It is
unauthenticated and rate-limit friendly at the poll intervals we use, but it
is not contractual -- every call is wrapped so that a bad response degrades to
"no new data" rather than taking the board down.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import (
    ClubStats,
    Game,
    GoalEvent,
    PlayerSeasonDetail,
    SeasonSeriesRecord,
    Shootout,
    Situation,
    StandingsRow,
    Star,
    goal_events_from_landing,
    player_details_from_api,
    series_meetings_from_api,
    shootout_from_landing,
    three_stars_from_landing,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api-web.nhle.com/v1"
USER_AGENT = "nhl-scoreboard/0.1 (+https://github.com/diggforbeer/scoreboard)"


#: (connect, read) seconds. Every fetch runs on the render loop, so this is
#: also how long one stalled request can freeze the panel. 10s read with
#: three retries froze it ~44s per poll -- ~2.5 min straight across three
#: back-to-back failed polls in a real board's log, 2026-10-10.
TIMEOUT = (5.0, 5.0)


#: How long a fetched ``gamecenter/{id}/landing`` payload is reused (#263).
#: situation(), goal_scoring() and three_stars() all read that one URL and
#: the run loop calls them back to back, so a few seconds covers one loop
#: pass -- including a slow first request -- without letting the data get
#: meaningfully staler than live_poll_seconds.
LANDING_REUSE_SECONDS = 5.0


class NHLApiError(RuntimeError):
    """Raised when the API could not be reached or returned unusable data."""


class NHLClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float | tuple[float, float] = TIMEOUT,
        session: requests.Session | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or _build_session()
        self.monotonic = monotonic
        #: game id -> (fetched at, landing payload), see LANDING_REUSE_SECONDS.
        self._landings: dict[int, tuple[float, dict[str, Any]]] = {}

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> NHLClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- endpoints -------------------------------------------------------

    def scores(self, date: str = "now") -> list[Game]:
        """Every game for ``date`` (``YYYY-MM-DD`` or ``now``), display-ordered."""
        payload = self._get(f"/score/{date}")
        games = _parse_items(payload.get("games") or [], Game.from_api, "game")
        games.sort(key=Game.sort_key)
        return games

    def schedule(self, team: str) -> list[Game]:
        """Every game on ``team``'s season schedule, in start order."""
        payload = self._get(f"/club-schedule-season/{team.strip().upper()}/now")
        games = _parse_items(payload.get("games") or [], Game.from_api, "game")
        games.sort(key=lambda g: g.start_utc)
        return games

    def situation(self, game_id: int) -> Situation | None:
        """Special-teams state for one live game; None at even strength."""
        payload = self._landing(game_id)
        try:
            return Situation.from_api(payload.get("situation"))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed situation for game %s: %s", game_id, exc)
            return None

    def goal_scoring(self, game_id: int) -> tuple[GoalEvent, ...]:
        """Every goal scored so far in ``game_id``, for the goal-detail screen (#122).

        Same landing payload ``situation()`` reads for the power-play
        indicator; the two poll independently but share one request
        (``_landing``, #263).
        """
        payload = self._landing(game_id)
        try:
            return goal_events_from_landing(payload)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed scoring for game %s: %s", game_id, exc)
            return ()

    def team_roster(self, team: str) -> dict[int, PlayerSeasonDetail]:
        """Jersey number + season points for every player on ``team`` (#124).

        Two calls, combined: neither ``roster/{team}/current`` nor
        ``club-stats/{team}/now`` alone has both jersey number and points
        (confirmed live) -- see ``player_details_from_api``. Malformed
        entries are skipped per-player, same precedent as ``_parse_items``,
        rather than losing the whole roster over one bad entry.
        """
        team = team.strip().upper()
        roster = self._get(f"/roster/{team}/current")
        club_stats = self._get(f"/club-stats/{team}/now")
        return player_details_from_api(roster, club_stats)

    def season_series(self, game_id: int) -> SeasonSeriesRecord | None:
        """Head-to-head wins this season between ``game_id``'s two teams (#157).

        A different endpoint from ``landing``: ``right-rail`` carries
        ``seasonSeriesWins``, oriented to this game's own away/home sides.
        ``0-0`` (not None) before any regular-season meeting has finished,
        including all through the preseason. None only when the key is
        missing or malformed.
        """
        payload = self._get(f"/gamecenter/{game_id}/right-rail")
        record = SeasonSeriesRecord.from_api(payload.get("seasonSeriesWins"))
        if record is None:
            log.warning("No usable seasonSeriesWins for game %s", game_id)
            return None
        # Same payload, so the meetings (#168) cost no extra request.
        return replace(record, meetings=series_meetings_from_api(payload.get("seasonSeries")))

    def three_stars(self, game_id: int) -> tuple[Star, ...]:
        """The three stars of a finished game (#156), or ``()`` until they're named.

        The same landing payload ``situation()`` and ``goal_scoring()``
        read, shared through ``_landing`` (#263); each feature still polls
        on its own schedule.
        """
        payload = self._landing(game_id)
        try:
            return three_stars_from_landing(payload)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed three stars for game %s: %s", game_id, exc)
            return ()

    def shootout(self, game_id: int) -> Shootout | None:
        """The shootout so far (#259), or None while landing has none yet.

        Another request to the landing URL, polled on its own faster
        schedule (``shootout_poll_seconds``) only during a shootout.
        """
        payload = self._get(f"/gamecenter/{game_id}/landing")
        try:
            return shootout_from_landing(payload)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed shootout for game %s: %s", game_id, exc)
            return None

    def standings(self, date: str = "now") -> list[StandingsRow]:
        """Every team's current standings line, unsorted across conferences.

        During the off-season this endpoint keeps serving the just-finished
        season's final standings rather than an empty result (verified with
        a live call) -- callers that care about "has the current season
        actually started" need a signal beyond just "rows came back", e.g.
        the favourite's own ``games_played``.
        """
        payload = self._get(f"/standings/{date}")
        return _parse_items(payload.get("standings") or [], StandingsRow.from_api, "standings row")

    def club_stats(self, team: str, date: str = "now") -> ClubStats:
        """``team``'s season stats per player (#201); both lists empty pre-season.

        ``now`` 307-redirects to ``/club-stats/{team}/{season}/{gameType}``.
        """
        payload = self._get(f"/club-stats/{team.strip().upper()}/{date}")
        return ClubStats.from_api(payload)

    # -- plumbing --------------------------------------------------------

    def _landing(self, game_id: int) -> dict[str, Any]:
        """``gamecenter/{id}/landing``, reused for LANDING_REUSE_SECONDS (#263).

        A failed fetch raises as before and caches nothing, so the next
        call retries. Entries for other games are dropped as they age out,
        so this never holds more than the few games polled together.
        """
        now = self.monotonic()
        self._landings = {
            gid: entry
            for gid, entry in self._landings.items()
            if now - entry[0] < LANDING_REUSE_SECONDS
        }
        if game_id in self._landings:
            return self._landings[game_id][1]
        payload = self._get(f"/gamecenter/{game_id}/landing")
        self._landings[game_id] = (now, payload)
        return payload

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise NHLApiError(f"GET {url} failed: {exc}") from exc
        except ValueError as exc:
            raise NHLApiError(f"GET {url} returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise NHLApiError(f"GET {url} returned {type(payload).__name__}, expected object")
        return payload


def _parse_items(raw_items: list[Any], parse: Callable[[Any], Any], label: str) -> list[Any]:
    """Parse each entry with ``parse``, skipping and logging one that's malformed.

    One bad game/row must not abort the whole response -- see #59.
    """
    items = []
    for raw in raw_items:
        try:
            items.append(parse(raw))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed %s entry: %s", label, exc)
    return items


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    # A timeout is retried once, not three times: a server that didn't
    # answer in 5s rarely does a second later, and the next poll is
    # seconds away anyway. Quick 429/5xx answers keep the full three.
    retry = Retry(
        total=3,
        connect=1,
        read=1,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
