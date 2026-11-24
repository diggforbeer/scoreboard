"""College polls: AP, Coaches and the Playoff Committee's rankings (#546).

One ESPN request (``.../college-football/rankings``) carries every poll. Which one means "ranked"
is the owner's choice (``[football] college_poll``), because the AP and the committee often
disagree; the rank badges and the upset alert go through
:meth:`Polls.rank_of` so they can never disagree with each other.

The scoreboard's own ``curatedRank`` is *not* used for that: the spike could not tell which poll
it follows (``football_api.md``). Rank is looked up here, by ESPN team id, from the chosen poll.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

POLL_AP = "ap"
POLL_COACHES = "usa"  #: ESPN's key for the AFCA Coaches Poll
POLL_CFP = "cfp"  #: the Playoff Committee's rankings, published from about week 10
#: The polls the board reads; ESPN also sends FCS and Division II/III polls, which are ignored.
POLLS = (POLL_AP, POLL_COACHES, POLL_CFP)
POLL_NAMES = {POLL_AP: "AP Top 25", POLL_COACHES: "Coaches Poll", POLL_CFP: "CFP Rankings"}
#: The scoreboard's ``curatedRank.current`` for a team in none of the top 25.
UNRANKED = 99
#: A poll older than this is treated as absent. They are weekly, but the committee's last
#: rankings (early December) must outlive the bowl gap, and last season's final polls must
#: not still be showing in the spring. Six and a half weeks does both.
FRESH_DAYS = 45


@dataclass(frozen=True, slots=True)
class RankEntry:
    rank: int  #: 1-25
    previous: int | None  #: last week's rank, ``None`` if it was not ranked
    team_id: int
    abbrev: str
    record: str  #: ``9-1``
    conference: str  #: ``SEC``; only the committee's entries have it, the AP's are empty
    points: float  #: voting points; the committee has none (0)
    first_place_votes: int

    @property
    def movement(self) -> int | None:
        """Places gained since last week (negative = fell); ``None`` for a new entry."""
        return None if self.previous is None else self.previous - self.rank


@dataclass(frozen=True, slots=True)
class Poll:
    key: str  #: one of :data:`POLLS`
    name: str
    date: datetime | None  #: the week the poll is for (UTC)
    updated: datetime | None  #: when ESPN last changed it (UTC)
    entries: tuple[RankEntry, ...]
    _by_team: dict[int, RankEntry] = field(default_factory=dict, repr=False, compare=False)

    def entry(self, team_id: int | str) -> RankEntry | None:
        try:
            return self._by_team.get(int(team_id))
        except (TypeError, ValueError):
            return None

    def rank_of(self, team_id: int | str) -> int | None:
        found = self.entry(team_id)
        return found.rank if found else None

    def is_fresh(self, now: datetime) -> bool:
        stamp = self.updated or self.date
        return stamp is not None and now - stamp <= timedelta(days=FRESH_DAYS)


@dataclass(frozen=True, slots=True)
class Polls:
    """The polls from one fetch, by key."""

    polls: dict[str, Poll]

    def get(self, key: str, now: datetime | None = None) -> Poll | None:
        """The poll ``key``, or ``None`` if ESPN did not send it or it is stale (when ``now``)."""
        poll = self.polls.get(key)
        if poll is None or (now is not None and not poll.is_fresh(now)):
            return None
        return poll

    def chosen(self, choice: str, now: datetime) -> Poll | None:
        """The poll that decides "ranked" for the setting ``choice``.

        ``cfp`` falls back to the AP until the committee has published (it starts around week 10),
        and a stale poll counts as absent, so out of season this is ``None``: nobody is ranked.
        An unknown ``choice`` is the AP.
        """
        key = choice if choice in POLLS else POLL_AP
        poll = self.get(key, now)
        if poll is None and key == POLL_CFP:
            poll = self.get(POLL_AP, now)
        return poll

    def rank_of(self, team_id: int | str, choice: str, now: datetime) -> int | None:
        """The team's rank in the chosen poll, or ``None`` if it is unranked or there is no poll."""
        poll = self.chosen(choice, now)
        return poll.rank_of(team_id) if poll else None


def _when(value: Any) -> datetime | None:
    """ESPN's ``2026-11-17T08:00Z`` as an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _entry(raw: Any) -> RankEntry | None:
    try:
        team = raw["team"]
        rank = int(raw["current"])
        team_id = int(team["id"])
        abbrev = str(team["abbreviation"]).strip()
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= rank <= 25 or not abbrev:
        return None
    try:
        previous = int(raw.get("previous") or 0)
    except (TypeError, ValueError):
        previous = 0
    try:
        points = float(raw.get("points") or 0)
        firsts = int(raw.get("firstPlaceVotes") or 0)
    except (TypeError, ValueError):
        points, firsts = 0.0, 0
    return RankEntry(
        rank=rank,
        previous=previous if 1 <= previous <= 25 else None,
        team_id=team_id,
        abbrev=abbrev,
        record=str(raw.get("recordSummary") or ""),
        conference=str(raw.get("conference") or ""),
        points=points,
        first_place_votes=firsts,
    )


def polls_from_payload(payload: Any) -> Polls | None:
    """The AP, Coaches and CFP polls in a ``/rankings`` payload.

    ``None`` if the payload is not the expected shape (no ``rankings`` list). A poll with no
    usable entries is dropped, so an empty poll is the same as an absent one. An entry that cannot
    be read is skipped and logged. ESPN's FCS and lower-division polls are ignored.
    """
    listed = payload.get("rankings") if isinstance(payload, dict) else None
    if not isinstance(listed, list):
        return None
    found: dict[str, Poll] = {}
    for raw in listed:
        key = raw.get("type") if isinstance(raw, dict) else None
        if key not in POLLS or key in found:
            continue
        entries: list[RankEntry] = []
        for item in raw.get("ranks") or []:
            built = _entry(item)
            if built is None:
                log.warning("Skipping an unreadable %s poll entry", key)
                continue
            entries.append(built)
        if not entries:
            continue
        entries.sort(key=lambda e: e.rank)
        found[key] = Poll(
            key=key,
            name=str(raw.get("name") or POLL_NAMES[key]),
            date=_when(raw.get("date")),
            updated=_when(raw.get("lastUpdated")),
            entries=tuple(entries),
            _by_team={e.team_id: e for e in entries},
        )
    return Polls(found)
