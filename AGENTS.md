# AGENTS.md — Conventions for AI agents working in this repo

This file is the entry point for any AI agent (pi sessions, Archon workflows,
review bots) operating in `animal-counter`. Read it before running anything.

The project is a **pig counter** running on a Jetson Orin Nano in K3s.
Counting logic is OC-SORT + custom anti-ID-switch guards. See `README.md` and
`docs/` for the full picture. This file covers **Archon workflow usage** and the
**relay protocol** that lets a pi session drive an Archon run on the user's
behalf (surface CLARIFY questions, point them to plannotator, feed their
answers back).

---

## 1. Archon — what it is and how it's configured here

Archon is a workflow runner (`archon` CLI at `/home/tt/.bun/bin/archon`, source
`/home/tt/repository/Archon`). It runs multi-phase AI workflows as detached
background processes, each phase spawning its own pi session in an isolated git
worktree.

Repo-local Archon config: `.archon/config.yaml` + `.archon/workflows/*.yaml`.

Prereqs already satisfied on this machine:
- `pi install npm:@plannotator/pi-extension` (plan review UI).
- `.archon/config.yaml`: `extensionFlags.plan: true` and env
  `PLANNOTATOR_REMOTE: "1"` (so the plan review server binds `0.0.0.0:19432`
  for remote/forwarded access instead of a random loopback port).
- Model tiers default to `ollama/glm-5.2` (local). Provider `pi`.

Verify setup any time:
```bash
archon doctor
archon validate workflows archon-jetson-dev
```

---

## 2. The `archon-jetson-dev` workflow

File: `.archon/workflows/archon-jetson-dev.yaml`. Use for autonomous dev with
**Jetson business validation** (run a reference video, compare the pig count to
the expected value derived from the filename).

**Six phases:**

| # | Node | Type | What happens | Human gate? |
|---|------|------|-------------|-------------|
| 1 | `clarify` | interactive loop | Pi asks 2-3 questions, converges on intent. Emits `READY_FOR_PLAN`. | **Yes** (pauses each iteration) |
| 2 | `plannotator-plan` | single pi session | Pi writes `PLAN.md`, calls `plannotator_submit_plan`. | **Yes** (HTTP review, NOT a pause) |
| 3 | `verify-plan` | bash | Sanity-checks `PLAN.md` has task checkboxes. | No |
| 4 | `implement` | loop (fresh context) | Pi implements one task at a time, `python3 -m py_compile`, commits. Emits `IMPL_DONE`. | No |
| 5 | `jetson-validate` | interactive loop | Pi runs `scripts/validate_on_jetson.sh`, parses `validation-report.json`. `pass` → `VALIDATED`; `count_mismatch` → HITL pause; `execution_error` → auto-retry. | **Yes** (only on mismatch) |
| 6 | `finalize` + `verify-pr-base` | pi + bash | Push branch, create draft PR, verify PR base. | No |

**Validation commands are Python/Jetson, NOT JS/TS.** Never run `bun run
type-check` / `bun run validate` — they don't exist here. Syntax check is
`python3 -m py_compile`; business validation is `scripts/validate_on_jetson.sh`.

**Do NOT auto-correct a count mismatch.** A mismatch means the app ran fine but
the count is wrong — the workflow pauses for human guidance deliberately
(anti "metric gaming"). Surface it to the user and let them decide.

---

## 3. Launching a workflow (detached, returns immediately)

Always launch **detached** so the workflow runs in the background and the CLI
returns the run-id at once:

```bash
cd /mnt/c/Dev/ai/animal-counter
archon workflow run archon-jetson-dev "<your request, with any research already done>" --detach
```

This prints a **run-id** (16 hex chars) and creates a git worktree at
`~/.archon/workspaces/ai/animal-counter/worktrees/archon/task-archon-jetson-dev-<ts>`
on branch `archon/task-archon-jetson-dev-<ts>`. Capture the run-id from stdout.

> ⚠ Never launch an interactive Archon workflow in the foreground from a pi
> bash tool — the CLARIFY phase is `interactive: true` and waits for user input
> on a live TTY. A foreground launch in a non-interactive bash call deadlocks at
> the first gate. Always use `--detach` and drive it via the relay protocol
> below.

---

## 4. Relay protocol — driving a detached run on the user's behalf

This is the protocol a pi session uses to relay Archon states to the user and
feed their answers back, without a live TTY.

### 4.1 State files (beacons) — `.archon-relay/`

Each interactive phase writes a small beacon file to `<worktree>/.archon-relay/`
so the relay can surface clean, curated state:

| Phase | File | States |
|-------|------|--------|
| CLARIFY | `CLARIFY.md` | `WAITING_FOR_USER` / `READY_FOR_PLAN` |
| PLAN | `PLANNOTATOR.md` | `PLAN_REVIEW_PENDING` / `PLAN_APPROVED` |
| JETSON-VALIDATE | `VALIDATION.md` | `PASS` / `MISMATCH_PENDING_USER` / `EXEC_ERROR_RETRY` / `ESCALATED` |

The worktree path comes from `workflow get` (see 4.2). Read the beacon with the
`read` tool. If a beacon is missing (the model didn't write it), fall back to
the pi session transcript under
`~/.pi/agent/sessions/<encoded-worktree-path>/` (path encodes `/` and `:` as
`-`). `.gitignore` already excludes `.archon-relay/` so beacons never get
committed.

### 4.2 Polling run state (machine-readable)

```bash
archon workflow get <run-id> --json --verbose
```

Returns `{ id, workflow_name, working_path, status, metadata, events[] }`.
- `status`: `running` | `paused` | `completed` | `failed` | `cancelled`.
- When `paused`, `metadata.approval` = `{ nodeId, type: 'interactive_loop' |
  'approval_gate', message, iteration, sessionId }`. `message` is the generic
  gate text; the **actual questions are in the beacon file**, not here.
- `events[]` (verbose): `node_started`, `node_completed`, `approval_requested`,
  `approval_received`. Interactive loops do NOT write `node_completed` until the
  completion signal is emitted.

Other state commands:
```bash
archon workflow status                       # active (running/paused) runs
archon workflow runs --json                  # recent runs (all statuses)
```

### 4.3 Feeding user feedback back into a paused run

When the run is `paused` at an interactive loop (CLARIFY questions, or a
validation mismatch), the user's reply becomes `$LOOP_USER_INPUT` for the next
iteration:

```bash
# Records approval + stores loop_user_input + auto-resumes inline (streams output).
# Run it backgrounded so the auto-resume keeps the workflow moving.
nohup archon workflow approve <run-id> "<the user's reply>" > /tmp/archon_resume.log 2>&1 &
```

- Human mode (no `--json`) = record approval **and auto-resume inline**. The
  run transitions `paused → failed → running` (the executor resumes via
  `findResumableRun`); the stored comment becomes `$LOOP_USER_INPUT`.
- `--json` mode = records approval **without resuming** (returns
  `{ ok, runId, action:'approve', type, resumable:true }`). To then drive it to
  completion separately:
  ```bash
  archon workflow resume <run-id>            # blocking, streams output
  # or:
  archon workflow run archon-jetson-dev --resume --detach   # re-run detached
  ```
- Cancel a run: `archon workflow abandon <run-id>`.

### 4.4 Plannotator plan review (HTTP — NOT a paused gate)

The `plannotator-plan` node is **not** `interactive: true`, so the run stays
`running` while it waits for the human HTTP decision. The plannotator extension
starts a review web server when the planner calls `plannotator_submit_plan`.

- URL: **`http://127.0.0.1:19432`** (port = `PLANNOTATOR_PORT` env, or
  `19432` remote-default because `PLANNOTATOR_REMOTE=1`; bound `0.0.0.0`).
- In a remote session the browser does **not** auto-open — the relay must tell
  the user to open it.
- Detect the pending review from the relay's side: the `PLANNOTATOR.md` beacon
  (`STATE: PLAN_REVIEW_PENDING`), or `PLAN.md` exists in the worktree + the
  server is listening (`ss -ltn | grep :19432` or `curl -sf http://127.0.0.1:19432`).
- The user approves/denies in the browser. On approve → planner prints
  `PLAN APPROVED — handing off to implement node.` and the run continues to
  `verify-plan → implement`. On deny → planner revises `PLAN.md` and resubmits.
- **The relay MUST NOT click Approve/Deny in the plannotator UI on the user's
  behalf.** Plan approval is exclusively the user's action via the browser. The
  relay only surfaces the review URL and tells the user to decide. (A relay may
  *add a comment / send feedback* to request a revision, but the final
  Approve/Deny is the user's.)
- On approval, the `verify-plan` node auto-archives the final approved
  `PLAN.md` to the **main repo's `plans/PR_<slug>.md`** (slug derived from the
  plan title). No relay action needed.

### 4.5 Full relay loop (end-to-end)

1. **Launch**: `archon workflow run archon-jetson-dev "<msg>" --detach` → capture run-id.
2. **Poll** every ~20-30s: `archon workflow get <run-id> --json --verbose` +
   `read <worktree>/.archon-relay/*.md`.
3. **CLARIFY paused** → read `CLARIFY.md` → surface questions to the user → on
   their reply, `nohup archon workflow approve <run-id> "<reply>" &`.
4. **PLAN phase** → detect `PLANNOTO.md` beacon (`PLAN_REVIEW_PENDING`) / port
   19432 listening → tell the user: **"Open http://127.0.0.1:19432 to review and
   approve/deny the plan."** Wait for their decision in the browser (the run
   stays `running`). **Do NOT approve/deny for them** — plan approval is the
   user's gate; the relay only surfaces the URL (optionally adds feedback
   comments, never the final Approve/Deny). On approval the run moves to
   `verify-plan`, which auto-archives the plan to `plans/PR_<slug>.md`.
