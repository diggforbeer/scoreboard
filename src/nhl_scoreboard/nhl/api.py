"""Client for the public NHL web API (api-web.nhle.com).

This is the same undocumented-but-public API the NHL's own site uses. It is
unauthenticated and rate-limit friendly at the poll intervals we use, but it
is not contractual -- every call is wrapped so that a bad response degrades to
"no new data" rather than taking the board down.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Game, GoalEvent, Situation, StandingsRow, goal_events_from_landing

log = logging.getLogger(__name__)

BASE_URL = "https://api-web.nhle.com/v1"
USER_AGENT = "nhl-scoreboard/0.1 (+https://github.com/diggforbeer/scoreboard)"


class NHLApiError(RuntimeError):
    """Raised when the API could not be reached or returned unusable data."""


class NHLClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or _build_session()

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
        payload = self._get(f"/gamecenter/{game_id}/landing")
        try:
            return Situation.from_api(payload.get("situation"))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed situation for game %s: %s", game_id, exc)
            return None

    def goal_scoring(self, game_id: int) -> tuple[GoalEvent, ...]:
        """Every goal scored so far in ``game_id``, for the goal-detail screen (#122).

        Same landing payload ``situation()`` already fetches for the
        power-play indicator -- this is a second request to that same URL,
        not a new endpoint, since the two features poll independently.
        """
        payload = self._get(f"/gamecenter/{game_id}/landing")
        try:
            return goal_events_from_landing(payload)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed scoring for game %s: %s", game_id, exc)
            return ()

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

    # -- plumbing --------------------------------------------------------

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
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
