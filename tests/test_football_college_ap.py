"""The AP Top 25 idle screen (#551): the view, the drawing, the scroll, and the slot in the mode.

Hermetic: the poll is the trimmed real capture in ``tests/fixtures/football`` (week of Nov 16).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from pathlib import Path

from scoreboard.display import college_idle as ci
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.football_scenes import LIVE, RANK_COLOR, RED_ZONE, WHITE
from scoreboard.football import scroll
from scoreboard.football.college_rankings import polls_from_payload
from scoreboard.football.college_views import build_ap, build_poll
from scoreboard.football.idle import Cached, IdleSnapshot
from scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from scoreboard.football.mode import FootballMode
from scoreboard.football.teams import use_directory
from teamcfg import fcfg
from test_football_college import _fbs_directory
from test_football_college_ranks import NOW, Feed, scoreboard
from test_football_scenes import H, check_snapshot, renderer

FIXTURES = Path(__file__).parent / "fixtures" / "football"
PAYLOAD = json.loads((FIXTURES / "college_rankings_trimmed.json").read_text())
POLLS = polls_from_payload(PAYLOAD)
FBS = _fbs_directory()


def ctx(favourite="UGA", polls=POLLS, now=NOW, **cfg):
    return IdleContext(
        0.0,
        now,
        [],
        IdleSnapshot(polls_cached=Cached(polls, 0.0) if polls is not None else None),
        fcfg(favourite_team=favourite, **cfg),
    )


def draw(view, px=0, width=128):
    c = AsciiCanvas(width, H)
    with use_directory(FBS):
        ci.draw_cfb_ap(renderer(width), c, view, px)
    return c


# -- the scroll rule is hockey's ----------------------------------------------------------------


def test_the_scroll_rule_is_the_renderers_not_a_copy_that_can_drift():
    r = renderer()
    assert r.height == scroll.PANEL_HEIGHT
    assert scroll.ROW_HEIGHT == r._STANDINGS_ROW_HEIGHT
    assert scroll.HOLD_SECONDS == r.SCROLL_HOLD_SECONDS
    assert scroll.MAX_PX_PER_SECOND == r.SCROLL_MAX_PX_PER_SECOND
    for rows in (3, 5, 16, 25):
        assert scroll.scroll_range(rows) == r.standings_scroll_range(rows)
        for minimum in (8.0, 30.0):
            assert scroll.scroll_seconds(rows, minimum) == r.standings_scroll_seconds(rows, minimum)
        for seconds in (6.0, 12.0, 30.0):
            for offset in [i * seconds / 20 for i in range(21)]:
                assert scroll.scroll_px(rows, offset, seconds) == r.standings_scroll_px(
                    rows, offset, seconds
                )


def test_twenty_five_rows_rest_at_both_ends_and_are_never_scrolled_faster_than_the_maximum():
    total = scroll.scroll_seconds(25, 8.0)
    assert total >= 2 * scroll.HOLD_SECONDS + scroll.scroll_range(25) / scroll.MAX_PX_PER_SECOND
    assert scroll.scroll_px(25, 0.0, total) == 0 == scroll.scroll_px(25, scroll.HOLD_SECONDS, total)
    assert scroll.scroll_px(25, total, total) == scroll.scroll_range(25)
    assert scroll.scroll_px(25, total - scroll.HOLD_SECONDS, total) == scroll.scroll_range(25)
    previous, fastest = 0, 0.0
    for step in range(int(total * 10)):
        px = scroll.scroll_px(25, step / 10, total)
        fastest = max(fastest, (px - previous) * 10)
        previous = px
    assert fastest <= scroll.MAX_PX_PER_SECOND + 10, "a rounding step, never a jump"
    assert not scroll.is_moving(25, 1.0, total) and scroll.is_moving(25, total / 2, total)
    assert not scroll.is_moving(25, total - 1.0, total)
    assert scroll.scroll_seconds(3, 8.0) == 8.0, "a short table does not stretch the slot"


# -- the view -----------------------------------------------------------------------------------


def test_the_view_is_the_ap_poll_with_its_movement():
    view = build_ap(ctx())
    assert view.title == "AP TOP 25" and len(view.rows) == 25 and view.scroll_rows == 25
    assert [r.rank for r in view.rows] == list(range(1, 26))
    first, fifth = view.rows[0], view.rows[4]
    assert (first.abbrev, first.record, first.movement) == ("UGA", "9-1", 0)
    assert fifth.abbrev == "MIA"
    moved = {r.abbrev: r.movement for r in view.rows}
    assert any(m is None for m in moved.values()), "a team new to the poll"
    assert any(m and m > 0 for m in moved.values()) and any(m and m < 0 for m in moved.values())
    assert view.team == "UGA"


def test_the_ap_screen_is_the_aps_whichever_poll_means_ranked():
    for poll in ("ap", "usa", "cfp"):
        assert build_ap(ctx(college_poll=poll)).rows[2].abbrev == "ND", poll
    assert build_poll(ctx(), "cfp").rows[2].abbrev == "ALA", "the committee's differs"


def test_the_screen_is_skipped_without_a_fresh_poll():
    assert build_ap(ctx(polls=None)) is None
    assert IDLE_SCREENS["cfb_ap"](ctx(polls=None)) is None
    assert IDLE_SCREENS["cfb_ap"](ctx()) is not None
    assert build_ap(ctx(now=NOW + timedelta(days=60))) is None, "last season's poll"
    only_cfp = dataclasses.replace(POLLS, polls={k: v for k, v in POLLS.polls.items() if k != "ap"})
    assert build_ap(ctx(polls=only_cfp)) is None


# -- the drawing --------------------------------------------------------------------------------


def test_snapshots_at_rest_and_mid_scroll(update_snapshots):
    view = build_ap(ctx("WAKE"))
    bottom = scroll.scroll_range(25)
    for name, px in (("cfb_ap_top", 0), ("cfb_ap_mid", 36), ("cfb_ap_bottom", bottom)):
        c = draw(view, px)
        check_snapshot(name, c.render(), update_snapshots)
        assert all(0 <= x < 128 for x, _ in c.out_of_bounds), "never off the sides"


def test_only_rows_part_way_off_the_panel_are_clipped_and_never_at_the_sides():
    """Like hockey's tables, a row part-way off the panel is still drawn (the driver clips it) so
    the scroll is smooth: what goes off is only ever above or below, and only by those rows."""
    view = build_ap(ctx())
    for px in (0, 17, 60, scroll.scroll_range(25)):
        for x, y in draw(view, px).out_of_bounds:
            assert 0 <= x < 128 and (y < 0 or y >= 32), (px, x, y)
    assert not any(y < 0 for _, y in draw(view, 0).out_of_bounds), "nothing above at the top"
    assert not any(y >= 32 for _, y in draw(view, scroll.scroll_range(25)).out_of_bounds)


def test_movement_has_an_arrow_in_its_colour_and_new_is_amber():
    view = build_ap(ctx())

    def colours(abbrev):
        index = next(i for i, r in enumerate(view.rows) if r.abbrev == abbrev)
        px = max(0, index * 6 - 6)
        c = draw(view, min(px, scroll.scroll_range(25)))
        left = ci.LABEL_WIDTH + 2  # only the movement column: the label has an amber of its own
        return c.colors(left + ci.MOVE_X, 0, left + ci.ABBREV_X - 1, 31)

    up = next(r.abbrev for r in view.rows if r.movement and r.movement > 0)
    down = next(r.abbrev for r in view.rows if r.movement and r.movement < 0)
    new = next(r.abbrev for r in view.rows if r.movement is None)
    assert LIVE in colours(up) and RED_ZONE in colours(down) and ci.AMBER in colours(new)


def test_the_lead_team_is_white_with_a_bar_and_its_rank_in_the_badge_colour():
    c = draw(build_ap(ctx("UGA")), 0)
    assert WHITE in c.colors(0, 0, 127, 5) and RANK_COLOR in c.colors(0, 0, 127, 5)
    assert c.lit(ci.LABEL_WIDTH - 1, 0, ci.LABEL_WIDTH - 1, 5), "the bar"
    other = draw(build_ap(ctx("MIA")), 0)
    assert RANK_COLOR not in other.colors(0, 0, 127, 5), "only the lead team's row"
    nobody = draw(build_ap(ctx("")), 0)
    assert RANK_COLOR not in nobody.colors(0, 0, 127, 31)
    assert not nobody.lit(ci.LABEL_WIDTH - 1, 0, ci.LABEL_WIDTH - 1, 31)


def test_the_label_stays_put_while_the_rows_scroll():
    view = build_ap(ctx())
    a, b = draw(view, 0), draw(view, 60)
    assert a.lit(0, 0, ci.LABEL_WIDTH - 2, 31) == b.lit(0, 0, ci.LABEL_WIDTH - 2, 31)
    assert a.lit(ci.LABEL_WIDTH, 0, 127, 31) != b.lit(ci.LABEL_WIDTH, 0, 127, 31)


# -- in the mode --------------------------------------------------------------------------------


def college_mode(favourite="UGA", rows=(("cfb_ap", 8.0),), now=NOW):
    client = Feed(scoreboard(), None)
    client.session.routes["/rankings"] = __import__("test_football_plays").FakeResponse(PAYLOAD)
    cfg = fcfg(favourite_team=favourite, rotation=[{"screen": s, "seconds": n} for s, n in rows])
    clock = {"mono": 1000.0}
    mode = FootballMode(
        lambda: __import__("scoreboard.config", fromlist=["x"]).ScoreboardConfig(),
        client_factory=lambda: client,
        football=lambda: cfg,
        monotonic=lambda: clock["mono"],
        utc_now=lambda: now,
        league="college-football",
    )
    mode.idle_origin = 1000.0  # the rotation starts at the top of its turn
    mode.worker.poll_once()
    return mode, clock


def test_the_slot_stretches_to_a_readable_scroll_and_the_table_moves_through_it():
    mode, clock = college_mode()
    total = scroll.scroll_seconds(25, 8.0)
    assert total > 8.0
    seen = {}
    for step in range(int(total) + 1):
        clock["mono"] = 1000.0 + step
        scene = mode.scene()
        assert scene.kind == "cfb_ap", step
        seen[step] = (scene.scroll_px, scene.scrolling)
    assert seen[0] == (0, False) and seen[1] == (0, False), "rests at the top"
    assert seen[int(total / 2)][1] is True and 0 < seen[int(total / 2)][0] < 119
    assert seen[int(total)][0] == 119 and seen[int(total)][1] is False
    pixels = [px for px, _ in seen.values()]
    assert pixels == sorted(pixels), "it only goes down"


def test_with_no_fresh_poll_the_row_is_skipped_never_blank():
    mode, _ = college_mode(now=NOW + timedelta(days=60), rows=(("cfb_ap", 8.0),))
    assert mode.scene().kind != "cfb_ap"


def test_the_row_after_it_follows_once_the_slot_is_over():
    mode, clock = college_mode(rows=(("cfb_ap", 8.0), ("clock", 5.0)))
    total = scroll.scroll_seconds(25, 8.0)
    clock["mono"] = 1000.0 + total + 1
    assert mode.scene().kind == "clock"
    clock["mono"] = 1000.0 + total + 5 + 1
    assert mode.scene().kind == "cfb_ap"
