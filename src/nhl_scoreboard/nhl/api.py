"""Client for the public NHL web API (api-web.nhle.com).

This is the same undocumented-but-public API the NHL's own site uses. It is
unauthenticated and rate-limit friendly at the poll intervals we use, but it
is not contractual -- every call is wrapped so that a bad response degrades to
"no new data" rather than taking the board down.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Game

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
        games = [Game.from_api(raw) for raw in payload.get("games", [])]
        games.sort(key=Game.sort_key)
        return games

    def standings(self, date: str = "now") -> list[dict[str, Any]]:
        return list(self._get(f"/standings/{date}").get("standings", []))

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
