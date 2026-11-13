# ESPN football API: findings for the scoreboard app

Checked 2026-11-12 against a live NFL game (WSH @ NYG, event 401873052) and a
completed one (CIN vs ATL, event 401873038). Related: issue #341 (Football
mode screen-flow design) and **`football_screen.md`**, the screen design and
todo list that this file backs. Read and update the two together.

The API is free, keyless and **undocumented**, so it can change without
notice. Parse defensively and tolerate missing fields.

## Endpoints

| Purpose | URL |
|---|---|
| Scoreboard | `site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard` (also `?dates=YYYYMMDD`, `?week=N&seasontype=2`) |
| Game detail and drives | `.../nfl/summary?event=<id>` |
| Teams, colours, logos | `.../nfl/teams` (32 teams) |
| Roster | `.../nfl/teams/{id}/roster` |
| Play-by-play with participants | `sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/<id>/competitions/<id>/plays?limit=300` |
| Live situation | core URL above ending in `/situation` |

- The scoreboard sends `cache-control: max-age=7`; polling every 10-15 s
  during a game is enough.
- `/standings` on the site API returns 404.
- College football: `.../college-football/scoreboard` has the same shape
  (`curatedRank` is populated), so one parser covers both leagues.

## Scoreboard fields

- **Game state:** `status.type.state` is `pre` / `in` / `post`; also `period`,
  `displayClock`, `shortDetail` (e.g. `7:45 - 1st`).
- **Teams:** each competitor has `homeAway`, `score`, `linescores`, `records`
  (overall, home, road), `team.color`, `alternateColor`, `abbreviation`, `logo`.
- **Context:** `venue`, `weather` (temperature, conditions), `broadcasts`,
  `odds` (spread, over/under), `leaders` (passing, rushing, receiving, with
  headshots and jersey numbers).
- **Live `situation` block:** `down`, `distance`, `yardLine`,
  `shortDownDistanceText` (`4th & 8`), `possessionText` (`WSH 20`),
  `possession` (team id), `isRedZone`, `homeTimeouts`, `awayTimeouts`,
  `lastPlay` (includes win probability).

## Field coordinates

`yardLine` runs 0-100 from the **home** team's goal line, not the offense's.
Washington (away) at "WSH 20" is `yardLine: 80`; "NYG 25" is 25. The away team
drives toward 0, so the field view must flip direction by `homeAway`. Each
play's `start`/`end` also carry `yardsToEndzone`, relative to the offense
(confirmed on a NYG rush: `yardLine` 28 -> 37 while `yardsToEndzone` fell
72 -> 63; for an away-team drive `yardLine` falls as `yardsToEndzone` falls). The
first-down marker is `yardLine +/- distance`, sign set by drive direction.

## Play data

`summary` -> `drives.current.plays[]` and `drives.previous[].plays[]`. Each
play has: `type.text`, `text`, `statYardage`, `scoringPlay`, `isTurnover`,
`isPenalty`, `period`, `clock`, `wallclock`, scores after the play, `start` and
`end` (`yardLine`, `down`, `distance`, `yardsToEndzone`, `team.id`), and
`yardsAfterCatch` on completions.

Play types seen:

- Rush / pass: `Rush`, `Pass Reception`, `Pass Incompletion`, `Sack`
- Scoring: `Passing Touchdown`, `Rushing Touchdown`, `Field Goal Good`,
  `Field Goal Missed`
- Turnovers: `Pass Interception Return`
- Special teams: `Kickoff`, `Punt`
- Stoppages: `Penalty`, `Timeout`, `Official Timeout`, `Two-minute warning`,
  `End Period`, `End of Half`, `End of Game`

Also `Coin Toss` (the first play, `text` is just `GAME`, no yardage).

More types turned up in a 13-game survey (see "Play text" and "The play feed" below):
`End of Regulation`, `Interception Return Touchdown`, `Muffed Punt Recovery (Opponent)`,
`Fumble Recovery (Own)`, `Fumble Recovery (Opponent)` and `Sack Opp Fumble Recovery`.
Still unseen: safety, blocked kick, free kick, turnover on downs. Unknown types fall back
to the plain play-text screen.

