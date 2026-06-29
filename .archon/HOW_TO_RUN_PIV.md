# How to run the `archon-plannotator-piv` workflow (fresh-session runbook)

> Read this file when the user asks to run the Plannotator-gated PIV workflow on
> this repo (animal-counter). Everything is already set up on this machine — you
> do NOT need to redo any configuration.

## What this workflow is

`archon-plannotator-piv` is an **Archon** workflow (not a native Pi command) that:
1. **CLARIFY** — Pi (GLM-5.2 via Ollama Cloud) asks 2-3 targeted questions, then
   pauses for the user to say "ready".
2. **PLAN** — a Pi session writes `PLAN.md` and submits it to the **Plannotator**
   review UI (HTTP server on `127.0.0.1:19432`). The human approves, or denies with
   feedback (Pi iterates on the plan until approved).
3. **IMPLEMENT** — Pi executes the approved plan task-by-task, with validation +
   commits, in the Archon worktree.
4. **VALIDATE** — final validation + summary.

## Pre-flight checks (do these first)

```bash
~/archon-dev.sh status                                 # server up? else: ~/archon-dev.sh start
cd ~/repository/Archon && git branch --show-current    # MUST be archon-piv-patches
ls /mnt/c/Dev/ai/animal-counter/.archon/workflows/archon-plannotator-piv.yaml
```

If the server is down: `~/archon-dev.sh start` then wait ~12s.
If the Archon branch is not `archon-piv-patches`: `git checkout archon-piv-patches`.

## Launch — one command

```bash
~/archon-run-piv.sh "<your task in free text, e.g. add a header comment to app/src/core/tracking.py>"
```

The script:
- ensures the server is up,
- creates a conversation + launches the workflow,
- auto-approves the Clarify "ready" gate,
- waits for the Plannotator UI and prints `http://localhost:19432`.

Then **tell the user** to open `http://localhost:19432` and approve (or deny with
feedback). Do NOT approve for them — plan validation is a human gate.

## After the user approves in the browser

The workflow continues automatically to IMPLEMENT + VALIDATE. Monitor with:

```bash
~/archon-dev.sh logs              # live server log
# or check the run that archon-run-piv.sh printed:
cd ~/repository/Archon/packages/core && HOME=/home/tt bun -e \
  "import Database from 'bun:sqlite';const db=new Database('/home/tt/.archon/archon.db');const r=db.prepare(\"SELECT status FROM remote_agent_workflow_runs ORDER BY started_at DESC LIMIT 1\").get();console.log(r);"
```

When the run reaches `completed`, the implementation commit is in the Archon
worktree (path printed in the run metadata / logs). Verify with `git log` there.

## Manual fallback (if the script ever breaks)

```bash
# 1. server up
~/archon-dev.sh status || ~/archon-dev.sh start

# 2. create conversation
curl -sS -X POST http://localhost:3000/api/conversations \
  -H "Content-Type: application/json" \
  -d '{"codebaseId":"8d267146c60353c13e7f365c83a4b9cb","message":"<task>"}'
#   → note conversationId

# 3. launch workflow
curl -sS -X POST http://localhost:3000/api/workflows/archon-plannotator-piv/run \
  -H "Content-Type: application/json" \
  -d '{"conversationId":"<convId>","message":"<task>"}'

# 4. approve Clarify gate once the run is "paused"
curl -sS -X POST http://localhost:3000/api/workflows/runs/<runId>/approve \
  -H "Content-Type: application/json" -d '{"comment":"ready"}'

# 5. wait for :19432, then ask the user to review there
```

## What NOT to do

- Do not try to trigger the workflow via the Archon **chat** (models don't emit
  `/invoke-workflow` reliably). Use the API / script / Web UI Workflows page.
- Do not approve the plan in Plannotator on the user's behalf.
- Do not re-apply the provider patches — they're committed on
  `archon-piv-patches`. See `~/archon-piv-patches/README.md` only if Archon was
  updated.

## Reference

- Workflow definition: `./.archon/workflows/archon-plannotator-piv.yaml`
- Project config: `./.archon/config.yaml` (`extensionFlags.plan: true`, `PLANNOTATOR_REMOTE: "1"`)
- Patches & update procedure: `~/archon-piv-patches/README.md`
- Launcher script: `~/archon-run-piv.sh`