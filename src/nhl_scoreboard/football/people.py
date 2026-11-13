"""Who did it, with a jersey number (#354): rosters, participants, and the fallbacks.

``fb_run`` and ``fb_pass`` put a number on the ball and the scoring screens name the scorer, so a
play needs to say *who*. ESPN splits that across three places, and this module joins them:

* the **core plays** feed lists each play's ``participants`` (a role and an athlete ``$ref``);
* the athlete id is read **straight out of the ``$ref``**: no athlete is ever fetched;
* a **team roster** maps athlete id to name and jersey number. It is cached hourly per team.

Fallbacks, because the feed is undocumented and not every player has a number (5 of 79 on one
roster did not): a player with no number is shown by their **last name**; an athlete who is not on
the roster (traded, just signed) is named from the **play text** (``J.Burrow``); and nothing here
ever raises. Where the play text names nobody for a role (a tackler, a long snapper) the name is
empty and so is the label.

When to fetch the core feed (measured 2026-11-13 on a finished game, ``football_api.md``): the whole
list is 37 KB on the wire (757 KB decoded) in 0.3s and a 25-play page is 5 KB in 0.14s, so
**fetch it only when the site summary shows a play it has not seen** (about one play a minute),
the whole list in one request. That is :class:`CoreSync`. Core play ids match the site feed's
exactly, so the two join on ``id``; the core list also holds the ``Coin Toss`` the site feed omits.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import Play, _dict, _int, _list, _str

log = logging.getLogger(__name__)

#: A roster is good for this long before it is fetched again (like the NHL hourly caches).
ROSTER_TTL_SECONDS = 60 * 60
#: After a failed roster fetch, wait this long before trying that team again.
ROSTER_RETRY_SECONDS = 60.0


# -- the roster ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RosterPlayer:
    athlete_id: int
    name: str  #: ``M. Bergeron``
    full_name: str  #: ``Matthew Bergeron``
    last_name: str
    #: The jersey number as ESPN sends it (``"65"``); ``""`` when the player has none.
    jersey: str
    position: str  #: ``G``, ``QB``

    @staticmethod
    def from_api(raw: Any) -> RosterPlayer | None:
        a = _dict(raw)
        athlete_id = _int(a.get("id"), None)
        if athlete_id is None:
            return None
        full = _str(a.get("fullName")) or _str(a.get("displayName"))
        return RosterPlayer(
            athlete_id=athlete_id,
            name=_str(a.get("shortName")) or full,
            full_name=full,
            last_name=_str(a.get("lastName")) or _last_name(full),
            jersey=str(a.get("jersey")).strip() if a.get("jersey") not in (None, "") else "",
            position=_str(_dict(a.get("position")).get("abbreviation")),
        )


def roster_from_payload(payload: Any) -> dict[int, RosterPlayer]:
    """Every player in a ``.../teams/{id}/roster`` payload, by athlete id. Never raises."""
    players: dict[int, RosterPlayer] = {}
    for group in _list(_dict(payload).get("athletes")):
        items = _list(_dict(group).get("items")) if isinstance(group, dict) else []
        for item in items:
            player = RosterPlayer.from_api(item)
            if player is not None:
                players[player.athlete_id] = player
    return players


# -- who did it ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Person:
    role: str
    athlete_id: int | None
    #: ``M. Bergeron`` from the roster, else the play text's ``M.Bergeron``, else ``""``.
    name: str
    jersey: str
    position: str
    #: Whether the roster had this athlete.
    on_roster: bool

    @property
    def last_name(self) -> str:
        return _last_name(self.name)

    @property
    def label(self) -> str:
        """What a screen puts on the ball: the jersey number, else the last name in capitals."""
        return self.jersey or self.last_name.upper()


def _last_name(name: str) -> str:
    """``J.Burrow`` -> ``Burrow``; ``D.St. Brown`` -> ``Brown``; ``K.Walker Jr.`` -> ``Walker``."""
    tokens = [t for t in re.split(r"[.\s]+", name) if t]
    while tokens and tokens[-1].lower() in ("jr", "sr", "ii", "iii", "iv"):
        tokens.pop()
    return tokens[-1] if tokens else ""


def _text_name(play: Play, role: str) -> str:
    """The name the play's text gives for ``role``, if it names one."""
    i = play.info
    if role == "scorer":
        return i.rusher or i.target or i.kicker or i.returner
    if role in ("kicker", "punter", "patScorer"):
        return i.kicker
    names = {
        "passer": i.passer,
        "receiver": i.target,
        "rusher": i.rusher,
        "returner": i.returner,
        "interceptor": i.interceptor,
        "sackedBy": i.sackers[0] if i.sackers else "",
    }
    return names.get(role, "")


