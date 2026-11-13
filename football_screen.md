# Football (NFL) screens: design and todo

Lives on the `football` branch. Boards only get it if they pick `football`
under Software update on the admin page. Replaces issue #341 as the place this
is tracked: tick boxes here, in the PR that does the work.

Documentation first: nothing below is built yet.

## Companion files: read both

- **`football_screen.md`** (this file): what the board shows, when, for how
  long, and the todo list. Product design.
- **[`football_api.md`](football_api.md)**: what ESPN's feed actually returns:
  endpoints, field meanings, the `yardLine` orientation, play types,
  participants and jersey numbers, caveats. Technical reference.

The two are meant to be read and updated together. A screen design here that
depends on a data field should point at the section of `football_api.md` that
verifies it; a new finding about the feed goes in `football_api.md` and, if it
changes a design, is reflected here. When they disagree, check the live feed and
fix both.

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

## Choosing the sport

Decided by the owner: a board runs **NHL or NFL, one at a time**, chosen with a
picker. There is no mixing, no priority between the two sports, and no
"NHL wins" rule.

- A new setting picks the sport: `[scoreboard] sport = "nhl"` (the default, so a
  board that never touches it behaves exactly as today) or `"nfl"`. The admin
  page's Scoreboard card gets a matching dropdown.
- With `nhl`, the app is exactly the existing NHL app. Nothing in `screens.md`
  changes and no football code runs.
- With `nfl`, the board runs the football logic in this file: its own data
  source (ESPN), its own scene selection and its own `fb_` screens. The NHL
  logic stays idle.
- **Teams work like NHL.** In NFL mode the admin page's Scoreboard card shows an
  NFL **favourite team** and **followed teams** (the 32 NFL teams), in place of the
  NHL ones, set the same way. Changing the picker swaps which pickers show.
  - They are stored separately from the NHL settings (proposed: a `[football]`
    section with `favourite_team` and `also_follow`), not shared, because the
    abbreviations overlap between the leagues (`BUF`, `CAR`, `DAL`, `DET`, `MIN`
    and others) and mean different teams. Switching sport and back keeps each
    sport's choices.
  - The favourite is the board's primary team: its game takes the screen, gets the
    full celebrations and the horn, and its logo and colours are used where the NHL
    board uses the favourite's. Followed teams are the secondary ones: they take
    their turn on the screen and get the quick score updates, as in NHL.
  - Open: whether the followed-team rules (primary-first, quick turns, goal-style
    updates) are copied exactly or adjusted for football, where a game is three
    hours and a score is rarer than an NHL goal.
- Shared between the two: the panel, brightness and night mode, the admin page,
  Wi-Fi, the updater, holidays, the clock and the button. These are not
  sport-specific.
- The screens that are not sport-specific stay: `ap_setup`, `wifi_join`,
  `address`, `connecting`, `no_data`, `no_games`, and the idle clock. How much of
  the idle rotation (standings and so on) carries over is for the NFL side to
  decide; the NHL-only ones (NHL standings, matchup, leaders) do not apply.
- The picker keeps all sport-specific code behind one switch, which is what lets
  the branch merge to `main` later without changing NHL boards.

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
between the two. **Every** play gets an animation before this layout, not just runs and passes:
see "Every other play" below.

### Every other play

Decided by the owner: **animate every play**, not only runs and passes. Every
play follows the same shape as `fb_run` / `fb_pass`: the animation on the field,
then the play-text layout with the result, then the next play. Checked against the
text of 4 finished games on 2026-11-12; type names and wording below are what was
actually seen unless marked unverified.

Common rules for every animation:

- It ends with the ball settled at the play's `end.yardLine` (`start.yardLine`
  when the play is nullified), and the down-and-distance band updated.
- The label (`PUNT 53 YD`, `SACK -6`) is drawn over the field while it plays,
  and the play-text layout then shows the feed's own sentence.
- Directions flip with the possessing team, as in `fb_field`: `yardLine` runs 0-100
  from the **home** goal line.
- A play with a number in its text uses the jersey number, from the roster map, in
  the same way `fb_run` and `fb_pass` do; a missing number falls back to the last
  name.

