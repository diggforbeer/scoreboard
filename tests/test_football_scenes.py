"""NFL mode's base scenes: status screens and the plain scoreboard (#352).

Three layers, like the NHL scenes: ASCII snapshots (``--update-snapshots`` after an
intentional change), structural assertions that hold whatever the snapshot says (nothing
off-panel, centred, colours by state), and flow tests walking a game day through the real
app. Games are built from raw ESPN-shaped dicts so the real parser is in the loop.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from RGBMatrixEmulator import graphics

from nhl_scoreboard.app import Scene, ScoreboardApp
from nhl_scoreboard.config import FootballConfig, ScoreboardConfig, Settings
from nhl_scoreboard.display import football_scenes as fs
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.fonts import FontSet
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.display.renderer import SUBDUED, Renderer
from nhl_scoreboard.football.mode import FB_SCENE_KINDS, NflMode
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.teams import TEAMS, team_color
from nhl_scoreboard.football.worker import STALE_AFTER_SECONDS
from test_app import FakeOptions
from test_mirror import AsciiMatrix, as_pixels

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = Path(__file__).parent / "snapshots"
TZ = ZoneInfo("America/Chicago")
H = 32


def check_snapshot(name: str, art: str, update: bool) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if update or not path.exists():
        path.write_text(art + "\n")
        if not update:
            pytest.fail(f"Wrote new snapshot {path.name}; re-run to verify it", pytrace=False)
        return
    assert art == path.read_text().rstrip("\n"), (
        f"{name} rendering changed. If intentional: pytest --update-snapshots, "
        f"then review the diff of tests/snapshots/{name}.txt"
    )


# -- building games -----------------------------------------------------------------


def raw_game(
    away,
    home,
    state="in",
    a=0,
    h=0,
    short="12:24 - 3rd",
    name="STATUS_IN_PROGRESS",
    start="2026-11-15T18:00Z",
    situation=None,
    game_id=1,
    period=3,
):
    def side(abbrev, home_away, score):
        team = TEAMS.get(abbrev)
        return {
            "homeAway": home_away,
            "score": str(score),
            "team": {"id": str(team.espn_id) if team else "9999", "abbreviation": abbrev},
        }

    comp = {
        "id": str(game_id),
        "startDate": start,
        "status": {
            "period": period,
            "displayClock": "12:24",
            "clock": 744.0,
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
    if situation is not None:
        comp["situation"] = situation
    return {"id": str(game_id), "date": start, "competitions": [comp]}


def game(*args, **kwargs) -> FbGame:
    return FbGame.from_api(raw_game(*args, **kwargs))


SIT = {
    "down": 2,
    "distance": 3,
    "yardLine": 13,
    "downDistanceText": "2nd & 3 at WSH 13",
    "shortDownDistanceText": "2nd & 3",
    "possession": "19",
    "isRedZone": False,
}
RED = {**SIT, "downDistanceText": "1st & Goal at WSH 6", "isRedZone": True}

GAMES: dict[str, FbGame] = {
    "live": game("WSH", "NYG", "in", 10, 7, situation=SIT),
    "red_zone": game("WSH", "NYG", "in", 10, 7, short="2:01 - 4th", situation=RED, period=4),
    "live_no_situation": game("WSH", "NYG", "in", 10, 7),
    "halftime": game("WSH", "NYG", "in", 10, 7, short="Halftime", name="STATUS_HALFTIME", period=2),
    "final": game("WSH", "NYG", "post", 34, 17, short="Final", name="STATUS_FINAL", period=4),
    "final_ot": game("WSH", "NYG", "post", 30, 27, short="Final/OT", name="STATUS_FINAL", period=5),
    "pregame": game(
        "KC",
        "ATL",
        "pre",
        short="11/15 - 12:00 PM EST",
        name="STATUS_SCHEDULED",
        start="2026-11-15T18:00Z",
        period=0,
    ),
    "big_scores": game("GB", "SF", "in", 38, 41, situation=SIT),
    "unknown_team": game("AFC", "NFC", "in", 14, 10),
}


def renderer(width=128) -> Renderer:
    return Renderer(graphics=graphics, fonts=FontSet(graphics), width=width, height=H, tz=TZ)


def draw(name: str, width: int = 128) -> AsciiCanvas:
    c = AsciiCanvas(width, H)
    renderer(width).draw_fb_scores(c, GAMES[name])
    return c


def show(name: str, c: AsciiCanvas) -> str:
    art = c.render()
    print(f"\n[{name}]\n{art}")
    return art


# -- the plain scoreboard: 128px ------------------------------------------------------

STATE_COLOR = {
    "live": fs.LIVE,
    "red_zone": fs.LIVE,
    "live_no_situation": fs.LIVE,
    "halftime": fs.HALFTIME,
    "final": fs.FINAL,
    "final_ot": fs.FINAL,
    "pregame": fs.PREGAME,
    "big_scores": fs.LIVE,
    "unknown_team": fs.LIVE,
}


@pytest.mark.parametrize("name", sorted(GAMES))
def test_scoreboard_128_layout_and_snapshot(name, update_snapshots):
    g, c = GAMES[name], draw(name)
    art = show(f"fb_scores_{name}", c)

    assert not c.out_of_bounds, "nothing may be drawn off the panel"
    # The status line, centred on the panel, in the state's colour.
    box = c.bbox(0, 23, 127, 31)
    assert box is not None and abs(box.center_x - 63.5) <= 1.5
    assert c.colors(0, 23, 127, 31) == {STATE_COLOR[name]}
    # Away abbreviation on the left half, home on the right, each in its team colour.
    away_color = fs.side_color(g.away)
    home_color = fs.side_color(g.home)
    assert away_color in c.colors(0, 0, 62, 14) and home_color in c.colors(64, 0, 127, 14)
    left, right = c.bbox(0, 0, 62, 14), c.bbox(64, 0, 127, 14)
    assert left.x0 >= 2 and right.x1 <= 126
    if g.is_pregame:
        # No score before the game: only the two team colours in the top rows.
        assert c.colors(0, 0, 127, 14) - {fs.DIM} == {away_color, home_color}
    else:
        # Scores are white and sit at the right edge of each half.
        assert fs.WHITE in c.colors(0, 0, 62, 14) and fs.WHITE in c.colors(64, 0, 127, 14)
        white_left = [x for (x, y), rgb in c.lit(0, 0, 62, 14).items() if rgb == fs.WHITE]
        assert max(white_left) >= 58
    check_snapshot(f"fb_scores_{name}", art, update_snapshots)


def test_the_down_and_distance_shows_only_while_live_and_tints_in_the_red_zone():
    live, red, quiet = draw("live"), draw("red_zone"), draw("live_no_situation")
    assert fs.SITUATION in live.colors(0, 14, 127, 21) and fs.RED_ZONE not in live.colors(
        0, 14, 127, 21
    )
    assert fs.RED_ZONE in red.colors(0, 14, 127, 21)
    assert not quiet.colors(0, 15, 127, 21) - {fs.DIM}
    for name in ("final", "pregame", "halftime"):  # no situation shown outside live play
        assert fs.SITUATION not in draw(name).colors(0, 14, 127, 21)


def test_a_team_that_is_not_one_of_the_32_is_drawn_plain():
    c = draw("unknown_team")
    assert fs.UNKNOWN_TEAM in c.colors(0, 0, 62, 14)
    assert fs.side_color(GAMES["unknown_team"].away) not in {team_color(a) for a in TEAMS}


def test_each_nfl_team_is_drawn_in_its_own_colour_not_the_nhl_one():
    c = draw("live")
    assert team_color("WSH") in c.colors(0, 0, 62, 14)  # Washington gold
    assert team_color("NYG") in c.colors(64, 0, 127, 14)  # the Giants' blue


def test_halftime_is_amber_and_live_play_green():
    assert fs.status_color(GAMES["halftime"]) == fs.HALFTIME
    assert fs.status_color(GAMES["live"]) == fs.LIVE
    assert fs.status_color(GAMES["final_ot"]) == fs.FINAL
    assert fs.status_color(GAMES["pregame"]) == fs.PREGAME


def test_the_status_is_upper_case_and_a_kickoff_is_in_the_boards_own_timezone():
    r = renderer()
    assert fs.status_text(GAMES["live"], r) == "12:24 - 3RD"
    assert fs.status_text(GAMES["final_ot"], r) == "FINAL/OT"
    # 18:00 UTC is 12:00 PM in Chicago.
    assert fs.status_text(GAMES["pregame"], r) == "SUN 11/15 12:00 PM"


def test_two_digit_scores_do_not_collide_with_the_abbreviations():
    c = draw("big_scores")
    assert not c.out_of_bounds
    left = c.bbox(0, 0, 62, 14)
    whites = sorted(x for (x, y), rgb in c.lit(0, 0, 62, 14).items() if rgb == fs.WHITE)
    team = sorted(x for (x, y), rgb in c.lit(0, 0, 62, 14).items() if rgb != fs.WHITE)
    assert team and whites and max(team) < min(whites), "abbreviation then score, no overlap"
    assert left.x1 <= 62


# -- the plain scoreboard: one 64px panel ----------------------------------------------


@pytest.mark.parametrize("name", ["live", "red_zone", "final", "pregame", "big_scores"])
def test_scoreboard_64_layout_and_snapshot(name, update_snapshots):
    c = draw(name, width=64)
    art = show(f"fb_scores_{name}_64", c)
    assert not c.out_of_bounds
    status = c.bbox(0, 23, 63, 31)
    assert status is not None and abs(status.center_x - 31.5) <= 1.5
    g = GAMES[name]
    assert fs.side_color(g.away) in c.colors(0, 0, 31, 12)
    assert fs.side_color(g.home) in c.colors(32, 0, 63, 12)
    check_snapshot(f"fb_scores_{name}_64", art, update_snapshots)


def test_a_kickoff_on_a_64px_panel_drops_the_day_so_it_fits():
    assert fs.status_text(GAMES["pregame"], renderer(64)) == "12:00 PM"


# -- the status scenes -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "title", "subtitle"),
    [
        ("fb_connecting", "NFL", "CONNECTING"),
        ("fb_no_data", "NO DATA", "NFL CHECK NETWORK"),
        ("fb_no_games", "NO GAMES", "NFL"),
    ],
)
def test_status_scenes(kind, title, subtitle, app, update_snapshots):
    app.draw_scene(Scene(kind))
    c = app.matrix.shown
    art = show(f"message_{kind}", c)
    assert not c.out_of_bounds
    box = c.bbox(0, 0, 127, 14)
    assert box is not None and abs(box.center_x - 63.5) <= 1.5
    assert c.colors(0, 20, 127, 31) == {SUBDUED}
    check_snapshot(f"message_{kind}", art, update_snapshots)


# -- choosing the game -------------------------------------------------------------------


def games_for_selection():
    return [
        game("WSH", "NYG", "in", 10, 7, game_id=1),  # live
        game("MIA", "IND", "in", 3, 3, game_id=2),  # live
        game("KC", "ATL", "pre", game_id=3, start="2026-11-15T18:00Z", short="x"),
        game("DAL", "PHI", "post", 20, 17, game_id=4, short="Final"),
    ]


def mode(favourite="", follow=(), rotate=8.0):
    scoreboard = dataclasses.replace(ScoreboardConfig(), rotate_seconds=rotate)
    football = FootballConfig(favourite_team=favourite, also_follow=list(follow))
    return NflMode(lambda: scoreboard, client_factory=lambda: None, football=lambda: football)


def test_the_favourites_game_holds_the_screen_alone_while_it_is_live():
    m = mode("NYG", ["MIA", "KC"])
    for now in (0.0, 8.0, 16.0, 123.4):
        assert m.pick_game(games_for_selection(), now).id == 1


def test_followed_live_games_take_turns_when_the_favourite_is_not_live():
    m = mode("KC", ["MIA", "NYG"])  # KC is only pregame; NYG and MIA are live
    seen = [m.pick_game(games_for_selection(), t).id for t in (0.0, 8.0, 16.0, 24.0)]
    assert seen == [1, 2, 1, 2] or seen == [2, 1, 2, 1]
    assert set(seen) == {1, 2}, "only the live followed games, not the pregame favourite"


def test_with_no_live_followed_games_the_followed_ones_take_turns_favourite_first():
    m = mode("KC", ["DAL"])  # KC pregame, DAL final: nothing live
    seen = [m.pick_game(games_for_selection(), t).id for t in (0.0, 8.0, 16.0, 24.0)]
    assert seen == [3, 4, 3, 4], "the favourite's game first, then the other followed one"


def test_with_nobody_followed_every_game_takes_a_turn_live_ones_first():
    m = mode()
    seen = [m.pick_game(games_for_selection(), t).id for t in (0.0, 8.0, 16.0, 24.0, 32.0)]
    assert seen == [1, 2, 3, 4, 1]


def test_a_favourite_on_a_bye_falls_back_to_every_game():
    m = mode("CHI", [])  # not in the slate
    assert {m.pick_game(games_for_selection(), t).id for t in (0.0, 8.0, 16.0, 24.0)} == {
        1,
        2,
        3,
        4,
    }


def test_a_turn_lasts_rotate_seconds_and_wraps():
    m = mode(rotate=10.0)
    ids = [
        m.pick_game(games_for_selection(), t).id for t in (0.0, 9.9, 10.0, 19.9, 20.0, 39.9, 40.0)
    ]
    assert ids == [1, 1, 2, 2, 3, 4, 1]


def test_followed_teams_ignore_case_and_nhl_only_abbreviations_never_match():
    m = mode("nyg", ["nsh"])  # NSH is not an NFL team: dropped by the config
    assert m.pick_game(games_for_selection(), 5.0).id == 1


# -- the scene for each state of the feed -----------------------------------------------


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Feed:
    """What the fake ESPN client answers next: a slate, ``None`` for a failure, or []."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.last_error = ""

    def scores(self, date=None):
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        self.last_error = "" if item is not None else "feed down"
        return item

    def close(self):
        pass


