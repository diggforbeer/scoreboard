"""What the college idle screens show (#551 and its siblings): plain data, built from the cached
polls and the slate, with no drawing. ``idle_screens.py`` registers each builder as a screen's
``should_show``; ``display/college_idle.py`` draws the view it returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .college_rankings import POLL_AP, POLL_CFP, POLL_NAMES

if TYPE_CHECKING:
    from .idle_screens import IdleContext


#: How ESPN's conference names are shortened to fit beside a record (4 letters of room).
CONFERENCE_SHORT = {
    "big ten": "B1G",
    "big 12": "B12",
    "pac-12": "PAC",
    "fbs indep.": "IND",
    "american": "AAC",
    "sun belt": "SBC",
    "mountain west": "MWC",
    "conference usa": "CUSA",
    "mid-american": "MAC",
}


def short_conference(name: str) -> str:
    """``Big Ten`` as ``B1G``: the known names by table, any other upper-cased and cut to 4."""
    key = name.strip().lower()
    return CONFERENCE_SHORT.get(key, key.upper()[:4])


@dataclass(frozen=True, slots=True)
class PollRow:
    rank: int
    abbrev: str
    record: str
    #: Places gained since the last poll (negative = fell); ``None`` for a team new to the poll.
    movement: int | None
    #: The voting points (0 where the poll has none).
    points: int
    #: A first-place vote count above zero, shown beside the points.
    firsts: int
    #: The team's conference, short (``SEC``, ``B1G``); the committee's rankings carry it, the AP's
    #: do not.
    conference: str = ""


@dataclass(frozen=True, slots=True)
class PollView:
    """A ranking poll as a scrolling table."""

    key: str
    #: ``AP TOP 25``.
    title: str
    #: The three short lines the label block at the left of the table shows.
    label: tuple[str, str, str]
    rows: tuple[PollRow, ...]
    #: The lead college team, highlighted when it is in the poll.
    team: str

    @property
    def scroll_rows(self) -> int:
        """How many rows the slot has to scroll past (``football.scroll``)."""
        return len(self.rows)


#: The label block's lines for each poll's screen.
POLL_LABELS = {POLL_AP: ("AP", "TOP", "25"), POLL_CFP: ("CFP", "RANK", "25")}


def build_poll(ctx: IdleContext, key: str) -> PollView | None:
    """The poll ``key`` as a view, or ``None`` when there is no fresh copy of it: not fetched yet,
    or older than ``FRESH_DAYS`` (out of season), so the screen is skipped rather than shown blank.
    ``chosen()`` is not used: the AP's screen is the AP's whatever ``college_poll`` says."""
    polls = ctx.idle.polls()
    poll = polls.get(key, ctx.utc) if polls is not None else None
    if poll is None or not poll.entries:
        return None
    rows = tuple(
        PollRow(
            rank=e.rank,
            abbrev=e.abbrev,
            record=e.record,
            movement=e.movement,
            points=int(e.points),
            firsts=e.first_place_votes,
            conference=short_conference(e.conference),
        )
        for e in poll.entries
    )
    return PollView(
        key=key,
        title=POLL_NAMES[key].upper(),
        label=POLL_LABELS[key],
        rows=rows,
        team=ctx.config.favourite_team.strip().upper(),
    )


def build_ap(ctx: IdleContext) -> PollView | None:
    return build_poll(ctx, POLL_AP)


def build_cfp(ctx: IdleContext) -> PollView | None:
    """The Playoff Committee's rankings (#552), only once they exist for this season: they start
    around week 10, so before that ESPN sends none (``None``), and last season's last table is
    older than ``FRESH_DAYS`` by the time the next season has begun."""
    return build_poll(ctx, POLL_CFP)
