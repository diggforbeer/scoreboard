"""The maths every field screen shares (#358): where a yard is, which way a team drives,
where the first-down line is, which lane a run or pass takes, and the arc of a kick.

Pure functions and one small layout class, no drawing and no Pillow. The screens (the field,
the run, the pass, the kicks) all use these, so they cannot disagree about where the ball is.

**The one thing to know about ESPN's ``yardLine``** (``football_api.md``, "Field coordinates"):
it runs 0-100 **from the home team's goal line**, not from the offence's. So the home end zone is
always on the left and the away end zone on the right, the home team drives **toward** 100 (to
the right) and the away team toward 0 (to the left). "NYG 28" is 28 whether NYG has the ball or
not; "WSH 20" is 80. Which way the first-down line lies, and any left/right flip, follow from
who has the ball, never from the yard line itself.

**100 yards are 100 pixels** on a full 128px panel: with 14px end zones the playing field is
exactly 100px wide, one pixel a yard. On a 64px panel (or a 64px region of a wider one) the end
zones are 7px and the field is about 50px, half a pixel a yard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import FbGame

# -- layout constants. Mirrored in tests/test_football_field.py: change both together. ---------
#: Rows (inclusive) the field occupies. Rows above hold the one-line band of text.
FIELD_TOP = 8
FIELD_BOTTOM = 30
#: End-zone depth in pixels: 14 gives a 100px field on a 128px panel, 7 on anything narrower.
EZ_WIDE = 14
EZ_NARROW = 7
#: A field region this wide or wider gets the wide end zones.
WIDE_MIN_WIDTH = 112
#: Rows kept clear at the top and bottom edge of the field for the lanes.
LANE_MARGIN = 2

HOME = "home"
AWAY = "away"

#: How far across the field (0 = the offence's left, 1 = its right) each run gap and pass
#: direction lies. The offence faces the goal it is attacking, so its left is up the panel when
#: it drives right and down the panel when it drives left (see ``lane_y``).
LANES: dict[str, float] = {
    "left end": 0.10,
    "left tackle": 0.22,
    "left guard": 0.36,
    "up the middle": 0.50,
    "right guard": 0.64,
    "right tackle": 0.78,
    "right end": 0.90,
    # A pass is thrown to a side, not a gap.
    "left": 0.20,
    "middle": 0.50,
    "right": 0.80,
    # The empty string (the text named no direction) goes up the middle.
    "": 0.50,
}


@dataclass(frozen=True, slots=True)
class FieldLayout:
    """Where the field sits on the panel (or in a region of it)."""

    left: int  #: first column of the region
    right: int  #: one past the last column
    top: int = FIELD_TOP
    bottom: int = FIELD_BOTTOM  #: the last row, inclusive

    @classmethod
    def for_panel(cls, width: int, left: int = 0, right: int | None = None) -> FieldLayout:
        """The whole panel, or the region ``left``..``right`` of it (the play-text layout puts
        the field in the left half)."""
        return cls(left=left, right=width if right is None else right)

    # -- the region -----------------------------------------------------

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def end_zone(self) -> int:
        """End-zone depth in pixels: 14 on a wide field (100px for 100 yards), else 7."""
        return EZ_WIDE if self.width >= WIDE_MIN_WIDTH else EZ_NARROW

    @property
    def x0(self) -> int:
        """The column of yard line 0, the home goal line."""
        return self.left + self.end_zone

    @property
    def span(self) -> int:
        """Pixels from goal line to goal line."""
        return self.width - 2 * self.end_zone

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def mid_y(self) -> int:
        return (self.top + self.bottom) // 2

    @property
    def pixels_per_yard(self) -> float:
        return self.span / 100

    # -- yards and pixels ----------------------------------------------------

    def x(self, yard_line: float) -> float:
        """The (fractional) column of ``yard_line``, 0-100 from the home goal line."""
        return self.x0 + self.span * yard_line / 100

    def px(self, yard_line: float) -> int:
        return round(self.x(yard_line))

    def yard_at(self, x: float) -> float:
        """The yard line at column ``x``: the inverse of :meth:`x`."""
        return (x - self.x0) * 100 / self.span

    def end_zone_columns(self, side: str) -> tuple[int, int]:
        """First and last column (inclusive) of ``HOME``'s or ``AWAY``'s end zone."""
        if side == HOME:
            return self.left, self.x0 - 1
        if side == AWAY:
            return self.px(100), self.right - 1
        raise ValueError(f"side must be {HOME!r} or {AWAY!r}, not {side!r}")


# -- which way a team drives --------------------------------------------------------------


def drive_direction(possession: str) -> int:
    """``+1`` if the team with the ball drives toward yard line 100 (the home team does, to the
    right), ``-1`` toward 0 (the away team, to the left)."""
    if possession == HOME:
        return 1
    if possession == AWAY:
        return -1
    raise ValueError(f"possession must be {HOME!r} or {AWAY!r}, not {possession!r}")


def clamp_yard_line(yard_line: float) -> float:
    return max(0.0, min(100.0, yard_line))


def first_down_line(yard_line: float, distance: float, direction: int) -> float:
    """Where the first-down marker is: ``distance`` yards ahead of the ball in the direction of
    play, stopping at the goal line (in goal-to-go the marker is the goal line itself)."""
    return clamp_yard_line(yard_line + direction * distance)


def goal_to_go(yard_line: float, distance: float, direction: int) -> bool:
    """True when the first-down line would be past the goal line."""
    target = yard_line + direction * distance
    return target <= 0 or target >= 100


def possession_side(game: FbGame, team_id: int | None) -> str | None:
    """``HOME``, ``AWAY`` or ``None`` for the team with the ball, from its ESPN id."""
    if team_id is None:
        return None
    if game.home.espn_id == team_id:
        return HOME
    if game.away.espn_id == team_id:
        return AWAY
    return None


# -- lanes and arcs ---------------------------------------------------------------------------


def lane_y(lane: str | float, direction: int, layout: FieldLayout) -> float:
    """The row of a run gap or pass direction (``"left tackle"``, ``"middle"``, or a fraction).

    The offence faces the goal it attacks, so its *left* is the top of the panel when it drives
    right (``direction`` +1) and the bottom when it drives left. A name the table does not know
    goes up the middle rather than raising: the text is from an undocumented feed.
    """
    fraction = lane if isinstance(lane, float | int) else LANES.get(lane, 0.5)
    fraction = max(0.0, min(1.0, float(fraction)))
    if direction < 0:
        fraction = 1.0 - fraction
    low = layout.top + LANE_MARGIN
    high = layout.bottom - LANE_MARGIN
    return low + fraction * (high - low)


def arc_height(yards: float, minimum: float = 3.0, maximum: float = 14.0) -> float:
    """How high a kick or pass of ``yards`` arcs, in pixels: longer goes higher, within limits."""
    return max(minimum, min(maximum, abs(yards) * 0.22))


def arc_point(
    start_x: float, end_x: float, base_y: float, height: float, t: float
) -> tuple[float, float]:
    """The ball at fraction ``t`` (0-1) of a parabolic arc from ``start_x`` to ``end_x``, rising
    ``height`` pixels above ``base_y`` at the middle and back to ``base_y`` at the ends."""
    t = max(0.0, min(1.0, t))
    return start_x + (end_x - start_x) * t, base_y - height * 4 * t * (1 - t)


def arc_points(
    start_x: float, end_x: float, base_y: float, height: float, steps: int | None = None
) -> list[tuple[float, float]]:
    """Points along the arc, about one per pixel of horizontal travel."""
    n = steps if steps is not None else max(8, int(abs(end_x - start_x)))
    return [arc_point(start_x, end_x, base_y, height, i / n) for i in range(n + 1)]