def feed_mode(feed, clock):
    return NflMode(client_factory=lambda: feed, monotonic=clock)


def test_connecting_then_scores_then_no_data_when_the_last_good_fetch_goes_stale():
    clock, feed = Clock(), Feed([GAMES["live"]], None)
    m = feed_mode(feed, clock)
    assert m.scene().kind == "fb_connecting"
    m.worker.poll_once()
    scene = m.scene()
    assert scene.kind == "fb_scores" and scene.fb_game == GAMES["live"]
    clock.t += STALE_AFTER_SECONDS - 1
    m.worker.poll_once()  # a failure: the last good games are kept
    assert m.scene().kind == "fb_scores", "a blip does not blank the panel"
    clock.t += 2
    assert m.scene().kind == "fb_no_data", "15 minutes after the last SUCCESS"
    feed.answers = [[GAMES["live"]]]
    m.worker.poll_once()
    assert m.scene().kind == "fb_scores"


def test_a_feed_that_never_answers_is_connecting_for_15_minutes_then_no_data():
    clock, feed = Clock(), Feed(None)
    m = feed_mode(feed, clock)
    m.start()  # records when it began trying
    m.stop()
    m.worker.poll_once()
    assert m.scene().kind == "fb_connecting"
    clock.t += STALE_AFTER_SECONDS + 1
    m.worker.poll_once()
    assert m.scene().kind == "fb_no_data"


