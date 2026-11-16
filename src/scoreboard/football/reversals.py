"""Detect when the feed changes a play that was celebrated (#357).

The owner's decision (``football_screen.md``, "Reviews and reversals"): **celebrate at once**,
and if the play is later changed, say so on a ``fb_reversal`` screen and carry on. This module
is the "say so" half: it remembers every celebrated play and compares it with each poll.

What the feed actually does (``football_api.md``, "The play feed"; seen on nine reversed plays in
13 finished games): ESPN does not remove a reversed play, it **rewrites it in place**. The type
and flags become the final ruling and the text keeps the original call, then ``the play was
REVERSED.``, then the corrected play. So a reversed touchdown looks like an ordinary
incompletion with ``scoringPlay`` false. Detection is therefore a comparison of *outcomes*:

* ``play_gone``: the play is no longer in the feed;
* ``flag_cleared``: it no longer scores (``scoringPlay`` false) or is no longer a turnover;
* ``type_changed``: its type is not the one that was celebrated;
* ``score_dropped``: the scoring team's score after the play is lower than what was announced;
* ``possession_restored``: a turnover on downs after which the same team has the ball again.

The review sentence is **not** a rule on its own, because a review can go the *other* way (an
incompletion reversed into a touchdown is celebrated, correctly). It supplies the reason, and an
upheld review, or one that leaves the celebrated outcome as it was, is not a reversal. A text-only
change is not one either.

None of these has been seen *while a review is in progress* (that needs a live game), so every
match is logged at INFO with the rules that fired and the play id, which is how they get tightened.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .events import Event, EventDetector, FieldGoal, GenericScore, ScoreEvent, Touchdown, Turnover
from .models import FbGame, Play
from .playtext import Review

log = logging.getLogger(__name__)

#: Shown when the feed gives nothing usable to explain the change.
DEFAULT_REASON = "PLAY CHANGED ON REVIEW"
#: A reason longer than this is cut, so a screen can fit it.
MAX_REASON = 120

_TITLES = {
    Touchdown: ("touchdown", "TOUCHDOWN OVERTURNED"),
    FieldGoal: ("field_goal", "FIELD GOAL NEGATED"),
    GenericScore: ("score", "SCORE OVERTURNED"),
    Turnover: ("turnover", "TURNOVER OVERTURNED"),
}
_NOISE = re.compile(r"^\s*(?:\([^)]*\)\s*|\S+(?: and \S+)* reported in as eligible\.\s*)+", re.I)


@dataclass(frozen=True, slots=True, kw_only=True)
class Reversal(Event):
    """A celebrated play the feed has since changed."""

    #: The celebration this undoes.
    original: Event
    #: ``touchdown`` / ``field_goal`` / ``score`` / ``turnover``, and the title a screen shows.
    original_kind: str
    title: str
    #: Every rule that fired, most telling first; ``rule`` is the first.
    rules: tuple[str, ...]
    rule: str
    #: Why, from the feed's own words: the corrected play, a penalty, or ``DEFAULT_REASON``.
    reason: str
    #: The review written into the play, if there is one.
    review: Review | None
    #: The play as the feed has it now (``None`` if it is gone).
    current: Play | None
    #: The down and distance after the play as now ruled, if the feed gives it.
    down_distance: str = ""


class ReversalDetector:
    def __init__(self, scores: EventDetector | None = None) -> None:
        """``scores`` is the event detector whose running score a reversal must correct (see
        ``EventDetector.retract``); pass it, or a reversed touchdown swallows the next real one."""
        self._scores = scores
        #: game id -> play id -> the celebration, until it is reversed
        self._celebrated: dict[int, dict[str, Event]] = {}
        #: game id -> play id -> the newest polled version of every play seen
        self._latest: dict[int, dict[str, Play]] = {}

    # -- what was celebrated ------------------------------------------------

    def remember(self, event: Event) -> Reversal | None:
        """Note a celebrated play. Only scores and turnovers can be reversed.

        If the feed has *already* changed the play (a reversal that landed while the celebration
        was still waiting in the queue), the reversal is returned straight away.
        """
        if not isinstance(event, tuple(_TITLES)):
            return None
        if isinstance(event, FieldGoal) and not event.made:
            return None
        self._celebrated.setdefault(event.game_id, {})[event.play.id] = event
        latest = self._latest.get(event.game_id, {}).get(event.play.id)
        if latest is not None:
            return self._check(event, latest)
        return None

    def remember_all(self, events: Iterable[Event]) -> list[Reversal]:
        out = [self.remember(e) for e in events]
        return [r for r in out if r is not None]

    def pending(self, game_id: int) -> int:
        """Celebrated plays still being watched for a change."""
        return len(self._celebrated.get(game_id, {}))

    # -- each poll ---------------------------------------------------------------

    def on_poll(self, game: FbGame | int, plays: Sequence[Play]) -> list[Reversal]:
        """Compare a poll's plays (rewritten ones included) with what was celebrated."""
        game_id = game if isinstance(game, int) else game.id
        latest = self._latest.setdefault(game_id, {})
        by_id = {p.id: p for p in plays}
        latest.update(by_id)
        out: list[Reversal] = []
        for play_id, event in list(self._celebrated.get(game_id, {}).items()):
            reversal = self._check(event, by_id.get(play_id), poll_has_game=bool(plays))
            if reversal is not None:
                out.append(reversal)
        return out

    def forget(self, keep: Callable[[int], bool]) -> None:
        for table in (self._celebrated, self._latest):
            for game_id in [g for g in table if not keep(g)]:
                del table[game_id]

    # -- the comparison --------------------------------------------------------------

    def _check(self, event: Event, now: Play | None, poll_has_game: bool = True) -> Reversal | None:
        # A play missing from a poll that returned nothing at all is a failed fetch, not a reversal.
        if now is None and not poll_has_game:
            return None
        rules = _rules_fired(event, now)
        if not rules:
            if now is not None and now.info.review is not None:
                log.debug(
                    "[%s] play %s was reviewed (%s) but the celebrated outcome stands",
                    event.game_id, event.play.id,
                    "reversed in its favour" if now.info.review.reversed else "upheld",
                )  # fmt: skip
            return None
        reversal = _build(event, now, rules)
        # Reported once: a later change to the same play is a new play, so it is forgotten.
        self._celebrated.get(event.game_id, {}).pop(event.play.id, None)
        log.info(
            "[%s] reversal detected: play=%s kind=%s rules=%s review=%s reason=%r",
            event.game_id, event.play.id, reversal.original_kind, ",".join(rules),
            "yes" if reversal.review is not None else "no", reversal.reason,
        )  # fmt: skip
        if self._scores is not None and isinstance(event, ScoreEvent):
            self._scores.retract(
                event.game_id,
                max(0, event.away_score - event.away_before),
                max(0, event.home_score - event.home_before),
            )
        return reversal


