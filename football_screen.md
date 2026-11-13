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

- Jersey numbers are not in the play data; `participants` carries athlete ids.
  The number probably needs a roster lookup (`/teams/{id}/roster`). Unverified.
- Delay against TV is unknown. `broadcast_delay_seconds` may apply.
- Undocumented API: it can change without notice.

## Screens

Every football screen draws as much of the field as fits, with the possessing
team's logo at its end of the panel.

### `fb_field`: the resting screen

Field across the panel with yard ticks and end zones tinted in team colours. A
ball dot at `yardLine`, a first-down marker at `yardLine + distance`. A small
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

Touchdown, field goal, interception and fumble each get a short celebration or
alert screen, like the NHL `goal` screen, possibly reusing the goal horn.
Separate design needed.

## Timing (proposed, tune on hardware)

| Screen | Trigger | Length |
|---|---|---|
| `fb_field` | Resting state between plays | Until the next play arrives |
| `fb_run` / `fb_pass` | New play detected | 2-4s, scaled by yardage |
| Play-text layout | After the animation | Until the next play, at least ~5s |

## Open questions

- [ ] NFL only, or other leagues through the same ESPN shape?
- [ ] Does football replace the NHL scene logic, or run alongside it for
      followed teams?
- [ ] If jersey numbers prove unavailable: initials or last name instead?
- [ ] Which other plays get their own animation (punt, kickoff, field goal,
      sack)?
- [ ] Which team(s) does a board follow, and where is that set?

## Todo

### Infrastructure

- [x] `football` branch exists, with its own pre-releases (#342)
- [x] Updater can follow a branch; admin page picker (#342)
- [ ] Confirm on a real board: `football` appears in the dropdown and installs

### Research

- [ ] Verify jersey numbers via the roster endpoint
- [ ] Measure feed delay against a live broadcast
- [ ] Capture sample payloads for each play type (punt, sack, penalty,
      touchdown, field goal, interception, fumble) into the repo as fixtures
- [ ] Decide the polling interval and how to stay under ESPN's tolerance

### Documentation

- [ ] Football section in `screens.md`: how each screen is chosen and how long
      it stays up
- [ ] Mockup of `fb_field`
- [ ] Mockup of `fb_run`
- [ ] Mockup of `fb_pass`
- [ ] Mockup of the play-text layout, on 128px and 64px panels
- [ ] Scoring and turnover screens designed
- [ ] Priority against the NHL screens written down

### Build (after the design is agreed)

- [ ] Data layer: ESPN client and models
- [ ] `fb_field` renderer
- [ ] Play detection and the animation queue
- [ ] `fb_run` and `fb_pass` animations
- [ ] Play-text layout and scrolling
- [ ] Scoring and turnover screens
- [ ] Config and admin page settings
- [ ] Demo mode steps and `scripts/render-screens.py` images
- [ ] Tests
