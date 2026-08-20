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

**Seven phases:**

| # | Node | Type | What happens | Human gate? |
|---|------|------|-------------|-------------|
| 1 | `clarify` | interactive loop | Pi asks 2-3 questions, converges on intent. Emits `READY_FOR_PLAN`. | **Yes** (pauses each iteration) |
| 2 | `plannotator-plan` | single pi session | Pi writes `PLAN.md`, calls `plannotator_submit_plan`. | **Yes** (HTTP review, NOT a pause) |
| 3 | `verify-plan` | bash | Sanity-checks `PLAN.md` has task checkboxes. | No |
| 4 | `implement` | loop (fresh context) | Pi implements one task at a time, `python3 -m py_compile`, commits. Emits `IMPL_DONE`. | No |
| 5 | `jetson-validate` | interactive loop | Pi runs `scripts/validate_on_jetson.sh`, parses `validation-report.json`. `pass` → `VALIDATED`; `count_mismatch` → HITL pause; `execution_error` → auto-retry. | **Yes** (only on mismatch) |
| 6 | `docs-sync` | single pi session | Fresh session syncs `README.md`, `AGENTS.md`, `docs/**`, `ansible/README.md` to the changed surface (paths/symbols/env vars/hostPaths/contracts). Writes `DOCS.md` beacon; flags shared/contract docs needing sister-repo resync. | No |
| 7 | `finalize` + `verify-pr-base` | pi + bash | Push branch, create draft PR, verify PR base. | No |

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
| DOCS-SYNC | `DOCS.md` | `DOCS_SYNCED` (with `UPDATED:` list + `SHARED_CONTRACT_RESYNC:` flag) |

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
   - `PASS` → report success, run proceeds to **docs-sync**.
   - `MISMATCH_PENDING_USER` → surface `VALIDATION.md` mismatch to the user →
     on their guidance, `nohup archon workflow approve <run-id> "<guidance>" &`.
     (Do NOT auto-fix.)
   - `EXEC_ERROR_RETRY` → let it auto-retry; `ESCALATED` → surface to user.
7. **docs-sync** → autonomous (no gate). Read `.archon-relay/DOCS.md`: report
   which docs were synced. If `SHARED_CONTRACT_RESYNC` names a doc (e.g.
   `docs/IPC_CONTRACT.md`), **surface to the user** that the sister-repo
   (`wloonis/animal-counter-companion`) copy must be resynchronized — this is
   not done by the workflow (it can only edit this repo).
8. **Completed** → report the PR URL from `finalize` + final validation summary
   + doc-sync summary.

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
  `app/src/main.py` **tracking/counting DECISION logic** — i.e. the counting
  line-crossing + guard/tracker decision code, NOT recording-lifecycle code
  like the `DisplayThread` filename/video-writer/record flow, `app/src/core/*`,
  tracker/guard params). **A change to `app/src/main.py` that is limited to
  recording lifecycle (filename, video writer, `DisplayThread` recording flow),
  UI, or infrastructure does NOT justify `--full` — use standard.** When unsure,
  check the diff: if it does not alter *what gets counted* (crossing detection,
  guard eligibility, tracker params), it is standard. k3s/ansible/docs/UI/
  infra-only changes → standard.
- **Skip validation entirely for branches that touch NO file under `app/`**
  (ansible playbooks, docs, k3s manifests, scripts, RTC). The counting-video
  validation only proves the *counting pipeline* still counts correctly — it is
  meaningless for infra/docs/ansible-only changes and only risks a false
  mismatch from the model mis-parsing a green run (BL-64 hit this). The
  `archon-jetson-dev` workflow's `jetson-validate` node auto-detects this
  (`git diff --name-only main...HEAD -- app/` empty →
  signals VALIDATED without running the script). Don't force a validation run
  on such branches.