| Play type (`type.text`) | Animation | Label | Length |
|---|---|---|---|
| `Kickoff` | Ball on the kicker's tee at the 35, **arcs high** to the landing spot parsed from `to ATL 6`, then the returner's number **runs back** to the end spot | `KICKOFF 59 YD`, then `RETURN 24 YD` | 5s |
| `Kickoff`, touchback | Same arc, lands in the end zone, ball **steps out** to the 25 | `TOUCHBACK` | 4s |
| `Punt`, fair catch | Long, high arc (more hang than a kickoff); lands, a **flag/hand** icon marks the catch | `PUNT 53 YD`, `FAIR CATCH` | 5s |
| `Punt`, returned | Arc, then the returner's number runs back (`O.Zaccheaus to ATL 24 for -3 yards`) | `PUNT 51 YD`, `RETURN -3` | 5s |
| `Punt`, out of bounds | Arc, then the ball **skips to the sideline** edge and stops | `OUT OF BOUNDS` | 4s |
| `Punt`, touchback | Arc into the end zone, ball steps out to the 20 | `TOUCHBACK` | 4s |
| `Rush` | `fb_run` (above), including a QB scramble | `RUSH +9` | 2-4s |
| `Pass Reception` | `fb_pass` (above) | `PASS +12` | 2-4s |
| `Pass Incompletion` | Ball arcs toward the lane and target in the text, **drops and bounces** short of the receiver; the ball marker stays put | `INCOMPLETE`, plus `#14` if a target is named (`to K.Pitts`) | 3s |
| `Sack` | The QB's number **drops back**, then a burst at the sack spot as the marker slides **backwards** to it | `SACK -6`, sacker's number or name | 3s |
| `Field Goal Good` | Kick spot, ball arcs through the uprights (see `fb_fieldgoal`) | `FIELD GOAL 31 YD` | celebration |
| `Field Goal Missed` | Ball arcs and drifts off the side the text names (`Wide Left` / `Wide Right`) | `NO GOOD`, direction | 3s (see `fb_fg_miss`) |
| `Penalty` | A **yellow flag** flies in and lands at the enforcement spot; the marker moves to the new spot | `FLAG`, the foul, yards (`FALSE START 5 YD`); `NO PLAY` when the text says so | 4s |
| `Timeout` | A clock icon **freezes**; the team's timeouts left shown as dots | `TIMEOUT NYG #2`, `0:45` | 3s |
| `Official Timeout` | Same clock icon, neutral colour | `OFFICIAL TIMEOUT` | 3s |
| `Two-minute warning` | Clock icon with `2:00` | `2-MIN WARNING` | 3s |
| `End Period` | Quarter number wipes across the field | `END Q1` | 3s |
| `End of Half` | Same, then the board holds on a halftime card | `HALFTIME` | until play resumes |
| `End of Game` | Hands over to the final scoreboard (held like an NHL final) | `FINAL` | held |
| `Coin Toss` | `fb_cointoss` | | 6s |
| Scores, turnovers | The play's own animation first, then the celebration or turnover alert | | see those sections |

Per-play notes, from real text:

- **Kickoffs:** text is `E.McPherson kicks 59 yards from CIN 35 to ATL 6. K.Herbert
  to ATL 30 for 24 yards (J.Kiser; T.Davis).` The kick distance, the landing spot,
  the returner, the return yards and the tackler are all in it. A penalty on the
  play shows up in the same text (`PENALTY on ATL-M.Ford, Offensive Holding`), which
  is why `start`/`end` can disagree with the printed return: use the printed
  return for the animation and `end.yardLine` for where the ball finally sits.
  Touchbacks appeared 8 times in the sample.
- **Punts:** four endings seen: `fair catch by D.Meyers`, `out of bounds`, a
  return (`O.Zaccheaus to ATL 24 for -3 yards`) and a touchback. The punt's own
  distance (`punts 53 yards`) sets the arc length.
- **Incompletions:** 80 in the sample, the most common non-run, non-pass type, so
  this animation must be quick. Direction (`short right`, `deep left`) sets the
  lane and the arc height; a named target (`to K.Pitts`) puts a number on it, and
  `[C.Thomas]` brackets mark the defender who broke it up.
