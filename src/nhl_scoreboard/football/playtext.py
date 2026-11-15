"""What the animations need out of a play's text (#353).

ESPN's play ``text`` is a human sentence, not data, and it is the only place some
facts live: how far a kick went, where it landed, who returned it, whether it was a
touchback or a fair catch, which side a field goal missed on, what a penalty was
and whether it cancelled the play. This module pulls those out, **defensively**:

* every field is optional and defaults to "not found";
* each pattern is independent, so one that does not match never affects another;
* the whole parse is wrapped so a play can never fail to load because its text was
  odd (``parse_text`` never raises).

Patterns were written against about 2,400 real plays from 13 finished games
(2026-11-08, see ``football_api.md``). Things worth knowing that the data showed:

* A **penalty can ride on almost any play type**, not only ``Penalty``: the text
  is the underlying play followed by ``PENALTY on ATL-M.Bergeron, Offensive
  Holding, 10 yards, enforced at CIN 8 - No Play``. ``underlying_text`` is the
  part before the first penalty, so an animation can show the play and then the
  flag; ``no_play`` says whether the down was wiped out, and a penalty can be
  ``declined`` or ``offsetting``.
* A **reviewed play is rewritten in place**: its ``type`` and flags show the *final*
  ruling, while the text keeps the original call, then ``The Replay Official
  reviewed the pass completion ruling, and the play was REVERSED.``, then the
  corrected play. ``review`` carries both halves.
* A **two-point attempt and the extra point ride on the touchdown play's text**
  (``TWO-POINT CONVERSION ATTEMPT ... ATTEMPT FAILS``, ``extra point is GOOD``).
* A **kneel is a ``Rush``**, a **spike and an intentional grounding are a ``Pass
  Incompletion``** (the grounding's penalty is in the text, not the type).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# A player as ESPN writes them: ``M.Penix``, ``Mi.Wilson`` (two-letter initial when two
# players share one), ``D.St. Brown``, ``K.Walker Jr.``.
NAME = r"[A-Z][a-z]?\.(?:[A-Z][a-z]?\.\s?)?[A-Za-z'\u2019\-]+(?:\s(?:Jr|Sr|II|III|IV)\.?)?"
#: A spot on the field (``ATL 6``, ``NYG 28``, ``LV -8``), midfield (a bare ``50``) or the end zone.
SPOT = r"(?:[A-Z]{2,3}\s-?\d+|end zone|(?<!\d)50(?!\d))"

_KICK = re.compile(
    rf"(?P<kicker>{NAME}) kicks (?P<onside>onside )?(?P<yards>\d+) yards? from "
    rf"(?P<from>{SPOT}) to (?:landing zone to )?(?P<land>{SPOT})"
)
_PUNT = re.compile(rf"(?P<kicker>{NAME}) punts (?P<yards>\d+) yards? to (?P<land>{SPOT})")
_RETURN = re.compile(
    rf"\.\s+(?P<who>{NAME})\s+(?:to|pushed ob at|ran ob at)\s+(?P<spot>{SPOT})\s+"
    rf"for\s+(?P<yards>-?\d+|no)\s+(?:yards?|gain)"
)
_NO_ADVANCE = re.compile(rf"(?P<who>{NAME}) \(didn't try to advance\)")
_FAIR_CATCH = re.compile(rf"fair catch by (?P<who>{NAME})")
_FIELD_GOAL = re.compile(
    rf"(?P<kicker>{NAME}) (?P<yards>\d+) yard field goal is (?P<result>GOOD|No Good)"
    rf"(?:, (?P<dir>[A-Za-z ]+?))?(?:,\s*Center|\.|$)"
)
_EXTRA_POINT = re.compile(r"extra point is (?P<result>GOOD|No Good)", re.I)
_TWO_POINT = re.compile(r"TWO-POINT CONVERSION ATTEMPT", re.I)
_TWO_POINT_RESULT = re.compile(r"ATTEMPT (?P<result>SUCCEEDS|FAILS)", re.I)
_TIMEOUT = re.compile(r"Timeout #(?P<n>\d+) by (?P<team>[A-Z]{2,3}) at (?P<clock>\d+:\d+)")
_OFFICIAL_TIMEOUT = re.compile(r"Official Timeout at (?P<clock>\d+:\d+)")
_SACK = re.compile(
    rf"(?P<qb>{NAME}) sacked at (?P<spot>{SPOT}) for (?P<yards>-?\d+) yards?"
    rf"(?: \((?P<by>[^)]+)\))?"
)
_PASS = re.compile(
    rf"(?P<qb>{NAME}) pass (?P<inc>incomplete )?(?:(?P<depth>short|deep) )?"
    rf"(?P<dir>left|middle|right)?"
)
_TARGET = re.compile(rf"(?:intended for|to) (?P<who>{NAME})")
_RUN = re.compile(
    rf"(?P<who>{NAME}) (?:scrambles )?"
    rf"(?P<gap>left end|left tackle|left guard|up the middle|right guard|right tackle|right end)"
)
_KNEEL = re.compile(rf"(?P<who>{NAME}) kneels")
_INTERCEPT = re.compile(rf"INTERCEPTED by (?P<who>{NAME})(?: \[[^\]]+\])?(?: at (?P<spot>{SPOT}))?")
_RECOVERED = re.compile(
    rf"recovered by (?:(?P<team>[A-Z]{{2,3}})-(?P<who>{NAME}))(?: at (?P<spot>{SPOT}))?", re.I
)
_PENALTY = re.compile(
    rf"penalty on (?P<team>[A-Z]{{2,3}})(?:-(?P<player>[^,]+?))?, (?P<name>[^,]+?), "
    rf"(?:(?P<declined>declined)|(?P<offsetting>offsetting)|(?P<yards>\d+) yards?"
    rf"|placed at (?P<placed>{SPOT}))"
    rf"(?:, enforced at (?P<spot>{SPOT}))?(?P<noplay> - No Play)?",
    re.I,
)
_REPLAY_REVIEW = re.compile(
    r"The Replay Official reviewed the (?P<subject>.+?) ruling, and the play was "
    r"(?P<outcome>REVERSED|Upheld)\.",
    re.I,
)
_CHALLENGE = re.compile(
    r"(?:^|[.\)\]]\s*)(?P<by>[A-Z][A-Za-z' ]{1,30}?) challenged the (?P<subject>.+?) ruling, "
    r"and the play was (?P<outcome>REVERSED|Upheld)\.",
    re.I,
)
_CHALLENGE_TIMEOUT = re.compile(r"\(Timeout #(?P<n>\d+)\.\)")


@dataclass(frozen=True, slots=True)
class Penalty:
    team: str
    #: Empty for a penalty on the team as a whole (``PENALTY on SEA, Illegal Formation``).
    player: str
    name: str  #: ``False Start``, ``Offensive Holding``
    yards: int | None
    declined: bool
    offsetting: bool
    #: Where it was enforced or the ball placed (``CIN 8``), if the text says. The team is
    #: as the text writes it, which is not always ESPN's abbreviation (``HST``, ``ARZ``, ``CLV``).
    spot: str


@dataclass(frozen=True, slots=True)
class Review:
    """A challenge or replay review written into the play."""

    #: ``The Replay Official`` or the challenging team's name.
    by: str
    #: What was ruled on: ``pass completion``, ``fumble``, ``incomplete pass``.
    subject: str
    reversed: bool
    #: The play as first called, and as finally ruled (when it was reversed).
    original_text: str
    corrected_text: str
    #: The number of the timeout a team's challenge cost, if the text says.
    timeout_cost: int | None


@dataclass(frozen=True, slots=True)
class PlayText:
    # -- kicks ---------------------------------------------------------
    kicker: str = ""
    kick_yards: int | None = None
    #: Where a kick started and where it came down (``CIN 35`` / ``ATL 6`` / ``end zone``).
    kick_from: str = ""
    landing: str = ""
    onside: bool = False
    touchback: bool = False
    fair_catch: bool = False
    #: Where a touchback is spotted (``NO 35``) when the text says; ``""`` otherwise.
    touchback_spot: str = ""
    out_of_bounds: bool = False
    downed: bool = False
    returner: str = ""
    #: Return yards: negative for a loss, 0 for "no gain", ``None`` if there was no return.
    return_yards: int | None = None
    return_spot: str = ""
    lateral: bool = False
    # -- field goals and points after ----------------------------------
    fg_yards: int | None = None
    #: ``Wide Left``, ``Wide Right``, ``Short``, ``Blocked`` ... on a miss, else ``""``.
    fg_miss: str = ""
    #: ``good`` / ``no good`` / ``""`` for the extra point riding on a touchdown.
    extra_point: str = ""
    #: ``good`` / ``failed`` / ``attempt`` (no result in the text) / ``""``.
    two_point: str = ""
    touchdown: bool = False
    # -- scrimmage -----------------------------------------------------
    passer: str = ""
    target: str = ""
    #: ``short`` / ``deep`` / ``""`` and ``left`` / ``middle`` / ``right`` / ``""``.
    pass_depth: str = ""
    pass_direction: str = ""
    incomplete: bool = False
    spike: bool = False
    rusher: str = ""
    #: ``left end``, ``up the middle`` ... or ``""``.
    run_gap: str = ""
    scramble: bool = False
    kneel: bool = False
    sack: bool = False
    sack_spot: str = ""
    sack_yards: int | None = None
    sackers: tuple[str, ...] = ()
    # -- turnovers -----------------------------------------------------
    interceptor: str = ""
    intercept_spot: str = ""
    fumble: bool = False
    recovered_by_team: str = ""
    recovered_by: str = ""
    muffed: bool = False
    # -- stoppages -----------------------------------------------------
    timeout_team: str = ""
    timeout_number: int | None = None
    timeout_clock: str = ""
    # -- penalties and review ------------------------------------------
    penalties: tuple[Penalty, ...] = ()
    #: True when a penalty says ``- No Play``: the down did not count.
    no_play: bool = False
    #: The play before its first penalty (what happened, then the flag), else the whole text.
    underlying_text: str = ""
    review: Review | None = None

    @property
    def has_penalty(self) -> bool:
        return bool(self.penalties)

    @property
    def accepted_penalty(self) -> bool:
        """A penalty that was neither declined nor offset: it changes the result."""
        return any(not p.declined and not p.offsetting for p in self.penalties)


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    if value.lower() == "no":
        return 0
    try:
        return int(value)
    except ValueError:
        return None


def _penalties(text: str) -> tuple[Penalty, ...]:
    out: list[Penalty] = []
    for m in _PENALTY.finditer(text):
        out.append(
            Penalty(
                team=m["team"].upper(),
                player=(m["player"] or "").strip(),
                name=m["name"].strip(),
                yards=_int(m["yards"]),
                declined=bool(m["declined"]),
                offsetting=bool(m["offsetting"]),
                spot=m["spot"] or m["placed"] or "",
            )
        )
    return tuple(out)


def _review(text: str) -> Review | None:
    m = _REPLAY_REVIEW.search(text)
    by = "The Replay Official"
    if m is None:
        m = _CHALLENGE.search(text)
        if m is None:
            return None
        by = m["by"].strip()
    reversed_ = m["outcome"].lower() == "reversed"
    rest = text[m.end() :]
    cost = _CHALLENGE_TIMEOUT.search(rest)
    corrected = _CHALLENGE_TIMEOUT.sub("", rest).strip() if reversed_ else ""
    return Review(
        by=by,
        subject=m["subject"].strip(),
        reversed=reversed_,
        original_text=text[: m.start()].strip(),
        corrected_text=corrected,
        timeout_cost=_int(cost["n"]) if cost else None,
    )


def parse_text(type_text: str, text: str) -> PlayText:
    """Everything the animations want from ``text``. Never raises."""
    type_text = type_text if isinstance(type_text, str) else ""
    text = text if isinstance(text, str) else ""
    try:
        return _parse(type_text, text)
    except Exception:  # an odd sentence must never stop a play loading
        log.debug("could not parse play text %r", text, exc_info=True)
        return PlayText(underlying_text=" ".join(text.split()))


def _parse(type_text: str, raw: str) -> PlayText:
    text = " ".join(raw.split())
    review = _review(text)
    # A reversed play's own details are in the corrected sentence, not the original call.
    t = review.corrected_text if review is not None and review.reversed else text
    if not t:
        t = text

    pen_match = re.search(r"penalty on ", t, re.I)
    underlying = t[: pen_match.start()].strip() if pen_match else t
    penalties = _penalties(t)
    no_play = bool(re.search(r"- No Play", t, re.I))

    f: dict[str, Any] = {
        "penalties": penalties,
        "no_play": no_play,
        "underlying_text": underlying,
        "review": review,
        "touchdown": bool(re.search(r"TOUCHDOWN", t)),
        "lateral": "Lateral to" in t,
        "fumble": "FUMBLES" in t or "fumbles" in t,
        "muffed": "MUFFS" in t,
    }

    # kicks ----------------------------------------------------------
    km = _KICK.search(t) or _PUNT.search(t)
    if km is not None:
        f["kicker"] = km["kicker"]
        f["kick_yards"] = _int(km["yards"])
        f["landing"] = km["land"]
        if "from" in km.re.groupindex:
            f["kick_from"] = km["from"]
            f["onside"] = bool(km["onside"])
        tail = t[km.end() :]
        sentence = tail.split(" PENALTY", 1)[0]
        f["touchback"] = "Touchback" in tail or "touchback" in sentence
        tbs = re.search(rf"Touchback to the (?P<spot>{SPOT})", tail)
        f["touchback_spot"] = tbs["spot"] if tbs else ""
        f["out_of_bounds"] = "out of bounds" in sentence and not _RETURN.search(tail)
        f["downed"] = "downed by" in tail
        fc = _FAIR_CATCH.search(tail)
        if fc:
            f["fair_catch"] = True
            f["returner"] = fc["who"]
        ret = _RETURN.search(tail)
        if ret:
            f["returner"] = ret["who"]
            f["return_yards"] = _int(ret["yards"])
            f["return_spot"] = ret["spot"]
        else:
            na = _NO_ADVANCE.search(tail)
            if na:
                f["returner"] = na["who"]
                f["return_yards"] = 0

    # field goals and the points after a touchdown --------------------
    fg = _FIELD_GOAL.search(t)
    if fg:
        f["kicker"] = fg["kicker"]
        f["fg_yards"] = _int(fg["yards"])
        if fg["result"].lower() == "no good":
            f["fg_miss"] = (fg["dir"] or "").strip()
    xp = _EXTRA_POINT.search(t)
    if xp:
        f["extra_point"] = xp["result"].lower()
    if _TWO_POINT.search(t):
        r = _TWO_POINT_RESULT.search(t)
        f["two_point"] = (
            "attempt" if r is None else ("good" if r["result"].lower() == "succeeds" else "failed")
        )

    # scrimmage --------------------------------------------------------
    # (before any two-point attempt, whose own pass or run is a different play)
    play_text = _TWO_POINT.split(t, maxsplit=1)[0]
    sk = _SACK.search(play_text)
    if sk:
        f["sack"] = True
        f["passer"] = sk["qb"]
        f["sack_spot"] = sk["spot"]
        f["sack_yards"] = _int(sk["yards"])
        if sk["by"]:
            f["sackers"] = tuple(s.strip() for s in re.split(r"[;,]", sk["by"]) if s.strip())
    elif "spiked the ball" in play_text:
        f["spike"] = True
        f["incomplete"] = True
        sp = re.search(rf"(?P<qb>{NAME}) spiked", play_text)
        if sp:
            f["passer"] = sp["qb"]
    else:
        pm = _PASS.search(play_text)
        if pm and "kicks" not in play_text[: pm.start()]:
            f["passer"] = pm["qb"]
            f["incomplete"] = bool(pm["inc"])
            f["pass_depth"] = pm["depth"] or ""
            f["pass_direction"] = pm["dir"] or ""
            tm = _TARGET.search(play_text, pm.end())
            if tm:
                f["target"] = tm["who"]
    kn = _KNEEL.search(play_text)
    if kn:
        f["kneel"] = True
        f["rusher"] = kn["who"]
    else:
        rn = _RUN.search(play_text)
        if rn:
            f["rusher"] = rn["who"]
            f["run_gap"] = rn["gap"]
        if " scrambles " in play_text:
            f["scramble"] = True
            sm = re.search(rf"(?P<who>{NAME}) scrambles", play_text)
            if sm:
                f["rusher"] = sm["who"]

    # turnovers --------------------------------------------------------
    ic = _INTERCEPT.search(t)
    if ic:
        f["interceptor"] = ic["who"]
        f["intercept_spot"] = ic["spot"] or ""
    rc = _RECOVERED.search(t)
    if rc:
        f["recovered_by_team"] = rc["team"].upper()
        f["recovered_by"] = rc["who"]

    # stoppages --------------------------------------------------------
    to = _TIMEOUT.search(text)
    if to:
        f["timeout_team"] = to["team"]
        f["timeout_number"] = _int(to["n"])
        f["timeout_clock"] = to["clock"]
    ot = _OFFICIAL_TIMEOUT.search(text)
    if ot:
        f["timeout_clock"] = ot["clock"]

    return PlayText(**f)