def resolve_people(play: Play, players: Mapping[int, RosterPlayer]) -> tuple[Person, ...]:
    """Everyone the core feed names on ``play``, with names and numbers where known."""
    out: list[Person] = []
    for part in play.participants:
        rp = players.get(part.athlete_id) if part.athlete_id is not None else None
        if rp is not None:
            out.append(Person(part.role, part.athlete_id, rp.name, rp.jersey, rp.position, True))
        else:
            out.append(
                Person(part.role, part.athlete_id, _text_name(play, part.role), "", "", False)
            )
    return tuple(out)


def find(people: Iterable[Person], *roles: str) -> Person | None:
    """The first person in any of ``roles``, in the order the roles are given."""
    people = list(people)
    for role in roles:
        for person in people:
            if person.role == role:
                return person
    return None


# -- joining the two feeds -----------------------------------------------------------------------


def merge_core(
    site_plays: Sequence[Play], core_plays: Sequence[Play], include_core_only: bool = True
) -> list[Play]:
    """The site feed's plays with the core feed's participants attached, joined on play id.

    ``include_core_only`` keeps the plays only the core feed has (the ``Coin Toss``). A site play
    with no core counterpart is kept as it is. The result is in play order.
    """
    core = {p.id: p for p in core_plays}
    merged = [
        dataclasses.replace(p, participants=core[p.id].participants)
        if p.id in core and core[p.id].participants
        else p
        for p in site_plays
    ]
    if include_core_only:
        have = {p.id for p in site_plays}
        merged.extend(p for p in core_plays if p.id not in have)
    return sorted(merged, key=Play.sort_key)


class CoreSync:
    """Decides when the core feed is worth fetching: only when the site summary shows a new play.

    The core list costs 37 KB and 0.3s for a whole game, so fetching it every poll would be a
    waste; a play arrives about once a minute. ``should_fetch`` is true for the first look at a game
    and whenever the site feed has a play it had not seen at the last core fetch.
    """

    def __init__(self) -> None:
        self._seen: dict[int, set[str]] = {}

    def should_fetch(self, game_id: int, site_plays: Iterable[Play]) -> bool:
        seen = self._seen.get(game_id)
        return seen is None or any(p.id not in seen for p in site_plays)

    def fetched(self, game_id: int, site_plays: Iterable[Play]) -> None:
        self._seen[game_id] = {p.id for p in site_plays}

    def forget(self, keep: Callable[[int], bool]) -> None:
        for game_id in [g for g in self._seen if not keep(g)]:
            del self._seen[game_id]


# -- the roster cache ----------------------------------------------------------------------------


class RosterCache:
    """Each team's roster, fetched on first use and then at most once an hour.

    ``fetch(team_id)`` returns ``{athlete id: RosterPlayer}`` or ``None`` on failure. ``get`` never
    raises and never blocks the caller twice: a failure keeps whatever the last good fetch gave (or
    nothing) and is not retried for ``retry`` seconds. Held by ``NflMode``, so a sport switch
    starts with an empty cache. Not thread-safe: the feed worker owns it.
    """

    def __init__(
        self,
        fetch: Callable[[int], dict[int, RosterPlayer] | None],
        monotonic: Callable[[], float] = time.monotonic,
        ttl: float = ROSTER_TTL_SECONDS,
        retry: float = ROSTER_RETRY_SECONDS,
    ) -> None:
        self._fetch = fetch
        self._monotonic = monotonic
        self._ttl = ttl
        self._retry = retry
        self._entries: dict[int, tuple[float, dict[int, RosterPlayer]]] = {}
        self._retry_after: dict[int, float] = {}

    def get(self, team_id: int) -> dict[int, RosterPlayer]:
        now = self._monotonic()
        entry = self._entries.get(team_id)
        if entry is not None and now - entry[0] < self._ttl:
            return entry[1]
        if now < self._retry_after.get(team_id, 0.0):
            return entry[1] if entry else {}
        try:
            players = self._fetch(team_id)
        except Exception as exc:  # a roster must never take the loop down
            log.warning("roster fetch for team %s raised %s", team_id, exc)
            players = None
        if players is None:
            self._retry_after[team_id] = now + self._retry
            return entry[1] if entry else {}
        self._retry_after.pop(team_id, None)
        self._entries[team_id] = (now, players)
        log.info("roster for team %s: %d players", team_id, len(players))
        return players

    def players_for(self, team_ids: Iterable[int]) -> dict[int, RosterPlayer]:
        """Both teams of a game, merged, for :func:`resolve_people`."""
        merged: dict[int, RosterPlayer] = {}
        for team_id in team_ids:
            merged.update(self.get(team_id))
        return merged

    def age(self, team_id: int) -> float | None:
        """Seconds since that roster was fetched, or ``None`` if it never was."""
        entry = self._entries.get(team_id)
        return None if entry is None else self._monotonic() - entry[0]

    def clear(self) -> None:
        self._entries.clear()
        self._retry_after.clear()