- **Sacks:** `sacked at CIN 31 for -6 yards (L.London)`. A sack for 0 yards
  (`for 0 yards`) is seen too: the burst plays with no slide. A sack that ends in a
  fumble is `Sack Opp Fumble Recovery` and goes to the turnover screen.
- **Penalties:** type `Penalty` is used **even when a play happened**. One sample is
  a QB scramble that gained 6 yards and was then wiped out by a hold
  (`scrambles up the middle to CIN 1 for 6 yards ... PENALTY on ATL-M.Bergeron,
  Offensive Holding, 10 yards`). Rule: if the text contains a result before the
  word `PENALTY`, play that result **compressed** (about 1s), then the flag, then
  the marker moves to the enforced spot. `No Play` in the text means the first part
  did not count. `declined` (6 in the sample) shows the flag then `DECLINED`, with
  the ball staying where the play left it.
- **Timeouts:** `Timeout #1 by CIN at 01:10.` carries the team, the timeout number
  and the clock. Timeouts left is `3 - number`, which should be checked against the
  situation block's `homeTimeouts` / `awayTimeouts`.
- **Stoppages:** `Official Timeout at 11:12.`, `Two-Minute Warning`, `END QUARTER 1`,
  `END QUARTER 2` (type `End of Half`), `END GAME`.

**Pace, queueing and catch-up.** Plays are about 35-60s apart in real time, so a
2-5s animation fits easily. But the feed is polled every 10-15s, so one poll can
return several plays at once, and a kickoff follows a score within seconds.

- Animations play **in play order** (`sequenceNumber`), one at a time.
- A backlog of more than **two** plays is caught up by playing the oldest at double
  speed and skipping straight to the newest. The ball always lands where the
  newest play puts it, so the field is never wrong.
- Stoppage cards (timeouts, two-minute warning, end of period) are **dropped first**
  when there is a backlog, because they carry no ball movement.
- A board that starts mid-game draws the current field and does **not** replay the
  plays before startup (same baseline rule as goal detection).
- The animation clock starts when the play is **shown**, not at its `wallclock`, so
  `broadcast_delay_seconds` shifts everything together.

**Not seen in the sample, so unverified:** the type names for a QB kneel (5 kneels
in the text, type unknown), a spike (1), an onside kick (0), a safety (0), a
blocked kick (0), a two-point attempt, an intentional grounding (1) and a free
kick. Each falls back to the plain play-text layout until its type is seen.

### `fb_cointoss`: the opening coin toss

The first screen of a game. It shows a coin flipping, settling on the team that
**receives the opening kickoff**, then `<TEAM> RECEIVE`.

#### What the feed gives us (checked 2026-11-12, two finished/live games)

- The toss is a play of type `Coin Toss` (type id `70`) in the **core** `plays`
  endpoint, first in the list, `sequenceNumber` 100, period 1, clock `15:00`.
  Its text is just `GAME`.
- The **site `summary` leaves it out**: `drives.previous[0]` starts at the
  kickoff. So a board reading only the site endpoints never sees a toss play.
- The play does **not** say who won the toss, what they called, or whether they
  chose to receive, defer, or pick an end. None of that is in any field I could
  find (no `participants`, and no text on the play or anywhere in `summary` or the
  competition object).
- What it does carry is the **result**: `team` and `end.team` are the team that
  receives, `start.team` is the team that kicks. The first `Kickoff` play agrees
  (`start.team` kicks, `end.team` receives), so the receiver can also be read
  from the site `summary` without the core endpoint.
- **Timing:** a game days away returns 0 plays. In a game that was live, the toss
  play's `modified` time was within a minute of the opening kickoff's
  `wallclock`, so the feed appears to publish it **at kickoff, not at the real
  toss** (which happens about three minutes before). Unverified for the
  pre-kickoff window of a game starting in minutes.

So the screen can honestly say who **receives**. It cannot say who **won** or
**deferred**, and must not imply it. Anything beyond that (`won the toss`,
`deferred`, `chose to receive`) needs another source and is out of scope.

#### When it shows

- Triggered by the first `Coin Toss` play seen for a game the board follows (the
  favourite, or an `also_follow` team), when the game goes live.
- Not shown for a game that is already in progress at startup (baselined on first
  sight, like goals), or one that is not followed.
