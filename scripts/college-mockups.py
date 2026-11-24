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
        "down": int(down[0]),
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

# 4. halftime card: never a rank (owner's call, 2026-11-22), even for a ranked team
g4 = game("UGA", "AUB", "in", 21, 10, "Halftime", 2, name="STATUS_HALFTIME", ranks=(1, None))
draw(128, lambda r, c, g: r.draw_fb_halftime(c, g), g4, "04_halftime_no_rank")

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


# ---- the AP Top 25 idle screen (#551) ----
from datetime import UTC, datetime  # noqa: E402

from scoreboard.display.college_idle import draw_cfb_ap  # noqa: E402
from scoreboard.football import scroll as fscroll  # noqa: E402
from scoreboard.football.college_rankings import polls_from_payload  # noqa: E402
from scoreboard.football.college_views import build_ap, build_cfp  # noqa: E402
from scoreboard.football.idle import Cached  # noqa: E402
from scoreboard.football.idle_screens import IdleContext  # noqa: E402

rank_payload = json.loads((FX / "college_rankings_trimmed.json").read_text())
ap_polls = polls_from_payload(rank_payload)


def ap_png(favourite, px, name):
    cfg = TeamView(FootballConfig(), favourite, [], favourite)
    now = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    ctx = IdleContext(0.0, now, [], IdleSnapshot(polls_cached=Cached(ap_polls, 0.0)), cfg)
    with use_directory(FBS):
        view = build_ap(ctx)
        c = AsciiCanvas(128, H)
        draw_cfb_ap(rend(), c, view, px)
    assert not [p for p in c.out_of_bounds if p[1] >= 0 and p[1] < H], name
    png(c, 128, name)
    return view


ap_view = ap_png("UGA", 0, "19_ap_top25_rest_top")
ap_png("WAKE", 36, "20_ap_top25_mid_scroll_lead_team_listed")
ap_png("UGA", fscroll.scroll_range(len(ap_view.rows)), "21_ap_top25_rest_bottom")


# ---- the CFP rankings idle screen (#552): the AP's layout, the conference at the right ----
cfp_ctx = IdleContext(
    0.0,
    datetime(2026, 11, 18, 12, 0, tzinfo=UTC),
    [],
    IdleSnapshot(polls_cached=Cached(ap_polls, 0.0)),
    TeamView(FootballConfig(), "TEX", [], "TEX"),
)
with use_directory(FBS):
    cfp_view = build_cfp(cfp_ctx)
    for px, name in ((0, "22_cfp_rankings_rest_top"), (24, "23_cfp_rankings_mid_scroll_lead_team")):
        c = AsciiCanvas(128, H)
        draw_cfb_ap(rend(), c, cfp_view, px)
        png(c, 128, name)


# the playoff cut (#585): a one-pixel line after the last team in the field, `cfp_field` of them
with use_directory(FBS):
    for field, px, name in (
        (12, 56, "39_cfp_cut_line_after_12_mid_scroll"),
        (4, 0, "40_cfp_cut_line_after_4_at_rest"),
    ):
        view = build_cfp(
            dataclasses.replace(
                cfp_ctx, config=TeamView(FootballConfig(cfp_field=field), "TEX", [], "TEX")
            )
        )
        c = AsciiCanvas(128, H)
        draw_cfb_ap(rend(), c, view, px)
        png(c, 128, name)


# ---- the conference standings idle screen (#553): real standings, captured 2026-11-20 ----
from scoreboard.display.college_idle import draw_cfb_conference  # noqa: E402
from scoreboard.football.college_standings import college_standings_from_payload  # noqa: E402
from scoreboard.football.college_views import build_conference  # noqa: E402

conf_standings = college_standings_from_payload(
    json.loads((FX / "college_conference_standings_trimmed.json").read_text())
)


def conference_png(favourite, px, name):
    cfg = TeamView(FootballConfig(), favourite, [], favourite)
    snap = IdleSnapshot(college_standings_cached=Cached(conf_standings, 0.0))
    ctx = IdleContext(0.0, datetime(2026, 11, 20, 12, 0, tzinfo=UTC), [], snap, cfg)
    with use_directory(FBS):
        view = build_conference(ctx)
        c = AsciiCanvas(128, H)
        draw_cfb_conference(rend(), c, view, px)
    png(c, 128, name)
    return view


