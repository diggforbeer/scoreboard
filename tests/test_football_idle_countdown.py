"""``fb_countdown`` (#423): the kickoff countdown, a pure function of the clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display import football_idle
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football.idle import IdleSnapshot
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.models import FbGame
from test_football_scenes import H, check_snapshot, raw_game, renderer

KICKOFF = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)


def make_game(records=("5-3-1", "4-5"), broadcast="FOX", state="pre", start="2026-11-22T18:00Z"):
    raw = raw_game("DAL", "NYG", state, start=start, short="x", name="STATUS_SCHEDULED")
    comp = raw["competitions"][0]
    for side in comp["competitors"]:
        rec = records[0] if side["homeAway"] == "home" else records[1]
        if rec:
            side["records"] = [{"type": "total", "summary": rec}]
    if broadcast:
        comp["broadcasts"] = [{"names": [broadcast]}]
    return FbGame.from_api(raw)


class Art:
    """A crest stand-in: a solid 16px square."""

    width = height = 16
    pixels = tuple((x, y, (200, 100, 0)) for x in range(16) for y in range(16))


class Logos:
    def get(self, abbrev, size):
        return Art()


def draw(game, now, *, logos=False, width=128):
    r = renderer(width)
    r.nfl_logos = Logos() if logos else None
    c = AsciiCanvas(width, H)
    r.draw_fb_countdown(c, game, now)
    return c


def test_countdown_text_is_hours_minutes_seconds_and_never_negative():
    assert football_idle.countdown_text(42 * 60 + 15) == "0:42:15"
    assert football_idle.countdown_text(3600) == "1:00:00"
    assert football_idle.countdown_text(0) == "0:00:00"
    assert football_idle.countdown_text(-30) == "0:00:00"
    assert football_idle.countdown_text(59.9) == "0:00:59"


def test_snapshot_with_crests_and_without(update_snapshots):
    now = KICKOFF - timedelta(minutes=42, seconds=15)
    for name, logos in (("fb_countdown", True), ("fb_countdown_no_logos", False)):
        c = draw(make_game(), now, logos=logos)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds


def test_the_kickoff_line_is_local_time_and_broadcast():
    assert football_idle.kickoff_line(make_game(), renderer()) == "SUN 12:00 PM  FOX"
    assert football_idle.kickoff_line(make_game(broadcast=""), renderer()) == "SUN 12:00 PM"
    assert football_idle.kickoff_line(make_game(start=""), renderer()) == ""


def test_records_and_broadcast_are_left_out_when_the_feed_has_none():
    now = KICKOFF - timedelta(minutes=30)
    full = draw(make_game(), now).pixels
    bare = draw(make_game(records=("", ""), broadcast=""), now).pixels
    assert len(bare) < len(full)
    # Nothing in the bottom row but the kickoff time when records and broadcast are absent.
    left_corner = [p for p in bare if p[1] >= 26 and p[0] < 24]
    assert left_corner == []


def test_every_second_of_the_window_fits_the_panel_and_changes_the_picture():
    previous = None
    for seconds in range(3600, -1, -1):
        c = draw(make_game(), KICKOFF - timedelta(seconds=seconds), logos=seconds % 600 == 0)
        assert not c.out_of_bounds, seconds
        assert c.pixels, seconds
        if previous is not None and seconds % 600 != 0 and (seconds + 1) % 600 != 0:
            assert c.pixels != previous.pixels, f"the digits did not move at {seconds}"
        previous = c


def test_the_digits_follow_the_clock_and_hold_at_zero_after_kickoff():
    base = draw(make_game(), KICKOFF - timedelta(seconds=2)).pixels
    assert draw(make_game(), KICKOFF - timedelta(seconds=1)).pixels != base
    zero = draw(make_game(), KICKOFF).pixels
    assert draw(make_game(), KICKOFF + timedelta(minutes=5)).pixels == zero


def test_a_64px_panel_is_never_asked_for_it():
    # The selection skips the idle screens on a narrow panel (see test_football_idle_selection);
    # drawing it anyway must still not raise or write off-panel.
    c = draw(make_game(), KICKOFF - timedelta(minutes=5), width=64)
    assert c.pixels


def test_the_screen_shows_for_a_favourite_pregame_only():
    show = IDLE_SCREENS["fb_countdown"]
    cfg = FootballConfig(favourite_team="NYG")

    def ctx(games):
        return IdleContext(0.0, KICKOFF, games, IdleSnapshot(), cfg)

    assert show(ctx([make_game()]))
    assert not show(ctx([make_game(state="in")]))
    assert not show(ctx([make_game(start="")]))
    assert not show(ctx([]))
    assert not show(IdleContext(0.0, KICKOFF, [make_game()], IdleSnapshot(), FootballConfig()))


from test_football_scenes import _pixels, app  # noqa: E402,F401  (the real-app fixture)


def test_through_the_real_app_the_countdown_replaces_the_pregame_scores_inside_the_window(
    app,  # noqa: F811
):
    feed, clock = app.feed, app.clock_box

    def land(start):
        raw = raw_game("WSH", "NYG", "pre", start=start, short="x", name="STATUS_SCHEDULED")
        feed.answers = [[FbGame.from_api(raw)]]
        app._nfl.worker.poll_once()

    app.select_scene()
    land("2026-11-15T20:30:00Z")  # 90 minutes after the app's clock: outside the window
    assert app.select_scene().kind != "fb_countdown"
    land("2026-11-15T19:42:15Z")  # 42:15 away
    scene = app.select_scene()
    assert scene.kind == "fb_countdown" and scene.fb_game.is_pregame
    first = _pixels(app, scene)
    assert first, "the app draws the countdown"
    app.clock = lambda: datetime(2026, 11, 15, 19, 42, 16, tzinfo=UTC)
    assert _pixels(app, scene) != first, "the countdown follows the app's clock"
    clock.t += 1
    land("2026-11-15T19:00:00Z")  # kickoff reached and not yet live: still the countdown at 0:00:00
    assert app.select_scene().kind == "fb_countdown"
    land("2026-11-15T19:00:00Z")
    feed.answers = [[FbGame.from_api(raw_game("WSH", "NYG", "in", 0, 0, short="1st"))]]
    app._nfl.worker.poll_once()
    assert app.select_scene().kind in ("fb_field", "fb_scores", "fb_play", "fb_playtext")
