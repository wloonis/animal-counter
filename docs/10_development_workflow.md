# 10 — Development workflow (`archon-jetson-dev`)

How a feature goes from "I want X" to "validated on the Jetson + draft PR",
driven by the **`archon-jetson-dev`** workflow
(`.archon/workflows/archon-jetson-dev.yaml`). This is the developer-facing
guide; the agent-facing relay internals (beacon file formats, CLI flags,
pitfalls) live in [`AGENTS.md`](../AGENTS.md) — read that for the mechanics,
this for the process.

## What it is

An autonomous development loop with **Jetson business validation**: an AI agent
clarifies your request, writes a plan you approve, implements it, then runs the
app on the Jetson against reference videos and checks the **pig count matches
the expected value** before opening a PR. The human stays in the loop at the
*decisions* (clarifying answers, plan approval, mismatch handling) and out of
the *busywork* (rsync, kubectl, py_compile, report parsing).

The validation criterion is deliberately strict: 4 priority videos, **4/4
exact count** (the expected count is derived from the filename,
`validation-<seq>-#<count>.mp4`). A count mismatch is a **business failure** —
the workflow pauses for you, it never auto-tweaks the counting logic to match
a number (anti "metric gaming").

## The 6 phases — what happens, who acts

| # | Phase | Who acts | What |
|---|-------|----------|------|
| 1 | **CLARIFY** | you | The AI does light codebase recon and asks 2–3 **decision** questions (scope, extend-vs-new, testing bar). You answer, push back, or say "ready". Usually 1–2 round-trips. |
| 2 | **PLAN** | AI | Writes `PLAN.md` (atomic tasks, named files, validation commands) and submits it through plannotator's HTTP UI. Planning only — no code edits here. |
| 3 | **Plan review** (HITL) | you | Open `http://127.0.0.1:19432`, read the plan, **approve** or **deny with feedback**. Denied → the AI revises `PLAN.md` and resubmits. |
| 4 | **VERIFY-PLAN** | AI | Sanity check that `PLAN.md` exists with tasks. |
| 5 | **IMPLEMENT** | AI | Edits task-by-task with `python3 -m py_compile` validation + commits. No Jetson calls yet. |
| 6 | **JETSON-VALIDATE** | AI + you on mismatch | Runs `scripts/validate_on_jetson.sh --full` on the Jetson, reads `validation-report.json`: **pass** → finalize; **count_mismatch** → HITL pause (you guide the fix); **execution_error** → auto-retry/escalate. |
| 7 | **FINALIZE** | AI | Pushes the worktree branch + opens a **draft PR**. |

## Prerequisites (one-time per machine)

- `pi install npm:@plannotator/pi-extension`
- `.archon/config.yaml` has `extensionFlags.plan: true` and
  `PLANNOTATOR_REMOTE: "1"` (so plan review happens over HTTP, not a local app).
- `.env.local` with `JETSON_IP` / `JETSON_USER` / `JETSON_PASSWORD` — run
  `scripts/jetson_discover.sh` to populate it (see
  [`02_setup.md`](02_setup.md)).
- Validation videos in `validation/videos/` and expected counts in
  `validation/expected_counts.json` (see [`06_validation.md`](06_validation.md)).
- A built `countingapp:local` image on the Jetson. If `app/requirements.txt`
  changed in the branch, the workflow's **Step 0** rebuilds it automatically
  via `ansible/playbooks/app/deploy_app.yml --tags build`; otherwise it reuses
  the existing image. See [`03_deployment.md`](03_deployment.md).

## Launching a run

```bash
archon workflow run archon-jetson-dev "<your request>" --detach
```

Example:

```bash
archon workflow run archon-jetson-dev "activate GIoU association (COUNTING_TRACKER_IOU=giou) and validate 4/4" --detach
```

`--detach` is **required**: the workflow returns a run-id immediately and runs
in the background. A foreground launch deadlocks at the CLARIFY gate (the
interactive approval needs a TTY the background call doesn't have). You then
drive the run via the **relay loop**.

## Driving a detached run (the relay loop)

Because the run has no live TTY, you (or an AI relay agent) drive it through
files and the CLI — the full beacon-file format + every CLI flag is in
[`AGENTS.md`](../AGENTS.md) §4 (Relay protocol). In short:

1. **Poll** the run state:
   ```bash
   archon workflow get <run-id> --json --verbose
   ```
   The `status` and `metadata.approval` tell you which gate is pending.

2. **Read the beacon** for the current phase, written to `.archon-relay/` in
   the worktree:
   - `.archon-relay/CLARIFY.md` — the questions to answer (state `WAITING_FOR_USER`).
   - `.archon-relay/PLANNOTATOR.md` — the plan review URL (state `PLAN_REVIEW_PENDING`).
   - `.archon-relay/VALIDATION.md` — the validation result (state `PASS` / `MISMATCH_PENDING_USER` / `EXEC_ERROR_RETRY` / `ESCALATED`).

3. **Act on the gate**:
   - Answer CLARIFY questions / approve the plan / handle a mismatch by feeding
     the reply back in:
     ```bash
     archon workflow approve <run-id> "<your answer or feedback>"
     ```
     In human mode this records the input and auto-resumes the run inline
     (background it with `nohup` if you don't want to hold the terminal).
   - **Plan review** happens on the HTTP UI at `http://127.0.0.1:19432` — open
     it, approve or deny. The run stays `running` while it waits (this is **not**
     a paused gate); the relay detects it via the beacon + the port.

The worktree for a run lives under
`~/.archon/workspaces/<repo>/worktrees/<branch>` — inspect it to see the
in-progress code. The branch is the run's own; changes land there until finalize
pushes.

## Where a human acts (the gates)

| Gate | When | What you do |
|------|------|-------------|
| CLARIFY | start | Answer 2–3 decision questions (or push back on scope). |
| Plan review | after PLAN | Approve / deny the plan on `127.0.0.1:19432`. |
| Count mismatch | after JETSON-VALIDATE | Decide: re-tune a threshold, revert, or accept the mismatch. **The workflow never auto-corrects a count** — that's your call. |
| Repeated execution errors | after JETSON-VALIDATE | Only if `max_iterations` is exceeded: help diagnose an infra failure (Jetson down, image not rebuilt, video missing). |

## What this workflow is NOT for

- **Quick fixes / typos** → just edit + commit, no need for the loop.
- **JS/TS projects** → it's Python/Jetson-specific (no `bun run validate`).
- **Standard PIV without Jetson validation** → use `archon-plannotator-piv`.
- **Count auto-correction** → a mismatch is a hard stop; the workflow will not
  tweak counting logic to match an expected number.

## Pitfalls (highlights)

- **Always `--detach`** — foreground deadlocks at CLARIFY.
- **`archon serve` (web UI, port 3090) is unavailable** in this source/bun
  install — interact via the CLI + plannotator only.
- **The worktree is on its own branch** — changes stay there until finalize
  pushes; to inspect a run's working tree, read under its `working_path`.
- **A fresh worktree is missing gitignored files** (`.env.local`, validation
  videos, model weights) — Step 0 of JETSON-VALIDATE copies them from the main
  repo (`git worktree list`); without that, rsync `--delete` would also wipe
  the Jetson's model.
- **`OCSORTTracker(iou=...)` expects an instance**, not a string — see
  [`AGENTS.md`](../AGENTS.md) §7.

The full pitfall list is in [`AGENTS.md`](../AGENTS.md) §6, and the project
conventions the workflow must respect are in [`AGENTS.md`](../AGENTS.md) §7.