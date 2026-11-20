#!/usr/bin/env python3
"""College football mockups: real FBS teams and colours through the real renderer, as LED dots.

    python scripts/college-mockups.py [OUT_DIR]      # default docs/college

Draws each college screen the board can show (rank badges, the upset alert, touchdown and field
goal screens, ...) with real FBS teams and their LED-tuned colours, from the trimmed ESPN fixtures
in tests/fixtures/football. Scores and clocks are made up. Add a function here for every new
college screen so a reviewer can see it without a board; the images are committed in docs/college.
"""

import dataclasses
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tests"), str(REPO / "src")]

from PIL import Image, ImageDraw  # noqa: E402

from scoreboard.display.ascii import AsciiCanvas  # noqa: E402
from scoreboard.football import events as ev  # noqa: E402
from scoreboard.football.college_teams import directory_from_table, table_from_payloads  # noqa: E402
from scoreboard.football.director import DETAIL, EVENT  # noqa: E402
from scoreboard.football.models import FbGame  # noqa: E402
from scoreboard.football.teams import use_directory  # noqa: E402
from test_football_events import make_play  # noqa: E402
from test_football_scenes import H, renderer  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "college"
OUT.mkdir(parents=True, exist_ok=True)
FX = REPO / "tests/fixtures/football"
table = table_from_payloads(
    json.loads((FX / "college_standings_trimmed.json").read_text()),
    json.loads((FX / "college_teams_trimmed.json").read_text()),
)
FBS = directory_from_table(table)
CELL = 8


def dot():
    big = Image.new("L", (CELL * 8, CELL * 8), 0)
    pad = CELL * 8 // 10
    ImageDraw.Draw(big).ellipse((pad, pad, CELL * 8 - pad, CELL * 8 - pad), fill=255)
    return big.resize((CELL, CELL), Image.LANCZOS)


D = dot()


def png(canvas, width, name):
    img = Image.new("RGB", (width * CELL, H * CELL), (0, 0, 0))
    lit = canvas.lit(0, 0, width - 1, H - 1)
    for y in range(H):
        for x in range(width):
            img.paste(lit.get((x, y), (14, 14, 14)), (x * CELL, y * CELL), D)
    img.save(OUT / f"{name}.png")
    print("wrote", name)


def raw(away, home, state, a, h, short, period, sit=None, name="STATUS_IN_PROGRESS", gid=1):
    def side(abbrev, ha, score):
        t = FBS.by_abbrev[abbrev]
        return {
            "homeAway": ha,
            "score": str(score),
            "team": {"id": str(t.espn_id), "abbreviation": abbrev},
        }

    comp = {
        "id": str(gid),
        "startDate": "2026-11-21T19:30Z",
        "status": {
            "period": period,
            "displayClock": "3:12",
            "clock": 192.0,
            "type": {
                "state": state,
                "name": name,
                "shortDetail": short,
                "detail": short,
                "completed": state == "post",
            },
        },
        "competitors": [side(home, "home", h), side(away, "away", a)],
    }
    if sit:
        comp["situation"] = sit
    return {"id": str(gid), "date": "2026-11-21T19:30Z", "competitions": [comp]}


def game(*a, ranks=(None, None), **k):
    with use_directory(FBS):
        g = FbGame.from_api(raw(*a, **k))
    return dataclasses.replace(
        g,
        away=dataclasses.replace(g.away, rank=ranks[0]),
        home=dataclasses.replace(g.home, rank=ranks[1]),
    )


def sit(possession_abbrev, yard, down="2nd & 6", red=False):
    return {
        "down": 2,
        "distance": 6,
        "yardLine": yard,
        "downDistanceText": f"{down} at X {yard}",
        "shortDownDistanceText": down,
        "possession": str(FBS.by_abbrev[possession_abbrev].espn_id),
        "isRedZone": red,
    }


def draw(width, fn, g, name):
    c = AsciiCanvas(width, H)
    with use_directory(FBS):
        fn(renderer(width), c, g)
    assert not c.out_of_bounds, name
    png(c, width, name)


def rend(width=128):
    return renderer(width)


# 1. a ranked team at home vs unranked: the common Saturday
g1 = game("AUB", "UGA", "in", 14, 24, "3:12 - 2nd", 2, sit("UGA", 62), ranks=(None, 1))
draw(128, lambda r, c, g: r.draw_fb_scores(c, g), g1, "01_live_scoreboard_ranked_vs_unranked")

# 2. two ranked teams (the marquee game)
g2 = game("TEX", "ALA", "in", 17, 20, "11:42 - 4th", 4, sit("TEX", 38, "1st & 10"), ranks=(5, 3))
draw(128, lambda r, c, g: r.draw_fb_scores(c, g), g2, "02_live_scoreboard_two_ranked")

# 3. the field band with ranks
draw(128, lambda r, c, g: r.draw_fb_field(c, g), g2, "03_field_with_ranks")

# 3b. the same band between plays (no down and distance): room for the badges
g3b = game("TEX", "ALA", "in", 17, 20, "11:42 - 4th", 4, ranks=(5, 3))
draw(128, lambda r, c, g: r.draw_fb_field(c, g), g3b, "03b_field_with_ranks_no_down")

# 4. halftime card
g4 = game("UGA", "AUB", "in", 21, 10, "Halftime", 2, name="STATUS_HALFTIME", ranks=(1, None))
draw(128, lambda r, c, g: r.draw_fb_halftime(c, g), g4, "04_halftime_ranked")

