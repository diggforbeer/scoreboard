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
play's `start`/`end` also carry `yardsToEndzone`, relative to the offense. The
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

Not yet seen (names unconfirmed): fumble, safety, blocked kick, two-point
attempt. The sample is two games, so fall back to the plain play-text screen for
unknown types.

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
- Only `passer` and `receiver` participant types are confirmed. The type given
  to a rusher was not checked.

## Caveats

- **Lag:** the latest play appeared within about a minute of its `wallclock`.
  TV delay is separate, so `broadcast_delay_seconds` still applies.
- **`$ref` hosts:** core `$ref` URLs sometimes use the host `espn.pvt`; rewrite
  to `espn.com` before fetching.
- **Offseason:** no live data outside game windows, so tests need recorded
  fixtures.
