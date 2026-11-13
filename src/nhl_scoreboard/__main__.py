"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings, resolve_timezone
from .nhl.api import NHLApiError, NHLClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nhl-scoreboard", description=__doc__)
    parser.add_argument("-c", "--config", help="Path to scoreboard.toml")
    parser.add_argument(
        "--backend",
        choices=["rgbmatrix", "RGBMatrixEmulator"],
        help="Force a matrix backend instead of auto-detecting",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Print today's scores to stdout and exit (no matrix needed)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Cycle every scene with synthetic data instead of live NHL data "
            "(needs the real matrix backend)"
        ),
    )
    parser.add_argument(
        "--dump-plays",
        metavar="EVENT_ID",
        help="Print every play of an NFL game (ESPN event id) in order and exit",
    )
    parser.add_argument(
        "--watch-nfl",
        metavar="EVENT_ID",
        help="Print the plays of an NFL game as the animation queue would show them",
    )
    parser.add_argument(
        "--fixture",
        metavar="FILE",
        help="With --watch-nfl: replay a saved summary file instead of polling ESPN",
    )
    parser.add_argument(
        "--chunk",
        type=int,
        default=3,
        help="With --fixture: how many more plays each simulated poll reveals (default 3)",
    )
    parser.add_argument(
        "--sport",
        choices=["nhl", "nfl"],
        help="Which sport --dump prints (default: the configured [scoreboard] sport)",
    )
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = Settings.load(args.config)

    if args.watch_nfl:
        return _watch_nfl(args.watch_nfl, args.fixture, args.chunk, settings)
    if args.dump_plays:
        return _dump_plays(args.dump_plays)
    if args.dump:
        if (args.sport or settings.scoreboard.sport) == "nfl":
            return _dump_nfl(settings)
        return _dump(settings)

    # Imported lazily so --dump works on a machine with no matrix backend.
    from .app import ScoreboardApp
    from .display.matrix import load_backend
    from .hostname import AliasPublisher

    app = ScoreboardApp(settings, backend=load_backend(args.backend))
    if not args.demo:
        app.alias_publisher = AliasPublisher()
    app.install_signal_handlers()
    if args.demo:
        app.run_demo()
        return 0
    app.run()
    return 0


def _dump(settings: Settings) -> int:
    tz = resolve_timezone(settings.scoreboard.timezone)
    try:
        with NHLClient() as client:
            games = client.scores()
    except NHLApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not games:
        print("No games today.")
        return 0
    for game in games:
        print(
            f"{game.away.abbrev:>3} {game.away.score:>2} @ "
            f"{game.home.abbrev:>3} {game.home.score:>2}  {game.status_label(tz)}"
        )
    return 0


def _dump_nfl(settings: Settings) -> int:
    """Today's NFL games as text, like ``_dump`` does for the NHL (#350)."""
    from .football.api import NflClient

    tz = resolve_timezone(settings.scoreboard.timezone)
    with NflClient() as client:
        games = client.scores()
        if games is None:
            print(f"error: {client.last_error}", file=sys.stderr)
            return 1
    if not games:
        print("No games today.")
        return 0
    for game in games:
        line = (
            f"{game.away.abbrev:>3} {game.away.score:>2} @ "
            f"{game.home.abbrev:>3} {game.home.score:>2}  {game.status_label(tz)}"
        )
        sit = game.situation
        if game.is_live and sit and sit.down_distance_text:
            line += f"  | {sit.down_distance_text}"
        print(line)
    return 0


def _watch_nfl(event_id: str, fixture: str | None, chunk: int, settings: Settings) -> int:
    """Show an NFL game's plays as the animation queue would hand them out (#355)."""
    from .football import watch as w
    from .football.api import NflClient

    delay = settings.scoreboard.broadcast_delay_seconds
    if fixture:
        feed = w.FixtureFeed.from_file(fixture, chunk)
        monotonic, sleep, utc_now = w.simulated()
        w.watch(feed, event_id, delay_seconds=delay, exhausted=lambda: feed.exhausted,
                monotonic=monotonic, sleep=sleep, utc_now=utc_now)  # fmt: skip
        return 0
    with NflClient() as client:
        w.watch(lambda: client.plays(event_id), event_id, delay_seconds=delay)
    return 0


def _dump_plays(event_id: str) -> int:
    """Every play of one NFL game, in order, as text (#353)."""
    from .football.api import NflClient

    with NflClient() as client:
        plays = client.plays(event_id)
        if plays is None:
            print(f"error: {client.last_error}", file=sys.stderr)
            return 1
    if not plays:
        print("No plays yet.")
        return 0
    for play in plays:
        print(
            f"{play.sequence:>7}  Q{play.period} {play.clock:>5}  {play.kind.value:<26} {play.text}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
