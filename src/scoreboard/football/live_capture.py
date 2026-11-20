"""Record a live college game from ESPN's feed, to settle what the spike could not (#558).

The spike found no game in progress, so these were unverified: the live ``situation`` block, the
halftime and end-of-quarter status text, overtime, how soon ``summary.scoringPlays`` shows a new
score, the types of the rarer scores, and which poll ``curatedRank`` follows. A capture polls the
way the board does (the same scoreboard request, the same pace) and writes:

* ``observations.jsonl``: one compact line per poll with the fields above, the fetch time and
  size (the performance question in #558), and what changed;
* ``transitions.log``: a plain line each time the game's status changes, for reading;
* ``raw/``: the gzip'd event and summary payloads, kept only when they changed, so the real
  shapes become test fixtures.

Pure logic here; ``scripts/capture-college-live.py`` is the command line.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
TIMEOUT = (5.0, 10.0)


def find_event(scoreboard: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    for event in scoreboard.get("events") or []:
        if str(event.get("id")) == str(event_id):
            return event
    return None


def _sides(comp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for c in comp.get("competitors") or []:
        team = c.get("team") or {}
        out[c.get("homeAway", "?")] = {
            "abbrev": team.get("abbreviation"),
            "id": team.get("id"),
            "score": c.get("score"),
            "curatedRank": (c.get("curatedRank") or {}).get("current"),
            "linescores": [ls.get("value") for ls in c.get("linescores") or []],
        }
    return out


def compact(event: dict[str, Any] | None, summary: dict[str, Any] | None) -> dict[str, Any]:
    """The few fields #558 asks about, from the scoreboard's event and (if fetched) the summary."""
    out: dict[str, Any] = {}
    if event:
        comp = (event.get("competitions") or [{}])[0]
        status = comp.get("status") or event.get("status") or {}
        stype = status.get("type") or {}
        out["state"] = stype.get("state")
        out["status_name"] = stype.get("name")
        out["detail"] = stype.get("detail")
        out["short_detail"] = stype.get("shortDetail")
        out["period"] = status.get("period")
        out["clock"] = status.get("displayClock")
        out["sides"] = _sides(comp)
        sit = comp.get("situation")
        if isinstance(sit, dict):
            out["situation"] = {
                k: sit.get(k)
                for k in (
                    "down",
                    "distance",
                    "yardLine",
                    "shortDownDistanceText",
                    "downDistanceText",
                    "possessionText",
                    "possession",
                    "isRedZone",
                    "homeTimeouts",
                    "awayTimeouts",
                )
            }
            last = sit.get("lastPlay")
            if isinstance(last, dict):
                out["situation"]["lastPlay"] = (last.get("text") or "")[:120]
        else:
            out["situation"] = None
        out["notes"] = [n.get("headline") for n in comp.get("notes") or []]
    if summary:
        plays = summary.get("scoringPlays") or []
        out["scoring_plays"] = len(plays)
        if plays:
            last = plays[-1]
            out["last_scoring_play"] = {
                "type": (last.get("type") or {}).get("text"),
                "text": (last.get("text") or "")[:120],
                "period": (last.get("period") or {}).get("number"),
                "clock": (last.get("clock") or {}).get("displayValue"),
                "away": last.get("awayScore"),
                "home": last.get("homeScore"),
            }
        out["scoring_types"] = sorted({(p.get("type") or {}).get("text") or "?" for p in plays})
        header = ((summary.get("header") or {}).get("competitions") or [{}])[0]
        out["summary_status"] = ((header.get("status") or {}).get("type") or {}).get("name")
        drives = summary.get("drives") or {}
        out["drives_previous"] = len(drives.get("previous") or [])
        out["drive_current"] = bool(drives.get("current"))
    return out


