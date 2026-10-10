# CLAUDE.md

NHL scoreboard for a 128×32 HUB75 LED matrix (two 64×32 P2.5 panels) on a
Raspberry Pi 4, shipped as a flashable image built by rpi-image-gen in CI.
Python app in `src/nhl_scoreboard/`; image definition in `image/`.

## Workflow

- **`main` is protected.** No direct pushes; every change is a branch and a
  pull request (`gh pr create`). CI must be green. A code-owner review is
  required, and GitHub never counts the author's own review, so PRs the
  owner authors need the admin bypass to merge.
- **GitHub Issues is the backlog.** Before starting anything new, check
  `gh issue list`; work that's already an issue should reference it. When
  you discover new work — a decision to make, a follow-up, something to
  verify on hardware — file an issue rather than leaving a TODO in code or
  a note in a commit message. Use the area labels: `display`, `hardware`,
  `image`, `audio`, `ci`, plus GitHub's `bug` / `enhancement` /
  `documentation`.
- **PRs close issues.** Put `Closes #N` in the PR body so merging closes
  the issue. One issue per PR where practical.
- **Decisions live in issues, not chat.** If a choice is waiting on the
  owner (e.g. #5, the favourite marker), the options and recommendation
  go in the issue so the next session can pick it up.
- `.github/pull_request_template.md` has the checklist: tests, lint,
  snapshot diff reviewed, docs updated.
- **`@claude` mentions trigger a cloud Claude Code run** (`.github/workflows/
  claude.yml`, `anthropics/claude-code-action`) — write `@claude` in an
  issue, a comment, or a PR review and it responds there, on GitHub's own
  runners, independent of any local session. Deliberately gated on the
  mention, not `issues: opened` alone: this repo's every-issue-gets-a-PR
  backlog flow means an agent that reacted to every filed issue unprompted
  would fight the workflow above, not help it. Bills against the Claude
  Code Pro/Max subscription, not metered API usage: needs the
  `CLAUDE_CODE_OAUTH_TOKEN` repo secret set (Settings → Secrets and
  variables → Actions), generated locally with `claude setup-token`.
- **It can run this repo's own tests and lint, and (best-effort) open its
  own PR.** The action's tag-mode default `--allowedTools` is a fixed,
  narrow list with no general Bash (confirmed by reading
  `anthropics/claude-code-action`'s own source, not assumed) — `claude.yml`
  extends it via `claude_args` to allow setting up the venv, `pytest`,
  `ruff check`/`format`, and `gh pr create`, and instructs it (via
  `--append-system-prompt`) to actually run the test/lint suite before
  claiming success and to call `gh pr create` itself for issue-triggered
  runs. That second part overrides a default that's hard-coded into the
  action's own base prompt (issue-triggered runs are told to only leave a
  compare/quick_pull link) — there's no dedicated toggle for it, so it's a
  best-effort prompt override, not guaranteed; verify it actually opened a
  PR rather than just a link before trusting it. Either way, review what
  it produces the same as any other PR — a real test run doesn't make the
  *change* correct, only that it doesn't fail the suite as written.
- **What a cloud run can actually execute, concretely.** The current
  full `--allowedTools` list lives in exactly one place --
  `claude.yml`'s own `claude_args` -- and is intentionally not
  duplicated here verbatim, since the two would drift the moment either
  changes; read that file for the exact string. In broad strokes, as of
  this writing it covers: venv setup and test/lint (`python3 -m venv`,
  `source`/`. path/to/activate`, `pip install`, `pytest`, `ruff check`,
  `ruff format`), `python3` and `nhl-scoreboard` generally plus
  `playwright install` (for rendering/screenshotting the admin page or
  demo-mode panel scenes, #153), `git fetch`/`git merge`/`gh pr view`
  (resolving a merge conflict against `main`), and
  `gh pr create`/`gh issue create`/`gh issue list`/`gh issue close`/
  `gh issue view`/`gh label list`. Deliberately **not** `Bash(gh:*)` or
  general Bash -- see `claude.yml`'s own comments for why, and extend
  the list there (one confirmed-blocked command at a time, with the
  real evidence for why) rather than assuming a tool exists because it
  would be convenient.
- **To actually reproduce CI locally or in a cloud run**, this is what
  each `ci.yml` job runs, in order -- the same commands work either
  place:
  ```bash
  python3 -m venv .venv && source .venv/bin/activate   # skip if .venv already exists
  pip install -e '.[dev]'
  pytest --cov --cov-report=term-missing   # plain `pytest` (no --cov) is fine too, just less CI-faithful
  ruff check .
  ruff format --check .
  ```
  `ci.yml` also runs a `shell` job (`shellcheck` on `scripts/*.sh` and
  the two grow-rootfs/setup-ap scripts) and a `layer-lint` job
  (`python -m py_compile image/files/scripts/scoreboard-provision` plus
  parsing the image layer YAML) -- neither is in the cloud run's
  allowlist today (no `Bash(shellcheck:*)` or general Bash), so a cloud
  run can't reproduce those two locally; they're still checked by CI
  itself on the PR regardless.

## Commands

```bash
./scripts/setup-dev.sh               # first time: .venv, dev extras, scoreboard.local.toml, logos
source .venv/bin/activate
pytest                               # 199 tests, ~1s, fully offline
pytest -s tests/test_render.py       # prints every rendered frame as ASCII
pytest --update-snapshots            # after an INTENTIONAL layout change; then review the diff
ruff check . && ruff format .        # CI runs both; an unused `noqa` fails CI (RUF100)

nhl-scoreboard --dump                                            # today's scores as text; no display
nhl-scoreboard --backend RGBMatrixEmulator -c scoreboard.local.toml   # live board at http://localhost:8888
python scripts/preview.py --fixture                              # frames as ASCII, offline
python scripts/fetch-logos.py                                    # team logos -> assets/logos/ (git-ignored)
./scripts/fetch-vendor.sh                                        # HUB75 driver source -> image/files/vendor/
```

`scoreboard.local.toml` is the git-ignored dev config. Same format as the
file the Pi reads from its boot partition (`image/files/boot/scoreboard.toml`).

## Testing conventions

- **Every rendered scene has a snapshot** in `tests/snapshots/*.txt` (ASCII,
  128 wide, full 32 rows so vertical position is fixed). Names: `text_*`
  for the abbreviation layout, `logo_*` for the logo layout, plus `clock`,
  `message_*`. A one-pixel change fails the test.
- **Snapshots alone are not enough.** Each scene also has structural
  assertions in `tests/test_render.py` (`assert_game_layout`,
  `assert_logo_layout`, `assert_indicator`, `assert_centered`): nothing
  off-panel, text centred, scores right-aligned, colours by state, favourite
  underline only where it belongs. Add both when adding a scene.
- **Tests are hermetic.** No network, no NHL artwork. Logo tests use
  synthetic circle PNGs in team colours (`synthetic_logos` fixture).
  `tests/fixtures/score.json` is a trimmed real API capture; `test_flow.py`
  builds games with its `game()` helper.
- **Time is injectable.** `ScoreboardApp(clock=..., monotonic=...)`; the
  `Clock` and `tick()` helpers in `tests/test_flow.py` walk a whole game day.
  Advancing time without `tick()`/`refresh()` trips the real 15-minute
  staleness guard and yields `no_data` — that is correct, not a bug.
- **The drawing canvas is a recorder.** `display/ascii.py` `AsciiCanvas`
  records `SetPixel` calls and out-of-bounds attempts. The emulator's
  `graphics` module is pure Python, so it draws through this canvas exactly
  as the real binding would.
- `tests/test_app.py` `FakeCanvas`/`FakeMatrix`/`FakeClient` are shared by
  `test_flow.py`. `FakeClient` records `situation_calls` and `schedule_calls`.
- **The one deliberate exception to "hermetic": `tests/e2e/`.** A real
  Chromium browser (Playwright) against a real `admin_server.py`
  subprocess serving a real `frontend/dist` build (#178 story 10's own
  follow-up) -- excluded from the default `pytest` run by a `e2e` marker
  (`pyproject.toml`'s `addopts = "-q -m 'not e2e'"`), run explicitly with
  `pytest -m e2e` after `pip install -e '.[dev,e2e]'` +
  `playwright install chromium` + building the frontend. Its own CI job
  (`ci.yml`'s `e2e`) does exactly that on every PR. Every story of the
  admin-page rebuild was verified this same way by hand, once, per story
  -- this codifies the smallest useful slice (page loads, one save
  round-trips) so a regression in the "static page + WebSocket on one
  port" mechanism itself is caught automatically instead of relying on
  that manual discipline continuing forever.

## Rendering rules

- One code path: logos and text draw through `SetPixel`; never `SetImage`.
  Hardware, emulator and tests must render identically.
- Layout constants live in the renderer and are mirrored in
  `tests/test_render.py` (`SCORE_BASELINE=13`, `RULE_Y=19`, status
  baseline `H-2`, logos 32px at each edge). Change both together. There is
  no favourite-team marker on the game scene at all -- #5 tried amber score
  digits, #33 removed them outright; don't reintroduce one without a new
  decision to do so.
- The game/goal/preview scenes are computed from `self.width`, not
  hardcoded to 128 -- but at the default 128px (two chained 64x32 panels),
  two full 32px logos leave the 64px column between them untouched, while
  on a single 64x32 panel (`chain_length = 1`) they'd meet with zero room
  left for the score column (#38). `Renderer._logo_span` handles this by
  cropping each logo's centre-facing edge -- never its outer, panel-flush
  edge -- down to half its width and no further, rather than shrinking the
  artwork to a smaller square; `Renderer._LOGO_MIN_MIDDLE` is the reserved
  middle-column width that decision is tuned against (32px, so two-digit
  scores still clear each other at 64px). Alternatives considered and
  rejected in #38: shrinking to smaller logos (loses recognisable detail
  faster than cropping does) and alternating a single full-size team per
  frame (changes the scene's information density, not just its size).
- Fonts are vendored BDF (`fonts/`): `7x13B` scores/abbrevs, `6x10` preview
  day, `5x7` status, `4x6` power-play indicator. Glyphs can have a blank
  edge column, so alignment assertions allow 1px.
- Team colours (`display/teams.py`) are LED-tuned: navy/burgundy identities
  are lifted to a brighter secondary so they don't read as black.
- Logo variant is `dark` for a reason: several teams' `light` marks are
  near-black (TOR light leaf: 67/255 luminance vs 228 for dark).
- Some official crests don't downscale legibly at 32px no matter the
  variant -- fine linework (shield stripes, letterform strokes) turns to
  mush, same failure mode regardless of colour. `display/logos.py`'s
  `default_directories()` checks `assets/logos/overrides/{size}/{variant}/`
  *before* the fetched directory for exactly this (#12); WSH is the first
  one there. That override is NOT the NHL CDN's `WSH_dark.svg` cropped
  smaller -- that endpoint serves an ornate eagle+shield+sword mark, not
  the team's actual current primary logo (the bold two-wing "W" with a
  simple eagle head). The override PNG was built from a user-supplied
  reference photo: flood-fill background removal from the image border
  inward (protects internal whites -- the eagle head, the outline stroke
  -- that aren't connected to the border, unlike a naive "remove all
  near-white pixels" threshold would), then the same crop-to-bbox +
  LANCZOS-to-32px pipeline `fetch-logos.py` already uses for every other
  team. If another team's crest needs this treatment, check whether the
  CDN is even serving their true current primary mark before assuming the
  crest itself is just "too detailed" -- verify like this one was, don't
  assume the auto-fetched SVG is right by default.

## App flow

`_select_base_scene` always tries the favourite first (`_favourite_scene`,
default favourite `NSH`): `select_scene()` picks live → final (held
`final_hold_minutes` from when the game *ended*, not from when we first
saw it final -- exact if we watched it finish, estimated from the start
time otherwise; see `Game.estimated_end`) → today's game if pregame else
next from the season schedule → countdown inside `countdown_hours`,
preview beyond. `_favourite_scene` returns `None` immediately with no
`favourite_team` configured, or falls through to the idle rotation (below)
having nothing to show -- either way the board then cycles every game
today by index, `rotate_seconds` each (#150 removed the old two-value
`rotation` ("favourite"/"all") setting that used to gate this: a future
multi-favourite "red-zone" feature needs "which game(s) currently preempt
the rotation" to be a richer question than that toggle could express, so
it was deleted rather than built on top of).

Power-play state (`situation`) is fetched from `gamecenter/{id}/landing`
**only** for the favourite's game and the on-screen game, at
`live_poll_seconds`, never during intermission. Do not widen this without
asking; it was an explicit decision.

Goal detection (`_detect_goals`) fires **only** for the favourite's own
score increasing in a game they're playing -- same scoping precedent as the
power-play indicator above, deliberate, don't widen without asking. It
drives two independent things off one detection: `GoalHornPlayer.play()`
(fires immediately, regardless of what's on screen) and a `Scene("goal", …)`
override in `select_scene()` that replaces only the exact game's normal
`"game"` scene, for `goal_flash_seconds`, and never interrupts a countdown,
preview, or a different game mid-rotation. The baseline score for a game is
recorded on first sighting *without* firing, so a game already 3-1 at
startup does not celebrate.

The `three_stars` scene (#156) is the NHL's three stars of the favourite's
game, from `gamecenter/{id}/landing`'s top-level `threeStars` (verified
present on a real final game; `NHLClient.three_stars()`, a third separate
fetch of the same URL `situation()`/`goal_scoring()` already hit). The
trigger is **not** a detector of its own: it's `refresh()`'s existing
first-time-final branch (the one that records `ended_at`), filtered to the
favourite's game and to one we actually watched go live -- a game already
final at startup is a first sighting, same "baseline without firing"
precedent as goal detection, so a restart mid-hold doesn't re-show it.
Fetching is decoupled from that transition (`refresh_three_stars()`, every
loop tick, throttled to `live_poll_seconds`) for the same reason
`refresh_goal_details()` is: `score/now` may flip to FINAL/OFF before
`landing` has named the stars (not verified either way -- the only real
payload checked was days old), so an empty result is retried until the
stars arrive, the game leaves `self.games`, or its `final_hold_minutes`
is over. Fire-once is a separate guarantee (`_three_stars_shown`, pruned
with the other per-game state, #64). It's the last layer of
`_apply_goal_override`'s chain, over the held-final `game` scene only,
for `three_stars_seconds`, then the normal final takes over. Stars are
whoever the NHL named -- either team, never filtered to the favourite.
`Star.goals`/`assists`/`points` are **per-game** totals, not
season-to-date like `GoalEvent`'s `goalsToDate`/`assistsToDate`; a
goalie's entry carries goalie stats instead (unmodelled), so it reads 0
and draws no stat. Layout: one static frame, "3 STARS" plus one tiny-font
line per star (rank, name in team colour, one stat token `2G`/`1A`/`3P`),
between the two logos like `goal_detail`; a name that doesn't fit drops
to the surname, then truncates. The one-star-per-frame alternative wasn't
needed at 128px -- only 12+ letter surnames truncate between logos.

The `standings` scene (#40) is the favourite's conference playoff picture:
`conference_standings()`/`standings_window()` (`nhl/models.py`) rank the
favourite's conference by `conferenceSequence` and trim it to the
favourite plus up to two teams on either side, clamped at either end of
the conference so a team sitting 1st or last still gets a full-size
window. Layout is Option C from #40 (favourite ± a few spots, one screen,
no pagination) -- Option A (paginate the full 8) and Option B
(favourite-centric single line) were considered and explicitly not
chosen. Suppressed entirely until the favourite's own `games_played > 0`:
`standings/now` keeps serving the just-finished season's *final* table
all through the off-season rather than an empty result (verified with a
live call while filing #40), and `games_played` is the only signal on
hand for "is this actually the current season." Only ever shown as part
of the favourite's idle rotation (below), same precedent as the
power-play indicator and goal detection above -- never in place of a live
game or a held final. Standings are polled on an hourly TTL
(`STANDINGS_TTL_SECONDS`), the same idea as `SCHEDULE_TTL_SECONDS` for the
season schedule. `clinchIndicator` values are parsed onto `StandingsRow`
but not rendered or colour-coded -- they're confirmed from only one real,
end-of-season response and not documented anywhere; don't act on them
without verifying against a few more live examples first. Note that the
window itself is a straight `conferenceSequence` cut (favourite ± a few
spots by overall conference rank), not the NHL's actual playoff line
(top 3 per division + next 2 wild cards, conference-wide) -- `StandingsRow.
in_playoff_position` already computes the real rule from `division_sequence`/
`wildcard_sequence` (both parsed, both unused by the renderer today), so a
correction wouldn't need a new API call, just wiring it in; flagged, not
yet decided on.

`_favourite_scene`'s non-live branch (`_rotate_idle_scenes`, #150) cycles
a config-driven list of screens -- `countdown_preview` (auto-switches
between countdown/preview based on `countdown_hours`, same as before;
which one shows isn't a user choice, so it isn't split into two entries),
`standings`, `clock` -- each with its own dwell time, read from an
explicit `[[rotation]]` array of tables in `scoreboard.toml`
(`config.py`'s `RotationEntry`/`_parse_rotation`). No `[[rotation]]` in
the file (`Settings.rotation == []`) falls back to `_default_rotation`,
which derives the pre-#150 list from `rotate_seconds` +
`show_standings` + `show_clock_between_games` (`show_clock_between_games`
still defaults `false`, so an upgraded board's rotation is unchanged
until the owner opts in) -- those three settings are only read for that
derivation and are ignored the moment an explicit `[[rotation]]` exists.
**That was the intent from #150 itself, but `show_standings` didn't
actually honour it until a later fix**: `_standings_scene()` also checked
`cfg.show_standings` directly, so an explicit `[[rotation]]` entry for
`"standings"` could still be silently defeated by a stale `show_standings`
value left over from before a board migrated -- caught when the owner
noticed the admin page's "Show favourite's playoff standings" checkbox
felt redundant once the Rotation section could add/remove that row
directly. Fixed by removing that live check (the gate now lives solely in
`_default_rotation`, where it belongs) and dropping the field from the
admin page's Scoreboard section (`_SCOREBOARD_FIELDS`,
`saveScoreboard`/App.tsx) -- same "received in the asdict payload, not
sent back on save" precedent `savePanel` already set for `pitch_mm`. The
TOML field itself (`scoreboard.toml`'s `show_standings`) stays, for a
board that's never touched `[[rotation]]` at all.
An entry with nothing to show for the current pass (`standings` before
`games_played > 0`, or `countdown_preview` with no upcoming game at all)
is skipped rather than shown blank; the remaining entries keep cycling.
`_rotate_idle_scenes` returns `None` only when every configured entry is
currently unavailable, at which point `_favourite_scene` returns `None`
too and `_select_base_scene` falls through to cycling today's games by
index. Unknown `screen` values and non-positive `seconds` are dropped by
`_parse_rotation` at load time (logged, never fatal, never rendered --
this repo's usual config-typo convention) so `_rotate_idle_scenes` never
has to handle an invalid entry itself. Distinct from `show_clock_when_idle`,
which only covers the unrelated "no games left to preview at all" case
(`_select_base_scene`'s fallback when `_favourite_scene` returns `None`
entirely). Admin-UI support for editing `[[rotation]]` itself is #151, not
built yet -- today it's boot-partition-TOML-only.

`matchup` (#157) is a fourth `[[rotation]]` screen and the first
**opt-in** one (`top_west`/`top_east`, #200, and `leaders`, #201, below are
opt-in too): deliberately absent from `_default_rotation`, so a board
never shows it (or calls `right-rail` at all) unless the owner lists
`{screen = "matchup", seconds = N}` explicitly. It shows the favourite's
head-to-head wins this season against the upcoming game's opponent
(`SeasonSeriesRecord`, drawn away-home like the game scene), fetched per
upcoming game id on an hourly TTL (`SEASON_SERIES_TTL_SECONDS`) with the
same backoff-on-failure as standings -- never live-polled. Skipped for
the pass (not shown blank) with no upcoming game, before the first fetch
lands, or when the API had no usable tally; `0-0` is a real answer and
does render. This is the first scene showing opponent-specific data;
that precedent covers exactly this win tally and nothing broader
(opponent leaders, injuries, etc. each need their own decision). Only the
tally ships -- individual past-meeting scores (#168) and team/player
stat leaders (#169) are separate follow-ups.

`top_west`/`top_east` (#200) are two more opt-in `[[rotation]]` screens
(also absent from `_default_rotation`): the top five teams of one
conference by `conferenceSequence`, reusing `conference_standings()`/
`_refresh_standings()` from the existing `standings` scene (#40) with no
favourite-window trimming and, by the owner's choice, no `games_played`
gate -- unlike `standings`, it just shows whatever the latest table says.
Layout (`Renderer.draw_conference_leaders`) reuses `_draw_standings_rows`
with a `"WEST"`/`"EAST"` label drawn in the logo's slot instead of the
favourite's crest, so the conference is named without costing one of the
five rows that fit; the favourite is still highlighted if it appears in
the list. **Independently built alongside `leaders` (#201) below, and
both features happened to reuse the exact same Scene kind and method name
(`"leaders"` / `_leaders_scene`)** -- merging the two PRs together is what
surfaced it: Python let the second definition silently shadow the first
with no error, and `git merge` didn't flag it as a conflict either, since
the two method bodies sat in different enough surrounding context to
auto-merge cleanly as sequential, not overlapping, hunks. Renamed this
one's Scene kind to `conference_leaders` and its method to
`_conference_leaders_scene`/`draw_conference_leaders` to resolve it --
worth remembering that a clean `git merge` (no `<<<<<<<` markers) is not
proof two independently-built features didn't collide on a name; grep for
duplicate `def`s after merging two features that touch the same area.

`leaders` (#201) is another `[[rotation]]` screen, also opt-in (absent from
`_default_rotation`): the favourite's top goal scorer, top point getter and
top two goalies by `gamesPlayed`, from `club-stats/{TEAM}/now`
(`NHLClient.club_stats()`, hourly TTL `LEADERS_TTL_SECONDS`, same backoff as
standings, cache keyed by team and reset on a favourite switch). No
minimum-games floor, by the owner's decision: ties -- everyone at zero early
on -- are broken at random once per fetch (`team_leaders()`), so the pick
holds for the TTL rather than flickering per frame. Verified live that the
endpoint returns *empty* `skaters`/`goalies` pre-season instead of last
season's table, so the screen is skipped only on empty arrays. Layout: logo
left like `standings`, tiny-font title + up to four rows. Not yet seen
against a real in-season payload; the layout snapshots (`leaders_logo`,
`leaders_text`) still need generating with `pytest --update-snapshots`.

**A live favourite-team switch used to leave this (and the countdown/
preview screen) stuck on the previous team's opponent for up to an
hour**, found live via the admin page (#178): the upcoming game handed
to `_matchup_scene` comes from `next_favourite_game()`, whose own
`self._schedule` cache is a single season schedule for whichever team it
was last fetched for, invalidated purely by `SCHEDULE_TTL_SECONDS`
elapsing -- nothing in that check knows *which* team the cached games
belong to. `_apply_reloaded_settings` (`app.py`) now explicitly resets
`self._schedule`/`self._schedule_retry_after` whenever
`scoreboard.favourite_team` changes, forcing a fresh fetch on the very
next call rather than waiting out the stale TTL. Only ever mattered for
the season-schedule fallback -- `favourite_game_today()` reads
`self.games` (today's full slate, already fetched for every team, not
favourite-scoped) fresh on every call, so a newly-favourited team with a
game *today* was never affected by this.

The physical button (#50, `button.py`, `[button]`, off by default) is one
momentary switch between a GPIO pin and GND -- GPIO 26 by default, 16 the
documented alternative, both from the verified free-pin table in Hardware
facts; don't pick another pin without re-checking that table. A short
press mutes the goal horn for `mute_minutes` (`_on_goal()` still records
the goal and shows the goal scene, it just skips `horn.play()`); a hold of
`hold_seconds` calls `advance()`. That long press is a no-op whenever the
favourite's own scene is up, since that flow never reads `self.index` --
expected, not a bug; stepping `_rotate_idle_scenes`'s time-based slots is
out of scope. Thread safety is the non-obvious part: gpiozero fires
`when_pressed`/`when_released` from its pin-monitoring thread and
`when_held` from a separate hold-timer thread, so those callbacks only set
plain bools, and `run()`'s own thread consumes them once per iteration
(`handle_button()`) and does every actual mutation -- the same rule
`admin_server.py` follows for its own thread. A long press is told
apart from a short one by a per-press "hold already fired" bool that
`when_pressed` resets and `when_released` checks, so a hold never also
counts as a tap on release. Dependency follows the light sensor's pattern:
`gpiozero` is a dev extra (tests drive the real `gpiozero.Button` through
its `MockFactory`, conftest's `mock_pins`), the image gets
`python3-gpiozero` from apt, and a missing library or unclaimable pin makes
`Button.open()` return `None`, never raise. Not yet verified on hardware
(#164, part of #4): notably, which gpiozero pin backend Debian's package picks on the
Pi, and that it coexists with the HUB75 driver's own direct GPIO access.

Boot volume (#189): `run()` starts a one-shot daemon thread
(`_apply_boot_volume`) calling `GoalHornPlayer.apply_volume()`, so a
`volume` set only in the boot TOML reaches the ALSA mixer without an admin
page visit. Off the render thread because `amixer` blocks; failures are
logged, never raised. Live reloads still apply via `admin_server.py`.

Shots on goal (#70) render in the same indicator band as the PP/EN
indicator, as a fallback when neither is active -- `_draw_situation`
(`renderer.py`) tries PP/EN first, then always falls through to
`TeamSide.sog`. Deliberately **not** a separate fetch: `TeamSide.sog`
already comes from `score/now` (verified with a real live call before
building anything -- an earlier draft of this fetched it from
`gamecenter/{id}/landing` instead, alongside situation, before that
check turned up that the score feed already had it for free), so SOG
has none of situation's scoping/caching (`situation_targets`,
`live_poll_seconds`) -- it's available for every game the app already
knows about, live or final, whether or not it's the favourite's.
`TeamSide.sog`
defaults to `0`, never `None`, so the indicator band's old "nothing to
show, draw a plain rule" case no longer exists -- `_draw_situation`
always draws something now, and the plain-rule fallback was removed
from both `_draw_game_with_logos` and `_draw_game_text`.

Night mode (#92, `[night_mode]`) dims to `dim_brightness` inside a
`start_time`-`end_time` window (local to `scoreboard.timezone`, may wrap
midnight) unless a relevant game is live or ended less than
`cooldown_minutes` ago (`self.ended_at`, same as `final_hold_minutes`).
While it's actively dimming it **wins over the ambient sensor**
(`refresh_brightness()` checks it first), deliberately: a lux sensor in a
dark TV room would dim a live game, and a lit room would keep a scheduled
window bright forever -- that's the whole argument of #92. Outside the
window the sensor behaves exactly as before; with no sensor,
`panel.brightness` is re-applied each poll, which is what restores the
panel once the window ends. `suppress_scope` is `tracked` (favourite's
game only) or `all` (any live game) -- same favourite-vs-all scoping
precedent as the power-play indicator, goal detection and standings.
`tracked` with no `favourite_team` silently behaves as `all`; that's a
valid combination (no `favourite_team` configured, with night mode on),
not a misconfiguration, so no warning. `dim_brightness = 0` is zero-power
blanking: `draw()` clears and swaps the canvas and skips scene selection
and rendering entirely, rather than trusting brightness 0 alone to be dark
on every backend. Transitions are instant; eased steps were considered and
cut, and a dim-by-default "passive mode" is #94, not this.

Holiday decorations (#236 tracking, #237 framework + Halloween,
`[holiday]`, off by default) are an **overlay, not a scene**:
`draw_scene()` draws the scene, then `HolidayOverlay.draw()`
(`display/holiday.py`) decorates the same canvas before the swap, so no
scene knows holidays exist. Each holiday is a date window in `HOLIDAYS`
(local to `scoreboard.timezone`); `themes` is just the checkbox list, never
dates. Never drawn on `goal`/`goal_detail`/`three_stars`/`ap_setup`/
`wifi_join` (`NO_OVERLAY_SCENES`) or under night-mode blanking. A fly-by
(the ghost) only *starts* on an allowed scene, after a random
`flyby_min_minutes`-`flyby_max_minutes` gap; static decorations (pumpkins)
only go on `clock`/`no_games` -- the 32px logos fill both edges of every
game/countdown/preview scene. `run()` sleeps `ANIMATION_FRAME_INTERVAL`
(50ms) only while the last frame drew something moving, `FRAME_INTERVAL`
otherwise. Demo steps carry an optional `holiday`, forced on with an
immediate fly-by and redrawn every frame for the step. The admin page's
own Holiday Cheer tab (#238) edits `[holiday]`: its checkbox list comes from
`HOLIDAYS` (sent as `available`, each with a human `window` string), so a
new holiday needs no frontend change; `_coerce_holiday` rejects unknown
themes and a min-over-max gap rather than repairing them like the TOML
loader does, and the section is sent last on connect, after the snapshot.
Each `Holiday` carries its own `Flyby` (frames, palette, speed,
`align` "middle" to float or "bottom" to walk) and `corners` draw
function, so adding one is a registry entry, not overlay code.
Thanksgiving (#239) is two entries sharing the turkey/leaves art: US
(`thanksgiving`, the 7 days up to the 4th Thursday of November) and
Canadian (`thanksgiving_ca`, Fri through the 2nd Monday of October,
`default_on=False` so it isn't ticked unasked -- `DEFAULT_THEMES`).
Overlaps go to the higher `Holiday.priority` (registry order is just
calendar/checkbox order): `thanksgiving_ca` has priority 1 and takes its
long weekend over from `halloween`, by the owner's call; kept to a long
weekend so it displaces as little of Halloween as possible. Christmas
(#240, Dec 1-26): Santa walks the bottom edge and drops presents behind
him (`Flyby.drops`/`drop_spacing`/`drop_column`, a pure function of
distance travelled; `linger_seconds` keeps the pass -- and the fast loop
-- alive a moment after he's gone so the trail is seen); `corners` draws
present stacks plus snow. Snow falls only in a `SNOW_BAND` at each edge:
the real panel can't report which pixels the clock text lit, so flakes
can't weave around it, and they're slow enough (1.5-3 px/s) for the
normal 2fps loop -- a month of snow never holds the fast loop on.
New Year's (#241, Dec 31-Jan 1, the one window that wraps the year) is
the first mover that isn't a sprite crossing: `Fireworks` (staggered
`Rocket`s that rise, then burst into an outer ring plus a lighter inner
one) implements the same `draw(canvas, elapsed, w, h) -> bool` contract as
`Flyby`, so `HolidayOverlay` schedules either without knowing which.
Sparks stop drawing below `MIN_SPARK_FADE` rather than fading to near-
black -- a linear fade left dark holes over logos in a rendered preview.
Corners are champagne flutes plus confetti that twinkles at 2fps (no fast
loop), in the same edge bands as the snow. Valentine's (#242, Feb 7-14):
a beating heart floats across (two frames, full and squeezed), and two
beat out of step beside the clock at 2fps. The flying heart is outlined
(`_outlined`, pale pink) -- a plain red heart vanished crossing a red team
logo in a rendered preview; any red/white-on-anything sprite added later
should get the same check. Groundhog Day (#247, Feb 2) adds a third
mover kind, `Popup` (rises out of a mound, looks left/right, then either
startles at a dark silhouette and ducks, or stays and sinks), and is the
one holiday that needs the date: shadow-or-not is `random.Random(year)`,
so `HolidayOverlay.draw(day=...)` threads the board's local date through
to every mover's `draw` and every `corners` function (ignored by the
rest); the clock shows a sun (shadow, six more weeks) or a cloud. Holiday *screens* (a Christmas
tree, as a `[[rotation]]` entry) are #243.

April Fools' (#248, `april_fools.py`) is an Easter egg for the owners'
own Predators boards, **not** a holiday overlay and deliberately **not** a
Holiday Cheer checkbox or gated on `[holiday]` (owner's call): with
`favourite_team = "NSH"`, on April 1 before noon local time, NSH becomes
MIL (the Milwaukee Admirals, the Preds' AHL affiliate) on the
`countdown`/`preview`/`matchup`/`standings`/`leaders`/`clock`/`no_games`
screens (`PRANK_SCENES`), and the standings drop them to the bottom of the
conference winless with 0 points -- or, if they really are last, to the top
unbeaten -- so the screen never shows their true spot. **Never** on `game`,
`goal`, `goal_detail` or `three_stars`: April 1 is late-season, and a
relabelled live game reads as a bug. The swap happens in `draw_scene()`
(scene's game, the `favourite` passed to the renderer) except the standings
reorder, which needs the whole conference and so lives in
`_standings_scene()`. The Admirals logo is a committed override
(`assets/logos/overrides/32/dark/MIL.png`, owner-supplied reference image,
same flood-fill/largest-component/crop/LANCZOS pipeline as WSH -- the
largest-component step dropped the ™ mark); its colours live in
`display/teams.py`'s `GUEST_COLORS`, deliberately not `TEAM_COLORS`, which
drives logo fetching and horn-upload keys. Left out of README.md on purpose.

Demo mode (#47, `nhl-scoreboard --demo`) loops every scene with synthetic
data (`demo.py`'s `demo_steps()`, built through `Game.from_api()` etc.
like the tests) at `DEMO_SCENE_SECONDS` each, until Ctrl-C. `run_demo()`
deliberately bypasses the real state machine -- no `select_scene()`,
`refresh()`, situation/brightness sampling, config reload or NHL client
call -- and hands synthetic `Scene`s straight to `draw_scene()` (the
dispatch half of `draw()`, split out for this). Coercing real game data
into every state on demand isn't possible, and a bench board may have no
network. It never plays the goal horn: only `refresh()`'s
`_detect_goals()` reaches `_on_goal()`, and `draw_scene()`'s goal branch
only draws. Both layouts are shown by toggling `renderer.logos` per step
between the configured library and `None` (text fallback), restored on
exit; with `show_logos = false` every step is just text.

## NHL API notes

- `api-web.nhle.com/v1/score/now` 307-redirects to `/score/{date}`; follow it.
- `score/now`'s per-team objects include `sog` (shots on goal) directly --
  no extra fetch needed for that (#70). It has no *special-teams* data
  though: `gamecenter/{id}/landing` has a `situation` object **only
  while something is on** (PP / EN / PS); absent at even strength.
  4-on-4 arrives as a situation but is not an advantage.
- `club-schedule-season/{TEAM}/now` is ~180KB for the season; cached 1h.
- Team logo URLs are per-team in the score payload; the pattern is
  `assets.nhle.com/logos/nhl/svg/{ABBR}_{light|dark}.svg`.
- Game states seen: `FUT PRE LIVE CRIT FINAL OFF`.
- `gamecenter/{id}/right-rail` (#157, a different endpoint from
  `landing`) has `seasonSeriesWins: {awayTeamWins, homeTeamWins}` --
  oriented to *that game's own* away/home (verified: the same NSH-CGY
  series reads `0-3` from a game NSH hosted, `3-0` from one it played
  away), season-to-date across completed regular-season meetings only
  (every meeting's right-rail shows the same total, not a running count),
  OT/SO wins counted as wins, `0-0` all through the preseason. No team
  abbreviations on that object; pair it with the `Game` it was fetched
  for. `seasonSeries[]` lists every meeting: completed ones carry
  `awayTeam.score`/`homeTeam.score` and `gameOutcome.lastPeriodType`
  (`REG`/`OT`, plus `otPeriods`), future ones have no scores -- verified
  against real 2025-26 responses but not parsed or shown yet (#168). No stat
  leaders here: `teamGameStats` is per-game aggregates (shots, PP,
  penalties), not leaders.
- `clock.inIntermission` lags the period actually ending -- confirmed
  against a real live game (NSH @ CAR, 2026-09-24) sitting at
  `timeRemaining: "00:00"`, `running: false`, `inIntermission: false` for
  well over one `live_poll_seconds` cycle, on both `score/now` and
  `gamecenter/{id}/landing`, not just a one-frame flicker. `Game.
  in_intermission` (`nhl/models.py`) now infers intermission itself from
  `timeRemaining == "00:00" and not running` whenever the flag hasn't
  caught up, gated on the game actually being live (`LIVE`/`CRIT`) --
  a `FINAL`/`OFF` game's clock sits at `00:00`/not-running too, and is
  not an intermission, so the state check matters, not just the clock
  values. This one field feeds the status label text, the status colour
  (`_status_color`, checks `in_intermission` *before* `is_final`), the
  situation-poll skip, and `poll_interval()`'s slowdown -- fixed once at
  the parse site rather than patched separately at each read site.

## Hardware facts (verified, don't relearn)

- Adapter board (Seengreat / XICOOLEE / WatangTech) is the driver's
  `regular` mapping, pin for pin. OE on GPIO 18 = hardware PWM without the
  Adafruit solder mod. It back-powers the Pi: **one** supply, into the
  board's barrel jack; nothing into the Pi's USB-C.
- **A wrong `hardware_mapping` is a silent failure, not an error** --
  verified on real hardware (an Adafruit RGB Matrix Bonnet left on the
  shipped `"regular"` default): `nhl-scoreboard.service` starts, stays
  active, keeps polling the NHL API, logs nothing wrong -- it is just
  driving the wrong physical GPIO pins for that adapter, so the panel
  stays completely dark with zero diagnostic signal anywhere
  (`systemctl status`/`journalctl` both look completely healthy).
  Switching to `"adafruit-hat"` (no other change) fixed it immediately.
  `[panel]` settings including `hardware_mapping` don't hot-reload
  (baked into the constructed `RGBMatrix`) -- a restart is required
  after changing it, not just a config save. First thing to check on a
  dark panel with an otherwise-healthy service.
- `dtparam=audio=off` and `isolcpus=3` are required; the HUB75 driver and
  onboard audio share the PWM peripheral. Audio → USB. Not the 3.5mm jack,
  not I2S -- **the actual conflict is GPIO 18** (OE, hardware PWM per the
  bullet above), which is also the Pi's native I2S PCM clock pin. A
  previous version of this note said "GPIO 21 is LAT" -- that was wrong
  (see the pin table below) and has been corrected; the practical advice
  (don't enable I2S) was right regardless.
- **Full `regular`-mapping GPIO pin table, confirmed against the exact
  vendored commit** (`scripts/fetch-vendor.sh`'s pinned `MATRIX_REF`),
  not the library's docs/wiki, which can drift from what's actually
  pinned -- read the pinned commit's `lib/hardware-mapping.c` struct
  literally rather than trust prose:
  OE=18, CLK=17, Strobe/LAT=4, address A-E=22/23/24/25/15,
  chain-0 RGB (both sub-panel rows)=R1:11 G1:27 B1:7 R2:8 G2:9 B2:10.
  That's every pin this driver claims at `parallel=1` (this project's
  config) -- also confirmed by reading `lib/framebuffer.cc`'s
  `InitGPIO`, which only ORs chain-1/chain-2 pins into the claimed-pins
  bitmask when `parallel >= 2`/`>= 3` respectively, so those pins are
  never touched at `parallel=1` regardless of what the mapping struct
  lists for them. Genuinely free GPIOs on the 40-pin header at this
  project's config: 5, 6, 12, 13, 14, 16, 19, 20, 21, 26 (2/3 are taken
  by the BH1750 sensor's I2C bus, #44) -- 14/15 are the UART pair (15
  already claimed above), so prefer 26 or 16 for anything new (e.g.
  #50's button) over 14, same "pick an unremarkable pin" reasoning that
  put the sensor on 2/3.
- Pixel pitch (`pitch_mm`) is informational; the driver never sees it.
- Panel spec sheet (the actual purchased hardware): 64×32 / 2048 dots,
  160×80mm at P2.5, 1R1G1B, ≥140° viewing angle, 1/16 scan, HUB75 header,
  ≤12W at 5V/2.5A per panel (fed through the adapter board's VH4 header,
  not the Pi). 1/16 scan is the standard scan rate for a 32-row panel --
  matches `PanelConfig`'s `rows=32` default with no multiplexing/
  `row_address_type` override needed. Two panels chained (`chain_length=2`
  default) means a ~24W supply budget, not 12W -- size accordingly.
- The goal horn's default siren (`assets/horns/_default.wav`) is committed
  to the repo, unlike logos or the HUB75 driver source: it's synthesized
  (`scripts/generate-default-horn.py`, stdlib `wave`, no external assets),
  so there's no third-party content to keep out of the repo and no fetch
  step needed. Team-specific horns (`{ABBR}.wav`) are a user drop-in slot,
  same reasoning as logos not being redistributed -- but those, if a user
  supplies them, are never committed either.
- **Horn uploads (#193)**: the admin page's Audio tab uploads a WAV for
  `default` (`_default.wav`) or one `TEAM_COLORS` abbreviation, over the
  existing WebSocket as base64 (`upload_horn`; `max_size` raised to fit the
  2 MB `HORN_MAX_BYTES` cap) rather than a new HTTP POST path -- the file
  name is never client-supplied, only a validated team key. Files land in
  `/var/lib/nhl-scoreboard/horns` (`audio.upload_directory()`, persistent
  across reflash/update, unlike `/usr/share`), which `default_directories()`
  searches before the image-baked directory. Not verified on hardware (#4);
  deleting an upload back to the shipped horn is not built.

## Image build facts (each cost a failed CI run)

- rpi-image-gen builds **Debian**, not Raspberry Pi OS. Imager's "OS
  customisation" dialog does nothing here; settings come from
  `scoreboard.toml` on the FAT boot partition, applied every boot by
  `scoreboard-provision.service`.
- Runs on `ubuntu-24.04-arm` (native arm64, free for public repos).
  `install_deps.sh` calls `apt install` without `apt-get update`; we update
  first.
- `device.user1pass` must satisfy upper/lower/digit/symbol/8+.
  `user1sudo` ∈ {none, passwd, nopasswd}. `sudo` must not appear in
  `user1groups`.
- HUB75 bindings build via upstream's CMake/scikit-build-core at the repo
  root (`pip install .`). **Not** `bindings/python` (gone) and **not**
  `make -C lib` (its `-march=native` would target the CI runner's CPU, not
  a Pi 4). Needs `python3-pil` for `Imaging.h`.
- The build toolchain (`build-essential`, `cmake`, `ninja-build`,
  `cython3`, `python3-dev`, `python3-pip`) is purged after compiling
  the bindings, in the same hook, which re-imports `rgbmatrix` right
  after the purge as its own test -- a purge that broke something fails
  the build there rather than shipping it. `python3-pil` is NOT purged:
  unlike the others it's a genuine runtime dependency
  (`display/logos.py` imports `PIL.Image` to decode team logos), not
  just a build-time one. Also keep `libpython3.13` explicit in the
  package list: the compiled extension links against it directly
  (CMake's `Development.Embed` component links the way an embedding
  host would, not the usual dlopen-and-resolve style most C extensions
  use), which is an ELF dependency `apt` cannot see -- purging
  `python3-dev` alone swept it via `--auto-remove` and broke the image
  (`ImportError: libpython3.13.so.1.0`) even though the required test
  suite was entirely green. This is *why* `nhl-scoreboard.img` is now a
  required check (below): the self-verifying import check in the hook
  caught it correctly, but nothing gated the merge on that check having
  run at all.
- Wi-Fi is **iwd**, not NetworkManager. DHCP `.network` files are already
  generated by the base layers; don't add more (first match wins).
- Locate the image in `work/image-<name>/`; never `find | head` under
  `pipefail`.
- Read failed logs with `gh run view <id> --log-failed` (gh is authed).
  Unauthenticated, only annotations are readable; the workflow republishes
  the failure tail as one.
- Builds queue rather than cancel (`cancel-in-progress: false`) — a doc
  push once cancelled a finished 12-minute build mid-compress.
- Team logos are `actions/cache`d across runs (keyed on `fetch-logos.py`
  + `display/teams.py`), skipping the whole rasterise step on a hit.
  Confirmed genuinely working across two consecutive runs (real
  `Cache hit for:` + `Cache restored from key:` + the step showing
  `skipped`), ~9-11s saved.
- **`sys.apt_cachedir` (caching APT downloads for the target rootfs) was
  tried and does NOT work, despite being correctly wired -- don't
  re-attempt this without new information.** It's a genuine
  rpi-image-gen feature (`layer/base/sys-build-base.yaml`, confirmed via
  the tool's own source; override syntax confirmed against
  `examples/setoptions`: the full `IGconf_sys_apt_cachedir=<path>` form
  after `--`, not dotted notation). Wired up correctly by every check
  available from outside the tool: `sys-build-base` active in our layer
  chain (confirmed in our own build log), the bind-mount setup-hook
  genuinely executes (`mount --bind '<cache>' "$1/var/cache/apt/archives"`
  visible in the log), a real permission bug in the cache-*save* step
  found and fixed along the way (`tar: apt-cache/partial: Cannot open:
  Permission denied` -- needs `sudo chmod -R a+rX` before
  `actions/cache`'s post-job save, since apt writes `partial/` as root
  inside its own namespace; `actions/cache` treats a failed save as a
  warning, not a job failure, so this shipped silently once already).
  None of that mattered: after two consecutive runs, GitHub's cache
  genuinely restored (`Cache hit for:` + `Cache restored from key:`,
  no tar error) into a directory that rpi-image-gen itself then reported
  as `Apt cache: 0 pkgs` -- confirmed via the caches API too (306 bytes
  saved total, nowhere near real `.deb` content). The bind-mount
  executes; something later in bdebstrap's own multi-phase pipeline
  (separate essential/bootstrap vs customize chroot sessions, possibly)
  never actually writes packages through it. Diagnosing further means
  reading bdebstrap's own internals, not this repo's config -- out of
  scope for what this project needs. Removed from the workflow rather
  than shipped as inert complexity that looks like it's helping.
- `nhl-scoreboard.img` is a **required status check** on `main`, and
  `build-image.yml` runs on `pull_request` (unconditionally at the
  trigger level) with the actual path-relevance check done *inside* the
  workflow, as a job-level `if:` gated by a `changes` job. Do not move
  that filtering back to `on: push: paths:` for `pull_request` — a
  required check whose *workflow* never triggers for a PR blocks that
  PR's merge forever (GitHub shows "Pending", not "skipped"/"passed");
  only a job skipped via `if:` reports as passing. This is not
  theoretical: #21 merged with every required check green and broke the
  real build (see the `libpython3.13` entry above) because back then
  `Build image` only ran *after* merge, so nothing had actually gated it.
  A PR run also skips compression and the artifact upload (`if:
  github.event_name != 'pull_request'` on those two steps) -- it only
  needs to prove the build succeeds, not produce a distributable image,
  and compression alone was ~85s of an otherwise sub-minute job.
- `release.yml` tags and releases **every merge to `main`** automatically
  (CalVer: `vYYYY.MM.DD`, `.1`/`.2`… same-day suffix). `pyproject.toml`'s
  `version` is deliberately NOT kept in sync -- doing so would need a
  commit to the protected `main` branch (a PR, or a bypass-capable bot
  identity), which tags avoid entirely since `refs/tags/*` isn't covered
  by the branch ruleset. Pushing that tag with `GITHUB_TOKEN` does **not**
  trigger `build-image.yml`'s own `tags: ["v*"]` push trigger -- GitHub
  doesn't cascade workflow runs from events the built-in token caused, to
  prevent recursion -- so `release.yml` explicitly invokes
  `build-image.yml` via `workflow_dispatch` (the documented exception:
  always fires, any token) once the tag and release exist. Don't try to
  make the tag-push trigger do this instead; it structurally cannot.
  Verified this precisely against GitHub's own docs before relying on it,
  not assumed. Tension worth knowing: #9 wanted the *first* persisted
  release gated on #4 (real hardware verified) -- this workflow has no
  such gate, so merging it is itself what fires the first automatic
  release, whenever that happens to be. That `workflow_dispatch` call
  needs `actions: write` in `release.yml`'s own `permissions:` block --
  `contents: write` alone is not enough and fails with "403: Resource
  not accessible by integration". Separately, `build-image.yml` needs
  its *own* `contents: write` for the "Attach image to release" step
  (`softprops/action-gh-release`) to update the release and upload
  assets -- a completely different permissions gap on a different
  workflow's token, not the same bug twice. Neither was theoretical:
  the first release this workflow ever created (`v2026.09.22`) hit both
  of them back to back -- tag and release created fine, the dispatch
  call failed on the first gap, a manual `gh workflow run` retry then
  hit the second. Both fixed; if a *third* release-pipeline permission
  gap ever turns up, check every workflow's token separately rather
  than assume they share one `permissions:` block -- they don't, each
  workflow's `GITHUB_TOKEN` is scoped by its own file.
- `build-image.yml` has no `push: branches: [main]` trigger, deliberately
  removed once `release.yml` existed: that trigger produced an untagged,
  14-day-expiring build on every relevant merge, immediately superseded
  by the tag-triggered build `release.yml` fires moments later for the
  same commit. Pure waste once every merge gets auto-released. Do not
  add it back "to keep main green" -- `pull_request` already gates
  merges on a real build (see above); nothing still needs a build to
  fire on the merge itself. `tags: ["v*"]` stays, unfiltered by path
  now (it used to share `push:`'s `paths:` list with the removed
  branch trigger) -- a human pushing a real release tag by hand should
  get a build regardless of what changed.

## WiFi AP + captive-portal setup mode (#131)

Infrastructure phase only, sub-issue of #116 -- gets a phone able to reach
the board at all when it has no working network yet, plus (#132) the
nearby-network scan `nhl-scoreboard-setup-ap` caches for the setup page to
render as a picker. The setup page itself lives in `setup_server.py` (see
the "WiFi setup page" section below); wiring a submission into the
credential-submission/rollback flow is #133, not done anywhere yet.

- **Trigger condition** (`image/files/scripts/nhl-scoreboard-setup-ap`,
  `cmd_check`/`is_online`): "has a default route", checked with
  `ip route show default`, not "no `[wifi]` configured" -- scoreboard-
  provision's `apply_wifi()` already treats a bare config as "relying on
  ethernet" and does nothing, so re-checking that here would needlessly
  pop an AP on every ethernet-only boot. A default route is used instead
  of matching specific interface names (eth0 vs enp0s0 vs a USB dongle
  vary by hardware) -- it is also exactly what the app itself needs to
  reach `api-web.nhle.com`, so "no default route" and "board can't do its
  job" are the same condition. `nhl-scoreboard-setup-ap.service` orders
  itself `After=scoreboard-provision.service`, which already blocks up to
  its own `WIFI_CONNECT_TIMEOUT` resolving any configured Wi-Fi (connect,
  or roll back) before returning -- so by the time this script runs, that
  outcome is already settled and it needs no wait/retry loop of its own.
- **AP mode is iwd's own** (`net.connman.iwd.AccessPoint`, via `iwctl ap`),
  not hostapd -- this image already depends on iwd (`CLAUDE.md`: "Wi-Fi is
  iwd, not NetworkManager"), so this adds no second WiFi daemon. iwd's AP
  support only handles the 802.11 side; it does not assign the interface
  an IP or hand out leases, so the script still sets a static IP itself
  (`10.42.0.1/24` by default) before calling `iwctl ap`.
- **`iwctl ap <dev> start-open`** (an open, unencrypted network) is tried
  first, falling back to a fixed-passphrase WPA2-PSK network if that
  fails. **Not verified against real hardware or a known iwd version**
  (#4) -- start-open needs a newer iwd than could be confirmed against
  whatever this image's Debian release actually ships without a real
  board to check. Treat the open-network path as the intended default,
  not a confirmed one, until it's checked on hardware.
- **dnsmasq is a genuinely new dependency** (`image/layer/nhl-scoreboard.
  yaml`), added for DHCP leases + wildcard DNS (`address=/#/<ap-addr>`, so
  every hostname a phone's OS probes resolves to the board -- that's what
  actually triggers the OS's captive-portal prompt). Flagged here as a
  real tradeoff per #131, not snuck in quietly -- the project has
  otherwise stuck to stdlib/essential packages. Its own `dnsmasq.service`
  is masked at image-build time (a plain `ln -sf /dev/null` symlink, the
  same thing `systemctl mask` itself creates -- not `systemctl mask`
  directly, since there's no running init inside the mmdebstrap chroot for
  it to talk to): only the scoped instance `nhl-scoreboard-setup-ap`
  starts directly, `--conf-file`'d and `bind-interfaces`'d to the AP
  interface only, ever runs.
- **No self-monitoring teardown loop.** A WiFi radio cannot be an AP and a
  station at the same time, so there is nothing meaningful for this
  script to poll for on its own interface once the AP is up. `stop` (also
  run from `ExecStopPost`, so it fires however the service is asked to
  end) is meant to be driven by #133's submission flow once *it* confirms
  a real network joined -- not by this script guessing.
- Tested the same way as `nhl-scoreboard-grow-rootfs`/`scoreboard-
  provision`: the real script, run as a subprocess, with `ip`/`iwctl`/
  `dnsmasq`/`logger` faked on the PATH (`tests/test_setup_ap.py`). What
  that does *not* prove: that `start-open` exists, that a real phone shows
  a captive-portal prompt for the result, or that iwd AP mode and dnsmasq
  actually cooperate on a real radio -- all #4.
- CI's `shell` job (`.github/workflows/ci.yml`) does not yet shellcheck
  this script -- adding it needs a change to a workflow file, which is
  outside this change's own write access; tracked as a follow-up rather
  than silently skipped.
- **Nearby-network scan** (#132, `scan_networks`/`parse_networks`): runs
  `iwctl station <dev> scan` + `get-networks` itself, still in station
  mode, immediately before the `Mode ap` switch above, and caches the
  result as a JSON array of unique SSIDs to
  `/run/nhl-scoreboard-setup-ap-networks.json`
  (`NHL_SCOREBOARD_AP_SCAN_FILE`). Has to happen here and only here: this
  chip can't scan while its own AP is active (see the next section for
  why), so once `Mode ap` is set there is no later point at which a scan
  would even be possible. `parse_networks` is an awk script that anchors
  on the one thing iwctl's plain-text table reliably ends each data row
  with -- a security token (`open`/`psk`/`8021x`/`wep`) followed by
  asterisks -- rather than fixed column positions, which shift with
  whatever the longest nearby SSID happens to be. Same "not verified
  against real hardware" caveat as the rest of this script (#4): a format
  mismatch degrades to an empty cached list, never a script failure --
  covered by `tests/test_setup_ap.py`'s scan tests with a synthetic table,
  not a real `iwctl` binary.

## WiFi setup page + captive-portal probe handling (#132)

The other half of #132 -- "what does a phone see once it's on the AP" --
now that #131 (AP reachability) and #141 (the panel's own join QR code)
are merged. Scope is strictly the page and captive-portal probe handling;
actually joining the chosen network is #133, not built yet.

- **No live scan, by design.** Verified live and corroborated against
  real-hardware reports on this board's exact brcmfmac chip family (see
  #132's own issue comments): the chip cannot scan for nearby networks
  while its own AP is active (`iwctl station wlan0 get-networks`/`scan`
  both fail with "No station on device" once `Mode` is switched to `ap`)
  -- default brcmfmac is single-interface, and the documented `apsta=1`
  concurrent AP+STA workaround is reported to crash this exact chip's
  firmware under concurrent use, so it is not being pursued. The setup
  page instead renders whatever the previous section's cached scan
  contains -- a snapshot from moments before the AP came up, not a live
  list.
- **Text entry is never hidden behind the picker.** That cached scan can
  miss a network that's out of range at that exact instant,
  hidden/non-broadcasting, or one that only appears afterward, with no way
  to rescan short of restarting the whole setup-ap cycle. `setup_server.
  py`'s page always renders a plain SSID text field alongside the picker,
  not as a fallback to remove later; on submit, a non-empty manual entry
  (`ssid_other`) wins over whatever radio button (`ssid_choice`) happens
  to still be selected.
- **A new stdlib module, not a new systemd service.** `setup_server.py`
  is `http.server`-based, no dependencies -- the pattern the original
  `status_server.py` used too, before it was replaced by `admin_server.py`
  (#178 story 10; unlike that page, `setup_server.py` genuinely must work
  offline, so it stays stdlib-only on principle, not just by inheritance)
  -- and is started/stopped by `ScoreboardApp` itself
  (`_sync_setup_server()`, called once per `run()` loop tick), gated on
  nothing but whether `nhl-scoreboard-setup-ap`'s own state file exists --
  the same signal `_ap_setup_scene` already keys off of for the panel's QR
  scene. `nhl-scoreboard.service` already runs as root and already polls
  that file every frame, so this needed no new unit, no new packaging, and
  no new privilege: binding `wifi_setup.port`'s default of 80 needs root,
  which the service already has.
- **Port 80, not `status.port`'s 8080.** Captive-portal probes (Apple's
  `/hotspot-detect.html`, Android's `/generate_204`, Windows NCSI's
  `/connecttest.txt`/`/ncsi.txt`) ask for plain HTTP on the well-known
  port by a fixed hostname; dnsmasq's wildcard DNS (`address=/#/<ap-addr>`,
  #131) only gets those requests as far as this board's IP -- the port
  still has to be the one the probe actually asks for, or the request
  never reaches this server at all.
- **Every non-setup-page GET gets a 302 to `/`, not just the three named
  probes.** Wildcard DNS means literally any hostname a phone's OS decides
  to probe resolves here, so enumerating only the three documented probes
  and 404ing everything else would still fail to pop the prompt for
  anything not on that list -- the redirect is a deliberate catch-all,
  with the three named probes only special-cased for a debug log line. A
  relative `Location: /` is enough: it resolves against whatever host the
  client thinks it just asked, which is fine, since wildcard DNS already
  points that host back at this board.
- **This module never touches iwd/iwctl.** On submit it writes
  `{"ssid": ..., "password": ...}` to
  `/run/nhl-scoreboard-setup-submission.json` (`ap_submission_state_path`,
  atomic tmp+replace, same convention as `Settings.save()`) and nothing
  else -- that file is the hand-off point for #133's still-unbuilt join
  flow, not consumed by anything yet. `password` is `None` for an open
  network, matching the `open`/`password` distinction the AP's own state
  file (#131) already makes.
- Per #132's own issue text, captive-portal auto-popup is "the single most
  fragile part of the whole idea" -- inconsistent across iOS/Android/
  desktop, and sometimes doesn't fire at all, no matter how this is
  implemented. #141's panel QR code is the reliable fallback: it gets a
  phone onto the AP without depending on captive-portal detection firing
  at all, and this page is reachable by typing its fixed address manually
  regardless of whether the "Sign in to network" prompt ever appears.

## Wiring the setup page's submission into a real join (#133)

Closes the loop #131/#132 leave open: turning a submitted SSID/password
into an actual network join, safely, with the AP setup flow's own
first-time-user constraints -- not #51's original boot-time-only
assumptions.

- **`apply_wifi()` moved from `scoreboard-provision` into
  `nhl_scoreboard/wifi.py`**, an importable module, so both the boot-time
  caller and this live join flow call the exact same tested join/rollback
  path instead of two implementations of "try new credentials, roll back
  on failure." `scoreboard-provision` itself now just parses `[wifi]` out
  of the TOML and hands it off -- the 26 existing subprocess-level tests in
  `tests/test_scoreboard_provision.py` needed zero changes after this
  move, since they exercise behaviour through the script's own CLI
  boundary, not where the code physically lives.
- **`apply_wifi()` now returns `bool`** (`True` for an already-current
  profile or a genuine new success, `False` only when a real attempt was
  made and the network never came up) -- the boot-time caller still
  ignores it, but the live join flow needs to know which panel message and
  which of "drop the AP" / "bring it back" to do next.
- **The panel is the feedback channel, not the HTTP response** (decided
  directly in #133's own issue discussion, not assumed): attempting the
  join means switching the radio out of `Mode ap`, which tears down the AP
  the phone's setup-page request arrived over -- killing that connection
  before any response describing success/failure could reach it.
  `wifi_join.py`'s `WifiJoinAttempt` writes a state file
  (`/run/nhl-scoreboard-wifi-join-state.json`) with `attempting`/
  `connected`/`failed`, read by `_wifi_join_scene()` the same way #141's
  `_ap_setup_scene()` already reads its own -- and given **top** priority
  in `select_scene()`, even over `ap_setup`: a failed attempt restarts
  `nhl-scoreboard-setup-ap`, which recreates its own state file underneath
  the still-counting-down "Failed..." message, and that message has to win
  until its own display window (`OUTCOME_DISPLAY_SECONDS`, 15s) elapses.
- **The join runs on a background thread**, off `ScoreboardApp.run()`'s own
  loop -- `WifiJoinAttempt.poll()` is called every frame and must never
  block; a real attempt can take up to `connect_timeout_seconds` (90s by
  default), and freezing score polling/rendering for that long would
  defeat the point of a scoreboard that's still trying to show something
  during setup.
- **A failed join restarts AP mode** (also decided directly, not a
  judgment call left to whoever built this) so the person can reconnect
  and retry from the same phone -- treated as the *expected* retry path,
  not a rare edge case, which matters given the real-hardware finding
  below.
- **The AP is only ever stopped/started via `systemctl {stop,start}
  nhl-scoreboard-setup-ap.service`** (#173), never by running the
  setup-ap script directly. `start` ends in `exec dnsmasq`, so dnsmasq is
  the unit's Main PID; the original direct-script call tore the radio down
  under it without systemd ever stopping the unit, orphaning dnsmasq behind
  a unit that stayed "active" forever while `wlan0` was genuinely down
  (diagnosed live on a Pi 3B+). `systemctl stop` kills the tracked process
  and runs the unit's own `ExecStopPost` teardown. A non-zero `systemctl`
  exit is logged as a warning, not ignored. The script itself also retries
  each `iwctl ap ... start*` once before giving up on that mode -- a
  defensive guard against this chip's known transient mode-switching
  failures, not proven to eliminate them (#4).
- **`[wifi] connect_timeout_seconds`** (default 90, matching
  `nhl_scoreboard.wifi`'s own `WIFI_CONNECT_TIMEOUT` default) is a real
  `WifiConfig` dataclass field now, exposed properly instead of left as the
  `NHL_SCOREBOARD_WIFI_TIMEOUT` env var (still there, still the underlying
  default, but that one's for tests/low-level overrides, not something a
  real user would find). `ssid`/`password`/`country` stay deliberately
  unmodelled in `WifiConfig` -- `scoreboard-provision` reads those straight
  out of raw TOML (predates this dataclass) and nothing else needs typed
  access to them; `Settings.from_dict` filters the raw `[wifi]` dict down
  to just `connect_timeout_seconds` before handing it to `_build()`, so
  those three don't trip its "unknown key" warning on every single load.
- **Real-hardware risk, not yet re-verified after this landed**: repeated
  rapid AP start/stop/mode-switch cycling (manual testing during #132's own
  investigation) put this board's radio into a bad state once --
  `iwctl ap <dev> start` failing with `START_AP failed: -22` and
  `Could not register frame watch type ...: -114` in `iwd`'s own log,
  recovered only by backing off / a clean boot. Given the decision above
  that failure-then-retry is the expected path, not an edge case, this
  needs real-hardware testing of *that specific path* (submit bad
  credentials, confirm the AP comes back, retry, repeat a few times) before
  trusting it, not just the happy path -- #4, same as everything else here
  that needs a Pi.

## Admin page frontend (React, deployed to the device -- #178)

The old status/config page (`status_server.py`, HTML-forms-with-full-page-
POST) has been replaced with a real React frontend + WebSocket live
updates, and as of Story 10 it's the page that actually ships and starts
on boot -- `status_server.py` is deleted. Tracked issue #178 has the full
design, phasing, and decisions (Vite, TypeScript, incremental rollout,
WebSocket kept scoped to update-check/apply progress and save-without-
reload, plus a read-only status snapshot -- not live game/score data,
and not a channel for pushing scene changes to the panel itself). Built
as vertical slices, one story at a time. **The server module was renamed
`ws_server.py` -> `admin_server.py` in Story 10**, once it started serving
the built static page too, not just a WebSocket -- every story below
before Story 10 refers to it by its old name, describing what was true
when it was written; that history is left as-is rather than rewritten.

- **Story 1 (done): prove the pipeline end to end.** `frontend/` (a Vite +
  React + TypeScript SPA, `frontend/README.md` has the exact run commands)
  connects over a real WebSocket to `src/nhl_scoreboard/ws_server.py` (a
  new, minimal `websockets`-based server) and displays one real piece of
  app state -- the installed version, the same value
  `updater.installed_version()` already provides the admin page's status
  grid. Deliberately narrow: local-dev only, not started by
  `ScoreboardApp`, not wired into the image build or any systemd unit, one
  message on connect and nothing further. `websockets` lives in
  `pyproject.toml`'s `dev` extras, not `[project]` dependencies, until a
  later story actually deploys this -- confirmed live that
  `python3-websockets` (15.0.1-1) is a real apt package on this image's
  Debian release for when that day comes, so it'll follow the same
  apt-not-pip pattern as everything else on the device.
- **status_server.py's own "no client-side JS" framing was corrected
  first (#177)**: it was never actually required to work offline the way
  `setup_server.py`'s captive-portal page genuinely is (that page *is* the
  mechanism for getting the board online at all; the admin page's whole
  purpose only makes sense once the board already has real connectivity).
  That correction is what cleared the way for this -- `setup_server.py`
  itself is explicitly out of scope for any of this and stays exactly as
  it is.
- **Story 2 (done): the first real section, Audio.** Chosen deliberately
  as the smallest section (`enabled`/`device`/`horn_dir`, 3 fields) to
  prove the read/edit/save round trip before a bigger one. `ws_server.py`
  now sends the current `[audio]` values on connect (via `Settings.load`,
  same as `status_server.py`) and handles a `save` message the same way
  `status_server.py`'s `/save` POST does -- write into a throwaway
  `Settings` instance, reload fresh from disk afterward, never mutate
  anything in memory (this process has no live `ScoreboardApp` to mutate
  anyway). Validation is hardcoded to Audio's own 3 fields, not
  generalised over `status_server.py`'s `_Field`/`_coerce_section` shape
  -- one section isn't enough evidence yet for what the right shared
  abstraction is; that's a later story's job once a second section shows
  the actual pattern, not before. Verified with a real headless-browser
  interaction (not just unit tests): unchecked the box, typed a device
  string, clicked Save, watched "Saved." appear with zero page reload --
  the actual thing this whole rebuild is for.
- **Story 3 (done): the idle rotation list (`[[rotation]]`, #150/#151).**
  Unlike Audio (fixed scalar fields), this is an ordered, variable-length
  list -- `config.py`'s own `Settings.save()` already special-cases
  `"rotation"` to replace the whole list rather than patch keys (see its
  docstring), so `ws_server.py` just validates the incoming list the same
  way `config.py`'s `_parse_rotation` does (unknown screen, non-positive
  seconds) and passes it through -- except a live save rejects the whole
  list on the first bad row instead of silently dropping it, since a
  person editing this page should see exactly what's wrong, unlike a
  hand-edited boot TOML where a typo must not stop the board booting.
  Also enforces the same row cap `status_server.py`'s HTML version
  recommended (`ROTATION_MAX_ROWS = 8`), server-side, not just via the
  frontend disabling its own button. **The numeric "order" field and the
  full-page-round-trip add/remove buttons in the HTML version existed
  specifically to work around having no client-side JS (#151) -- gone
  here.** Row order is just the list's own order now; the frontend does
  real add/remove/reorder (↑/↓ swap-with-neighbour) in local state, one
  Save sends the whole list. Verified with a real headless-browser
  interaction: added three rows, edited two, removed one, reordered the
  remaining two, saved, and confirmed the file on disk matched exactly
  (right screens, right seconds, right order) -- not just that the UI
  looked right.
- **Story 4 (done): Reboot and Software update.** The first two things
  that are actions on the real system rather than config file edits, and
  the first real use of *push* rather than request/response --
  `updater.check()`/`apply()` run out of process (the real
  `nhl-scoreboard-update-{now,apply}.service` units `status_server.py`
  already triggers via `systemctl start --no-block`, not reimplemented
  here) and write `updater.STATE_FILE` on their own schedule, with no way
  for this process to know when except by watching for it -- exactly the
  "click Check, refresh manually to see if anything changed" gap this
  whole rebuild started from. `_watch_update_state` polls that file's
  mtime and broadcasts a fresh `config`/`update` message to *every*
  connected client the moment it changes -- the first thing here that
  isn't scoped to the one connection that asked. Reboot has no such
  watch: the board going down *is* the confirmation, and nothing is left
  running to report back once it does. Verified two ways: a real headless-
  browser click-through with the real `systemctl` shadowed by a fake
  binary on `PATH` (logging its args instead of running -- confirmed the
  exact right unit names got called, and confirmed the real one was never
  touched), and, separately, writing straight to the state file with zero
  clicks at all to prove the actual point -- the page updated itself
  (installed/latest/checked-at, the Install button appearing) with no
  user action whatsoever, which is the literal thing this rebuild was
  for.
- **Story 5 (done): Scoreboard, 16 fields -- the biggest section, and
  the moment to actually generalise.** Every earlier entry here said
  hardcoding each section was deliberate because one or two sections
  wasn't enough evidence for the right shared shape; Scoreboard is that
  third data point, and it's the same bool/str/float/select shape Audio
  already had, just five times the field count. `_FieldSpec` +
  `_AUDIO_FIELDS`/`_SCOREBOARD_FIELDS` replace the old one-off
  `_coerce_audio` with a generic `_coerce_scalar_fields`, used by both
  sections now (`[[rotation]]` stays its own thing -- a variable-length
  list was never the same shape). Also exposes `goal_detail_seconds`
  and `three_stars_seconds` (#122, #156), which were never actually
  added to `status_server.py`'s own HTML form -- a real, small gap in
  the page this is replacing, fixed in passing rather than carried
  forward. Verified with a real headless-browser interaction: edited
  `favourite_team`, unchecked `show_logos`, changed `logo_variant`,
  edited a timing field, saved, and confirmed both the re-rendered form
  (read back from the live DOM, not just component state) and the file
  on disk matched exactly.
- **Story 6 (done): Status page, `enabled`/`port`.** The smallest
  section after Audio, and the first `"int"` field -- `_FieldSpec`
  gained that kind (`port` must be a whole number, not `8080.5`;
  everything before this had been bool/str/float). Otherwise nothing
  new: straight application of the `_coerce_scalar_fields` pattern
  Scoreboard's story already proved out. Placed after Audio, matching
  `status_server.py`'s own section order. Verified with a real
  headless-browser interaction: changed the port, saved, confirmed
  "Saved." with the new value both in the live DOM and on disk.
- **Story 7 (done): Panel -- 17 fields, the biggest section yet** (every
  `PanelConfig` field except `pitch_mm`, which `status_server.py`'s own
  form has never exposed either -- informational only, the driver never
  reads it, per the Rendering rules note above). First real use of a new
  `_FieldSpec.restart_required` flag: 12 of the 17 fields are baked into
  the constructed `RGBMatrix` and only take effect after
  `nhl-scoreboard.service` restarts (see the "wrong hardware_mapping is a
  silent failure" hardware note); only the five brightness-related fields
  (`brightness`, `auto_brightness`, `min_brightness`, `max_brightness`,
  `brightness_poll_seconds`) hot-apply. The flag is informational for the
  frontend to badge -- it doesn't change validation, same idea as
  `status_server.py`'s own per-field `restart_required`. Also the second
  real use of the `"select"` kind (`hardware_mapping`, `rgb_sequence`),
  after `logo_variant` in Scoreboard. The frontend groups the 17 fields
  into three subheadings (Geometry, Driver/PWM, Brightness), badging the
  two restart-required groups -- the natural tie-in to the Reboot card
  two sections down, which is literally what those fields need after a
  save. Verified with a real headless-browser interaction: edited one
  field of each kind (int, select ×2, bool, str, float), saved, confirmed
  the live DOM reflected every change, and confirmed
  `scoreboard.local.toml` on disk matched exactly -- including that
  `pitch_mm`, never sent, was untouched.
- **Story 8 (done): Night mode (#92) -- 6 fields, none
  `restart_required`** (night mode is polled live, nothing here is baked
  into a constructed object the way Panel's fields are). The first
  section whose payload can't be a blind `dataclasses.asdict()` of the
  settings dataclass: `NightModeConfig` carries derived `start`/`end`
  fields (`datetime.time`, `field(init=False)`, parsed once from
  `start_time`/`end_time` in `__post_init__` so the app never re-parses
  the strings itself) that aren't JSON-serialisable and were never a
  value a person sets directly -- `_night_mode_payload` builds the dict
  by hand instead, naming only the 6 editable fields, rather than
  extending `_coerce_scalar_fields`'s asdict-based send helpers to cope
  with a non-serialisable field. Otherwise a plain `_coerce_scalar_fields`
  section: `start_time`/`end_time` are validated only as strings, not
  against the `HH:MM` format -- same as everywhere else in this project,
  `_parse_hhmm` (config.py) already warns and falls back to a default on
  a bad value rather than rejecting it, so there's nothing here for the
  live editor to additionally enforce. Verified with a real
  headless-browser interaction: toggled `enabled`, edited both times,
  changed `dim_brightness`, switched `suppress_scope` to `all`, edited
  `cooldown_minutes`, saved, confirmed the live DOM and
  `scoreboard.local.toml` on disk matched exactly.
- **Story 9 (done): Wi-Fi -- the smallest section yet, one field**
  (`connect_timeout_seconds`). `ssid`/`password`/`country` live in the
  same `[wifi]` TOML table but are deliberately not modelled by
  `WifiConfig` at all (`config.py`'s own `_wifi_config` filters them out
  before `_build()` sees them) -- actually joining a network is
  `setup_server.py`'s job, the offline-first captive-portal page, out of
  scope for this whole rebuild (see the note right after Story 1). A
  save here only ever patches `connect_timeout_seconds`, matching
  `Settings.save()`'s own per-key patching -- verified with a real
  headless-browser interaction against a dev config with no `[wifi]`
  table at all yet (the boot-partition template ships without one):
  changed the timeout, saved, confirmed the new table was created on
  disk with exactly that one key, and confirmed with `ssid`/`password`
  already present in the file (a real-world case, since scoreboard-
  provision writes those from a completed setup flow) that a save
  doesn't disturb them.
- **Story 10 (done): deploy to the real device, retire `status_server.py`.**
  The owner's own call, made live in conversation after trying Story 9's
  build locally ("we can delete the old site, and make this the one that
  starts on boot now"), with two follow-up decisions surfaced and
  confirmed before touching anything: port the status snapshot into the
  new page first (below), and continue on the same PR rather than filing
  a new issue. Three things landed together:
  1. **One port serves the built React page and the WebSocket.**
     `websockets`' own `process_request` hook (confirmed present in the
     pinned `websockets>=13`, tested directly against 17.1 before relying
     on it) intercepts every request; a genuine WebSocket upgrade
     (`Upgrade: websocket` -- what a real browser's `new WebSocket(...)`
     always sends, checked directly rather than assumed) is let through
     to the existing handler, anything else is served as a static file
     out of `ADMIN_DIR` (`/usr/share/nhl-scoreboard/admin` on the device,
     same directory-env-var pattern as fonts' `NHL_SCOREBOARD_FONT_DIR`),
     falling back to `index.html` for this single-page app's one route.
     No reverse proxy, no second port. `frontend/dist` is a CI build
     product now (`build-image.yml`'s new "Build admin frontend" step,
     `actions/setup-node` + `npm ci` + `npm run build`, right before the
     image build itself) that the image layer's own `customize-hooks`
     copies in exactly the way team logos already are -- Node never
     touches the device.
  2. **`AdminServer` wraps the server on a background thread**, exposing
     the same `start()`/`stop()`/`port` shape `StatusServer` had, so
     `app.py`'s integration is a small diff at the same three call sites
     `StatusServer` was built/started/stopped/rebuilt from (`__init__`,
     `run()`, `reload_config_if_changed()`), not a rewrite of
     `ScoreboardApp` itself. `StatusServer` ran a blocking `http.server`
     loop in a plain thread; `AdminServer` runs its own `asyncio` loop in
     the thread instead, signalling `stop()` via
     `asyncio.run_coroutine_threadsafe` rather than an OS-level shutdown
     call. `[status]`'s `enabled`/`port` fields are reused as-is -- same
     TOML section, same meaning, just a different implementation
     underneath; an existing board's boot-partition config needed no
     migration.
  3. **The status snapshot moved over too, not just the config editor.**
     `status_server.py` served two genuinely different things:
     `ScoreboardApp.status_snapshot()` (scene, current game, last poll,
     last error -- read-only "headless debugging" state, found during
     this story's own investigation, not something #178's earlier stories
     had touched) alongside the HTML-forms editor. Dropping the snapshot
     too would have been a real regression for anyone debugging a board
     with no HDMI output, so a new "Board status" section (rendered
     generically, key by key, same as `status_server.py`'s old
     `.stat-grid`) ships in the same story. `SNAPSHOT_PROVIDER` is the
     same "handed to it as a callable" relationship `StatusServer`'s own
     `snapshot` parameter had; broadcast on change (`_watch_snapshot`),
     same proven shape as `_watch_update_state`.

  **Wi-Fi `ssid`/`password`/`country` editing did *not* carry over** --
  explicitly dropped, a real decision surfaced and confirmed before
  deleting `status_server.py`, not an oversight: that page's Wi-Fi
  section had raw-TOML fields (unrelated to `WifiConfig`) that restarted
  `scoreboard-provision.service` on save, letting an already-online board
  switch networks directly from the admin page. The AP/captive-portal
  flow (#131-#133) is now the one way to (re)join a network -- it covers
  the far more common "board has no network yet" case with a real retry/
  rollback state machine that the old direct-edit path never had.
  Changing an already-online board's Wi-Fi now means walking it through
  that flow (e.g. by disconnecting it) rather than editing a field here.

  Verified two ways, since this story has no #4-style real-hardware
  check available: a full local production-mode run (`npm run build`,
  then `admin_server.py` pointed at the built `dist/` with
  `NHL_SCOREBOARD_ADMIN_DIR`, no Vite involved at all) -- confirmed the
  built page loads, a save round-trips, and the WebSocket still works on
  the same port a static GET does; and the normal Vite-dev-server pass
  used for every earlier story. **Not verified on real hardware** (no Pi
  in this session) -- flagged the same way every other real-hardware-only
  gap in this project is (see `image/layer/nhl-scoreboard.yaml`'s own
  `python3-websockets` addition and CLAUDE.md's Image build facts).
- **Follow-up, same day: the manual verification above is now a real CI
  job.** `tests/e2e/test_admin_page_smoke.py` + `ci.yml`'s `e2e` job do
  the same "browser against a built page + a save round trip" check on
  every PR -- see Testing conventions' own note on it. Doesn't replace
  real-hardware verification (#4), just catches a regression in the
  static-page-plus-WebSocket-on-one-port mechanism itself before it ships.
- **Follow-up (#185): the in-app updater redeploys the frontend too.**
  `build-app-bundle.py` adds `frontend/dist` to the one release bundle as
  a top-level `admin/` (when built -- `build-image.yml` builds it before
  the bundle step), so the existing sha256 covers it and the page can't
  lag the backend. `updater.apply()` stages it beside `ADMIN_DIR`, swaps
  it in by rename with the app tree, and restores the old one on
  rollback. A bundle with no `admin/` leaves the page untouched. One
  version signal for both: they always ship together.
- Not yet decided or built: the JSON-API-vs-WebSocket-for-everything
  question (every save/action so far has gone straight over the existing
  WebSocket connection rather than a separate HTTP endpoint -- worth
  confirming that's still the right call once something needs a shape
  this doesn't fit as naturally), and real-hardware verification of
  Story 10 itself (#4).

## Disk-destructive code (grow-rootfs)

`image/files/scripts/nhl-scoreboard-grow-rootfs` edits a live partition
table on the user's SD card. Getting it wrong bricks the card, not just
the app -- treat any change to it with the care that implies, not the
same bar as everything else in this repo.

- It is a **deliberate copy of `raspi-config`'s `do_expand_rootfs`**
  (`RPi-Distro/raspi-config`), not an original design -- that script is
  what every stock Raspberry Pi OS image has used for years. If you think
  you've found a better way (e.g. an online BLKPG resize with no reboot),
  check upstream did not already reject it before assuming it's safe;
  don't improvise here.
- The technique: grow the partition table entry (`sfdisk`) with the start
  sector explicitly unchanged -- this only rewrites sector 0, never
  touches the filesystem's data, but the running kernel has already
  cached the old table and only re-reads a fresh one at boot, hence the
  two-phase design across a `systemctl reboot`.
- Non-negotiable safety checks, present for a reason, do not remove:
  refuses unless the root partition is the **last** partition on the disk
  (otherwise growing it would overwrite whatever comes after); the start
  sector is passed back to `sfdisk` explicitly, never recomputed.
- MBR only. GPT has a backup header at the end of the disk that would
  also need relocating; this script does not attempt that, and this
  image's layout (`image/mbr/simple_dual`) is MBR, so it doesn't need to.
- `tests/test_grow_rootfs.py`: the actual script, run for real against a
  faked toolchain (every external command it touches is a recording
  fake) -- catches shell logic bugs and confirms the safety checks
  actually refuse when they should. When touching this script,
  mutation-test the change the way the start-sector assertion was
  verified: deliberately break the thing the test is supposed to catch
  and confirm it fails before trusting it passes.
- **Was disabled #121-#129, re-enabled by #129.** A real Pi 4 first boot
  once never came up at all (no DHCP lease on wifi *or* ethernet, LED
  matrix never showed anything, `sudo fdisk`/Disk Management from another
  machine showed the root partition still at its original shipped size --
  the `sfdisk` grow never even landed), which #121 responded to by
  commenting out `image/layer/nhl-scoreboard.yaml`'s `enable-units` call
  for this service as a precaution. #120's own investigation later found
  the actual cause was an outdated SPI EEPROM bootloader on that specific
  board (misreporting RAM size) -- unrelated to this repo or to
  grow-rootfs, confirmed because a board with grow-rootfs already
  disabled still failed to boot the same way before the EEPROM was
  reflashed. So the hang was never actually observed independent of the
  EEPROM issue; #4's hardware-verification checklist having this box
  checked with zero corroborating detail (no `journalctl` excerpt,
  nothing) was never real evidence either way. #129 re-enabled the
  `enable-units` line on that basis.
- **Confirmed against a real resize-and-reboot cycle on hardware,
  2026-09-28 (#129)** -- and it did NOT work out of the box, catching two
  real bugs neither `tests/test_grow_rootfs.py`'s faked toolchain nor CI
  could have caught:
  1. `findmnt / -o source -n` reported `/dev/disk/by-slot/system` on this
     board's OS, not a `/dev/mmcblk0pN`-style path. The script's
     `PART_NUM=$(echo "$ROOT_PART" | grep -o '[0-9]*$')` silently produced
     an empty string against that alias, which never matched
     `LAST_PART_NUM`, tripping the "not the last partition" safety refusal
     -- even though the partition genuinely was last -- and permanently
     marking the done-marker on exit 0 with the table never touched.
     Fixed by canonicalising with `readlink -f` before extracting the
     partition number, whatever alias `findmnt` hands back.
  2. **`sfdisk` genuinely was not installed on the image at all.** Debian
     split `fdisk`/`sfdisk`/`cfdisk` out of `util-linux` into their own
     `fdisk` package a while back (confirmed live: `dpkg -S sfdisk` found
     nothing, `apt-cache policy fdisk` showed `Installed: (none)`); the
     apt package list's own comment wrongly assumed util-linux always
     carries it. Fixed by adding `fdisk` to `image/layer/nhl-scoreboard.
     yaml`'s packages. Without it, stage 1 would fail every single boot
     forever (`sfdisk: command not found`, exit 127, the *retryable*
     failure path -- never a hang, just a partition that never grows).
  With both fixed, verified live: `nhl-scoreboard-grow-rootfs.service`
  ran stage 1 (`sfdisk`, reboot), then stage 2 automatically on the next
  boot (`resize2fs`), root partition went from 2.5G to 29.5G on a 29.7G
  card, and `nhl-scoreboard.service` came back up fine afterward. If a
  real board ever hangs or fails to grow again with this enabled, that's
  new evidence of a *different* bug, not this one -- capture it
  (HDMI console, `journalctl`) before changing anything, per #129.

## Enclosure (OpenSCAD) changes

Every change to a `.scad` file in `enclosure/` follows this path, no
exceptions, so a printed case can always be matched to its source and
the repo always shows what the current model looks like:

1. Make the design change in **both** `scoreboard-case-v3.scad` and
   `scoreboard-case-v3-pi3b.scad` unless it is deliberately
   variant-specific (they differ only in `pi_model`; say so in the PR if
   a change is applied to one only). `legs/scoreboard-legs.scad` (the glue-on
   legs) is a third model file with no Pi variant; `scripts/enclosure.sh`
   versions, renders and exports it with the others, and its STL is a single
   leg (`legs/scoreboard-legs-leg.stl`; print four).
2. Run `scripts/enclosure.sh all` (add `major` for a redesign, e.g. a
   new case generation; the default minor bump is right for everything
   else). It bumps `case_version` in every model file together, then
   re-renders a PNG of each model beside it
   (`enclosure/scoreboard-case-v3.png`, `...-pi3b.png`) and exports the
   printable halves as STLs beside it too
   (`scoreboard-case-v3-left.stl`, `-right.stl`, the `-pi3b` pair, and
   `legs/scoreboard-legs-leg.stl`).
   Needs `openscad`; the whole run takes about a minute.
   Never edit `case_version` by hand; the script refuses to run if the
   files have drifted apart.
3. `case_version` is printed as raised text on the inside of the back
   wall (`version_label()`), with the repo URL and board variant, so no
   extra step is needed for it to appear on the part.
4. The STL export in step 2 doubles as the compile check: it fails the
   script if either half doesn't export. For a closer look, run `openscad
   -D 'part="left"' -o /tmp/l.stl <file>` and confirm "Simple: yes".
5. Look at the regenerated PNG (not just that it exists): confirm the
   thing you changed is actually visible and right.
6. Commit the `.scad` changes, the version bump, the PNGs and the STLs together,
   and note the new version in the PR body. Update `enclosure/README.md`
   if the change alters what it describes.

**The STLs and PNGs are generated artifacts that must always match the
committed `.scad` files**: someone slices the STL straight from the repo,
so a stale one prints the wrong case. So:

- Never hand-edit or hand-export them; only `scripts/enclosure.sh`
  writes them. A PR that changes a `.scad` file without the regenerated
  STLs and PNGs is incomplete.
- Before committing, check `git status`: after any `.scad` change all
  four STLs (`*-left.stl`, `*-right.stl` for both variants) should show
  as modified, along with both PNGs. If an STL did not change, the
  change did not reach the geometry; confirm that is really the case
  (e.g. a variant-specific edit leaves the other variant's STL alone).
- If you rebase or merge and the `.scad` files, STLs or PNGs conflict,
  resolve the `.scad` conflict by hand, then re-run
  `scripts/enclosure.sh render` and `scripts/enclosure.sh stl` (not
  `all`, which would bump the version again) rather than picking one
  side's binary files. Do this too after merging another enclosure PR,
  even when git reports no conflict: the merged `.scad` may differ from
  both parents' STLs.
- If you find the committed STLs out of date with the `.scad` files
  (e.g. someone edited a `.scad` by hand), regenerate them in a PR of
  their own and say why.

## Config conventions

- Unknown keys in `scoreboard.toml` **warn and are ignored**, never fatal:
  a typo must not stop the board booting. Invalid `[[rotation]]` entries
  (#150) follow the same convention: dropped with a warning, never fatal,
  never rendered on the panel.
- Defaults are the Predators, `regular` mapping, 128×32, Central time
  (America/Chicago). Anything can be overridden in the toml.
- With no `favourite_team` configured, the board falls through to cycling
  every game today by index -- there is no longer a separate `rotation`
  setting to degrade (removed by #150).

## Style

- ruff, line length 100, rules `E F W I N UP B SIM RUF`. CamelCase methods
  that mirror the C++ binding (`SetPixel`, `Clear`, `SwapOnVSync`) carry
  `# noqa: N802`. Only add `noqa` for enabled rules.
- Commit messages explain *why*; the first line under ~65 chars. Include
  what a failed CI run taught if that's what drove the change.
- Match the surrounding comment density; comments say why, not what.
