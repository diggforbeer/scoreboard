"""Client for ESPN's public NFL scoreboard (#350).

Free, keyless and undocumented, so it can change without notice (see
``football_api.md``). Modelled on ``nhl/api.py`` -- the same retry policy and
timeouts -- with one deliberate difference: a failure never raises. ``scores()``
returns ``None`` ("no data") when the feed could not be reached or made no
sense, and ``[]`` only when ESPN really said there are no games (a bye week, the
off-season). The caller can tell the two apart, which the staleness logic needs.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import FbGame, Play
from .people import RosterPlayer, roster_from_payload

log = logging.getLogger(__name__)

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
#: The core API: per-play ``participants`` (who did it) and the ``Coin Toss`` play (#354).
CORE_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
#: Plays asked for per core page. A game has 150-200, so one page covers it; longer ones follow
#: ``pageCount``.
CORE_PAGE_LIMIT = 300
CORE_MAX_PAGES = 10
USER_AGENT = "nhl-scoreboard/0.1 (+https://github.com/diggforbeer/scoreboard)"

#: (connect, read) seconds, as the NHL client. Fetches may run on the render
#: thread until the worker story lands, so this is also how long a stalled
#: request can freeze the panel.
TIMEOUT = (5.0, 5.0)

#: The scoreboard answers ``cache-control: max-age=7`` to ``9`` (seen 2026-11-12/13),
#: so asking faster than this only returns the same bytes. The lowest interval
#: any caller should poll at.
MIN_POLL_SECONDS = 10.0


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    # One retry for a timeout (a server that did not answer in 5s rarely does a
    # second later and the next poll is seconds away); quick 429/5xx keep three.
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


class NflClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float | tuple[float, float] = TIMEOUT,
        session: requests.Session | None = None,
        core_url: str = CORE_URL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.core_url = core_url.rstrip("/")
        self.timeout = timeout
        self.session = session or _build_session()
        #: The last failure, or ``""`` after a success. For the admin page's status.
        self.last_error = ""

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> NflClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def scores(self, date: str | None = None) -> list[FbGame] | None:
        """Every game on ``date`` (``YYYYMMDD``; default today's slate), best-first.

        ``None`` means no data (network error, bad status, not JSON, not the
        shape expected); ``[]`` means ESPN answered and there are no games.
        """
        params = {"dates": date} if date else None
        payload = self._get("/scoreboard", params)
        if payload is None:
            return None
        games = _parse_events(payload.get("events"))
        games.sort(key=FbGame.sort_key)
        return games

    def plays(self, event_id: int | str) -> list[Play] | None:
        """Every play of a game so far, in the order they happened (#353).

        Read from the site ``summary``: ``drives.previous[].plays`` plus
        ``drives.current.plays``. ``None`` is no data (as for ``scores``); ``[]`` is a
        game with no plays yet. The coin toss is not in this endpoint (see
        ``football_api.md``). Drives are only a grouping: plays are de-duplicated by id
        and sorted by ``sequenceNumber``, so the order ESPN lists drives in never matters.
        """
        payload = self._get("/summary", {"event": str(event_id)})
        if payload is None:
            return None
        return plays_from_summary(payload)

    def core_plays(self, event_id: int | str) -> list[Play] | None:
        """A game's plays from the **core** feed, each with its ``participants`` (#354).

        The same plays as :meth:`plays` (ids match exactly) plus the ``Coin Toss`` the site feed
        omits. One request covers a whole game (37 KB on the wire); a longer one follows
        ``pageCount``. ``None`` is no data, ``[]`` is a game with no plays. See
        ``people.merge_core`` to join it with the site plays, and ``people.CoreSync`` for when
        it is worth fetching.
        """
        path = f"/events/{event_id}/competitions/{event_id}/plays"
        first = self._get(path, {"limit": str(CORE_PAGE_LIMIT)}, base=self.core_url)
        if first is None:
            return None
        pages = [first]
        total = _int_or(first.get("pageCount"), 1)
        for page in range(2, min(total, CORE_MAX_PAGES) + 1):
            more = self._get(
                path, {"limit": str(CORE_PAGE_LIMIT), "page": str(page)}, base=self.core_url
            )
            if more is None:
                return None
            pages.append(more)
        plays: dict[str, Play] = {}
        for payload in pages:
            for item in payload.get("items") or []:
                try:
                    play = Play.from_api(item)
                except (ValueError, TypeError, AttributeError, KeyError) as exc:
                    log.warning("Skipping unusable core play: %s", exc)
                    continue
                plays[play.id] = play
        return sorted(plays.values(), key=Play.sort_key)

    def roster(self, team_id: int | str) -> dict[int, RosterPlayer] | None:
        """A team's roster by athlete id (jersey, name, position), or ``None`` on failure (#354)."""
        payload = self._get(f"/teams/{team_id}/roster")
        if payload is None:
            return None
        return roster_from_payload(payload)

    # -- plumbing --------------------------------------------------------

    def _get(
        self, path: str, params: dict[str, str] | None = None, base: str | None = None
    ) -> dict[str, Any] | None:
        url = f"{base or self.base_url}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return self._fail(f"GET {url} failed: {exc}")
        except ValueError as exc:
            return self._fail(f"GET {url} returned invalid JSON: {exc}")
        if not isinstance(payload, dict):
            return self._fail(f"GET {url} returned {type(payload).__name__}, expected an object")
        if self.last_error:
            log.info("ESPN scoreboard is reachable again")
        self.last_error = ""
        return payload

    def _fail(self, message: str) -> None:
        # Warn on the first failure of a run, then stay quiet until it recovers,
        # so a long outage is one line in the journal, not one per poll.
        if not self.last_error:
            log.warning("ESPN scoreboard unavailable: %s", message)
        else:
            log.debug("ESPN scoreboard still unavailable: %s", message)
        self.last_error = message
        return None


def plays_from_summary(payload: dict[str, Any]) -> list[Play]:
    """The plays in a site ``summary`` payload, de-duplicated by id and in play order.

    ``drives.previous[].plays`` plus ``drives.current.plays``; drives are only a grouping,
    so the order ESPN lists them in never matters. A play listed twice keeps the later copy
    (ESPN rewrites a play in place after a review). Unusable plays are skipped.
    """
    drives = payload.get("drives")
    drives = drives if isinstance(drives, dict) else {}
    previous = drives.get("previous")
    groups = list(previous) if isinstance(previous, list) else []
    if isinstance(drives.get("current"), dict):
        groups.append(drives["current"])
    plays: dict[str, Play] = {}
    for group in groups:
        for item in (group.get("plays") if isinstance(group, dict) else None) or []:
            try:
                play = Play.from_api(item)
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                log.warning("Skipping unusable play: %s", exc)
                continue
            plays[play.id] = play
    return sorted(plays.values(), key=Play.sort_key)


def _parse_events(raw: Any) -> list[FbGame]:
    games: list[FbGame] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            games.append(FbGame.from_api(item))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            log.warning("Skipping unusable event: %s", exc)
    return games


def _int_or(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