conference_png("UTSA", 0, "24_conference_american_rest_top")
conference_png("USF", 40, "25_conference_american_mid_scroll_lead_team_listed")
conference_png("ND", 0, "26_conference_independents_two_teams_no_conference_record")
conference_png("GASO", 0, "27_conference_sun_belt_nested_merged_by_seed")


# ---- the next-game idle screen (#554): real schedule and postseason captures (2026-11-20) ----
from scoreboard.football.api import _parse_events  # noqa: E402
from scoreboard.football.college_views import PollView  # noqa: E402,F401
from scoreboard.football.idle import Scoreboard, schedule_from_payload  # noqa: E402
from scoreboard.football.idle_views import build_college_preview  # noqa: E402

uga_schedule = schedule_from_payload(
    61, json.loads((FX / "college_schedule_UGA_trimmed.json").read_text())
)
postseason = json.loads((FX / "college_postseason_trimmed.json").read_text())


def preview_png(now, favourite, name, scoreboard=None, games=(), week_games=None):
    from scoreboard.football.idle import Cached

    snap = IdleSnapshot(
        scoreboard=scoreboard,
        schedules={FBS.by_abbrev[favourite].espn_id: Cached(uga_schedule, 0.0)},
        polls_cached=Cached(ap_polls, 0.0),
        week_cached=Cached(week_games, 0.0) if week_games is not None else None,
    )
    cfg = TeamView(FootballConfig(), favourite, [], favourite)
    ctx = IdleContext(0.0, now, list(games), snap, cfg)
    with use_directory(FBS):
        view = build_college_preview(ctx)
        assert view is not None, name
        c = AsciiCanvas(128, H)
        rend().draw_fb_preview(c, view, now)
    assert not c.out_of_bounds, name
    png(c, 128, name)
    return view


preview_png(datetime(2026, 11, 20, 12, 0, tzinfo=UTC), "UGA", "28_preview_next_game_ranked")
bye_board = Scoreboard(games=(), season_type=2, season_year=2026, week=8)
# The capture is from week 12, so for week 8's bye every game after Oct 24 is made "not yet played".
as_of_week_8 = json.loads((FX / "college_schedule_UGA_trimmed.json").read_text())
for event in as_of_week_8["events"]:
    if event["date"] > "2026-10-24T":
        status = event["competitions"][0]["status"]["type"]
        status.update(state="pre", completed=False, name="STATUS_SCHEDULED")
        for side in event["competitions"][0]["competitors"]:
            side.pop("score", None)
uga_schedule_real, uga_schedule = uga_schedule, schedule_from_payload(61, as_of_week_8)
preview_png(
    datetime(2026, 10, 24, 12, 0, tzinfo=UTC), "UGA", "29_preview_bye_week", scoreboard=bye_board
)
uga_schedule = uga_schedule_real
bowl = json.loads(json.dumps(postseason["events"][0]))
for side, (tid, abbrev), where in zip(
    bowl["competitions"][0]["competitors"],
    ((61, "UGA"), (251, "TEX")),
    ("away", "home"),
    strict=True,
):
    side["id"] = side["team"]["id"] = str(tid)
    side["team"]["abbreviation"] = abbrev
    side["homeAway"] = where
bowl_games = _parse_events([bowl])
preview_png(
    datetime(2026, 12, 6, 12, 0, tzinfo=UTC),
    "UGA",
    "30_preview_bowl_named",
    scoreboard=Scoreboard(games=(), season_type=3, season_year=2026, week=1),
    week_games=Scoreboard(games=tuple(bowl_games), season_type=3, week=1),
)

# the kickoff countdown (already the NFL's, shared by both leagues) now carries the poll numbers
from scoreboard.display.football_idle import draw_fb_countdown  # noqa: E402

