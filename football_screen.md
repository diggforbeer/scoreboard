# Football (NFL) screens: design and todo

Lives on the `football` branch. Boards only get it if they pick `football`
under Software update on the admin page. Replaces issue #341 as the place this
is tracked: tick boxes here, in the PR that does the work.

Documentation first: nothing below is built yet.

## Data source (checked against a live game, 2026-11-12)

ESPN's unofficial, free, keyless API.

- `site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard`: each live
  game has a `situation` block: `lastPlay`, `down`, `distance`, `yardLine`,
  `possessionText`, `isRedZone`, timeouts.
- `.../summary?event=<id>`: `drives.current.plays[]`, every play with `type`
  (seen: `Kickoff`, `Rush`, `Pass Reception`), `text`, `start`/`end`
  (`yardLine`, `yardsToEndzone`, down and distance, possessing team id),
  `statYardage`, `clock`, `period`, `wallclock`.
- Pass direction is in the text (`pass short left to C.Skattebo`), and so is
  the run gap (`right guard`).

Known gaps:

- Jersey numbers are not in the site `summary` play data. They are available:
  the core `plays` endpoint lists `participants` (`passer`, `receiver`,
  `rusher`, `scorer`, `kicker` and more) with athlete ids, and a cached team
  roster maps id to jersey (74 of 79 players had one). Verified 2026-11-12;
  details in `football_api.md`.
- Delay against TV is unknown. `broadcast_delay_seconds` may apply.
- Undocumented API: it can change without notice.

## Screens

Every football screen draws as much of the field as fits, with the possessing
team's logo at its end of the panel.

### `fb_field`: the resting screen

Field across the panel with yard ticks and end zones tinted in team colours. A
ball dot at `yardLine`, a first-down marker `distance` yards ahead of it in the
direction of play. `yardLine` runs 0-100 from the **home** team's goal line,
not the offence's, so the away team drives toward 0 and the marker sign (and
the left-right flip of the whole view) depends on who has the ball (see
`football_api.md`). A small
band with the clock, quarter and `1ST & 10`. Red zone tinted when `isRedZone`.
Shown between plays.

### `fb_run`: a rush

Triggered by a new play of type `Rush`. The ball moves from `start.yardLine`
to `end.yardLine`, the carrier's **jersey number** on it. Up the middle stays
on the centre lane; the gap in the text (`left end`, `right guard`) nudges the
lane for outside runs. Length scales with yardage.

### `fb_pass`: a pass

Triggered by a new play of type `Pass Reception`. The ball arcs from the
quarterback's spot at `start.yardLine` to the receiver's at `end.yardLine`,
the **receiver's number** appearing on the catch. Yards after the catch are a
short run from the landing point. Depth and direction (`short`, `deep`,
`left`, `middle`, `right`) set the arc's height and lane.

### Play-text layout

After the animation the field stays in the area it needs and the play text
takes one side: `J.McCarthy pass short middle to I.Likely for 9 yards`, with
the down and distance under it. Long text scrolls. For example, field on the
left ~64px, text on the right ~64px. On a single 64px panel it alternates
between the two. Plays that are not a run or a pass (penalty, punt, kickoff,
sack, field goal, timeout) skip the animation and go straight to this layout.

### Scoring and turnovers

These are the football equivalents of the NHL `goal` / `goal_detail` pair: a
short celebration over everything else, then a detail screen. They take the
whole panel and preempt `fb_field`, `fb_run`, `fb_pass` and the play-text
layout, in the same way `goal` preempts the game scene. The play animation
(`fb_run` / `fb_pass`) still plays first, so the ball is seen arriving in the
end zone, and the celebration starts when it lands.

#### What the feed gives us

Checked against 6 finished games on 2026-11-12 (`.../summary?event=<id>`).

