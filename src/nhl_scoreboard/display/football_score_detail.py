"""``fb_score_detail`` (#391): who scored, after the celebration.

Follows the touchdown or field-goal celebration for ``fb_score_detail_seconds`` (8s), like the
NHL's ``goal_detail``. Between the two teams' logos (the scoring team's at full brightness, the
other dimmed) four short lines::

    14 C. WOERNER              the scorer's jersey number and name (name alone with no number)
    1 YD PASS FROM             the yards and how: PASS FROM / RUN / INT RETURN / FUM RETURN
    M. PENIX                   the passer (a pass only)
    PAT GOOD     ATL 7 CIN 0   the extra point or two-point try, and the new score, scorer first

After a field goal: the kicker (``14 N. FOLK``), ``31 YD FIELD GOAL``, and the new score. The score
is the one on the play itself, which already includes the point after. A single 64px panel has no
logos and drops the passer's line first, then the point-after text. Static: it does not move.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.director import DETAIL
from ..football.events import FieldGoal, Touchdown
from ..football.people import Person, find
from ..football.teams import is_team, team_color
from .fonts import text_width
from .football_plays import AMBER_CARD, WHITE, event_screen, r_fit

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

#: The text column on a 128px panel sits between the two logos.
TEXT_LEFT, TEXT_RIGHT = 20, 108
LOGO_X = 11
LOGO_SIZE = 16
OTHER_TEAM_DIM = 0.5


def _upper(name: str) -> str:
    return name.upper().strip()


def person_line(person: Person | None, fallback: str) -> str:
    """``14 C. WOERNER``: the number then the name; the name alone with no number; the text's own
    spelling (``C.WOERNER``) when the roster does not know them; ``""`` when nobody is named."""
    if person is not None:
        name = _upper(person.name or fallback)
        return f"{person.jersey} {name}".strip() if person.jersey else name
    return _upper(fallback)


def scorer_name(scene: Scene) -> str:
    """The text's name for whoever carried or caught it: the receiver, rusher or returner."""
    event, info = scene.fb_event, scene.fb_play.info
    if isinstance(event, Touchdown):
        if event.via == "pass":
            return info.target
        if event.via == "run":
            return info.rusher
        if event.via == "interception":
            return info.interceptor or info.returner
        return info.returner or info.rusher or info.target
    return info.kicker


def scorer_line(scene: Scene) -> str:
    event = scene.fb_event
    roles = ("kicker",) if isinstance(event, FieldGoal) else ("scorer", "receiver", "rusher")
    return person_line(find(scene.fb_people, *roles), scorer_name(scene))


def how_lines(scene: Scene) -> tuple[str, str]:
    """The yards and how, and (for a pass) the passer: ``("1 YD PASS FROM", "M. PENIX")``."""
    event, play = scene.fb_event, scene.fb_play
    if isinstance(event, FieldGoal):
        yards = event.yards if event.yards is not None else play.info.fg_yards
        return (f"{yards} YD FIELD GOAL" if yards else "FIELD GOAL"), ""
    yards = f"{play.stat_yardage} YD " if play.stat_yardage else ""
    if event.via == "pass":
        passer = person_line(find(scene.fb_people, "passer"), play.info.passer)
        return f"{yards}PASS FROM", passer
    if event.via == "run":
        return f"{yards}RUN".strip(), ""
    if event.via == "interception":
        return f"{yards}INT RETURN".strip(), ""
    return f"{yards}FUM RETURN".strip() if play.info.fumble else f"{yards}RETURN".strip(), ""


def point_after(scene: Scene) -> str:
    """``PAT GOOD``, ``PAT NO GOOD``, ``2 PT GOOD``, ``2 PT NO GOOD`` or ``""``."""
    event = scene.fb_event
    if not isinstance(event, Touchdown):
        return ""
    if event.two_point:
        return {"good": "2 PT GOOD", "failed": "2 PT NO GOOD"}.get(event.two_point, "2 PT TRY")
    return {"good": "PAT GOOD", "no good": "PAT NO GOOD"}.get(event.extra_point, "")


