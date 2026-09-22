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

## Commands

```bash
source .venv/bin/activate            # python3 -m venv .venv && pip install -e '.[dev]' first time
pytest                               # 93 tests, ~1s, fully offline
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
  `tests/test_render.py` (`SCORE_BASELINE=13`, `RULE_Y=19`,
  `UNDERLINE_Y=15`, status baseline `H-2`, logos 32px at each edge).
  Change both together.
- Fonts are vendored BDF (`fonts/`): `7x13B` scores/abbrevs, `6x10` preview
  day, `5x7` status, `4x6` power-play indicator. Glyphs can have a blank
  edge column, so alignment assertions allow 1px.
- Team colours (`display/teams.py`) are LED-tuned: navy/burgundy identities
  are lifted to a brighter secondary so they don't read as black.
- Logo variant is `dark` for a reason: several teams' `light` marks are
  near-black (TOR light leaf: 67/255 luminance vs 228 for dark).

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

## NHL API notes

- `api-web.nhle.com/v1/score/now` 307-redirects to `/score/{date}`; follow it.
- `score/now` has no special-teams data. `gamecenter/{id}/landing` has a
  `situation` object **only while something is on** (PP / EN / PS);
  absent at even strength. 4-on-4 arrives as a situation but is not an
  advantage.
- `club-schedule-season/{TEAM}/now` is ~180KB for the season; cached 1h.
- Team logo URLs are per-team in the score payload; the pattern is
  `assets.nhle.com/logos/nhl/svg/{ABBR}_{light|dark}.svg`.
- Game states seen: `FUT PRE LIVE CRIT FINAL OFF`.

## Hardware facts (verified, don't relearn)

- Adapter board (Seengreat / XICOOLEE / WatangTech) is the driver's
  `regular` mapping, pin for pin. OE on GPIO 18 = hardware PWM without the
  Adafruit solder mod. It back-powers the Pi: **one** supply, into the
  board's barrel jack; nothing into the Pi's USB-C.
- `dtparam=audio=off` and `isolcpus=3` are required; the HUB75 driver and
  onboard audio share the PWM peripheral. Audio → USB. Not the 3.5mm jack,
  not I2S (GPIO 21 is LAT).
- Pixel pitch (`pitch_mm`) is informational; the driver never sees it.
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
  release, whenever that happens to be.

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