def _digest(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class Capture:
    def __init__(
        self,
        event_id: str,
        out_dir: Path,
        session: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        poll_seconds: float = 10.0,
        summary_seconds: float = 30.0,
        rankings_seconds: float = 600.0,
        grace_seconds: float = 600.0,
        idle_seconds: float = 60.0,
    ) -> None:
        self.event_id = str(event_id)
        self.out = Path(out_dir)
        (self.out / "raw").mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self._clock = clock
        self._mono = monotonic
        self.poll_seconds = poll_seconds
        self.summary_seconds = summary_seconds
        self.rankings_seconds = rankings_seconds
        self.grace_seconds = grace_seconds
        self.idle_seconds = idle_seconds
        self._hashes: dict[str, str] = {}
        self._last_summary = -1e9
        self._last_rankings = -1e9
        self._last_status: str | None = None
        self._final_at: float | None = None
        self.polls = 0
        self.failures = 0

    # -- plumbing -------------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, str] | None = None) -> tuple[Any, float, int]:
        started = self._mono()
        response = self.session.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
        response.raise_for_status()
        body = response.content if hasattr(response, "content") else b""
        return response.json(), self._mono() - started, len(body or b"")

    def _save_raw(self, kind: str, payload: Any) -> bool:
        """Keep ``payload`` (gzip'd) only if it differs from the last one of its kind."""
        digest = _digest(payload)
        if self._hashes.get(kind) == digest:
            return False
        self._hashes[kind] = digest
        stamp = self._clock().strftime("%Y%m%dT%H%M%S")
        path = self.out / "raw" / f"{stamp}-{kind}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return True

    def _append(self, name: str, line: str) -> None:
        with (self.out / name).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    # -- one poll -------------------------------------------------------------------------

    def poll_once(self) -> bool:
        """Poll once and record it. ``False`` when the capture is finished (the game has been
        final for the grace period)."""
        now = self._mono()
        stamp = self._clock().isoformat(timespec="seconds")
        self.polls += 1
        row: dict[str, Any] = {"ts": stamp}
        try:
            board, seconds, size = self._get("/scoreboard", {"groups": "80", "limit": "300"})
        except (requests.RequestException, ValueError) as exc:
            self.failures += 1
            self._append("observations.jsonl", json.dumps({"ts": stamp, "error": str(exc)[:200]}))
            return True
        event = find_event(board, self.event_id)
        row.update(scoreboard_seconds=round(seconds, 3), scoreboard_bytes=size)
        if event is None:
            row["event"] = "not on the scoreboard"
            self._append("observations.jsonl", json.dumps(row))
            return True
        self._save_raw("event", event)
        summary = None
        if now - self._last_summary >= self.summary_seconds:
            try:
                summary, s_seconds, s_size = self._get("/summary", {"event": self.event_id})
                self._last_summary = now
                row.update(summary_seconds=round(s_seconds, 3), summary_bytes=s_size)
                self._save_raw("summary", summary)
            except (requests.RequestException, ValueError) as exc:
                self.failures += 1
                row["summary_error"] = str(exc)[:120]
        if now - self._last_rankings >= self.rankings_seconds:
            try:
                rankings, _, _ = self._get("/rankings")
                self._last_rankings = now
                self._save_raw("rankings", rankings)
            except (requests.RequestException, ValueError):
                self.failures += 1
        row.update(compact(event, summary))
        self._append("observations.jsonl", json.dumps(row))
        status = row.get("status_name")
        if status != self._last_status:
            self._append(
                "transitions.log",
                f"{stamp}  {status}  period {row.get('period')}  {row.get('short_detail')}  "
                f"{(row.get('sides') or {}).get('away', {}).get('score')}-"
                f"{(row.get('sides') or {}).get('home', {}).get('score')}",
            )
            self._last_status = status
        if row.get("state") == "post":
            if self._final_at is None:
                self._final_at = now
            elif now - self._final_at >= self.grace_seconds:
                return False
        return True

    def delay(self) -> float:
        """Seconds to wait before the next poll: the board's pace while live, slower otherwise."""
        return (
            self.poll_seconds
            if self._last_status not in (None, "STATUS_SCHEDULED")
            else (self.idle_seconds)
        )

    def run(
        self, sleep: Callable[[float], None] = time.sleep, max_seconds: float | None = None
    ) -> None:
        started = self._mono()
        while self.poll_once():
            if max_seconds is not None and self._mono() - started >= max_seconds:
                log.info("capture stopped at its time limit")
                return
            sleep(self.delay())
