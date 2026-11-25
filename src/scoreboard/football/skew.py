"""How far the scoreboard feed runs ahead of the play-by-play (a measurement, not a behaviour).

The scoreboard names the play its live ``situation`` reflects (``lastPlay.id``); the plays feed
(``/summary``) lists plays by the same ids. The resting field, the score and the possession come
from the first, the animations from the second, so the field can show a play's result before the
play is shown. This logs, per watched game, when the scoreboard first names a play and when the
plays feed first has it::

    [401873077] scoreboard names play 4018730772112 (Punt); plays feed has it: no
    [401873077] plays feed has 4018730772112 (Punt) 11.2s after the scoreboard named it

The board's own ``play shown: id=...`` line (``queue.py``) gives the third time, so the whole chain
is in ``journalctl -u scoreboard | grep -E "skew|play shown"``. Whether the ids really match in a
live game is part of what this answers: a play the scoreboard names that the feed never lists is
logged as ``never listed`` once the game moves on.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable

from .models import FbGame, Play

log = logging.getLogger(__name__)

#: Plays remembered per game: enough for the lag, small enough to forget a finished game.
KEEP = 40
#: A named play still absent from the feed after this many newer plays were named is "never listed".
NEVER_AFTER = 3


class SkewLog:
    """Feed worker thread only."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        #: game id -> play id -> [monotonic time named, type, listed?, plays named since]
        self._named: dict[int, dict[str, list]] = {}

    def observe(self, game: FbGame, plays: Iterable[Play]) -> None:
        """One poll: the game as the scoreboard has it, and its plays as the feed has them."""
        now = self._monotonic()
        named = self._named.setdefault(game.id, {})
        listed = {p.id for p in plays}
        last = game.situation.last_play if game.situation is not None else None
        if last is not None and last.id and last.id not in named:
            for entry in named.values():
                entry[3] += 1
            named[last.id] = [now, last.type, False, 0]
            log.info(
                "[%s] scoreboard names play %s (%s); plays feed has it: %s",
                game.id,
                last.id,
                last.type,
                "yes" if last.id in listed else "no",
            )
        for play_id, entry in list(named.items()):
            named_at, kind, was_listed, newer = entry
            if was_listed:
                continue
            if play_id in listed:
                entry[2] = True
                log.info(
                    "[%s] plays feed has %s (%s) %.1fs after the scoreboard named it",
                    game.id,
                    play_id,
                    kind,
                    now - named_at,
                )
            elif newer >= NEVER_AFTER:
                entry[2] = True
                log.info(
                    "[%s] play %s (%s) named by the scoreboard, never listed",
                    game.id,
                    play_id,
                    kind,
                )
        while len(named) > KEEP:
            del named[next(iter(named))]

    def forget(self, keep: Callable[[int], bool]) -> None:
        for game_id in [g for g in self._named if not keep(g)]:
            del self._named[game_id]