def score_line(scene: Scene) -> str:
    """``ATL 7  CIN 0``: the new score, the scoring team first."""
    event, game = scene.fb_event, scene.fb_game
    away, home = (game.away.abbrev, event.away_score), (game.home.abbrev, event.home_score)
    mine, theirs = (home, away) if event.team == game.home.abbrev else (away, home)
    return f"{mine[0]} {mine[1]} {theirs[0]} {theirs[1]}"


def other_team(scene: Scene) -> str:
    game = scene.fb_game
    return game.away.abbrev if scene.fb_event.team == game.home.abbrev else game.home.abbrev


def _bottom(r: Renderer, canvas: Any, left: int, right: int, pat: str, score: str, passer: bool):
    """The point-after text at the left and the score at the right of the last row. When both do
    not fit: with no passer line the point-after text takes that row's place and the score stays
    below; with a passer it is dropped (the design's rule: the least important goes first)."""
    font = r.fonts.tiny
    gap = 4
    if pat and text_width(font, pat) + gap + text_width(font, score) <= right - left:
        r.text(canvas, font, left, 30, AMBER_CARD, pat)
        r.text_right(canvas, font, right, 30, AMBER_CARD, score)
        return
    if pat and not passer:
        r.text_center(
            canvas, font, (left + right) // 2, 22, AMBER_CARD, r_fit(pat, right - left, font)
        )
    r.text_center(
        canvas, font, (left + right) // 2, 30, AMBER_CARD, r_fit(score, right - left, font)
    )


def _logo(r: Renderer, canvas: Any, team: str, x: int, factor: float) -> None:
    logo = r.nfl_logos.get(team, LOGO_SIZE) if r.nfl_logos is not None and is_team(team) else None
    if logo is not None:
        ox, oy = x - logo.width // 2, 16 - logo.height // 2
        for dx, dy, (red, green, blue) in logo.pixels:
            canvas.SetPixel(
                ox + dx, oy + dy, round(red * factor), round(green * factor), round(blue * factor)
            )
        return
    color = team_color(team) if is_team(team) else WHITE
    shade = tuple(round(c * factor) for c in color)
    r.text_center(canvas, r.fonts.small, x, 19, shade, r_fit(team, 22, r.fonts.small))


@event_screen(Touchdown, DETAIL)
@event_screen(FieldGoal, DETAIL)
def draw_score_detail(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    canvas.Clear()
    wide = r.width >= 128
    color = team_color(event.team) if is_team(event.team) else WHITE
    left, right = (TEXT_LEFT, TEXT_RIGHT) if wide else (1, r.width - 1)
    cx, width = (left + right) // 2, right - left
    if wide:
        _logo(r, canvas, event.team, LOGO_X, 1.0)
        _logo(r, canvas, other_team(scene), r.width - LOGO_X, OTHER_TEAM_DIM)

    how, passer = how_lines(scene)
    pat = point_after(scene)
    score = score_line(scene)
    r.text_center(
        canvas, r.fonts.small, cx, 8, WHITE, r_fit(scorer_line(scene), width, r.fonts.small)
    )
    if wide:
        r.text_center(canvas, r.fonts.tiny, cx, 16, color, r_fit(how, width, r.fonts.tiny))
        if passer:
            r.text_center(canvas, r.fonts.tiny, cx, 22, color, r_fit(passer, width, r.fonts.tiny))
        _bottom(r, canvas, left, right, pat, score, bool(passer))
        return
    # 64px: no passer line (it goes first); the point-after text stays, it still has a row.
    short_how = how.replace(" FROM", "")
    r.text_center(
        canvas, r.fonts.small, cx, 7, WHITE, r_fit(scorer_line(scene), width, r.fonts.small)
    )
    r.text_center(canvas, r.fonts.tiny, cx, 14, color, r_fit(short_how, width, r.fonts.tiny))
    if pat:
        r.text_center(canvas, r.fonts.tiny, cx, 21, AMBER_CARD, r_fit(pat, width, r.fonts.tiny))
    r.text_center(canvas, r.fonts.tiny, cx, 28, AMBER_CARD, r_fit(score, width, r.fonts.tiny))