| Need | Where | Seen in the data |
|---|---|---|
| Is it a score? | `play.scoringPlay` | `true` on `Passing Touchdown` (13), `Rushing Touchdown` (10), `Field Goal Good` (30) |
| Score after the play | `play.awayScore`, `play.homeScore` | on every play; the delta says **who** scored and how many points |
| Is it a turnover? | `play.isTurnover` | `true` on `Pass Interception Return` (4), `Fumble Recovery (Opponent)` (5), `Sack Opp Fumble Recovery` (3) |
| Not a turnover | `isTurnover: false` | `Fumble Recovery (Own)`, `Punt`, `Field Goal Missed` |
| Scorer, distance, kicker | `play.text` | `... pass short right to C.Woerner for 1 yard, TOUCHDOWN.`; `N.Folk 31 yard field goal is GOOD` |
| Extra point result | same `play.text` | `... extra point is GOOD` rides on the touchdown play; there is no separate play |
| Miss detail | `play.text` | `38 yard field goal is No Good, Wide Left` |
| Interception spot | `play.text` | `INTERCEPTED by B.Carter at ATL 43` |

Not seen in those games, so **unverified**: safety, two-point conversion,
defensive and return touchdowns (pick-six, fumble return, punt and kickoff
return), a turnover on downs, a muffed punt, a blocked kick. The design below
handles them by the generic rules at the end of this section until a real
payload is captured.

#### Who gets a celebration

Same scoping rule as the NHL board, and to be confirmed by the owner (see the
open questions):

- The **favourite's** scores get the full celebration and the horn.
- A **followed** team's scores (`also_follow`) get the quick version: the plain
  score screen, no horn.
- An opponent's score, or an unfollowed game's, gets nothing beyond the normal
  play-text layout.
- Who scored comes from the **score delta**, not from the possessing team, so a
  pick-six counts for the defence.
- A game already in progress at startup does not celebrate: scores are
  baselined on first sight, as in `_detect_goals`.

#### `fb_touchdown`: the favourite scores a touchdown

Triggered by a new play with `scoringPlay` true whose `type` contains
`Touchdown`. Runs for `fb_score_seconds` (6s proposed, held to 4-15s like
`goal_flash_seconds`).

```
 0.0-1.0s   white flash, then both end zones pulse in the team colour
 1.0-3.0s   the whole field strobes; the ball spikes at the goal line
 1.0-3.5s   TOUCHDOWN drops in one letter at a time, team colour
 3.5-6.0s   shimmer across the letters; team city name fades in along the bottom
```

```
+----------------------------------------------------------------+
|  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  |   field strobing
|   T  O  U  C  H  D  O  W  N        (letters drop in, one by one)|
|  [logo]                  NASHVILLE                    [logo]   |
+----------------------------------------------------------------+
```

The look follows the goal light on purpose (full panel, no logos, no score
in the first seconds). It is a function of the seconds since the play, so it
runs the fast animation loop while up. The horn plays the instant the score is
detected, whatever is on screen.

#### `fb_score_detail`: who scored

Follows the celebration for `fb_score_detail_seconds` (8s proposed). Like
`goal_detail`, it waits for the celebration to finish and gets its own full
time.

```
+----------------------------------------------------------------+
| [logo]   #14  C. WOERNER                          [logo]       |
|          1 YD PASS FROM M. PENIX                               |
|          PAT GOOD                           ATL 7   CIN 0      |
+----------------------------------------------------------------+
```

- Line 1: scorer's jersey number and name. The number depends on the roster
  lookup (see the data gaps above); fall back to name only.
- Line 2: yards and how: `PASS FROM <passer>`, `RUN`, or for a return
  `INT RETURN` / `FUM RETURN`. The passer is parsed from the play text.
- Line 3: the extra-point result (`PAT GOOD`, `PAT NO GOOD`, `2 PT GOOD`),
  parsed from the same play text, and the new score. The score comes from
  `awayScore` / `homeScore` on the play, which already includes the point after.
- A single 64px panel drops the line-2 passer first, then the PAT text.

#### `fb_fieldgoal`: a made field goal

Triggered by `scoringPlay` true on a `Field Goal Good` play. Runs for
`fb_score_seconds`, then the same detail screen with the kicker.