5. **implement** → autonomous; report progress from commits/events.
6. **jetson-validate**:
   - `PASS` → report success, run proceeds to finalize.
   - `MISMATCH_PENDING_USER` → surface `VALIDATION.md` mismatch to the user →
     on their guidance, `nohup archon workflow approve <run-id> "<guidance>" &`.
     (Do NOT auto-fix.)
   - `EXEC_ERROR_RETRY` → let it auto-retry; `ESCALATED` → surface to user.
7. **Completed** → report the PR URL from `finalize` + final validation summary.

---

## 5. Quick reference — Archon CLI

```bash
archon workflow list                                  # available workflows
archon workflow run <name> "<msg>" --detach           # launch detached (returns run-id)
archon workflow status                                # active runs
archon workflow get <run-id> --json --verbose         # state + events
archon workflow runs --json --status paused           # filter recent runs
archon workflow approve <run-id> "<feedback>"          # approve + auto-resume inline
archon workflow approve <run-id> "<feedback>" --json  # approve, no resume
archon workflow resume <run-id>                       # resume a failed/paused run (blocking)
archon workflow run <name> --resume --detach          # resume most-recent failed detached
archon workflow abandon <run-id>                      # cancel
archon isolation list                                 # worktrees
archon isolation cleanup --merged                     # remove merged worktrees
archon complete <branch>                              # remove worktree + branches
archon validate workflows <name>                      # validate a workflow def
archon doctor                                         # verify setup
```

Plannotator (plan review): `http://127.0.0.1:19432` (only while a plan is
pending). NOTE: `archon serve` (web UI, port 3090) is **not available** in this
environment — it requires a compiled Archon binary, and this machine runs the
source/bun install (`bun /home/tt/.bun/bin/archon`). Run interaction is via the
CLI above (what the relay agent uses) and plannotator for plan review.

---

## 6. Pitfalls

- **Foreground launch deadlocks** at CLARIFY (interactive gate needs a TTY).
  Always `--detach`.
- **A `paused` run's `metadata.approval.message` is generic** — the real
  questions live in the beacon file / transcript, not in `get --json`.
- **`approve` human mode auto-resumes inline** and streams output — background
  it with `nohup` when relaying, or use `--json` + a separate `resume`.
- **`node_completed` is not written for interactive loops** until the
  completion signal emits — don't use its absence as a failure signal.
- **Count mismatch = HITL pause, never auto-fix.**
- **Plannotator review does not pause the run** — the run is `running` while it
  waits for the HTTP decision. Detect via beacon + port 19432.
- **`.archon-relay/` is gitignored** — beacons are scratch state, never commit.
- **The worktree is on its own branch** — changes land there until `finalize`
  pushes. To inspect a run's working tree, read under its `working_path`.

---

## 7. Project-specific conventions Archon workflows must respect

- Keep **OC-SORT** (not BoT-SORT/Norfair). Camera is fixed (no CMC).
- FPS_OUTPUT=30. Pigs counted right→left (crossed LEFT = +1, crossed RIGHT = -1).
- `.env` / `.env.local` are gitignored; defaults live in `app/src/settings.py`.
- Git push / PR (phase `finalize`): the GitHub repo is
  `https://github.com/wloonis/animal-counter.git` (private). Auth token is read
  from `.env.local` (key `GITHUB_TOKEN`). `.env.local` is gitignored — never
  commit its value; reference only the key name in tracked files.
- GitHub issues use the `BL-<n> — <title>` naming convention (e.g.
  `BL-57 — <title>`). Always increment from the highest existing `BL-<n>`
  (`gh issue list --state all` to check); never use `P1`/`P2`/etc. prefixes.
