# College football: the working loop

How an unattended session works the college football backlog (epics #532-#538) one issue at a time:
branch, build, test, open a PR, wait for CI, merge, pick up the next. Read this whole file first;
a session starts with no memory of the ones before it.

The integration branch is **`college-football`**. `main` is protected and is never touched by this
loop (a person merges `college-football` into `main` after seeing it work on a board).

## The queue

The order lives in the tracking issue titled **"College football: loop queue"** (the one labelled
`cfb-queue`). Read it first. It lists, in order, the issues that are ready, and the ones held.

| Label | Meaning | The loop |
|---|---|---|
| `cfb-ready` | Unambiguous, testable offline | Work it |
| `cfb-hold-owner` | Needs the owner's design decision | Skip; never guess |
| `cfb-hold-live` | Needs a real game in progress | Skip |
| `cfb-blocked` | A previous attempt stalled (see its PR) | Skip |

Work the first open `cfb-ready` issue in the queue whose blockers (named in its body) are closed.
A session works **at most 4 issues**, then stops and posts a summary on the queue issue.

If, while working, an issue turns out to need a decision, **stop that issue**: comment with the
options and your recommendation, label it `cfb-hold-owner`, remove `cfb-ready`, and take the next.
Do not make the design call.

## Per issue

1. **Fresh start.** `git fetch origin`, then `git checkout -b cfb/<issue>-<slug> origin/college-football`.
   Set up once per session: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
2. **Read** the issue, its epic, `CLAUDE.md`'s football sections, `football_api.md`, and the code you
   will touch. Reuse what exists (the football director, scenes, `FootballMode`, the college
   modules under `src/scoreboard/football/college_*.py` and `upset.py`).
3. **Build it with tests** in the repo's style: hermetic (fixtures in `tests/fixtures/football/`,
   no network), a snapshot per rendered scene plus structural assertions, and for anything the
   owner will look at, a mockup (below).
4. **Mutation-check** the logic you added: break it on purpose, confirm a test fails, restore.
   Rules that bit us: set `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` first; restore from a
   copy; ruff reformats code, so a mutation's search text may not match (check it applied); a test
   that loops forever when the code is broken needs a bound so it fails fast.
5. **Run the full suite and read the exit code**, not `tail`: `pytest -q -n auto -p no:warnings >
   out.txt 2>&1; echo exit=$?` (it takes over two minutes; run it in the background). Then
   `ruff check . && ruff format --check .`.
6. **Commit** with a message that explains why, and the trailers the harness gives you. One issue per
   PR. **Push without force** (`git push -u origin <branch>`).
7. **Open the PR into `college-football`** using `.github/pull_request_template.md`. Say what changed,
   why, the checks, what was mutation-tested (and any survivor, explained), and `Closes #N`
   in a way that works: the PR does not target `main`, so GitHub will not close the issue; you close it.
8. **Wait for CI without polling:** `subscribe_pr_activity` for the PR, then end your turn; the
   result wakes you. Never `sleep` in a loop.
9. **Merge only when green.** Green means **every check run is `success` for the PR's head commit**
   (`get_check_runs`; confirm the run's `head_sha` is the latest push). Then merge with a merge
   commit (`merge_method: merge`). `scoreboard.img` (the image build) can take ~5 minutes; wait for it.
10. **If CI is red:** read the failing job (`get_job_logs`), fix on the same branch, run the suite
    locally, push, and wait again. After **3 failed attempts**, stop: comment on the PR with what
    failed and what you tried, label the issue `cfb-blocked`, and move on. Never skip, disable or
    delete a test to get green; never `--no-verify`.
11. **After the merge:** close the issue (`state_reason: completed`), tick its line in the epic, and
    start the next issue from a fresh `origin/college-football` (do not stack branches: merging
    first means no conflicts).

## Mockups: the owner watches

Anything visual (a screen, a badge, a layout) gets a mockup so the owner can see it without a board:

- Add or extend a function in `scripts/college-mockups.py` for the screen (real FBS teams, real
  colours, the real renderer, LED-dot PNGs), run it, and **look at the images yourself** (read the
  PNG): collisions and unreadable text only show up when seen. Two real bugs were found this way.
- Commit the images in `docs/college/` with the PR and name them in the PR body.
- Review new `tests/snapshots/*.txt` by eye too; a snapshot test passing only proves it matches
  what you wrote.

## Never

- Push to `main`, merge into `main`, or merge a PR whose base is not `college-football`.
- Force-push or rewrite history on a shared branch.
- Change hockey or NFL behaviour (their tests must pass unchanged), the image definition,
  `.github/workflows/`, or `release.yml`, unless the issue is explicitly about that: file an issue
  instead.
- Use `rm -rf` or `rm` with an unquoted variable (the harness blocks it): use literal paths.
- Put secrets, the owner's name or email, or model identifiers in commits, PRs or code.
- Guess a design decision or a rule the issue leaves open. (A small numeric default that is easy to
  change, such as a turn length, is fine **if it is a setting**, is stated in the PR body under
  "Defaults I chose", and the issue says "decided and documented". Anything that changes what the
  board shows in a way the owner has not seen in a mockup is a decision.)
- Treat a test you cannot make pass as a reason to weaken it: stop and report.

## Live game nights

Some issues (#558 live verification, #562 red zone) need a real game. They stay `cfb-hold-live`
until a person starts a session for a game. For that:

```bash
python scripts/capture-college-live.py <espn_event_id> --out captures/<name>
```

records the compact per-poll log (`observations.jsonl`), the status changes (`transitions.log`) and
gzip'd raw payloads, polling the way the board does. Find the event id in the scoreboard URL or
`football_api.md`'s endpoint. What to look for is the checklist in #558. Turn what is learned into
fixtures and `football_api.md` findings, then unblock the dependent issues.

## Reporting

After each merge, a one-line comment on the epic issue. At the end of a session, a summary on the
queue issue: what merged (PR numbers), what is blocked and why, what needs the owner.
