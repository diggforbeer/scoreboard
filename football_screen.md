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
| `fb_cointoss` | First `Coin Toss` play for a followed game | `fb_cointoss_seconds`, 6s |
| `fb_touchdown` / `fb_fieldgoal` | Favourite's score | `fb_score_seconds`, 6s (held to 4-15s) |
| `fb_score_detail` | After the celebration | `fb_score_detail_seconds`, 8s |
| `fb_fg_miss` | Missed field goal in a followed game | 3s |
| `fb_turnover` | `isTurnover` | `fb_turnover_seconds`, 4s |
| `fb_reversal` | A celebrated play is reversed by review or penalty | `fb_reversal_seconds`, 5s |

## Open questions

- [ ] NFL only, or other leagues through the same ESPN shape?
- [ ] Does football replace the NHL scene logic, or run alongside it for
      followed teams?
- [ ] If jersey numbers prove unavailable: initials or last name instead?
- [ ] Which other plays get their own animation (punt, kickoff, field goal,
      sack)?
- [ ] Which team(s) does a board follow, and where is that set?
- [ ] Coin toss: the feed only says who receives, not who won or deferred. Is
      "`<TEAM>` RECEIVE" enough, or is a source for the winner worth finding?
- [ ] Coin toss: any sound (a soft ding for the favourite receiving), or silent?
- [ ] Celebration scoping: favourite only gets the full screen and horn, a
      followed team gets the quick screen, opponents nothing. Confirm.
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
- [ ] Capture the play types not yet seen: safety, two-point conversion, pick-six
      and other return touchdowns, turnover on downs, muffed punt, blocked kick
- [ ] Capture a real reviewed or reversed scoring play, and what the feed does with it
      (score drop? play removed? type changed?), to confirm the three detection rules
- [ ] Decide the polling interval and how to stay under ESPN's tolerance

### Documentation

- [ ] Football section in `screens.md`: how each screen is chosen and how long
      it stays up
- [ ] Mockup of `fb_cointoss`, on 128px and 64px
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
- [ ] `fb_cointoss` (detection from the `Coin Toss` play, with the first-kickoff fallback)
- [ ] Play detection and the animation queue
- [ ] `fb_run` and `fb_pass` animations
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
- [ ] Config and admin page settings
- [ ] Demo mode steps and `scripts/render-screens.py` images
- [ ] Tests