- Overtime has its own toss in the real game. Whether the feed publishes a second
  `Coin Toss` play in period 5 is **unverified**. If one arrives with a new id and
  `period >= 5`, it gets the same screen with the label `OT COIN TOSS`. If it
  does not, no screen.
- If the core endpoint is not being polled, the screen is built from the first
  `Kickoff` play's receiving team instead, a little later but with the same result.

#### What it looks like (about 6s, proposed `fb_cointoss_seconds`)

```
 0.0-0.5s   COIN TOSS in small type; a coin appears at centre
 0.5-3.0s   the coin flips: width squeezes to a line and back, spinning faster
            then slower, rising and falling a few pixels
 3.0-3.5s   it lands face-up; the face is the receiving team's logo
 3.5-6.0s   <TEAM> RECEIVE in team colour; the kicking team's logo fades small
            at the other edge with KICK
```

```
+----------------------------------------------------------------+
|   COIN TOSS                                                    |
|              (  o  )          <- coin mid-flip, narrow         |
+----------------------------------------------------------------+
|  [logo]            NYG RECEIVE                      [logo]     |
|  receives                                           kicks      |
+----------------------------------------------------------------+
```

- Whole panel, like the other celebration screens; it is a pure function of the
  seconds since it started, so it runs the fast animation loop while up.
- Team colours for the settled coin and text. Without logos the coin face is the
  three-letter abbreviation in team colour.
- On a single 64px panel the kicking team's logo and the `KICK` caption drop, and
  only `<TEAM> RECEIVE` remains.
- It plays **no horn**: there is nothing to celebrate yet. A soft sound is an
  open question.
- It ends by itself and the board moves to `fb_field` for the opening kickoff, the
  same way the goal screen hands back to the game.

#### Not designed here

- A **pre-game** toss screen. The feed has no plays before kickoff, so there is
  nothing to show before then; whatever the board shows pregame (countdown or
  preview) is unchanged.
- **Heads or tails**, the winner, or the defer decision, for the reason above.
- The second-half kickoff, which has no toss. It plays as an ordinary kickoff.

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

#### Reviews and reversals: celebrate now, explain if it changes

Decided by the owner: **celebrate immediately**, with no hold. Scoring plays
and turnovers are the plays most often reviewed, so if the feed later changes
one that was celebrated, the board says so on its own screen instead of
quietly correcting the score, then goes back to normal.

**Detecting a change.** For every play that got a celebration (a touchdown,
field goal or turnover, favourite or followed team), the app remembers the play
`id`, the scoring team, the points, the score before it, and the text. On each
poll it compares that against the feed. It is a **reversal** if any of these is
true:

1. The game score is now **lower** than the score the celebration announced
   (`awayScore` / `homeScore` dropped).
2. The play is gone from the feed, or its `scoringPlay` / `isTurnover` flag has
   become false.
3. The play's `type` has changed (for example `Passing Touchdown` becoming
   `Pass Incompletion` or `Penalty`).

The score drop is the main signal, because the feed reports the score on every
play. The others cover a play that is replaced without the score moving yet.
A play whose text merely changes while its type, flags and score stay the same
(a corrected spelling, or an extra-point line added) is **not** a reversal.

**What it shows.** `fb_reversal`, for `fb_reversal_seconds` (5s proposed),
preempting whatever is on screen like the celebration did. It is amber, not
green or red: this is neither good nor bad news yet, it is a correction.

```
+----------------------------------------------------------------+
| [logo]        TOUCHDOWN OVERTURNED                [logo]       |
|      OFFENSIVE PASS INTERFERENCE ON ATL-14                     |
|      SCORE BACK TO  ATL 0   CIN 0              (old score)     |
+----------------------------------------------------------------+
```

- **Title** from what was reversed: `TOUCHDOWN OVERTURNED`, `FIELD GOAL
  NEGATED`, `TURNOVER OVERTURNED`. Uses the original play's kind, which the app
  remembered.
- **Reason line** is the feed's own replacement text, trimmed: for example the
  penalty wording or the new play's text. The app does not try to understand it;
  it shows the first line, scrolling if it is long. If the feed gives no usable
  text, the line reads `PLAY CHANGED ON REVIEW`.
- **Score line** shows the score being restored and the new down and distance if
  the feed has them. On a single 64px panel the reason line goes first, then the
  score.
