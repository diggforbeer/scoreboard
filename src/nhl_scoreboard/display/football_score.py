"""``fb_score`` (#395): the generic score screen for anything the touchdown, field-goal and detail
screens do not know: a **safety**, a two-point conversion on its own, a return score of a kind
not yet seen in real data, or any scoring play with an unrecognised type.

Rule 1 of "Rules for anything unrecognised" (``football_screen.md``): a score is any play where the
score changed, so the favourite never goes uncelebrated. It shows the **points** scored, the
**scoring team**, the **new score** and **the first line of the play text**, deliberately plainer
than the touchdown: no strobe, no letters dropping in.

    SAFETY            the headline in the team's colour (``2 POINTS``, or ``SAFETY`` /
    NY GIANTS         ``2-POINT CONVERSION`` when the text says so)
    NYG 22  WSH 17    the team's short name; the new score, the scoring team first
    sacked in end zone for a SAFETY      the first sentence of the play text

The favourite's (``Scope.FULL``) opens with a short white flash (6s); a followed team's
(``Scope.QUICK``, 4s) is the static card. No detail screen follows. A single 64px panel uses
smaller type and drops the team-name line. The horn is not part of this story.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.director import EVENT
from ..football.events import GenericScore, Scope
from ..football.teams import is_team, team_color
from ..football.teams import team as nfl_team
from .fonts import text_width
from .football_plays import DIM, WHITE, event_screen, r_fit
from .goal_light import _Buffer, _ease, _scaled

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

FLASH_SECONDS = 0.12
FADE_SECONDS = 0.4


def title(scene: Scene) -> str:
    """``SAFETY`` or ``2-POINT CONVERSION`` when the text says so, else ``N POINTS``."""
    event, text = scene.fb_event, scene.fb_play.text.lower()
    if "safety" in text:
        return "SAFETY"
    if "two-point" in text or "2-point" in text:
        return "2-POINT CONVERSION"
    unit = "POINT" if event.points == 1 else "POINTS"
    return f"{event.points} {unit}"


def team_name(abbrev: str) -> str:
    return nfl_team(abbrev).name if is_team(abbrev) else abbrev


def score_line(scene: Scene) -> str:
    """``NYG 22  WSH 17``: the new score, the scoring team first."""
    event, game = scene.fb_event, scene.fb_game
    away, home = (game.away.abbrev, event.away_score), (game.home.abbrev, event.home_score)
    mine, theirs = (home, away) if event.team == game.home.abbrev else (away, home)
    return f"{mine[0]} {mine[1]}  {theirs[0]} {theirs[1]}"


def first_line(scene: Scene) -> str:
    """The first sentence of the play text, with the formation tag taken off the front."""
    text = scene.fb_play.text.strip()
    while text.startswith("("):
        end = text.find(")")
        if end < 0:
            break
        text = text[end + 1 :].strip()
    for stop in (". ", "\n"):
        if stop in text:
            text = text.split(stop)[0]
    return text.rstrip(".").upper()


def _fit_font(r: Renderer, text: str, width: int, fonts: tuple[Any, ...]) -> Any:
    return next((f for f in fonts if text_width(f, text) <= width), fonts[-1])


@event_screen(GenericScore, EVENT)
def draw_score(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    canvas.Clear()
    age = max(0.0, scene.fb_elapsed)
    color = team_color(event.team) if is_team(event.team) else WHITE
    wide = r.width >= 128
    if event.scope == Scope.FULL and age < FLASH_SECONDS:
        buf = _Buffer(r.width, r.height)
        buf.wash(WHITE, 0.35 * (1 - age / FLASH_SECONDS))
        buf.flush(canvas)
    fade = 1.0 if event.scope != Scope.FULL else _ease(age / FADE_SECONDS)
    shade = _scaled(color, 0.35 + 0.65 * fade)
    cx, width = r.width // 2, r.width - 4

    text = title(scene)
    big = _fit_font(r, text, width, (r.fonts.large, r.fonts.medium, r.fonts.small, r.fonts.tiny))
    if wide:
        r.text_center(canvas, big, cx, 11, shade, r_fit(text, width, big))
        r.text_center(
            canvas, r.fonts.small, cx, 19, shade, r_fit(team_name(event.team), width, r.fonts.small)
        )
        r.text_center(
            canvas, r.fonts.tiny, cx, 25, WHITE, r_fit(score_line(scene), width, r.fonts.tiny)
        )
        r.text_center(
            canvas, r.fonts.tiny, cx, 31, DIM, r_fit(first_line(scene), width, r.fonts.tiny)
        )
        return
    small = _fit_font(r, text, width, (r.fonts.small, r.fonts.tiny))
    r.text_center(canvas, small, cx, 8, shade, r_fit(text, width, small))
    r.text_center(
        canvas, r.fonts.tiny, cx, 17, WHITE, r_fit(score_line(scene), width, r.fonts.tiny)
    )
    r.text_center(canvas, r.fonts.tiny, cx, 26, DIM, r_fit(first_line(scene), width, r.fonts.tiny))