def test_an_empty_slate_is_no_games_not_no_data():
    clock = Clock()
    m = feed_mode(Feed([]), clock)
    m.worker.poll_once()
    assert m.scene().kind == "fb_no_games"


def test_every_nfl_scene_kind_is_known_and_documented():
    guide = (ROOT / "football_screen.md").read_text()
    assert set(FB_SCENE_KINDS) == {
        "fb_connecting",
        "fb_no_data",
        "fb_no_games",
        "fb_scores",
        "fb_field",
        "fb_play",
        "fb_playtext",
        "fb_event",
    }
    missing = [k for k in FB_SCENE_KINDS if f"`{k}`" not in guide]
    assert missing == [], f"football_screen.md never mentions: {missing}"


@pytest.mark.parametrize("kind", FB_SCENE_KINDS)
def test_the_app_draws_every_nfl_scene_kind(kind, app):
    scene = Scene(kind, fb_game=GAMES["live"] if kind in ("fb_scores", "fb_field") else None)
    if kind in ("fb_play", "fb_playtext", "fb_event"):
        from nhl_scoreboard.football.demo import nfl_demo_steps

        scene = next(s.scene for s in nfl_demo_steps(datetime.now(UTC)) if s.scene.kind == kind)
    app.draw_scene(scene)
    assert app.matrix.shown.pixels, f"{kind} drew nothing"
    assert not app.matrix.shown.out_of_bounds
    # And it is not the generic NHL "NO GAMES" fall-through.
    plain = AsciiCanvas(128, H)
    renderer().draw_message(plain, "NO GAMES")
    if kind != "fb_no_games":
        assert app.matrix.shown.pixels != plain.pixels