countdown_game = game(
    "TEX",
    "ALA",
    "pre",
    0,
    0,
    "11/22 - 12:00 PM EST",
    0,
    name="STATUS_SCHEDULED",
    ranks=(5, 3),
)
countdown_game = dataclasses.replace(
    countdown_game,
    start_utc=datetime(2026, 11, 22, 17, 0, tzinfo=UTC),
    away=dataclasses.replace(countdown_game.away, record="8-2"),
    home=dataclasses.replace(countdown_game.home, record="9-1"),
)
cd_canvas = AsciiCanvas(128, H)
with use_directory(FBS):
    draw_fb_countdown(rend(), cd_canvas, countdown_game, datetime(2026, 11, 22, 16, 17, tzinfo=UTC))
png(cd_canvas, 128, "31_countdown_ranked")

# the opt-in scores grid (#556): a Saturday slate, ranked games first
from scoreboard.display.college_idle import draw_cfb_scores  # noqa: E402
from scoreboard.football.college_views import ScoresView, scores_order  # noqa: E402

grid_games = [
    game("UTAH", "UCLA", "in", 17, 14, "3:12 - 3rd", 3, ranks=(2, 4), gid=1),
    game("OSU", "MICH", "in", 24, 21, "Halftime", 2, name="STATUS_HALFTIME", ranks=(1, 12), gid=2),
    game(
        "TEX",
        "ALA",
        "pre",
        0,
        0,
        "11/22 - 12:00 PM EST",
        0,
        name="STATUS_SCHEDULED",
        ranks=(8, 7),
        gid=3,
    ),
    game("ND", "MIA", "post", 31, 28, "Final", 4, name="STATUS_FINAL", ranks=(3, 5), gid=4),
    game("UGA", "UTSA", "in", 45, 3, "1:02 - 4th", 4, ranks=(6, None), gid=5),
    game("IU", "UTSA", "post", 30, 27, "Final/OT", 5, name="STATUS_FINAL", ranks=(11, None), gid=6),
]
with use_directory(FBS):
    for page, label in ((0, "32_scores_grid_page1"), (1, "33_scores_grid_page2")):
        view = ScoresView(scores_order(grid_games, False))
        c = AsciiCanvas(128, H)
        draw_cfb_scores(rend(), c, view, page)
        assert not c.out_of_bounds, label
        png(c, 128, label)

# the red zone (#562): ESPN's isRedZone flag, as sent. The field tints the 20 yards the offence
# attacks and the down and distance turns red; the scoreboard turns the same text red.
rz_away = game(
    "CLEM", "DUKE", "in", 10, 7, "9:30 - 4th", 4, sit("CLEM", 9, "1st & Goal", red=True), gid=7
)
rz_home = game(
    "CLEM", "DUKE", "in", 17, 10, "1:51 - 4th", 4, sit("DUKE", 91, "1st & Goal", red=True), gid=8
)
rz_no_flag = game("CLEM", "DUKE", "in", 10, 7, "9:30 - 4th", 4, sit("CLEM", 13, "2nd & 3"), gid=9)
draw(128, lambda r, c, g: r.draw_fb_field(c, g), rz_away, "34_red_zone_field_clemson_driving")
draw(128, lambda r, c, g: r.draw_fb_field(c, g), rz_home, "35_red_zone_field_duke_driving")
draw(128, lambda r, c, g: r.draw_fb_scores(c, g), rz_away, "36_red_zone_scoreboard")
draw(128, lambda r, c, g: r.draw_fb_field(c, g), rz_no_flag, "37_inside_20_flag_off_stays_plain")
draw(64, lambda r, c, g: r.draw_fb_field(c, g), rz_away, "38_red_zone_field_single_panel_64px")

# every college timeout shows the team stats (owner's call, 2026-11-22): the real Georgia at South
# Carolina numbers, both pages, in college's own rows (no yards per play or sacks in that feed).
from test_football_college_timeout_stats import STATS as TIMEOUT_STATS  # noqa: E402
from test_football_college_timeout_stats import draw as stats_draw  # noqa: E402

for _name, _elapsed in (("41_timeout_stats_page1", 1.0), ("42_timeout_stats_page2", 13.0)):
    png(stats_draw(_elapsed, stats=TIMEOUT_STATS), 128, _name)