# 5. pregame
g5 = game(
    "MICH", "OSU", "pre", 0, 0, "11/22 - 12:00 PM EST", 0, name="STATUS_SCHEDULED", ranks=(4, 2)
)
draw(128, lambda r, c, g: r.draw_fb_scores(c, g), g5, "05_pregame_ranked")

# 6. a single 64px panel: no badge
draw(64, lambda r, c, g: r.draw_fb_scores(c, g), g2, "06_single_panel_64px_no_badge")


# 7. touchdown celebration for a college team (the same screen the NFL uses, college colours)
def scene_for(g, event, stage, elapsed=2.0, seconds=6.0):
    from scoreboard.app import Scene

    return Scene(
        "fb_event",
        fb_game=g,
        fb_event=event,
        fb_play=event.play,
        fb_stage=stage,
        fb_elapsed=elapsed,
        fb_seconds=seconds,
    )


play = make_play(2, "rush_td_pat", score=(0, 7), off="NYG")
td = ev.Touchdown(
    play=play,
    game_id=1,
    team="UGA",
    scope=ev.Scope.FULL,
    away_score=14,
    home_score=31,
    points=7,
    away_before=14,
    home_before=24,
    via="run",
    extra_point="good",
)
for stage, label, t in (
    (EVENT, "07_touchdown_screen", 1.0),
    (EVENT, "07b_touchdown_screen_later", 4.0),
    (DETAIL, "08_touchdown_detail", 2.0),
):
    c = AsciiCanvas(128, H)
    with use_directory(FBS):
        rend().draw_fb_play_scene(c, scene_for(g1, td, stage, t))
    assert not c.out_of_bounds, label
    png(c, 128, label)

fg = ev.FieldGoal(
    play=make_play(2, "fg_good", score=(3, 0), off="WSH"),
    game_id=1,
    team="UGA",
    scope=ev.Scope.FULL,
    away_score=14,
    home_score=27,
    points=3,
    away_before=14,
    home_before=24,
    made=True,
    yards=47,
)
c = AsciiCanvas(128, H)
with use_directory(FBS):
    rend().draw_fb_play_scene(c, scene_for(g1, fg, EVENT, 1.5))
png(c, 128, "09_field_goal_screen")


# ---- upset alert screens ----
from scoreboard.football.upset import Upset  # noqa: E402


def upset_png(g, final, seconds, name):
    behind, ahead = (g.away, g.home) if g.away.score < g.home.score else (g.home, g.away)
    u = Upset(behind, ahead, final, ahead.score - behind.score)
    c = AsciiCanvas(128, H)
    with use_directory(FBS):
        rend().draw_fb_upset(c, g, u, seconds)
    assert not c.out_of_bounds, name
    png(c, 128, name)


# Georgia (#1) trailing unranked Missouri in the 3rd: the classic
u1 = game("MIZ", "UGA", "in", 21, 14, "3:12 - 3rd", 3, ranks=(None, 1))
upset_png(u1, False, 0.0, "10_upset_alert_bright")
upset_png(u1, False, 0.75, "10b_upset_alert_dim_half_second_later")
# at the half
u2 = game("MIZ", "UGA", "in", 17, 10, "Halftime", 2, name="STATUS_HALFTIME", ranks=(None, 1))
upset_png(u2, False, 0.0, "11_upset_alert_halftime")
# a ranked team losing to a lower-ranked one (#5 Texas trailing #19)
u3 = game("TEX", "OKST", "in", 20, 24, "8:40 - 4th", 4, ranks=(5, 19))
upset_png(u3, False, 0.0, "12_upset_alert_ranked_vs_lower_ranked")
# the final
u4 = game("MIZ", "UGA", "post", 24, 21, "Final", 4, name="STATUS_FINAL", ranks=(None, 1))
upset_png(u4, True, 0.0, "13_upset_final")
u5 = game("TEX", "OKST", "post", 24, 27, "Final/OT", 5, name="STATUS_FINAL", ranks=(5, 19))
upset_png(u5, True, 0.0, "14_upset_final_ranked_vs_ranked_ot")


# ---- the held final (#550) ----
from scoreboard.config import FootballConfig  # noqa: E402
from scoreboard.football.idle import IdleSnapshot  # noqa: E402
from scoreboard.football.idle_views import build_final  # noqa: E402
from scoreboard.priority import TeamView  # noqa: E402


def final_png(g, favourite, name):
    ctx_cfg = TeamView(FootballConfig(), favourite, [], favourite)
    from datetime import UTC, datetime

    from scoreboard.football.idle_screens import IdleContext

    with use_directory(FBS):
        ctx = IdleContext(
            0.0, datetime(2026, 11, 22, 1, 0, tzinfo=UTC), [g], IdleSnapshot(), ctx_cfg
        )
        view = build_final(ctx)
        c = AsciiCanvas(128, H)
        rend().draw_fb_final(c, view, ctx.utc)
    assert not c.out_of_bounds, name
    png(c, 128, name)


f1 = game("MIZ", "UGA", "post", 17, 31, "Final", 4, name="STATUS_FINAL", ranks=(None, 3))
final_png(f1, "UGA", "15_final_win_ranked")
f2 = game("MIZ", "UGA", "post", 28, 24, "Final", 4, name="STATUS_FINAL", ranks=(None, 3))
final_png(f2, "UGA", "16_final_loss_ranked_upset")
f3 = game("TEX", "OKST", "post", 27, 24, "Final/OT", 5, name="STATUS_FINAL", ranks=(5, 19))
final_png(f3, "TEX", "17_final_ot_two_ranked")
f4 = game("AUB", "MIZ", "post", 20, 17, "Final", 4, name="STATUS_FINAL")
final_png(f4, "AUB", "18_final_unranked")