def _rules_fired(event: Event, now: Play | None) -> tuple[str, ...]:
    if now is None:
        return ("play_gone",)
    rules: list[str] = []
    original = event.play
    if isinstance(event, ScoreEvent):
        side, announced = _scoring_side(event)
        if (now.home_score if side == "home" else now.away_score) < announced:
            rules.append("score_dropped")
        if not now.scoring_play:
            rules.append("flag_cleared")
    elif isinstance(event, Turnover):
        if event.reason == "on_downs":
            start, end = now.start, now.end
            if start is not None and end is not None and start.team_id == end.team_id:
                rules.append("possession_restored")
        elif original.is_turnover and not now.is_turnover:
            rules.append("flag_cleared")
    if now.type != original.type:
        rules.append("type_changed")
    return tuple(rules)


def _scoring_side(event: ScoreEvent) -> tuple[str, int]:
    """Which side the event scored for, and what that side's score was announced as."""
    if event.home_score - event.home_before >= event.away_score - event.away_before:
        return "home", event.home_score
    return "away", event.away_score


def _build(event: Event, now: Play | None, rules: tuple[str, ...]) -> Reversal:
    kind, title = next(v for cls, v in _TITLES.items() if isinstance(event, cls))
    review = now.info.review if now is not None else None
    if isinstance(event, ScoreEvent):
        restored = (
            (event.away_before, event.home_before)
            if now is None
            else (now.away_score, now.home_score)
        )
    else:
        restored = (
            (event.away_score, event.home_score)
            if now is None
            else (now.away_score, now.home_score)
        )
    return Reversal(
        play=now or event.play,
        game_id=event.game_id,
        team=event.team,
        scope=event.scope,
        sound=False,
        away_score=restored[0],
        home_score=restored[1],
        original=event,
        original_kind=kind,
        title=title,
        rules=rules,
        rule=rules[0],
        reason=_reason(now, review),
        review=review,
        current=now,
        down_distance=(now.end.down_distance_text if now is not None and now.end else ""),
    )  # fmt: skip


def _reason(now: Play | None, review: Review | None) -> str:
    """The feed's own words: the corrected play, else the penalty, else a plain default."""
    if review is not None and review.reversed and review.corrected_text:
        text = _tidy(review.corrected_text)
        if text:
            return text
    if now is not None:
        accepted = [p for p in now.info.penalties if not p.declined and not p.offsetting]
        if accepted:
            pen = accepted[0]
            tail = ", NO PLAY" if now.info.no_play else ""
            return _clip(f"{pen.name.upper()} ON {pen.team}{tail}")
    if review is not None and review.subject:
        return _clip(f"{review.subject.upper()} RULING REVERSED")
    return DEFAULT_REASON


def _tidy(text: str) -> str:
    """Trim formation and substitution noise (``(Shotgun)``, ``X reported in as eligible.``)."""
    cleaned = _NOISE.sub("", " ".join(text.split())).strip()
    return _clip(cleaned)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_REASON else text[: MAX_REASON - 3].rstrip() + "..."