- The ball is placed at the kick spot, then **arcs through the uprights**: two
  tall posts drawn at the end of the field with the arc height scaled to the
  distance. The uprights flash on a good kick.
- `FIELD GOAL` in team colour, with `31 YD` (parsed from the text) below it.
- The detail line reads `N. FOLK  31 YD` and the new score. It is `+3`, and
  `awayScore` / `homeScore` carry it.
- Horn: the favourite's only, same as a touchdown.

#### `fb_fg_miss`: a missed field goal

Triggered by a `Field Goal Missed` play in a followed team's game. Not a
celebration, so no horn and a short **3s** screen: the ball arcs and drifts off
to the side the text names (`Wide Left`, `Wide Right`, `Short`, `Blocked`), the
words `NO GOOD` and `38 YD  WIDE LEFT`. For the favourite's own miss it is
the same screen. For an opponent's miss it is the same screen too, since it is
good news for the board's owner.

#### `fb_turnover`: interception or fumble lost

Triggered by `isTurnover` true. Runs for `fb_turnover_seconds` (4s proposed).
This is an alert, not a celebration: it is colour-coded by who gained the ball.

```
+----------------------------------------------------------------+
| [logo]        INTERCEPTION                       [logo]        |
|   ball arc flips, lands at the other team's logo               |
|               INT  B. CARTER  ATL 43          (new possession) |
+----------------------------------------------------------------+
```

- Title from the play type: `INTERCEPTION`, `FUMBLE`. A sack that ends in a
  fumble (`Sack Opp Fumble Recovery`) reads `SACK-FUMBLE`.
- The ball visibly **turns around**: it leaves the offence's end of the field,
  and a short arrow draws toward the team that now has it, ending at the new
  spot. The possession logo swaps sides at the same moment.
- Colour: the favourite **gaining** the ball is green; the favourite **losing**
  it is red. Between two non-favourites it is amber and short.
- Detail line: who took it away and the yard line (`INTERCEPTED by B.Carter at
  ATL 43`), parsed from the text. A return that ran a long way shows the
  return yards.
- Sound: reuses the existing audio slots. The favourite **taking** the ball
  plays the ding; the favourite **giving** it away is left silent by default
  (open question). Neither uses the horn.

A turnover that is also a score (a pick-six) shows `fb_touchdown` only. The
touchdown wins, because it is the bigger event, and the detail line says
`INT RETURN`.

#### Rules for anything unrecognised

1. A score is any play where `awayScore` / `homeScore` changed. If the type
   is not recognised, show a generic `fb_score` screen: the delta in points,
   the scoring team, the new score, and the first line of the play text. This
   covers safety (2 pts), two-point conversions and return touchdowns until each
   is seen in real data.
2. A change of possession on a play that is not a punt, kickoff, or
   end-of-period, with `isTurnover` false, is treated as a turnover on downs
   and gets the amber `fb_turnover` with the title `ON DOWNS`.
3. An unknown `type` never throws: it falls back to the play-text layout.

#### Order and timing for one scoring play

| Step | Screen | Length |
|---|---|---|
| 1 | `fb_pass` or `fb_run` lands the ball | 2-4s |
| 2 | `fb_touchdown` or `fb_fieldgoal` | `fb_score_seconds`, 6s proposed |
| 3 | `fb_score_detail` | `fb_score_detail_seconds`, 8s proposed |
| 4 | `fb_field` at the kickoff | until the next play |

A turnover is step 1, then `fb_turnover` for 4s, then back to the play-text
layout.

#### Reviews and reversals

Scoring plays and turnovers are the plays most often reviewed. One of the
sample plays above had a challenge in its own text. A celebration for a play
that is then overturned is bad, and the feed may remove or change the play
after the fact.

- Proposed: hold the celebration until the play has survived **one more poll**,
  and skip it if the text contains `REVERSED` or `challenged` and the score did
  not change.
- If the score later drops, no screen is shown for the reversal; the board
  just returns to normal and the score band corrects itself.
