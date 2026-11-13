# Football (NFL) screens when no game is on: design and todo

What an NFL board shows **between games**: before kickoff, after the final whistle, on
a bye week, and through the long off-season. It is the NFL counterpart of the NHL
guide's "Before a game" and "Between games" sections in [`screens.md`](screens.md)
(`preview`, `countdown`, `standings`, the idle rotation, `clock`).

This file is a **proposal for the owner to edit**: nothing here is built or decided
unless it says so. The in-game screens (the field, every play, the celebrations) are
in [`football_screen.md`](football_screen.md); what ESPN's feed returns is in
[`football_api.md`](football_api.md). Read those two first. Open work for this file is
the todo at the bottom; update it in the PR that does the work.

An NFL season is 17 games in about 18 weeks, so a board is **idle most of the time**:
one live game on a Sunday (three hours), then six days of nothing. What it shows then
is most of what anyone sees of it. That is the reason for this file.

## What it shows today

Built in the base scenes (#352) and the in-game work (#377-#396). With no game live the
board falls back to these, and only these:

| Situation | What is shown today |
|---|---|
| Before the game | `fb_scores`: the matchup and the kickoff time (`SUN 11/15 12:00 PM`), blue |
| At the half | `fb_halftime` (#388) |
| Once final | `fb_scores`: the score and `FINAL`, grey, held until the slate moves on |
| Games today, none involve the favourite or followed teams | every game takes a turn, `rotate_seconds` each (`NflMode.pick_game`) |
| The feed answered and the slate is empty (a bye, the off-season) | `fb_no_games`: `NO GAMES` over `NFL` |
| The feed is stale or never answered | `fb_no_data` / `fb_connecting` |

So on a bye week or in March the board says `NO GAMES NFL` and nothing else, and the
idle clock, holidays and everything between games that the NHL board has are absent.
The scoreboard feed is asked for **today's slate only** (`scores(date=None)`), so the
board cannot say when the next game is.

## Principles

- **Never a blank or a bare "NO GAMES" while there is something worth saying.** The NHL
  rule ("a screen with nothing to show right now is skipped, never shown blank") carries
  over.
- **The favourite comes first.** Everything below is about the favourite's team; with no
  favourite set it is about the league.
- **Football is a weekly sport.** The next game is days away, not hours: the useful
  numbers are days and the day and time of kickoff, not a puck-drop countdown.
- **Same machinery as the NHL idle rotation where it fits**: a list of screens, each for
  its own number of seconds, a screen with nothing to show skipped. Whether NFL mode reads
  the existing `[[rotation]]` setting or gets its own is an open question.
- **Cheap on the feed.** Anything that needs more than the live scoreboard (a schedule, a
  standings table) is fetched rarely (hourly or daily) and cached, never per frame.
- **Everything is optional and degrades.** If the data for a screen is missing it is
  skipped, and the board falls back to the clock or `fb_no_games`.

## Proposed screens

Each is a proposal with the data it needs; "unverified" means the endpoint has not been
checked against the live feed yet (see Research).

### `fb_countdown`: kickoff is close

The favourite's game starts within the hour (or the hours before, as `countdown_minutes`
does in NHL). Both teams' logos at the edges, `KICKOFF IN` and a countdown in the middle
(`0:42:15`), the broadcast time under it. Replaces `fb_scores` for that game once it is
inside the window. Data: the game's start time, already in the scoreboard feed.

### `fb_preview`: the next game, days away

The favourite's next game, up to a week out: `SUN 12:00 PM`, `@ WSH` or `vs DAL`, both
logos, the week number, optionally the records and the broadcast. The NFL equivalent of the
NHL `preview`, with days instead of hours. Data: the next game's date and teams (needs
more than today's slate: see Research); records are on the scoreboard feed.

### `fb_bye`: a bye week

When the favourite has no game this week: `BYE WEEK`, the logo, and the next game
(`NEXT: SUN 11/22 @ DAL`). Replaces `NO GAMES`. Data: the team's schedule.

### `fb_final`: after the game

`fb_scores` already holds the final. Proposed: after the game the favourite's final stays
for a set time (the NHL's `final_hold_minutes`), then the rotation resumes. Optionally a
**recap** line (the winning team, the margin, the leading passer or rusher). Data: the
final score; leaders would need the summary or box score (unverified).

### `fb_offseason`: the long gap

From the end of the season to kickoff: the favourite's logo, `NEXT GAME`, and the days
to the opener (`SEP 6 · 142 DAYS`), with a few fixed dates worth marking (the draft, the
start of training camp) if the owner wants them. Data: the first game of next season (the
schedule is published in May, so before that only a configured or estimated date).

### `fb_standings`: the playoff picture

The favourite's **division** (four teams, W-L-T, the favourite highlighted) and, as a
second page, the **conference** seeds (1-7 with the cut line). The NFL counterpart of
`division`, `wildcard` and `standings`. Data: the standings table (unverified endpoint).

### `fb_week`: the league's slate

Everyone's score for the week on one frame, the way `scores` shows several NHL games: on a
Sunday, the other 15 games; on Monday, the whole week's finals. A grid of small score
cells, paged. Data: the scoreboard feed for the week (the `dates` parameter exists; the week
view is unverified).

### `fb_schedule`: the next few games

The favourite's next three games in a column: date, opponent, home or away. Data: the
schedule.

## Carry-over from the NHL idle rotation

The NHL side is in [`screens.md`](screens.md), "Between games". Proposed fate of each:

| NHL screen | In NFL mode |
|---|---|
| `clock` (`clock`, `show_clock_when_idle`) | **Carries over unchanged**: it is not sport-specific. The fallback when nothing else has anything to show. |
| `christmas_tree` and the holiday decorations | **Carry over unchanged**, with the one known gap in `CLAUDE.md`: the holiday overlay still uses NHL team colours with NFL abbreviations. |
| `address`, `ap_setup`, `wifi_join`, `connecting`, `no_data`, `no_games` | **Carry over** (`fb_connecting`, `fb_no_data` and `fb_no_games` already exist). |
| `preview`, `countdown` | Become `fb_preview`, `fb_countdown` above. |
| `standings`, `division`, `wildcard`, `conference_leaders` | Become `fb_standings` (a division page and a conference page). |
| `scores` (the all-games grid) | Becomes `fb_week`. |
| `matchup`, `matchup_meetings` (the NHL season series) | **Do not apply**: teams meet once or twice a year. Optionally a head-to-head line on `fb_preview`. |
| `leaders` (the favourite's top players) | Possible later as team leaders (passing, rushing); needs the roster stats endpoint. |
| `three_stars` | **Does not apply.** |

## Which screen is chosen (proposed)

Highest first; the first that has something to show wins, as in the NHL list in
`screens.md`:

1. The favourite's game live, or a followed team's live game (as today: `pick_game`).
2. The favourite's game is inside the kickoff window: `fb_countdown`.
3. The favourite's game just ended: `fb_final`, held for a set time.
4. **The idle rotation**: a list of screens, each for its own seconds (proposed default
   `fb_preview`, `fb_standings`, `fb_week`, `fb_schedule`, then the clock), a screen with
   nothing to show skipped.
5. The favourite is on a bye: `fb_bye` joins the rotation.
6. In the off-season: `fb_offseason` joins the rotation.
7. With no favourite set: every game of the week, as `pick_game` does today.
8. Otherwise the clock, else `fb_no_games`.

## Data needs and research

The board fetches only today's `scoreboard` now. Everything marked "unverified" above needs
a check against the live feed before it is designed in detail, and the findings go in
`football_api.md`:

- The **team schedule** (`/teams/{id}/schedule`) or the scoreboard with `dates=` across a
  week or a season: needed for `fb_preview`, `fb_bye`, `fb_schedule` and `fb_offseason`.
- The **standings** endpoint and its shape (the site API and the core API differ): for
  `fb_standings`.
- Whether the **scoreboard week view** (`?week=`, `?seasontype=`) returns a whole week: for
  `fb_week`.
- Box-score or leaders fields for a recap line.
- How the feed behaves in the **off-season** and in the gaps (preseason, the bye week, the
  playoffs): the `seasontype` values, and what the scoreboard returns on a day with no games.

## Open questions

- [ ] One rotation or two? Does NFL mode reuse the existing `[[rotation]]` setting (shared
      with NHL, with NFL screen names) or get its own `[football]` rotation?
- [ ] How long does a final stay (the NHL's `final_hold_minutes`), and is there a recap?
- [ ] The preseason and the playoffs: are they "games" for these screens, and how does the
      board name a round (`WILD CARD`, `SUPER BOWL`)?
- [ ] Records on `fb_preview`: wanted, and from which feed?
- [ ] The off-season dates (the draft, training camp): wanted, and configured by the owner or
      fixed in the code?
- [ ] 64px panels: which of these have a single-panel version, and which are skipped there.
- [ ] Thursday and Monday night games and holiday games (Thanksgiving, Christmas): any
      special treatment, or just games.

## Todo

### Research
- [ ] Verify the schedule, standings and week-view endpoints; add them to `football_api.md`.
- [ ] Capture the off-season and bye-week responses.

### Design
- [ ] Decide the open questions above.
- [ ] Mockups for each screen the owner keeps (128px, and 64px where it applies), made the way
      `football_screen.md`'s are (`scripts/render-screens.py --sport nfl` once built).
- [ ] The default idle rotation and its settings; the admin page's rotation card for NFL mode.

### Build (after the design is agreed, one story each)
- [ ] The schedule fetch and cache (hourly or daily, off the render thread).
- [ ] `fb_countdown`, `fb_preview`, `fb_bye`, `fb_offseason`
- [ ] `fb_final` (the hold, and the recap if kept)
- [ ] `fb_standings`, `fb_week`, `fb_schedule`
- [ ] The NFL idle rotation and the scene selection above, with the clock as the fallback
- [ ] Demo steps and `scripts/render-screens.py --sport nfl` images for each