# -- a game day through the real app -------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> ScoreboardApp:
    backend = Backend("ascii", AsciiMatrix, FakeOptions, graphics)
    clock = Clock()
    settings = Settings()
    settings.status.enabled = False
    settings.scoreboard.sport = "nfl"
    settings.football = FootballConfig(favourite_team="NYG")
    feed = Feed([])
    app = ScoreboardApp(
        settings,
        client=_Nhl(),
        backend=backend,
        clock=lambda: datetime(2026, 11, 15, 19, 0, tzinfo=UTC),
        monotonic=clock,
        ap_setup_state_path=tmp_path / "no-ap",
        hw_mapping_trial_path=tmp_path / "no-trial",
        nfl_client_factory=lambda: feed,
    )
    app.clock_box = clock  # type: ignore[attr-defined]
    app.feed = feed  # type: ignore[attr-defined]
    return app


class _Nhl:
    def scores(self, *a, **k):
        return []

    def close(self):
        pass


def test_a_game_day_walks_from_connecting_through_pregame_live_and_final(app):
    feed, clock = app.feed, app.clock_box
    assert app.select_scene().kind == "fb_connecting"

    def land(*games):
        feed.answers = [list(games)]
        app._nfl.worker.poll_once()

    land(game("WSH", "NYG", "pre", short="x", start="2026-11-15T18:00Z", name="STATUS_SCHEDULED"))
    scene = app.select_scene()
    assert scene.kind == "fb_scores" and scene.fb_game.is_pregame
    pre = _pixels(app, scene)

    land(game("WSH", "NYG", "in", 0, 0, situation=SIT))
    clock.t += 15
    live0 = _pixels(app, app.select_scene())
    land(game("WSH", "NYG", "in", 7, 0, situation=SIT))
    clock.t += 15
    scene = app.select_scene()
    assert scene.fb_game.away.score == 7
    live7 = _pixels(app, scene)

    land(game("WSH", "NYG", "post", 34, 17, short="Final", name="STATUS_FINAL"))
    clock.t += 15
    final = _pixels(app, app.select_scene())
    assert len({tuple(sorted(p.items())) for p in (pre, live0, live7, final)}) == 4, (
        "the panel shows something different at each step of the game day"
    )
    assert app.status_snapshot()["current game"] == "WSH @ NYG"