**Abbreviations differ between fields.** Washington is `WSH` in `team.abbreviation`
and `possessionText` ("WSH 20"), but `WAS` in some play text ("kicks 64 yards
from WAS 35"). Match teams by `team.id`, never by parsing abbreviations out of
text.

**Scoring plays:** a completed game's `summary` has a top-level `scoringPlays[]`
(type, text, scores after the play, team). It was absent from the live game's
summary while the score was 0-0, so treat it as optional.

Drive objects add `result` (`TD`, `FG`, `PUNT`, `INT`, `MISSED FG`,
`END OF HALF`, `END OF GAME`), `yards`, `offensivePlays`, elapsed time.

## Jersey numbers (closes the gap listed in #341)

- Site `summary` has no `participants`.
- The core `plays` endpoint does: each play lists `participants` with `type`
  (`passer`, `receiver`, ...) and an athlete `$ref`. The athlete record has
  `jersey` (e.g. Michael Penix Jr. = `9`).
- Cheaper: cache each team's roster as athlete id -> jersey and position
  (roster entries have a jersey for 74 of 79 players; the rest are likely
  inactive or practice squad), and take athlete ids from core `participants`.
- Participant `type` values seen across the live game's 37 plays: `passer`,
  `receiver`, `rusher`, `tackler`, `assistedBy`, `kicker`, `punter`, `returner`,
  `holder`, `snapper`, `penalized`, `other`. A rush has a `rusher`.
- The jersey count (74 of 79) is from one team's roster (ATL), not all 32.
- Plays also carry `teamParticipants` (`offense` / `defense` team ids).

## Caveats

- **Lag:** the latest play appeared within about a minute of its `wallclock`
  (re-checked: last play `01:43:28Z`, seen at `01:44:26Z`). `modified` is only
  minute-resolution; use `wallclock`.
  TV delay is separate, so `broadcast_delay_seconds` still applies.
- **`$ref` hosts:** core `$ref` URLs sometimes use the host `espn.pvt`; rewrite
  to `espn.com` before fetching.
- **Offseason:** no live data outside game windows, so tests need recorded
  fixtures.

## Coin toss

Checked 2026-11-12 on two games (CIN vs ATL final, WSH @ NYG live).

- A `Coin Toss` play (type id `70`) is the first play in the **core** `plays`
  list: `sequenceNumber` 100, period 1, clock `15:00`, text `GAME`. The site
  `summary` omits it; its `drives` start at the opening `Kickoff`.
- It names **no winner, call or choice**. No `participants`, no text.
- It does carry the result: `team` and `end.team` are the team that **receives**,
  `start.team` the team that **kicks**. The opening `Kickoff` play has the same
  `start.team` / `end.team`, so the receiver can be read from site data alone.
- `teamParticipants` labels the receiver `defense` and the kicker `offense` (the
  kickoff's own offence/defence), which reads backwards; use `start`/`end`.
- A game days away returns 0 plays, so there is no toss data before kickoff.
  In a live game the play's `modified` time was within a minute of the kickoff's
  `wallclock`: the feed seems to publish it at kickoff, not at the real toss.
- Unverified: whether overtime gets a second `Coin Toss` play (the check errored).

## Play text: what each play type carries (checked 2026-11-12, 4 finished games)

Counts are from about 690 plays across the 4 games.

- **Kickoff** (44): `E.McPherson kicks 59 yards from CIN 35 to ATL 6. K.Herbert to
  ATL 30 for 24 yards (J.Kiser; T.Davis).` Kick distance, landing spot, returner,
  return yards, tacklers. Touchback appears in the text (8 in the sample). A penalty
  can ride on the same play, so `start`/`end` and the printed return can disagree.
- **Punt** (25): `J.Bailey punts 53 yards to CIN 12, Center-L.McCullough, fair catch by
  D.Meyers.` Endings seen: `fair catch`, `out of bounds`, a return
  (`O.Zaccheaus to ATL 24 for -3 yards`) and touchback.
- **Pass Incompletion** (80): `(Shotgun) M.Penix pass incomplete short left to K.Pitts.`
  Direction and depth are always there; a target is sometimes named; `[C.Thomas]`
  marks a defender who broke it up. `statYardage` is 0 and the ball does not move.
- **Sack** (17): `(Shotgun) J.Burrow sacked at CIN 31 for -6 yards (L.London).` A
  0-yard sack exists. Sack plus fumble is its own type, `Sack Opp Fumble Recovery`.
- **Penalty** (48): type `Penalty` is used **even when a play was run**. Text is the
  underlying play, then `PENALTY on ATL-M.Bergeron, Offensive Holding, 10 yards,
  enforced at ...`, with `- No Play` when it nullifies the down. `declined` appears
  in 6 plays.
- **Field Goal Good / Missed**: `N.Folk 38 yard field goal is No Good, Wide Left,
  Center-..., Holder-...`. Distance and miss direction (`Wide Left` / `Wide Right`)
  are in the text; `statYardage` is the kick distance.
- **Timeout** (34): `Timeout #1 by CIN at 01:10.` Team, number and clock.
  **Official Timeout** (58): `Official Timeout at 11:12.`
- **Stoppages:** `Two-Minute Warning`, `END QUARTER 1`, `END QUARTER 2` (type
  `End of Half`), `END GAME`.
- **Answered by the 13-game survey (below):** a QB kneel is a `Rush`, a spike and an
  intentional grounding are a `Pass Incompletion`, an onside kick is a `Kickoff`.
- Plays were about 35-60s apart by `wallclock` in the live game, and the feed returns
  several at once when polled less often than that.

## Scoreboard client findings (#350, checked 2026-11-13)

Parsed by `football/api.py` and `football/models.py`; fixtures are trimmed real
payloads in `tests/fixtures/football/`.

- **Cache and polling floor:** the scoreboard answers `cache-control: max-age=9`
  (earlier seen as 7). Asking faster returns the same bytes, so
  `api.MIN_POLL_SECONDS = 10` is the lowest interval any caller should use. The
  intervals the app actually polls at are the worker story's decision.
- **No games is `{"events": []}`** (a date with no slate returned exactly that, with no
  `week`), so the client returns `[]` for it and `None` only for a failure.
- **Scores are strings** (`"7"`), as are team ids (`"19"`) and `situation.possession`
  (the id of the team with the ball). Parsed leniently; a junk value becomes 0 or `None`.
- **`situation` exists only while a game is live**; pre and final games do not carry it.
  `lastPlay` inside it is a summary with `start`/`end` `yardLine`, `statYardage`,
  `scoreValue` and the scoring `team`, but not participants or jersey numbers.
- **`winner`** is absent while a game is live, `True`/`False` once final.
- **`neutralSite: true`** on the international game (NE vs DET, shown as `VS`, not `@`).
- **`status.type.state`** is `pre` / `in` / `post`; `name` was `STATUS_SCHEDULED`,
  `STATUS_IN_PROGRESS`, `STATUS_FINAL`. **Not yet seen:** halftime, delayed, postponed,
  overtime (`Final/OT`) and suspended names. The client keeps any unknown state or name
  as sent and ranks it after the known ones.
- **Team ids** map to the 32 NFL teams (`football/teams.py`); an id that is not one of
  them (a Pro Bowl side) keeps ESPN's own abbreviation and is flagged `is_nfl = False`.

## The play feed (#353, 13 finished games from 2026-11-08, 2,441 plays)

Parsed by `football/models.py` (`Play`, `PlayKind`) and `football/playtext.py`; one real play
per case is in `tests/fixtures/football/play_cases.json`.

**Type counts:** Rush 664, Pass Reception 489, Pass Incompletion 285, Official Timeout 188,
Penalty 153, Kickoff 139, Timeout 101, Punt 99, Sack 69, Field Goal Good 54, Passing
Touchdown 39, Two-minute warning 27, End Period 26, Rushing Touchdown 21, Pass Interception
Return 20, End of Half 13, End of Game 13, Fumble Recovery (Opponent) 13, Fumble Recovery
(Own) 13, Field Goal Missed 7, Sack Opp Fumble Recovery 5, then one each of End of
Regulation, Muffed Punt Recovery (Opponent) and Interception Return Touchdown. None was
unknown to the parser. `sequenceNumber` is a string of digits and orders plays; ids are not
guaranteed to.

**The type is not the whole story.** Things the animation needs that are *not* types:

- A **kneel** is a `Rush` ("J.Burrow kneels to ATL 9 for -1 yards", 19 of them).
- A **spike** is a `Pass Incompletion` ("S.Sanders spiked the ball to stop the clock", 5).
- An **intentional grounding** is a `Pass Incompletion` with the penalty in the text (3).
- An **onside kick** is a `Kickoff` ("kicks onside 19 yards from PHI 35 to NYG 46", 2).
- A **two-point attempt** rides on the touchdown's text: `TWO-POINT CONVERSION ATTEMPT ...
  ATTEMPT FAILS` or `ATTEMPT SUCCEEDS` (7). So does the **extra point** (`extra point is GOOD`).
- A **penalty rides on almost any play type**, not only `Penalty`: the text is the play,
  then `PENALTY on ATL-M.Bergeron, Offensive Holding, 10 yards, enforced at CIN 7 - No Play`.
  153 are typed `Penalty` (154 plays say `No Play`), but penalties turn up inside Pass
  Reception, Rush, Kickoff, Punt and touchdowns. A penalty can be accepted, `declined` (26
  plays) or `offsetting`, and there can be two on one play.

**Penalty text shapes:** `PENALTY on ATL-M.Bergeron, Offensive Holding, 10 yards, enforced
at CIN 7 - No Play`; the same lowercase (`Penalty on NO-E.McCoy, ..., declined.`); a penalty
on a whole team with no player (`PENALTY on ATL, Delay of Game, 5 yards, enforced at ATL 32 -
No Play`); and a kickoff penalty with no yardage (`PENALTY on NYJ-A.Beck, Kickoff Out of
Bounds, placed at KC 40`). The team in the penalty text is the text's own abbreviation, which
is **not always ESPN's**: seen `HST` (HOU), `ARZ` (ARI), `CLV` (CLE).

**Names** are `M.Penix`, but also `Mi.Wilson` (a two-letter initial when two players share
one) and `D.St. Brown`. Midfield is written as a bare `50` (`sacked at 50`, `to 50`).

**Reviews and reversals: the play is rewritten in place** (20 plays mention a challenge or
review, 9 were reversed). The play's `type` and flags show the **final ruling**; the text is
the original call, then `The Replay Official reviewed the pass completion ruling, and the play
was REVERSED.` (or `Indianapolis challenged the runner was down by contact ruling, and the play
was REVERSED.`), then the corrected play. An upheld review reads `... and the play was Upheld.
The ruling on the field stands.` and a team's challenge adds `(Timeout #1.)`. A reversed
touchdown therefore looks like a plain incompletion (`scoringPlay` false, score unchanged)
whose text says it was reversed. This is how finished games look; **what the feed shows during
a review is not known**. See the reversal design in `football_screen.md`.

**Kickoff touchbacks** read `kicks 65 yards from CLV 35 to end zone, Touchback to the NO 35.`
(21 of 139 kickoffs), and punts `... to end zone, Center-T.Ott, Touchback.`; a punt ends in
`fair catch by`, `out of bounds`, `downed by`, a return (`O.Zaccheaus to ATL 24 for -3 yards`)
or a muff (`MUFFS catch, RECOVERED by`). A lateral reads `Lateral to R.Stevenson pushed ob at
NE 38 for 6 yards`.

## Feed lag, one real observation (#355, 2026-11-13)

Watching a live game with `nhl-scoreboard --watch-nfl 401873052` (polling every 10s), a new
play (a Q4 incompletion) was first shown **30.2s after its `wallclock`**: the feed, plus up to
10s of polling, ran about half a minute behind the play. One play in one game, so a hint, not
a measurement: the Pi 4 measurement todo is still what answers the deferred animation-pace
question. The queue logs `lag=` for every play it shows, so a full game's worth can be read
from the journal (`journalctl -u nhl-scoreboard | grep "play shown"`).

## Turnovers and possession (#356, the same 13 games)

- `end.team` is the team that has the ball **after** the play, `start.team` the one that had it
  before. On every turnover the feed flags (`isTurnover`: 20 interceptions, 12 fumbles lost, 5
  sack-fumbles, 1 pick-six) `end.team` differs from `start.team`, so `end.team` is the team that
  gained the ball.
- **A turnover on downs is not flagged.** `isTurnover` is false and the type is an ordinary
  `Rush`, `Pass Incompletion` or `Sack`. But on a scrimmage play possession changed **only on
  fourth down** (rush 4, incompletion 7, sack 3, no counter-examples, out of 31 fourth-down
  scrimmage plays), so "fourth down and `end.team` differs" identifies it.
- A missed field goal also changes `end.team` (the other team takes over), and so do punts and
  kickoffs: those are told apart by their type, not by possession.
- `Fumble Recovery (Own)` can still change `end.team` (a fumble on a punt return that the
  returning team recovers), and is **not** flagged: only `Fumble Recovery (Opponent)` is a turnover.

## Reversals: unverified while in progress (#357)

Finished games show a reversed play **rewritten in place** (see "The play feed"). What nobody
has seen is the feed **during** a review, or how long after the original call the rewrite
arrives. `football/reversals.py` is built on the finished shape and logs every match at INFO
(`reversal detected: play=... kind=... rules=... review=yes|no reason=...`), which is how the
live behaviour gets learned.

**To capture one from a live game** (a review happens in perhaps one game in three):

1. Find the event id on `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard`.
2. Poll it and keep every answer: `while true; do curl -s "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=<id>" > "cap-$(date +%s).json"; sleep 10; done`
3. When the broadcast shows a review, compare the captures on either side of it for the play's
   `id`, `type.text`, `scoringPlay`, `isTurnover`, the score and `text` (for example `jq` on
   `.drives.current.plays[-3:]`). The questions to answer: does the original play stay as it was
   until the ruling and then change, does it vanish for a poll, and how many seconds pass?
4. Keep the captures as fixtures under `tests/fixtures/football/` and add a test; if the rules
   in `reversals.py` do not match what is there, fix them from the evidence.

`nhl-scoreboard --watch-nfl <id>` also runs the play queue against the live feed and logs.