- **Then back to normal.** After `fb_reversal_seconds` the board returns to
  `fb_field`, with the ball at the restored spot, exactly as for any play. The
  score band is already corrected.

**Details and limits**

- It only shows for plays that were celebrated. A reversal on an opponent's
  score or an unfollowed game is silent, because nothing was announced.
- The horn cannot be unplayed. The board accepts that the favourite's horn may
  sound for a touchdown that is then overturned. The reversal screen is what
  makes that understandable.
- If the celebration is still on screen when the change arrives (a very quick
  flag), the reversal screen **replaces it at once** and the detail screen is
  skipped.
- A reversed play is shown once. If the play is then changed again (a score put
  back after a second review), it is treated as a new play: it celebrates
  again as a fresh score.
- There is no "under review" screen. Whether the feed shows a review in
  progress is unknown, and showing one would need a field that has not been
  seen. It is left out until real data shows one.

**Unverified.** None of the detection above has been seen on a real reversed
play. The first rule (score drops) is the likeliest to work; the other two are
guesses at how the feed represents a removed play. Capturing a real one is a
research todo, and the detector should log every case it matches so the rules
can be tightened from real games.

## Timing (proposed, tune on hardware)

| Screen | Trigger | Length |
|---|---|---|
| `fb_field` | Resting state between plays | Until the next play arrives |
| `fb_run` / `fb_pass` | New play detected | 2-4s, scaled by yardage |
| Play-text layout | After the animation | Until the next play, at least ~5s |
| Kickoff / punt | New play | 4-5s |
| Incompletion / sack / penalty / timeout | New play | 3-4s |
| Stoppage cards (official timeout, 2-min warning, end of period) | New play | 3s |
| `fb_cointoss` | First `Coin Toss` play for a followed game | `fb_cointoss_seconds`, 6s |
| `fb_touchdown` / `fb_fieldgoal` | Favourite's score | `fb_score_seconds`, 6s (held to 4-15s) |
| `fb_score_detail` | After the celebration | `fb_score_detail_seconds`, 8s |
| `fb_fg_miss` | Missed field goal in a followed game | 3s |
| `fb_turnover` | `isTurnover` | `fb_turnover_seconds`, 4s |
| `fb_reversal` | A celebrated play is reversed by review or penalty | `fb_reversal_seconds`, 5s |

## Open questions

- [x] NFL only (decided). College football and other leagues are out of scope;
      the code can use the `nfl` league path and the 32 NFL teams directly.
- [x] One sport per board, chosen with a **picker** (decided): a board runs NHL
      or NFL, never both. No mixing and no priority rules between the sports. See
      "Choosing the sport".
- [x] Sport picker lives on the **admin page, just like the NHL settings** (decided):
      a dropdown on the Scoreboard card that saves itself with an Undo, like the other
      cards. It is stored as `[scoreboard] sport` so a boot-partition TOML can set it
      too.
- [x] Changing the sport applies **live** (decided): the board swaps over without a
      restart or reboot. This is more than a favourite-team switch, so the build has
      to drop everything the old sport held (cached data, remembered scores and plays,
      the last scene, any animation in progress, the follow lists in use) and start
      the new sport from a clean baseline, so nothing celebrates on the first frame.
      The panel shows `connecting` until the new sport's first fetch lands.
- [x] Jersey numbers: they are available (core `plays` participants + roster, see
      `football_api.md`), so the fallback is only for the ~5 of 79 players with no
      number. Those show the last name instead (decided by default, shout if not).
- [x] Every play gets an animation (decided): kickoff, punt, incompletion, sack,
      penalty, timeout, field goal and the stoppages as well as runs and passes.
      See "Every other play".
- [~] Animation pace: **deferred by the owner**. Is a cap on how far a board can lag
      behind the live game (catch-up by skipping) acceptable, or must every play be
      shown in full? Not decided: build it, run it on a **Pi 4**, and see how slow or
      laggy it really is. The catch-up rules under "Every other play" stay as the
      provisional default until there are measurements.
- [x] Teams (decided): in NFL mode the admin page lets the owner set a **favourite
      team and followed teams, just like NHL**. See "Choosing the sport".
