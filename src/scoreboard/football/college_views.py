"""What the college idle screens show (#551 and its siblings): plain data, built from the cached
polls and the slate, with no drawing. ``idle_screens.py`` registers each builder as a screen's
``should_show``; ``display/college_idle.py`` draws the view it returns."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..config import CFP_FIELD_DEFAULT
from .college_rankings import POLL_AP, POLL_CFP, POLL_NAMES
from .college_standings import ConferenceRow, short_conference

if TYPE_CHECKING:
    from .idle_screens import IdleContext
    from .models import FbGame


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
    #: A line is drawn after this many rows (the playoff cut on the committee's screen); 0 draws
    #: none, as for the AP.
    cut: int = 0

    @property
    def scroll_rows(self) -> int:
        """How many rows the slot has to scroll past (``football.scroll``)."""
        return len(self.rows)


#: The label block's lines for each poll's screen.
POLL_LABELS = {POLL_AP: ("AP", "TOP", "25"), POLL_CFP: ("CFP", "RANK", "25")}


def build_poll(ctx: IdleContext, key: str, cut: int = 0) -> PollView | None:
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
        cut=cut,
    )


def build_ap(ctx: IdleContext) -> PollView | None:
    return build_poll(ctx, POLL_AP)


def build_cfp(ctx: IdleContext) -> PollView | None:
    """The Playoff Committee's rankings (#552), only once they exist for this season: they start
    around week 10, so before that ESPN sends none (``None``), and last season's last table is
    older than ``FRESH_DAYS`` by the time the next season has begun."""
    return build_poll(ctx, POLL_CFP, cut=getattr(ctx.config, "cfp_field", CFP_FIELD_DEFAULT))


@dataclass(frozen=True, slots=True)
class ConferenceView:
    """The lead team's conference as a scrolling table (#553)."""

    #: ``Southeastern Conference``.
    name: str
    #: ``SEC``, for the label block.
    short: str
    rows: tuple[ConferenceRow, ...]
    #: The lead college team, highlighted.
    team: str

    @property
    def scroll_rows(self) -> int:
        return len(self.rows)


def build_conference(ctx: IdleContext) -> ConferenceView | None:
    """The lead team's conference, or ``None`` (skip, never blank) when the standings are not
    fetched yet or stale, the team is in none, or no team in it has played a game (the table is
    all zeros before the season)."""
    standings = ctx.idle.college_standings(ctx.now)
    team = ctx.config.favourite_team.strip().upper()
    table = standings.conference_of(team) if standings is not None and team else None
    if table is None or not table.played:
        return None
    return ConferenceView(table.name, table.short, table.rows, team)


# -- the scores grid (#556) -----------------------------------------------------------------------

#: Games on one frame of the grid: four 32px columns across the 128px chain (idle screens are 128px
#: only), the same as hockey's ``scores_grid``.
SCORES_PER_PAGE = 4


@dataclass(frozen=True, slots=True)
class ScoresView:
    """The slate for the scores grid, ranked games first, in pages of ``SCORES_PER_PAGE``."""

    games: tuple[FbGame, ...]

    @property
    def pages(self) -> int:
        return max(-(-len(self.games) // SCORES_PER_PAGE), 1)

    def page(self, number: int) -> tuple[FbGame, ...]:
        start = number * SCORES_PER_PAGE
        return self.games[start : start + SCORES_PER_PAGE]


def _best_rank(game: FbGame) -> int:
    ranks = [t.rank for t in (game.away, game.home) if t.rank]
    return min(ranks) if ranks else 99


def scores_order(games: Sequence[FbGame], ranked_only: bool) -> tuple[FbGame, ...]:
    """Games with a ranked team first (best rank leading), then the rest; each group in kickoff
    order, so the order is steady while a game's score changes. ``ranked_only`` drops the rest."""
    far = datetime.max.replace(tzinfo=UTC)
    picked = [g for g in games if _best_rank(g) < 99 or not ranked_only]
    return tuple(sorted(picked, key=lambda g: (_best_rank(g), g.start_utc or far, g.id)))


def build_scores(ctx: IdleContext) -> ScoresView | None:
    """The scoreboard already polled, filtered by ``football.college_scores``; ``None`` with
    nothing to list (the slot is skipped, never shown blank)."""
    games = scores_order(ctx.games, getattr(ctx.config, "college_scores", "all") == "ranked")
    return ScoresView(games) if games else None
