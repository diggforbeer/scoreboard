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
  - **Built (story #348):** `[football] favourite_team` and `also_follow` in the config
    (`FootballConfig`), the 32 teams sent to the admin page from the NFL table so it has no
    second list, validated against the NFL table (an NHL-only abbreviation such as `NSH` is
    rejected on a live save and ignored with a warning from a hand-edited TOML). The favourite
    is not also followed, duplicates collapse, and with no favourite set the board shows every
    game. In NFL mode the Scoreboard card shows the NFL pickers in place of the NHL ones; its
    other settings (puck-drop countdown, shootout polling, goal timings) are NHL-only and are
    still shown, which a later story should hide.
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
- **NFL mode fetches off the render thread** (story #351). A feed worker
  (`football/worker.py`) owns the ESPN client and polls on its own thread; the render
  loop only reads the latest immutable snapshot, so a slow request never freezes the
  panel or an animation. The NHL side still fetches on the render loop (#267), so this is
  a difference between the sports on purpose. How it behaves:
  - It starts when the board enters NFL mode (or when `run()` starts in NFL mode) and
    stops on a switch back to NHL or on exit; nothing runs, and nothing fetches, otherwise.
  - A failed fetch **keeps the last good games** and records the error, so the panel does
    not blank on a blip. Failures back off (the poll interval, doubling, capped at 120s).
  - The data is **stale** when the last *successful* fetch is over 15 minutes old, the same
    window as NHL. Before the first success it is "connecting", not stale.
  - It polls at `live_poll_seconds` while a game is live and `poll_seconds` otherwise,
    never faster than every 10s (the feed caches for 7-9s). Changes on the admin page
    apply at the next poll.
  - A fetch slower than 3s is logged at WARNING with its duration.
- The picker keeps all sport-specific code behind one switch, which is what lets
  the branch merge to `main` later without changing NHL boards.

## Base scenes (what NFL mode shows today)

Before any of the designed screens below exist, NFL mode shows four plain scenes (story
#352; the play scenes of #377 are below). They are the thin base that gets real ESPN data onto the panel, the NFL counterpart
of the NHL text layout, and the designed screens build on them. `football/mode.py` keeps the
list (`FB_SCENE_KINDS`) and a test keeps this section, that list and the renderer in step.

| Scene | When | What it draws |
|---|---|---|
| `fb_connecting` | The feed has not answered yet | `NFL` over `CONNECTING` |
| `fb_no_data` | The last **successful** fetch is over 15 minutes old, or the feed has been failing for 15 minutes without ever answering | `NO DATA` over `NFL CHECK NETWORK` |
| `fb_no_games` | The feed answered and there are no games on the slate (a bye, the off-season) | `NO GAMES` over `NFL` |
| `fb_scores` | There is a game to show | One game as text (below) |

**`fb_scores`** (`display/football_scenes.py`): away on the left half and home on the right,
each abbreviation in its **NFL team colour** (never the NHL one) with its score in white at
the edge of its half; the down and distance (`2ND & 3 AT WSH 13`) in amber while a game is
live, red in the red zone; the state along the bottom in the state's colour: green for live
play, amber at halftime, grey once final, blue before kickoff. Before kickoff there is no
score, and the line is the kickoff time in the board's timezone (`SUN 11/15 12:00 PM`, just
`12:00 PM` on a single 64px panel). A team that is not one of the 32 (a Pro Bowl side) is
drawn plain. On a 64px panel the abbreviations and scores drop to the smaller font so both
sides fit.

**Which game** (`NflMode.pick_game`), using the NFL favourite and followed teams:

1. The favourite's game holds the screen **alone while it is live**.
2. Otherwise the games the followed teams are in take turns, `rotate_seconds` each, the
   favourite's first; if any of them is live, only the live ones.
3. With nobody followed, or none of them playing (a bye), every game takes a turn, live
   ones first.

Turns are timed by the monotonic clock, so a refresh that changes the slate never makes the
board skip or repeat a game. There is no hold timer for a finished game (NHL has
`final_hold_minutes`): a final stays on the rotation until the slate moves on.

### Play scenes (the plumbing, #377)

While a play, a celebration or a reversal is on screen the board shows one of three scene
kinds instead of `fb_scores`. `football/director.py` decides which (it draws nothing); the
renderer's registries in `display/football_plays.py` draw it, and **each designed screen is one
registered function**, so a screen's story only adds an entry:

| Scene | What it is | Register with |
|---|---|---|
| `fb_play` | The animation of one play, a pure function of the seconds since it began | `@play_screen(PlayKind.X)` |
| `fb_playtext` | The feed's own sentence once the animation is over | (the play-text story replaces it) |
| `fb_event` | A celebration, alert, coin toss or reversal; `Scene.fb_stage` is `event`, `detail` or `reversal` | `@event_screen(EventClass, stage)` |

Anything with no entry gets a plain generic version (the ball sliding from where the play
started to where it ended, a card with the headline and score), so an unknown play type or an
undrawn event still shows something and never raises.

**One play is a run of stages:** `[coin toss]  play animation  [celebration  detail | alert]
play text`, then the board returns to `fb_scores` (the resting field arrives with its own story).

- **Scope decides the size** (the detector already did): `FULL` (the favourite) gets the whole
  celebration and the detail screen; `QUICK` (a followed team) a short one with no detail; a
  field goal by a team nobody follows (`PLAIN`) gets only the play's own animation; a missed
  field goal is a short card for anyone in a followed game; a turnover an alert.
- **A reversal preempts** whatever is on screen and skips the detail screen; it is shown once.
- **The animation clock starts when a stage is shown**, so `broadcast_delay_seconds` moves
  everything together. Catch-up is the queue's (stoppages dropped first, the oldest plays
  skipped, the shown one at double speed); the events of skipped plays still celebrate, shown
  before the play that was animated.
- **Which game:** the one on screen first, then any other watched game with plays waiting, so a
  followed team's touchdown is not lost because another game was on screen.
- **Which games are fetched:** only live (or about-to-start, within 20 minutes) games the
  favourite or a followed team is in; with none of those, the first live game. Never the whole
  slate. The core feed (jersey numbers, the toss) is fetched when the site feed shows a new play.
- **Lengths** (`director.Timings`, the proposed values of "Timing", held to sane ranges;
  settings come with the settings story): play 3s, play text 5s, score 6s, detail 8s,
  quick 4s, missed field goal 3s, turnover 4s, reversal 5s, coin toss 6s.
- The live view does not show a stage mid-animation (it waits for it to end, like the NHL
  shootout and goal light); what the panel shows is exact.

The admin page's status box and Live view work in NFL mode: the status box reports the
feed's last successful poll and last error, and the Live view mirrors these scenes pixel for
pixel (tested for every state).

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

**Built (story #378, `display/football_scenes.py` `draw_fb_field`).** A live game rests on
`fb_field`; before the game, at the half and once it is final the board shows `fb_scores`.
Details the design left open:

- The **band** is `3RD 12:24` on the left, the down and distance on the right (`2ND & 7`;
  `1ST&GOAL` tightened to leave room; red in the red zone) and, on a 128px panel, the **score**
  between them (`WSH 10 NYG 17`, abbreviations in team colours), because nothing else on this
  screen says it. The 4x6 `Q` reads as a zero, so the quarter is `1ST`..`4TH`, not `Q3`. A 64px
  panel has no room: the clock and `2&7` only.
- The **red zone** is tinted dark red over the 20 yards in front of the goal line the offence
  attacks (the home team attacks yard 100, the away team yard 0), under the yard lines.
- The first-down line follows the offence and stops at the goal line (goal to go).
- **No situation** (a kickoff, between quarters) draws the plain field. An offence the app does
  not know shows the ball but no markers.
- `fb_field_64` stays a hand-drawn mockup: the image script renders 128px panels only; the 64px
  layout is pinned by snapshots (`tests/snapshots/fb_field_*_64.txt`).

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

**Built (story #379, `football/textlayout.py` + `display/football_plays.py`).** A pure
function of the seconds since the stage began:

- **128px:** the field in the left half (ball where the play ended, the play's label over it),
  the sentence on the right **three lines at a time** with the new down and distance fixed
  under it. A sentence of more than three lines is **held 2s, then scrolls up one line a second**
  and rests on the last lines for 1.5s. The scroll is line by line (the panel cannot clip a text
  draw to a window), not smooth.
- **64px:** the field and the text **take turns**: the field for 2s, then the text (three lines
  and the down, scrolling the same way), and the cycle repeats until the stage ends.
- **How long it stays up:** at least 5s, longer when the sentence needs scrolling (the
  field's turn included at 64px), capped at 15s so a board that is behind never sits on one
  play. Real sentences are 50-200 characters, so most scroll. It then returns to `fb_field`.
- The generic version is what every play shows; a designed play screen changes only its
  animation, not this layout.

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
- A backlog of more than **two** plays is caught up: stoppage cards are dropped first
  (oldest first), then the oldest plays are skipped until two remain, and the one shown is
  played at double speed. The ball always lands where the newest play puts it, so the field
  is never wrong. Implemented in `football/queue.py` (#355).
- Stoppage cards (timeouts, official timeouts, two-minute warning, end of a quarter) are
  **dropped first** when there is a backlog, because they carry no ball movement.
  **Halftime, the end of regulation and the end of the game are never dropped** (they carry
  state: a card, the final), and neither is the newest ball-moving play, so a long enough
  burst can leave more than two waiting when those are all that is left.
- A board that starts mid-game draws the current field and does **not** replay the
  plays before startup (same baseline rule as goal detection).
- The animation clock starts when the play is **shown**, not at its `wallclock`, so
  `broadcast_delay_seconds` shifts everything together.

**What 2,441 real plays (13 games, `football_api.md`) settled:** a QB kneel is a
`Rush` ("J.Burrow kneels to ATL 9"), a spike and an intentional grounding are a
`Pass Incompletion` (the grounding's penalty is in the text, not the type), an onside
kick is a `Kickoff` ("kicks onside 19 yards"), and a two-point attempt rides on the
touchdown play's text. So none of these need their own animation type: the animation
reads the flags off the play. **Still not seen:** a safety, a blocked kick, a free kick
and a turnover on downs. Each falls back to the plain play-text layout until it is seen.

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
**deferred**, and must not imply it. The owner confirmed this is enough; anything
beyond that (`won the toss`, `deferred`, `chose to receive`) is out of scope.

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
- It is **silent** (decided: sounds are touchdowns and field goals only, see
  "Sounds").
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

Same scoping rule as the NHL board, confirmed by the owner, with **one
exception: field goals** (see below):

- The **favourite's** scores get the full celebration and the horn.
- A **followed** team's scores (`also_follow`) get the quick version: the plain
  score screen, no horn.
- An opponent's score, or an unfollowed game's, gets nothing beyond the normal
  play-text layout.
- **Exception, field goals:** the outcome of every field goal, **made or missed**,
  is shown for **either team** in a game the board is following (the favourite's
  game, or a followed team's game). Decided by the owner. See `fb_fieldgoal` and
  `fb_fg_miss`. A field goal in an unfollowed game is still not shown.
- Who scored comes from the **score delta**, not from the possessing team, so a
  pick-six counts for the defence.
- A game already in progress at startup does not celebrate: scores are
  baselined on first sight, as in `_detect_goals`.

**Built (story #356, `football/events.py`).** The decision is made by an `EventDetector`, which
emits typed events (`Touchdown`, `FieldGoal` made or missed, `GenericScore`, `Turnover`,
`CoinToss`) each with a `scope` and a `sound` flag; the screens read those. Nothing is drawn or
played there. As built:

| Event | The favourite's | A followed team's | Anyone else's |
|---|---|---|---|
| Touchdown, other score | `FULL`, **sound** | `QUICK`, silent; but **not** when it scores on the favourite | not emitted |
| Field goal, made | `FULL`, **sound** | `QUICK`, silent | `PLAIN` (in a followed game only), silent |
| Field goal, missed | `QUICK`, silent | `QUICK`, silent | `PLAIN` (in a followed game only), silent |
| Turnover, coin toss | about the game: `FULL` in the favourite's game, `QUICK` in a followed team's | | not emitted |

- **In the favourite's own game only the favourite's scores count** (the NHL rule); two followed
  teams meeting both count. The sound flag is only the favourite's touchdown and made field goal.
- **Who scored is the score delta**, so a pick-six is the defence's touchdown (`via =
  "interception"`) and no separate turnover is emitted for it. A safety, or any score with an
  unrecognised type, is a `GenericScore`. The points are the delta, so a touchdown that carries
  its extra point reads as 7 and a two-point conversion as 8.
- **A turnover** is the feed's `isTurnover` flag, a muffed punt, or a **turnover on downs**: a
  scrimmage play on **fourth down** after which the other team has the ball. In the 2,441 real
  plays possession changed on a scrimmage play only on fourth down (14 times, no false positives).
- **The coin toss** comes from the opening kickoff (15:00 in the first quarter), because the
  site feed omits the `Coin Toss` play; once per game, and never for a board that joined mid-game.
- **Skipped plays still count.** The queue may skip plays to catch up, so the detector reads
  every skipped play as well as the one shown: a touchdown among them still celebrates.
- **Nothing fires for the score the board started with:** a game's score is seeded from the play
  queue's baseline (`PlayQueue.baseline`), a fresh detector (a new mode after a sport switch)
  starts empty, and an unseeded game treats its first play as the baseline. A score that goes
  *down* (a review) emits nothing here; that is the reversal detector (#357).

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
runs the fast animation loop while up. The touchdown sound (see "Sounds") plays
the instant the score is detected, whatever is on screen.

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

Triggered by `scoringPlay` true on a `Field Goal Good` play, for **either team**
in a followed game (decided: always show a field goal's outcome). Runs for
`fb_score_seconds`, then the same detail screen with the kicker.

| Kicking team | Screen | Sound |
|---|---|---|
| The favourite | The full celebration below | The favourite's field-goal sound |
| A followed team | The same animation, quick version, as for a followed team's touchdown | none |
| The opponent (or any other team in the game) | The same kick animation and `FIELD GOAL 31 YD`, **without the celebration**: no uprights flash, no strobe, in the kicking team's colours | none |

The opponent's version is deliberately plainer, because a field goal against the
favourite is not a celebration, but the board still shows what happened.

- The ball is placed at the kick spot, then **arcs through the uprights**: two
  tall posts drawn at the end of the field with the arc height scaled to the
  distance. The uprights flash on a good kick.
- `FIELD GOAL` in team colour, with `31 YD` (parsed from the text) below it.
- The detail line reads `N. FOLK  31 YD` and the new score. It is `+3`, and
  `awayScore` / `homeScore` carry it.
- Sound: the favourite's field-goal sound, played the instant the kick is
  detected as good (see "Sounds").

#### `fb_fg_miss`: a missed field goal

Triggered by a `Field Goal Missed` play for **either team** in a followed game
(decided: always show a field goal's outcome). Not a celebration, so no sound and
a short **3s** screen: the ball arcs and drifts off to the side the text names
(`Wide Left`, `Wide Right`, `Short`, `Blocked`), the words `NO GOOD` and
`38 YD  WIDE LEFT`. It is the same screen for the favourite's miss and the
opponent's.

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
- Sound: **none**, taking the ball or giving it away (decided: touchdowns and
  field goals only, see "Sounds").

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
- A sound cannot be unplayed. The board accepts that the favourite's touchdown or
  field-goal sound may play for a score that is then overturned. The reversal screen is what
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

**What the real feed shows (nine reversed plays in 13 finished games, #353).** ESPN does
not remove a reversed play and does not drop the score line: it **rewrites the play in
place**. The play's `type` and flags become the *final* ruling, and the text keeps the
original call, then a sentence, then the corrected play:

> `D.Prescott pass short right to C.Lamb for 11 yards, TOUCHDOWN.` `The Replay Official
> reviewed the pass completion ruling, and the play was REVERSED.` `D.Prescott pass
> incomplete short right to C.Lamb.` (type `Pass Incompletion`, `scoringPlay` false, score
> unchanged)

So in the finished feed a reversed touchdown looks like an ordinary incompletion whose text
says it was reversed. That makes rule 2 (the flag turned false) and rule 3 (the type
changed) the likely ones, and adds a fourth, much cheaper signal that needs no memory of
the earlier play: **the text contains `the play was REVERSED`** (`PlayText.review.reversed`,
with the original call and the corrected play split apart). Upheld reviews also appear
(`the play was Upheld. The ruling on the field stands.`) and must not count. A challenge
by a team names the team and costs a timeout (`(Timeout #1.)`).

**Still unverified:** what the feed shows *while* a review is in progress, and how long
after the original call it is rewritten. Those need a live game; the detector logs every case
it matches so the rules can be tightened.

**Built (story #357, `football/reversals.py`).** A `ReversalDetector` remembers every celebrated
score and turnover and compares each poll's plays (rewritten ones included) with what was
celebrated. It compares **outcomes**, and reports the rules that fired: `play_gone`,
`flag_cleared` (no longer scores, or no longer a turnover), `type_changed`, `score_dropped`, and
`possession_restored` (a turnover on downs that is not one any more). Decisions it embodies:

- **The review sentence is not a rule on its own.** A review can go the *other* way: an
  incompletion reversed into a touchdown is a touchdown the board celebrated, correctly. So
  `the play was REVERSED` only supplies the reason, and a review that is upheld, or reversed in
  the play's favour, is not a reversal. A text-only edit is not one either.
- **The reason is the feed's own words:** the corrected play with formation and substitution
  noise trimmed (`D.Prescott pass incomplete short right to C.Lamb.`), else the accepted penalty
  (`OFFENSIVE HOLDING ON ATL, NO PLAY`), else the ruling (`PASS COMPLETION RULING REVERSED`), else
  `PLAY CHANGED ON REVIEW`. The title is `TOUCHDOWN OVERTURNED`, `FIELD GOAL NEGATED`, `SCORE
  OVERTURNED` or `TURNOVER OVERTURNED`; the scope is the celebration's own; it never has a sound.
- **Reported once.** After it fires the play is forgotten; a later change is a new play.
- **A failed fetch is not a reversal:** an empty poll never makes a play "disappear".
- **A reversal that lands while the celebration is still waiting in the queue** (the poll with
  the rewritten play is applied first) is reported as soon as the celebration is remembered.
- **The running score is corrected.** A reversed touchdown leaves the event detector's tracked
  score 7 too high, which would make the *next* real touchdown show no change and go
  uncelebrated. The reversal takes back only its own points (`EventDetector.retract`), so later
  valid scores stay.
- **Same clock as the celebration:** `PlayWatcher` takes an `on_applied` hook, called when the
  broadcast delay lets a poll in, so a reversal appears the same delay after the celebration.
- Only celebrated plays are watched, so an opponent's score, or a game nobody follows, is silent.

## Real renders

Screens the board actually draws are rendered from the code, not by hand:
`python scripts/render-screens.py --sport nfl` walks `football.demo.nfl_demo_steps()` (the
same steps `nhl-scoreboard --demo` loops when `sport = "nfl"`) through the real app and writes
`docs/football/<step name>.png` with synthetic team-coloured circles for logos and a fixed clock,
so they are reproducible. `--sport nfl --check` fails when a committed image is stale, and a
test does the same. Nothing here touches `docs/screens/`.

| | |
|---|---|
| ![Connecting](docs/football/fb_connecting.png) | ![No data](docs/football/fb_no_data.png) |
| `fb_connecting`: the feed has not answered yet. | `fb_no_data`: nothing fresh for 15 minutes. |
| ![No games](docs/football/fb_no_games.png) | ![Pregame](docs/football/fb_scores_pregame.png) |
| `fb_no_games`: nothing on the slate. | `fb_scores`, before kickoff: start time along the bottom. |
| ![Live](docs/football/fb_scores_live.png) | ![Red zone](docs/football/fb_scores_redzone.png) |
| `fb_scores`, live: down and distance, clock and quarter. | `fb_scores` in the red zone: the situation line turns red. |
| ![Halftime](docs/football/fb_scores_halftime.png) | ![Final](docs/football/fb_scores_final.png) |
| `fb_scores` at halftime. | `fb_scores`, final. |

**The generic play scenes** (#377; what every play and event shows until its own screen is drawn):

| | |
|---|---|
| ![Generic play](docs/football/fb_play_rush.png) | ![Generic punt](docs/football/fb_play_punt.png) |
| `fb_play` for a rush: the ball slides from the start spot to the end spot, the play's name over it. | `fb_play` for a play with no screen yet (a punt). |
| ![Play text](docs/football/fb_playtext.png) | ![Event card](docs/football/fb_event_touchdown.png) |
| `fb_playtext`: the field on the left half, the feed's sentence on the right. | `fb_event` (stage `event`): the headline in the team's colour and the new score. |
| ![Event detail](docs/football/fb_event_detail.png) | ![Missed field goal card](docs/football/fb_event_fg_miss.png) |
| `fb_event` (stage `detail`): the play's text under the headline. | A missed field goal. |
| ![Turnover card](docs/football/fb_event_turnover.png) | ![Coin toss card](docs/football/fb_event_cointoss.png) |
| A turnover alert. | The coin toss: who receives. |
| ![Reversal card](docs/football/fb_event_reversal.png) | |
| `fb_event` (stage `reversal`): the correction and its reason. | |

`fb_field` and `fb_field_redzone` (the resting field, below) are real renders too: the same
names as their mockups, which they replaced.

**Retiring the mockups.** A designed screen that gets a real renderer adds its steps to
`football/demo.py`; a step named like a mockup replaces that image, and
`scripts/football-mockups.py` stops rewriting it. When the last mockup is replaced, delete
`scripts/football-mockups.py` and this paragraph's mockups section.

## Mockups

First drafts of how the screens look on the 128x32 panel (and a few at one 64x32
panel), drawn in the same round-LED style as the NHL guide. All are in
[`docs/football/`](docs/football/) and are produced by
`python scripts/football-mockups.py` (except `fb_field` and `fb_field_redzone`, which are real
renders now; see "Real renders").

**What these are and are not.** They are **design mockups, not renderer output**:
no football renderer exists yet, so each frame is drawn pixel by pixel by that
script, using the project's own BDF fonts and dot rendering so type size and pitch
are true to the panel. Teams are real NFL abbreviations (NYG and WSH) with plain
colour circles for logos, as the NHL guide does, because the crests are artwork
and are not committed. They are stills: a ball arc is drawn partway along its path,
a coin mid-flip, a touchdown at its settled look. When the real renderer lands,
the images should come from it and the script should be deleted.

**Layout decisions the mockups make**, which differ from the NHL screens and are
open for the owner's review:

- **The logos sit in the end zones**, about 12px, instead of 32px at each panel
  edge as in NHL. A 32px logo at each edge would leave only 64px for the field.
  With 14px end zones the playing field is exactly **100px for 100 yards**, one
  pixel a yard, which makes the maths and the animation easy. The team with the
  ball has its logo at full brightness and the other is dimmed.
- **Logo sizes and variant (decided in #349, from contact sheets of the real logos on turf):**
  **12px** in each end zone, **16px** for the larger uses (coin toss, score detail), the
  **dark** variant (the Giants' navy crest all but vanishes in ESPN's default art on turf; the
  dark art is readable, the same reason NHL uses it). 12px reads for most teams and 16px for all;
  **8px and below is a blob**, so on a single 64px panel the 7px end zones carry **no logo**, only
  the team-colour tint. Carolina's crest is a black panther and measures 31 (0-255) at 12px
  against 62 or more for every other team, so the fetch script **brightens a crest that dim**
  (CAR is the only one at present), the same idea as lifting navy team colours on the NHL side.
  Washington, Houston, Atlanta and the Jets are the next dimmest but read fine. A hand-picked
  override for any crest can go in `assets/logos/nfl/overrides/<size>/<variant>/`.
- **A one-line band across the top** (tiny 4x6 type): clock and quarter on the
  left, the down and distance or the play label on the right, in a colour that
  says the kind of play (green gain, red loss, amber neutral).
- **The field is 23px tall** under the band. Line of scrimmage is blue, the
  first-down line is yellow, the ball is a small orange-brown dot.
- **A number rides on the play** (the carrier or receiver), drawn above the ball
  or at the catch. The tiny font has no usable `#`, so the number is plain digits.
- **Built (story #358):** `football/geometry.py` (pure: yard to pixel, the direction each team
  drives, the first-down line and goal to go, run and pass lanes, kick and pass arcs, the layout
  constants) and `display/football_field.py` (the static field and the ball). Compared with
  `docs/football/fb_field.png` and `fb_field_64.png` the differences are deliberate: **goal lines**
  at yard 0 and 100 (brighter green) so the end-zone boundary reads, **no logo in a 64px end zone**
  (see the logo sizes above), and the logos are synthetic discs where the mockups drew rings
  (placeholders for the real art). The first-down line stops at the goal line in goal to go.
  Left and right are the offence's own: facing the goal it attacks, its left is **up the panel**
  when it drives right and **down** when it drives left.
- **`yardLine` runs from the home goal line**, so the home team's end zone is
  always on the left and the view flips its drive arrow and first-down line by
  who has the ball (see `football_api.md`). In every mockup NYG (home, left) is
  the favourite.

### The field and scrimmage plays

| | |
|---|---|
| ![Field](docs/football/fb_field.png) | ![Red zone](docs/football/fb_field_redzone.png) |
| `fb_field`: the resting screen. Clock, quarter, down and distance; ball, line of scrimmage and first-down line. | The same screen in the red zone (away team has the ball, so the drive runs the other way). |
| ![Run](docs/football/fb_run.png) | ![Pass](docs/football/fb_pass.png) |
| `fb_run`: the ball carrier's number moves with a fading trail. | `fb_pass`: an arc from the quarterback to the receiver's number. |
| ![Play text](docs/football/fb_playtext.png) | ![Field at 64px](docs/football/fb_field_64.png) |
| Play-text layout: the field on the left half, the feed's own text on the right. | `fb_field` on a single 64px panel. |

### Kicks, incompletions, sacks and penalties

| | |
|---|---|
| ![Kickoff](docs/football/kickoff_air.png) | ![Kickoff return](docs/football/kickoff_return.png) |
| Kickoff: the ball in the air on a high arc. | Kickoff return: the returner's number runs it back. |
| ![Punt, fair catch](docs/football/punt_fair_catch.png) | ![Punt return](docs/football/punt_return.png) |
| Punt, fair catch: long hang, a flag marks the catch. | Punt returned: the returner's number runs back, `RETURN -3`. |
| ![Incomplete](docs/football/incomplete.png) | ![Sack](docs/football/sack.png) |
| Incompletion: the ball drops short of the target number; the marker stays put. | Sack: the quarterback's number, a burst at the spot, the marker slides back. |
| ![Penalty](docs/football/penalty.png) | ![Penalty, no play](docs/football/penalty_no_play.png) |
| Penalty: a yellow flag at the spot. | Penalty card when the down is nullified (`NO PLAY`). |

### Stoppages, the toss and the end of a half

| | |
|---|---|
| ![Timeout](docs/football/timeout.png) | ![End of quarter](docs/football/end_quarter.png) |
| Timeout: clock icon, team, which timeout, and timeouts left as dots. | End of quarter, over the field. |
| ![Halftime](docs/football/halftime.png) | ![Coin toss, flipping](docs/football/cointoss_flip.png) |
| Halftime card with the score. | `fb_cointoss`, the coin mid-flip (narrow, rising). |
| ![Coin toss, result](docs/football/cointoss_result.png) | ![Coin toss at 64px](docs/football/cointoss_result_64.png) |
| `fb_cointoss` settled: the receiving team's logo and `NYG RECEIVE`; the kicking team small at the edge. | The same on a single 64px panel (the kicking team is dropped). |

### Scores, turnovers and reversals

| | |
|---|---|
| ![Touchdown](docs/football/touchdown.png) | ![Touchdown at 64px](docs/football/touchdown_64.png) |
| `fb_touchdown`: TOUCHDOWN at double size in the team colour, strobe rays behind, city name along the bottom. | At 64px it wraps to two lines. |
| ![Score detail](docs/football/score_detail.png) | ![Field goal](docs/football/fieldgoal.png) |
| `fb_score_detail`: scorer's number and name, how, the extra point and the new score. | `fb_fieldgoal`: the ball arcs over the uprights at the end of the field. |
| ![Opponent field goal](docs/football/fieldgoal_opponent.png) | ![Field goal missed](docs/football/fg_miss.png) |
| An opponent's made kick: the same animation, plainer, dim, no sound. | `fb_fg_miss`: `NO GOOD`, the distance and direction. |
| ![Turnover](docs/football/turnover.png) | ![Reversal](docs/football/reversal.png) |
| `fb_turnover`: red title, an arrow toward the team that now has the ball, who took it and where. | `fb_reversal`: amber `TOUCHDOWN OVERTURNED`, the reason, the restored score. |

**Rough edges to know about:** the touchdown letters are wide and nearly touch at
double size; the 5x7 and 4x6 text is small to read at a distance; the opponent's
field goal differs from the favourite's only by being dim, which may be too subtle;
and none of the animation can be judged from stills. The Pi 4 measurement (see
the deferred pace question) is where motion gets judged.

## Sounds

Decided by the owner: to start, sounds only for **touchdowns** and **field goals**,
and **per team**. Nothing else makes a sound: not the coin toss, interceptions,
fumbles, missed field goals, reversals, kickoffs or any other play. More can be
added later.

- **Two sound slots per team:** a touchdown sound and a field-goal sound. Each NFL
  team can have its own pair, like the NHL's per-team horns, plus a **default**
  touchdown sound and a default field-goal sound used when a team has no file of
  its own.
- **Who triggers them:** the favourite's own scores, the same moment the celebration
  is detected (not when the screen appears), and whatever is on screen. Opponents'
  scores are silent: the NHL's wah-wah has no counterpart here. Followed teams are
  silent by default (see the open question).
- **Stored apart from the NHL horns.** NFL and NHL abbreviations overlap (`BUF`,
  `CAR`, `DAL`, `DET`, `MIN` and more), so the NFL files live in their own folder
  or carry an `nfl` prefix. Proposed: `nfl/{ABBR}_td.wav`, `nfl/{ABBR}_fg.wav`,
  `nfl/_td.wav`, `nfl/_fg.wav`. The same upload directory and the same lookup
  order as the NHL horns (uploads before shipped files).
- **Admin page:** in NFL mode the Audio tab shows the touchdown and field-goal
  slots per team, with upload, Play and Delete like the NHL horns. Uploads are
  normalised the same way (RMS match, mono, WAV).
- **Existing controls apply:** the `audio` enabled switch, the volume, and the
  physical button's mute all silence them, as they do the NHL horn.
- **Shipped defaults:** a default touchdown sound and field-goal sound have to
  exist so a board makes a noise before anyone uploads. Generated like the NHL
  default horn, with no third-party audio committed. Team-specific files are a
  user drop-in, never committed.
- **A reversed score:** the sound has already played and cannot be taken back
  (see "Reviews and reversals").
- **Not verified on hardware** (the same caveat as the NHL audio): USB audio and
  its timing against the panel.

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
- [x] Coin toss (decided): "`<TEAM>` RECEIVE" is enough. The feed only says who
      receives, and the screen does not claim who won or deferred. No hunt for another
      source.
- [x] Sounds (decided): only **touchdowns and field goals**, **per team**, to start.
      The coin toss, turnovers, reversals and everything else are silent. See "Sounds".
- [~] (Deferred by the owner; silent is the working assumption.) Sounds: does a **followed** team's touchdown or field goal play its own team
      sound, or stay silent? The NHL rule is horn for the favourite only, and the
      celebration-scoping decision above gives followed teams a quiet quick screen,
      so silent is assumed. "Per team" could also mean followed teams get theirs.
- [x] Celebration scoping (confirmed by the owner): the favourite gets the full
      screen and horn, a followed team gets the quick screen, opponents and
      unfollowed games get nothing. Same as the NHL rule.
- [x] Reviews: celebrate immediately, and show a `fb_reversal` screen explaining
      the change if the play is overturned, then swap back (decided)
- [x] Field goals (decided): always show the outcome, made or missed, for **either
      team** in a followed game. An opponent's made field goal gets the plain kick
      animation with no celebration or sound; any miss gets `fb_fg_miss`.

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
      overtime gets a second `Coin Toss` play (the overtime check errored)
- [x] Type names for QB kneel, spike, onside kick, intentional grounding: found in 2,441
      real plays (#353); see `football_api.md`
- [~] Play types not yet seen: still a safety, a blocked kick, a free kick and a turnover
      on downs. Pick-sixes, two-point attempts and muffed punts are now seen
- [~] What the feed does with a reviewed or reversed scoring play: **finished games
      answered it** (the play is rewritten in place, with the reversal in its text); what it
      shows during a review, and how fast, still needs a live game
- [ ] Decide the polling interval and how to stay under ESPN's tolerance
- [ ] Measure on a **Pi 4** with the real panel: frame rate during the heaviest
      animations (kickoff and punt arcs, the touchdown strobe, the coin flip), CPU use,
      and how far behind the live game the queue falls over a full game. This answers
      the deferred animation-pace question; log queue depth and lag per play so it can
      be read from a real game

### Documentation

- [ ] Football section in `screens.md`: how each screen is chosen and how long
      it stays up
- [x] Mockup of `fb_cointoss` (128px, and the settled look at 64px); first drafts,
      see "Mockups"
- [x] Mockup of `fb_field` (128px and 64px)
- [x] Mockup of `fb_run`
- [x] Mockup of `fb_pass`
- [~] Mockups: kickoff, punt (fair catch, returned), incompletion, sack, penalty,
      timeout, end of period, halftime drawn. Still to draw: punt out of bounds and
      touchback, kickoff touchback, official timeout, two-minute warning
- [~] Mockup of the play-text layout: 128px drawn; the 64px version (alternating
      halves) is not
- [x] Scoring and turnover screens designed (see Scoring and turnovers)
- [~] Mockups: `fb_touchdown` (128px and 64px), `fb_score_detail`, `fb_fieldgoal`
      (favourite and opponent), `fb_fg_miss`, `fb_turnover`, `fb_reversal` drawn at
      128px. Still to draw at 64px: all but the touchdown
- [ ] Which non-sport screens and idle-rotation entries carry over to the NFL mode, written down

### Build (after the design is agreed)

- [x] Field geometry and the static field background (#358): `football/geometry.py`,
      `display/football_field.py`, snapshots at 128px and 64px; the screens that use it come next
- [x] NFL logos: `scripts/fetch-logos.py --sport nfl` (12px and 16px, dark), `LogoSet` for a team
      at several sizes, kept apart from the NHL art (#349)

- [x] Base scenes: the status screens and a plain text scoreboard with the favourite and
      followed-team selection (#352); see "Base scenes"
- [x] Data layer: ESPN client and models. Scoreboard client, models and `--dump --sport nfl`
      done (#350); play feed, `Play` model, play-text parser and `--dump-plays` done (#353);
      rosters, participants and jersey numbers done (#354, `football/people.py`). Not wired into
      the loop yet: the worker will fetch the core feed when the site summary shows a new play
- [x] `fb_field` renderer: live games rest on it, with the band, red zone and 64px layout (#378)
- [ ] `fb_cointoss` (detection from the `Coin Toss` play, with the first-kickoff fallback)
- [x] Play detection and the animation queue: the director, scene priority, hand-back, generic play and
      event screens, registries (#377)
- [ ] `fb_run` and `fb_pass` animations
- [ ] Kickoff and punt animations (arc, return, fair catch, out of bounds, touchback)
- [ ] Incompletion, sack and penalty (flag) animations, including a play wiped out by a penalty
- [ ] Timeout, official timeout, two-minute warning, end-of-period and halftime cards
- [x] Animation queue: ordering, double-speed catch-up, dropping stoppages first (#355;
      `football/queue.py`, with `--watch-nfl` to see it run and lag logged per play)
- [x] Play-text layout and scrolling (#379)
- [x] (#356) Score detection from the `awayScore` / `homeScore` delta, with a baseline on
      first sight
- [ ] `fb_touchdown` and `fb_fieldgoal` celebrations
- [ ] `fb_score_detail` (scorer, passer, PAT, new score) with the play-text parser
- [ ] `fb_fg_miss`
- [ ] `fb_turnover`, plus the on-downs and generic `fb_score` fallbacks
- [ ] Per-team touchdown and field-goal sounds: lookup, playback, mute-button
      support, admin Audio tab slots and uploads, shipped defaults (see "Sounds")
- [x] Reversal detector (remembers celebrated plays, compares each poll, logs every match) (#357)
- [ ] `fb_reversal` screen
- [x] Live sport switch: tear down the old sport's state and baseline the new one cleanly
- [x] `[scoreboard] sport` setting and the admin page picker (#345); NFL favourite and followed teams (`[football]`), shown instead of the NHL pickers in NFL mode (#348)
- [ ] Config and admin page settings
- [ ] Demo mode steps and `scripts/render-screens.py` images
- [ ] Tests