- **`validation/config.json` `mode` field MUST stay `"standard"` by default.**
  `scripts/validate_on_jetson.sh` reads `mode` from config.json as its default;
  do not leave it on `"full"` (a counting-code branch may flip it to `full`
  temporarily, but revert before merge). The `--full` CLI flag is a per-run
  override only — prefer changing the branch's behavior, not the committed
  config. Default = standard.
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
- **K3S is WiFi-only — runs on a DUMMY interface, not ethernet.** The Jetson
  has no ethernet cable in production and no RTC battery, so
  `install_k3s_with_docker_tasks.yml` puts the K3s node-ip (`192.168.50.10`,
  `JETSON_ETH_IP` — the name is historical, the value is now carried by
  `dummy0`) on a virtual `dummy0` interface (always UP, no carrier needed) and
  sets `flannel-iface: dummy0`. The system clock is restored at boot by
  `fake-hwclock` (no RTC battery) and re-applied right before k3s starts via
  `ExecStartPre=/sbin/fake-hwclock load` (a late sync from the dead onboard
  RTC would otherwise reset it to 1970 → k3s crash-loop). `k3s-clock-ready`
  gates k3s until the year is sane (first boot with no fake-hwclock data waits
  for the phone BL-65 time push). Do **NOT** revert K3s to the physical
  ethernet interface (`enP8p1s0`, linkdown without a cable) — it crash-loops.