- [ ] Coin toss: the feed only says who receives, not who won or deferred. Is
      "`<TEAM>` RECEIVE" enough, or is a source for the winner worth finding?
- [ ] Coin toss: any sound (a soft ding for the favourite receiving), or silent?
- [x] Celebration scoping (confirmed by the owner): the favourite gets the full
      screen and horn, a followed team gets the quick screen, opponents and
      unfollowed games get nothing. Same as the NHL rule.
- [ ] Should the favourite **giving away** the ball (interception, fumble) make
      a sound? Proposed default is silent; taking the ball plays the ding.
- [x] Reviews: celebrate immediately, and show a `fb_reversal` screen explaining
      the change if the play is overturned, then swap back (decided)
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
- [ ] Coin toss: find out when the feed publishes the toss play before kickoff, whether
      overtime gets a second `Coin Toss` play (the overtime check errored), and whether
      any source names the toss winner
- [ ] Find the type names for QB kneel, spike, onside kick, intentional grounding and
      free kick (the sample's text mentions kneels, a spike and a grounding)
- [ ] Capture the play types not yet seen: safety, two-point conversion, pick-six
      and other return touchdowns, turnover on downs, muffed punt, blocked kick
- [ ] Capture a real reviewed or reversed scoring play, and what the feed does with it
      (score drop? play removed? type changed?), to confirm the three detection rules
- [ ] Decide the polling interval and how to stay under ESPN's tolerance
- [ ] Measure on a **Pi 4** with the real panel: frame rate during the heaviest
      animations (kickoff and punt arcs, the touchdown strobe, the coin flip), CPU use,
      and how far behind the live game the queue falls over a full game. This answers
      the deferred animation-pace question; log queue depth and lag per play so it can
      be read from a real game

### Documentation

- [ ] Football section in `screens.md`: how each screen is chosen and how long
      it stays up
- [ ] Mockup of `fb_cointoss`, on 128px and 64px
- [ ] Mockup of `fb_field`
- [ ] Mockup of `fb_run`
- [ ] Mockup of `fb_pass`
- [ ] Mockups: kickoff, punt (fair catch / returned / out of bounds / touchback), incompletion,
      sack, penalty (flag), timeout, end of period, halftime
- [ ] Mockup of the play-text layout, on 128px and 64px panels
- [x] Scoring and turnover screens designed (see Scoring and turnovers)
- [ ] Mockups: `fb_touchdown`, `fb_score_detail`, `fb_fieldgoal`, `fb_fg_miss`,
      `fb_turnover`, on 128px and 64px
- [ ] Which non-sport screens and idle-rotation entries carry over to the NFL mode, written down

### Build (after the design is agreed)

- [ ] Data layer: ESPN client and models
- [ ] `fb_field` renderer
- [ ] `fb_cointoss` (detection from the `Coin Toss` play, with the first-kickoff fallback)
- [ ] Play detection and the animation queue
- [ ] `fb_run` and `fb_pass` animations
- [ ] Kickoff and punt animations (arc, return, fair catch, out of bounds, touchback)
- [ ] Incompletion, sack and penalty (flag) animations, including a play wiped out by a penalty
- [ ] Timeout, official timeout, two-minute warning, end-of-period and halftime cards
- [ ] Animation queue: ordering, double-speed catch-up, dropping stoppages first
- [ ] Play-text layout and scrolling
- [ ] Score detection from the `awayScore` / `homeScore` delta, with a baseline on
      first sight
- [ ] `fb_touchdown` and `fb_fieldgoal` celebrations
- [ ] `fb_score_detail` (scorer, passer, PAT, new score) with the play-text parser
- [ ] `fb_fg_miss`
- [ ] `fb_turnover`, plus the on-downs and generic `fb_score` fallbacks
- [ ] Horn and ding wiring
- [ ] Reversal detector (remembers celebrated plays, compares each poll, logs every match)
- [ ] `fb_reversal` screen
- [ ] Live sport switch: tear down the old sport's state and baseline the new one cleanly
- [ ] `[scoreboard] sport` setting and the admin page picker; NFL favourite and followed teams (`[football]`), shown instead of the NHL pickers in NFL mode
- [ ] Config and admin page settings
- [ ] Demo mode steps and `scripts/render-screens.py` images
- [ ] Tests