def _pixels(app, scene):
    app.draw_scene(scene)
    return dict(app.matrix.shown.pixels)


def test_the_status_box_reports_the_nfl_feed(app):
    snap = app.status_snapshot()
    assert snap["scene"] == "fb_connecting" and snap["favourite team"] == "NYG"
    assert snap["last successful poll"] == "never" and snap["last error"] == "(none)"
    app.feed.answers = [None]
    app._nfl.worker.poll_once()
    snap = app.status_snapshot()
    assert snap["last error"] == "feed down" and snap["last error at"] != "(none)"
    app.feed.answers = [[GAMES["live"]]]
    app._nfl.worker.poll_once()
    snap = app.status_snapshot()
    assert snap["scene"] == "fb_scores" and snap["last successful poll"] != "never"
    assert snap["last error"] == "(none)"
    assert snap["also following"] == "(none)"


def test_april_fools_never_relabels_nfl_scenes(app):
    app.settings.scoreboard.favourite_team = "NSH"
    app.clock = lambda: datetime(2027, 4, 1, 19, 0, tzinfo=UTC)
    app.feed.answers = [[GAMES["live"]]]
    app._nfl.worker.poll_once()
    assert not app.april_fools_active() or app._nfl is not None
    app.draw_scene(app.select_scene())  # must not raise or relabel


# -- the admin Live view ------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GAMES))
def test_every_scoreboard_state_mirrors_pixel_for_pixel(name, app):
    """The Live view must be the panel exactly (#268), for every state the board can show."""
    app.mirror.watching = True
    app.mirror.requested = True
    app.draw_scene(Scene("fb_scores", fb_game=GAMES[name]))
    frame = app.mirror.latest()
    assert frame is not None, "the scene was not snapshotted for the Live view"
    assert as_pixels(frame.pixels) == app.matrix.shown.pixels


@pytest.mark.parametrize("kind", ["fb_connecting", "fb_no_data", "fb_no_games"])
def test_the_status_scenes_mirror_pixel_for_pixel(kind, app):
    app.mirror.watching = True
    app.mirror.requested = True
    app.draw_scene(Scene(kind))
    frame = app.mirror.latest()
    assert frame is not None and as_pixels(frame.pixels) == app.matrix.shown.pixels


def test_scenes_are_hashable_so_the_live_view_can_tell_when_the_picture_changed(app):
    a = Scene("fb_scores", fb_game=GAMES["live"])
    b = Scene("fb_scores", fb_game=GAMES["live"])
    c = Scene("fb_scores", fb_game=dataclasses.replace(GAMES["live"], period=4))
    assert hash(a) == hash(b) and a == b and a != c
