#!/usr/bin/env python3
"""Record a live college football game's feed (see ``scoreboard.football.live_capture``).

    python scripts/capture-college-live.py 401858303 --out captures/clemson-duke

Polls the scoreboard at the board's pace, the game's summary every 30 s, and the rankings every
10 minutes; writes ``observations.jsonl``, ``transitions.log`` and gzip'd ``raw/`` payloads (kept
only when they change). Stops ten minutes after the game is final, or at ``--hours``.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from scoreboard.football.live_capture import Capture  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("event", help="ESPN event id (the id in the scoreboard URL)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--poll", type=float, default=10.0, help="seconds between polls while live")
    parser.add_argument("--hours", type=float, default=6.0, help="stop after this long")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    capture = Capture(args.event, args.out, poll_seconds=args.poll)
    print(f"capturing {args.event} into {args.out} (Ctrl-C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        capture.run(max_seconds=args.hours * 3600)
    print(f"{capture.polls} polls, {capture.failures} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
