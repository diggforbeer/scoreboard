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

## Commands

```bash
source .venv/bin/activate            # python3 -m venv .venv && pip install -e '.[dev]' first time
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

`rotation = "favourite"` (default, `NSH`): `select_scene()` picks live →
final (held `final_hold_minutes` from when the game *ended*, not from when
we first saw it final -- exact if we watched it finish, estimated from the
start time otherwise; see `Game.estimated_end`) → today's game if pregame
else next from the season schedule → countdown inside `countdown_hours`,
preview beyond. Falls back to `all` rotation if there is no favourite game
or the schedule fetch fails. `rotation = "all"` cycles every game today,
`rotate_seconds` each.

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
hand for "is this actually the current season." Only scoped to
`rotation = "favourite"`, same precedent as the power-play indicator and
goal detection above -- shown interleaved with the preview/countdown
scene, alternating on `rotate_seconds`' own cadence, never in place of a
live game or a held final. Standings are polled on an hourly TTL
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

`_favourite_scene`'s non-live branch (`_rotate_idle_scenes`) cycles
countdown/preview, standings (when shown) and, opt-in via
`show_clock_between_games` (default `false`), the idle clock -- same
`rotate_seconds` cadence as the standings alternation, now generalised
over a list instead of a single `% 2`. Off by default so existing
installs see no change; distinct from `show_clock_when_idle`, which only
covers the unrelated "no games left to preview at all" case (`_select_
base_scene`'s fallback when `_favourite_scene` returns `None` entirely).

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
knows about, live or final, in either rotation mode. `TeamSide.sog`
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
valid combination (`rotation = "all"` with night mode on), not a
misconfiguration, so no warning. `dim_brightness = 0` is zero-power
blanking: `draw()` clears and swaps the canvas and skips scene selection
and rendering entirely, rather than trusting brightness 0 alone to be dark
on every backend. Transitions are instant; eased steps were considered and
cut, and a dim-by-default "passive mode" is #94, not this.

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
- `dtparam=audio=off` and `isolcpus=3` are required; the HUB75 driver and
  onboard audio share the PWM peripheral. Audio → USB. Not the 3.5mm jack,
  not I2S (GPIO 21 is LAT).
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
- **Cannot be verified without real hardware** (tracked in #4, same as
  everything else that needs a Pi). What *is* tested,
  `tests/test_grow_rootfs.py`: the actual script, run for real against a
  faked toolchain (every external command it touches is a recording
  fake) -- this catches shell logic bugs and confirms the safety checks
  actually refuse when they should, but cannot confirm `sfdisk`/
  `resize2fs` behave as expected against a real disk. When touching this
  script, mutation-test the change the way the start-sector assertion
  was verified: deliberately break the thing the test is supposed to
  catch and confirm it fails before trusting it passes.
- **DISABLED as of #120** -- not removed, just not wired to run. A real
  Pi 4 first boot never came up at all (no DHCP lease on wifi *or*
  ethernet, LED matrix never showed anything, `sudo fdisk`/Disk Management
  from another machine showed the root partition still at its original
  shipped size -- the `sfdisk` grow never even landed) on hardware that
  the owner says previously booted fine, before this unit existed. #4's
  hardware-verification checklist had this box checked with zero
  corroborating detail (no `journalctl` excerpt, nothing) -- don't trust
  that checkmark as confirmation this ever actually worked on real
  hardware; treat it as unverified until #120 finds the real cause.
  `image/layer/nhl-scoreboard.yaml`'s `enable-units` call for this
  service is commented out, so freshly built images boot on their
  original small root partition (a real but survivable inconvenience --
  less disk headroom, not a bricked board) until this is resolved. Don't
  re-enable it without addressing #120 first.

## Config conventions

- Unknown keys in `scoreboard.toml` **warn and are ignored**, never fatal:
  a typo must not stop the board booting.
- Defaults are the Predators, favourite rotation, `regular` mapping,
  128×32, Central time (America/Chicago). Anything can be overridden in the toml.
- `rotation = "favourite"` with no `favourite_team` degrades to `all`.

## Style

- ruff, line length 100, rules `E F W I N UP B SIM RUF`. CamelCase methods
  that mirror the C++ binding (`SetPixel`, `Clear`, `SwapOnVSync`) carry
  `# noqa: N802`. Only add `noqa` for enabled rules.
- Commit messages explain *why*; the first line under ~65 chars. Include
  what a failed CI run taught if that's what drove the change.
- Match the surrounding comment density; comments say why, not what.