- Open question: whether a delay of a few seconds is acceptable here, given the
  feed already runs ahead of TV (`broadcast_delay_seconds` partly covers this).

## Timing (proposed, tune on hardware)

| Screen | Trigger | Length |
|---|---|---|
| `fb_field` | Resting state between plays | Until the next play arrives |
| `fb_run` / `fb_pass` | New play detected | 2-4s, scaled by yardage |
| Play-text layout | After the animation | Until the next play, at least ~5s |
| `fb_touchdown` / `fb_fieldgoal` | Favourite's score | `fb_score_seconds`, 6s (held to 4-15s) |
| `fb_score_detail` | After the celebration | `fb_score_detail_seconds`, 8s |
| `fb_fg_miss` | Missed field goal in a followed game | 3s |
| `fb_turnover` | `isTurnover` | `fb_turnover_seconds`, 4s |

## Open questions

- [ ] NFL only, or other leagues through the same ESPN shape?
- [ ] Does football replace the NHL scene logic, or run alongside it for
      followed teams?
- [ ] If jersey numbers prove unavailable: initials or last name instead?
- [ ] Which other plays get their own animation (punt, kickoff, field goal,
      sack)?
- [ ] Which team(s) does a board follow, and where is that set?
- [ ] Celebration scoping: favourite only gets the full screen and horn, a
      followed team gets the quick screen, opponents nothing. Confirm.
- [ ] Should the favourite **giving away** the ball (interception, fumble) make
      a sound? Proposed default is silent; taking the ball plays the ding.
- [ ] Is a few seconds' hold to survive a review acceptable, or celebrate at once
      and accept the occasional overturned touchdown?
- [ ] Opponent's missed field goal: show the `NO GOOD` screen (proposed) or skip?

## Todo

### Infrastructure

- [x] `football` branch exists, with its own pre-releases (#342)
- [x] Updater can follow a branch; admin page picker (#342)
- [ ] Confirm on a real board: `football` appears in the dropdown and installs

### Research

- [x] Verify jersey numbers via the roster endpoint (core `plays` participants + roster, see `football_api.md`)
- [ ] Measure feed delay against a live broadcast
- [ ] Capture sample payloads for each play type (punt, sack, penalty,
      touchdown, field goal, interception, fumble) into the repo as fixtures
- [ ] Capture the play types not yet seen: safety, two-point conversion, pick-six
      and other return touchdowns, turnover on downs, muffed punt, blocked kick
- [ ] Check what the feed does with a reviewed or reversed scoring play
- [ ] Decide the polling interval and how to stay under ESPN's tolerance

### Documentation

- [ ] Football section in `screens.md`: how each screen is chosen and how long
      it stays up
- [ ] Mockup of `fb_field`
- [ ] Mockup of `fb_run`
- [ ] Mockup of `fb_pass`
- [ ] Mockup of the play-text layout, on 128px and 64px panels
- [x] Scoring and turnover screens designed (see Scoring and turnovers)
- [ ] Mockups: `fb_touchdown`, `fb_score_detail`, `fb_fieldgoal`, `fb_fg_miss`,
      `fb_turnover`, on 128px and 64px
- [ ] Priority against the NHL screens written down

### Build (after the design is agreed)

- [ ] Data layer: ESPN client and models
- [ ] `fb_field` renderer
- [ ] Play detection and the animation queue
- [ ] `fb_run` and `fb_pass` animations
- [ ] Play-text layout and scrolling
- [ ] Score detection from the `awayScore` / `homeScore` delta, with a baseline on
      first sight
- [ ] `fb_touchdown` and `fb_fieldgoal` celebrations
- [ ] `fb_score_detail` (scorer, passer, PAT, new score) with the play-text parser
- [ ] `fb_fg_miss`
- [ ] `fb_turnover`, plus the on-downs and generic `fb_score` fallbacks
- [ ] Horn and ding wiring, and the review hold
- [ ] Config and admin page settings
- [ ] Demo mode steps and `scripts/render-screens.py` images
- [ ] Tests
