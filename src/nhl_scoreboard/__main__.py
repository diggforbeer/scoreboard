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
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = Settings.load(args.config)

    if args.dump:
        return _dump(settings)

    # Imported lazily so --dump works on a machine with no matrix backend.
    from .app import ScoreboardApp
    from .display.matrix import load_backend

    app = ScoreboardApp(settings, backend=load_backend(args.backend))
    app.install_signal_handlers()
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


if __name__ == "__main__":
    raise SystemExit(main())