- Jetson: Orin Nano 8GB "Super", **WiFi IP is static `192.168.0.180`** (pinned by
  `configure_static_wifi.yml`, run by `prepare_jetson.sh` before hotspot setup;
  if it ever drifts, rediscover with `scripts/jetson_discover.sh`; in hotspot
  mode it's `JETSON_HOTSPOT_IP` `192.168.100.1`), user `nano-counter`,
  password from `.env.local` (`JETSON_PASSWORD`). App path on Jetson:
  `/data/orin/git/animal-counting/app` (`APP_PATH`); rendered k3s manifests:
  `/data/orin/git/animal-counting/k3s/` (`K3S_APP_PATH`, applied via explicit
  `k3s kubectl apply -f`, NOT the k3s auto-apply dir — a reboot does NOT
  re-apply them); files (videos): `/data/orin/files/` (`FILES_PATH`);
  Docker: `/data/orin/docker/` (`DOCKER_PATH`). Note the on-Jetson dir is
  `animal-counting`, not `animal-counter` (the repo name).

---

## 8. Pi bundled patch — local fix for #6101 / #6102 (PR #6501)

**Archon branch:** `archon-dev-0807-v2` (a superset of `origin/dev` + 5 local
commits: the pi pin below + 4 patch-script tooling commits under `patches/`;
no Archon `*.ts` source is modified). `origin/dev` now contains #2124 **merged**
(per-node extension posture, #2073), #2126 (interactive-loop completion), #2144
(portable per-node posture), and ~14 other PRs. **#2124 is #2073, NOT #6101** —
its own diff says "we MUST reuse a process-cached, already-reloaded loader", so
the runtime stays **shared** across nodes and the stale-ctx bug persists; the
patch below is still required. **Verified against pi 0.84.1 (latest npm):**
`clearInvalidation` is still absent from `loader.js`/`runner.js`, so the exact
`0.80.7` pin + the #6501 patch remain required — do not bump the bundle yet.

The bundled pi-coding-agent is **pinned to exact `0.80.7`** (not `^0.80.6`):
caret resolves to 0.80.9, whose `@earendil-works/pi-ai` ships a broken
`./oauth` subpath (`dist/oauth.js` is an empty `export {}` instead of re-
exporting from `./utils/oauth/index.js`), breaking Archon's
`@earendil-works/pi-ai/oauth` import (`getOAuthProvider not found`). pi-ai
0.80.7 has the correct barrel. Keep the exact pin.

The bundled pi-coding-agent (0.80.7) carries a **local patch** transposed from
upstream PR **#6501** (`wloonis:fix/embedded-library-runtime-theme`), which pi
**closed NOT_PLANNED** and never merged. It fixes two bugs that break Archon's
planner node (clarify disposes session 1 → the **shared extension runtime** is
poisoned → plannotator-plan inherits it → every `pi.*` API call throws
`This extension ctx is stale ...` on deny+resubmit):

- **#6101** — `AgentSession.dispose()` → `ExtensionRunner.invalidate()` sets a
  write-only `state.staleMessage` on the extension runtime. When a host reuses
  the same resource loader across sequential sessions (Archon's
  `getOrCreateReloadedExtensionLoader` → all nodes share one loader → one
  runtime), every later session reuses that runtime and throws from
  `runtime.assertActive()` on every Extension API call. **Fix:** add
  `clearInvalidation()` to the runtime and call it at the top of
  `ExtensionRunner.bindCore()`, so a reused runtime is reactivated when a new
  session rebinds it. `invalidate()` keeps its write-only `??=` semantics.
- **#6102** — `theme` is a Proxy that throws `Theme not initialized` until the
  TUI calls `initTheme()`. Library hosts (Archon) never run the TUI, so shared
  code paths that read `theme` throw. **Fix:** lazily bootstrap the builtin
  `dark` theme on first `theme` access instead of throwing. (Archon's dev+#2124
  `createArchonUIContext` already stubs `ctx.ui.theme`; this patch covers the
  global `theme` proxy read directly by loader/extension code.)

**Applied to** (compiled `dist/*.js`, transposed from the PR's `src/*.ts`):
- `packages/providers/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/loader.js`
- `.../dist/core/extensions/runner.js`
- `.../dist/modes/interactive/theme/theme.js`

⚠️ **The plannotator extension resolves `@earendil-works/pi-coding-agent` from
the bun hoisted cache (`node_modules/.bun/@earendil-works+pi-coding-agent@*/...`),
NOT from `packages/providers/node_modules`.** Patching only the providers copy
leaves plannotator's `continueWhenIdle() -> isIdle() -> assertActive()` using an
UNPATCHED `runner.js`, so the stale-ctx (#6101) crash persists on plan
submit/approve. **All copies must be patched.**

These files live in `node_modules` and are **wiped by `bun install`**. Re-apply
after any install that touches `@earendil-works/pi-coding-agent`. With **no
argument** the script auto-discovers and patches EVERY copy (providers + global
+ all `.bun/` cache versions):
```bash
bash /home/tt/repository/Archon/patches/pi-6501-embedded-runtime-theme.sh   # all copies
# (optional) single explicit path, legacy mode:
bash /home/tt/repository/Archon/patches/pi-6501-embedded-runtime-theme.sh \
    /usr/lib/node_modules/@earendil-works/pi-coding-agent
```
The script is idempotent (guards each edit with a `grep -q`) and warns if the
pi version is not `0.80.7` (anchors still apply across 0.79.1–0.80.9).

**Validation:** the patch was confirmed by a repro mirroring the PR's regression
test — `createExtensionRuntime()` → `invalidate()` (assertActive throws) →
`new ExtensionRunner(...).bindCore(...)` → `assertActive()` no longer throws
(runtime reactivated). In real Archon runs, each new session calls `bindCore()`
(via `_buildRuntime`/`bindExtensions`) on the runner wrapping the **shared**
runtime, so the poisoned marker from the previous node's dispose is cleared.

**When the upstream fix eventually lands** (a future pi release merges #6501 or
an equivalent), drop this patch: delete the script + remove this section. Until
then this is the **one** local patch on pi itself. Archon `*.ts` source has **0
local patches** — it runs purely on `origin/dev`; the only local commits on the
Archon branch are the pi pin and the `patches/` tooling scripts. Fallback
branches: `archon-dev-0807-exp` (pre-merge #2124 cherry-pick, kept as rollback),
`archon-piv-patches` (0.4.1 + 3 patches, older rollback).

### 8.1 Plannotator phase-leak reset (separate, on the installed extension)

A **second** patch — not on pi, on the installed `@plannotator/pi-extension` —
is still required. Plannotator's `phase` (and `lastSubmittedPath`,
`checklistItems`) is **module-level**, and Archon's
`getOrCreateReloadedExtensionLoader` keeps a **process-level cache** of the
reloaded extension loader (`reloadedExtensionLoaderCache` in
`packages/providers/src/community/pi/resource-loader.ts`), so every workflow
node in one run shares one loader → one runtime → one set of extension module
instances. The planner node's `enterPlanning()` sets `phase = "planning"`, which
leaks into the implement node; the implement node then inherits the planner's
planning/executing system prompt and (with `glm-5.2`) refuses to write code,
deadlocking the loop (idle timeout, no commits). Plannotator's own
`session_shutdown` handler only clears `sessionAlive`/`currentPiSession` — it
does **not** reset `phase` — so the leak is not handled upstream.

**Fix** (`patches/plannotator-phase-leak-reset.sh`, applied to the installed
`~/.pi/agent/npm/node_modules/@plannotator/pi-extension/index.ts` — loaded from
src, no dist): reset `phase` (and `phaseOwnerIdentity`, `lastSubmittedPath`,
`checklistItems`) to `idle` in plannotator's `session_shutdown` handler. When the
planner session tears down (it is a **different** session from the implementer —
confirmed in the BL-79 transcripts: planner `01a01f74` → implement `01a01f8b`),
the shared runtime is cleaned so the implement node starts in `idle` instead of
inheriting `planning`. Idempotent; re-run after any `pi install` / update of the
extension.
```bash
bash /home/tt/repository/Archon/patches/plannotator-phase-leak-reset.sh
```

**Why `session_shutdown` and not an identity check in `before_agent_start`.** An
earlier version of this patch tried to reset `phase` in `before_agent_start`
when a "different session" started, comparing `sessionId`/`sessionFile`/`cwd`.
That is **ineffective in the shared-runtime model**: `runtimeToken` is a single
`Symbol` created once at `plannotator()` init (shared across nodes),
`ctx.sessionManager` is stale/shared (the #6101 class — `getSessionId()` returns
the same id across nodes), and `cwd` is the same worktree. No identity field
reliably distinguishes nodes, so the reset condition was always false and the
leak persisted — observed on the BL-79 run, where the implement session (a
*different* transcript sessionId) still inherited `phase = "planning"`, told
itself *"I'm in Plannotator planning mode, which restricts edits to markdown
files only"*, refused to edit `.py` files, and looped re-submitting `PLAN.md`
instead of emitting `IMPL_DONE`. The `session_shutdown` teardown reset does not
depend on identity comparison. (The leftover `before_agent_start` identity reset
in `index.ts` is harmless and kept as belt-and-suspenders.)

**Caveat / fallback.** The `session_shutdown` handler's own comment notes some
teardown paths *"never reach our `session_shutdown` handler"*. If a future run
shows the leak recurring, the fallback is a **workflow-level override**: the
`implement` node prompt in `.archon/workflows/archon-jetson-dev.yaml` explicitly
tells the agent to disregard any stale *"plannotator planning mode / restrict
edits to markdown"* injection and edit source files freely. Both guards ship
together.

**History — a previously-needed sibling patch is now obsolete.** An earlier
combined script also wrapped plannotator's `continueWhenIdle` in a try/catch
guard (the plan-approval stale-ctx crash: after approval the planner session is
torn down but `continueWhenIdle`'s captured `ctx.isIdle()` threw an uncaught
"stale extension ctx" inside `setTimeout`, crashing Bun and orphaning the run).
That guard is **now upstream** in `@plannotator/pi-extension` >= 0.26.x:
`continueWhenIdle` is wrapped with an `isCtxAlive`/`sessionAlive` liveness probe
+ try/catch (plannotator issue #1140). Do **not** re-apply that guard — its
anchor no longer matches 0.26.x and it is redundant. The renamed script keeps
**only** the phase-leak reset.

---

## 9. Sister repo — Android app + Jetson companion

The **Android phone app** and the **Jetson host companion** (the HTTP bridge
the app talks to) have been **extracted** into a dedicated repository:

**`wloonis/animal-counter-companion`** — https://github.com/wloonis/animal-counter-companion

This repo keeps the **counting core** only: OC-SORT tracking, the counting
pipeline, TensorRT, the K3s `countingapp` pod, the Jetson system/K3s/RTC setup,
and the `validate_on_jetson.sh` reference-video validation. The split happened
at tag `v1.1.0` (the last monorepo release).

### What lives where

| Concern | Repo |
|---------|------|
| Counting pipeline (tracking, crossing, guards, `app/`) | **here** (`animal-counter`) |
| K3s countingapp deploy + Jetson system/RTC/K3s-boot playbooks | **here** |
| `validate_on_jetson.sh` reference-video validation | **here** |
| `counting-history.jsonl` **writer** (`app/src/core/history.py`) | **here** |
| `runtime-settings.json` / `.arret_requested` **reader** (`app/src/state.py`, `display_thread.py`) — reads `/conf` (BL-79 split) | **here** |
| `model-classes.json` **writer** (`app/src/state.py::publish_model_classes_json`) — app→companion class catalog (BL-78) | **here** |
| `counting_class_ids` **reader** (`app/src/main.py` hot-reload, validated against `model-classes.json`) — which classes the countingapp counts (BL-78) | **here** |
| Android phone app (`android/`) | **sister repo** |
| Jetson host companion (`jetson-companion.py` + systemd unit) | **sister repo** |
| Companion deploy playbook | **sister repo** (`ansible/playbooks/deploy_companion.yml`) |
| `counting-history.jsonl` **reader** (`HistoryIndex`) | **sister repo** |
| `runtime-settings.json` / `.arret_requested` **writer** (must write `/data/orin/conf` — BL-80 companion migration) | **sister repo** |
| `model-classes.json` **reader** (labels per-species sub-counts) | **sister repo** |
| `counting_class_ids` **writer** (proposes counted classes in `runtime-settings.json`) | **sister repo** (BL-80) |

### The IPC contract

The companion and the countingapp communicate **only** via shared files in
two hostPaths on the Jetson — `/files` (data: `counting-history.jsonl`, mp4
clips, dataset) and `/conf` (config/contrôle: `runtime-settings.json`,
`.arret_requested`, `model-classes.json` (BL-78)) — there is no HTTP/RPC between them. The authoritative
contract is [`docs/IPC_CONTRACT.md`](docs/IPC_CONTRACT.md), which is kept
**identical in both repos**. The tightest coupling is the `counting-history.jsonl`
schema (this repo writes it; the sister repo reads it). Any change to that
schema is a **coordinated change across both repos** — update
`docs/IPC_CONTRACT.md` in both, prefer additive changes (new fields / new
`type` values; the reader
tolerates unknown fields).

### Conventions for agents here

- **Do not** add Android/companion code here. The Android app, the companion,
  and the companion deploy playbook are in the sister repo. If a change seems
  to need them, open the work in `wloonis/animal-counter-companion`.
- The Android **build toolchain** (JDK 17 + Android SDK) is documented in the
  sister repo's `AGENTS.md`, not here.
- The companion is **no longer deployed from this repo** —
  `ansible/playbooks/system/configure_companion.yml` and
  `scripts/install_companion_standalone.sh` were removed; use the sister repo's
  `ansible/playbooks/deploy_companion.yml`.
- **GitHub issue numbering** (`BL-<n>`) is **shared system-wide** across both
  repos — always check `gh issue list --state all` in BOTH repos and increment
  from the highest existing `BL-<n>` anywhere. This repo is the historical
  source of the BL counter.
- Validation rules in §7 still apply: a branch that touches only
  `app/` counting **decision** logic may need `--full`; infra/docs/k3s/RTC-only
  branches skip validation. There is no more "companion-only" branch type here
  — companion work happens in the sister repo.
