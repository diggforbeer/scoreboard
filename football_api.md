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

Not yet seen (names unconfirmed): fumble, safety, blocked kick, two-point
attempt. The sample is two games, so fall back to the plain play-text screen for
unknown types.

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
- **Not seen as their own types, so unconfirmed:** QB kneel (5 mentions in text,
  type unknown), spike (1), intentional grounding (1), onside kick, safety, blocked
  kick, two-point attempt.
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