- Hysteresis H=0 (H=25 regressed video #18 — abandoned).
- Guard params: `COUNTING_LOST_BUFFER_FRAMES=60` (global expiration) vs
  `COUNTING_GUARD_MAX_AGE=15` (guard eligibility) — keep decoupled.
- Validation: `scripts/validate_on_jetson.sh` → `validation-report.json`
  with `validation_status`. Two modes: **standard** (default, no flag) validates
  only the reference video from `validation/config.json`; **`--full`** validates
  the manifest in `validation/expected_counts.json` (the 4 priority videos under
  `.videos`; the rest are in `.disabled`). **Run standard by default; use `--full`
  ONLY when the branch touches counting code** (`app/src/counting.py`,
  `app/src/main.py` tracking/counting logic, `app/src/core/*`, tracker/guard
  params). k3s/ansible/docs/UI/infra-only changes → standard.
- Do NOT relaunch validation on all 30 videos — only the priority set (and only
  in `--full` mode; standard uses the single reference video).
- Real K3s manifests are `k3s/templates/*.j2` (Ansible). `hostPath /app` is
  intentional (live code mount for rsync + hot restart) — do not "fix" it.
- **Docker image rebuild is required for dependency changes.** `app/Dockerfile`
  runs `pip install -r requirements.txt` at **BUILD** time; the `serve`
  entrypoint just runs `python3 src/main.py` (no re-install at startup).
  `scripts/validate_on_jetson.sh` only **rsyncs** code to the Jetson's `/app`
  (hostPath) — it does **NOT** rebuild the image. So any change to
  `app/requirements.txt` (or other build-time deps) requires rebuilding the
  `countingapp:local` image on the Jetson **before** validation. The
  `build_countingapp.yml` is a tasks file (rsyncs `app/` + runs
  `docker buildx build -t countingapp:local .` on the Jetson), not a standalone
  playbook — invoke it through `deploy_app.yml --tags build` from the
  `ansible/playbooks/app/` directory (so the playbook's `../../../app/` rsync
  source resolves to the repo's `app/`), from a worktree that contains the
  code changes:
  `cd ansible/playbooks/app && ansible-playbook -i ../../inventory/jetsons.yml deploy_app.yml --tags build`.
  Without this rebuild the app crashes on startup — e.g. `trackers>=2.5.0` must
  be installed in the image, not just rsync'd.
- **`OCSORTTracker(iou=...)` expects a `BaseIoU` instance, not a string.**
  `trackers>=2.5.0` accepts `iou=IoU()|GIoU()|DIoU()|CIoU()|BIoU()` (from
  `trackers.utils.iou`); passing the string `"giou"` raises
  `AttributeError: 'str' object has no attribute 'compute'` at runtime.
  `app/src/main.py` maps `settings.COUNTING_TRACKER_IOU` (string) to the
  matching instance via `_IOU_METRICS`.
- **The `trackers==2.5.0` PyPI wheel is BROKEN** (metadata-only, 9.6 KB, no
  `trackers/` package code — upstream `pyproject.toml` package discovery is
  broken; building a wheel from the sdist is also empty). The Dockerfile has a
  workaround: `pip download trackers==2.5.0 --no-binary :all:` (sdist) →
  extract → `cp -r trackers-2.5.0/trackers` into site-packages → verify
  `import trackers` at build time. If a future `trackers` release fixes the
  wheel, the workaround RUN can be removed.
- **A fresh worktree is missing gitignored files** the validation needs:
  `.env.local` (Jetson password), `validation/videos/*.mp4` (test videos),
  `app/model/` (weights), `app/.env`. Copy or symlink them from the main repo
  (`git worktree list` → first `worktree` path) before validating — otherwise
  the rsync `--delete` will also wipe the Jetson's model weights.
- **`app/entrypoint.sh` must be git mode `100755`** (executable). A `100644`
  checkout causes `ContainerCannotRun: permission denied`. Fix with
  `git update-index --chmod=+x app/entrypoint.sh`.
- **`build_countingapp.yml` rsync must `--exclude='model/old/'`** — the
  `app/model/old/` dir holds root-owned files from prior deploys; without the
  exclude, the `--delete` rsync fails with rc=23 (permission denied).
- Jetson: Orin Nano 8GB "Super", IP `192.168.0.180`, user `nano-counter`,
  password from `.env.local` (`JETSON_PASSWORD`). App path on Jetson:
  `/data/orin/git/animal-counter/app`; files: `/data/orin/files/`.