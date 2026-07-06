# Improvement backlog

This is the **living backlog** of the *animal-counter* project. It lists every
identified improvement (robustness, observability, testability, architecture,
performance, security, documentation), whether already shipped or to come.

Each item has a stable id (`BL-XX`) for tracking in commits, code reviews, and
discussions. The order of the recap table reflects priority, not implementation
order.

## Legend

| Field | Values |
|---|---|
| **Status** | ✅ done · 🔄 partial · ⬜ to do · ❌ abandoned |
| **Priority** | P0 (blocks production) · P1 (important) · P2 (nice-to-have) |
| **Effort** | S (<1h) · M (≈ ½ day) · L (>1 day) |
| **Risk** | 🟢 low (no counting logic touched) · 🟡 medium · 🔴 high |

## Recap table

| ID | Title | Category | Priority | Effort | Risk | Status |
|---|---|---|---|---|---|---|
| BL-01 | OC-SORT tuning | Robustness | P0 | M | 🟡 | ✅ done |
| BL-02 | Bidirectional ID-switch recovery guard | Robustness | P0 | L | 🔴 | ✅ done |
| BL-03 | GUARD_MAX_AGE (decoupled from lost buffer) | Robustness | P0 | S | 🟡 | ✅ done |
| BL-04 | `lost_tracks` cleanup on ID return | Robustness | P0 | S | 🟡 | ✅ done |
| BL-05 | REID-SUPPRESS (both +1 and −1) | Robustness | P0 | M | 🔴 | ✅ done |
| BL-06 | Resurrection guard (Pattern B safety net) | Robustness | P1 | S | 🟡 | ✅ done |
| BL-07 | Mirror guard (`log` mode) | Robustness | P2 | S | 🟢 | ✅ done |
| BL-08 | Counting-line hysteresis | Robustness | P2 | S | 🔴 | ❌ abandoned (regressed #18) |
| BL-09 | `result.json` flush fix | Robustness | P0 | S | 🟡 | ✅ done |
| BL-10 | GC `first_seen`/`last_seen`/`trails` | Robustness | P0 | S | 🟢 | ✅ done |
| BL-11 | `trails` as `deque(maxlen=60)` | Performance | P2 | S | 🟢 | ✅ done |
| BL-12 | `settings.py` defaults aligned | Architecture | P1 | S | 🟢 | ✅ done |
| BL-13 | Remove `process_for_tracking` | Architecture | P1 | S | 🟢 | ✅ done |
| BL-14 | `.env.example` + `.gitignore` | Security | P1 | S | 🟢 | ✅ done |
| BL-15 | Rename videos + manifest | Documentation | P1 | S | 🟢 | ✅ done |
| BL-16 | `docs/05_counting_pipeline.md` | Documentation | P1 | M | 🟢 | ✅ done |
| BL-17 | Residual GC `detections`/`area_in`/`area_out` | Robustness | P0 | M | 🟡 | ⬜ to do |
| BL-18 | Graceful shutdown (SIGTERM) | Robustness | P1 | S | 🟢 | ⬜ to do |
| BL-19 | Memory watch (RSS alert) | Robustness | P1 | S | 🟢 | ⬜ to do |
| BL-20 | Auto camera reconnect | Robustness | P1 | M | 🟡 | ⬜ to do |
| BL-21 | Prometheus `/metrics` endpoint | Observability | P1 | M | 🟢 | ⬜ to do |
| BL-22 | Structured JSON logging | Observability | P1 | S | 🟢 | ⬜ to do |
| BL-23 | Counter exposed via API (`/count`) | Observability | P1 | S | 🟢 | ⬜ to do |
| BL-24 | Real-time dashboard | Observability | P2 | L | 🟢 | ⬜ to do |
| BL-25 | `counting.py` unit tests | Testability | P1 | M | 🟢 | ⬜ to do |
| BL-26 | Local validation mode | Testability | P1 | M | 🟢 | ⬜ to do |
| BL-27 | CI (lint + compile + tests) | Testability | P1 | S | 🟢 | ⬜ to do |
| BL-28 | Track fixtures (ID replay) | Testability | P2 | M | 🟢 | ⬜ to do |
| BL-29 | Refactor `main.py` (658 lines) | Architecture | P1 | L | 🟡 | ⬜ to do |
| BL-30 | Align all defaults (paths) | Architecture | P2 | S | 🟢 | ⬜ to do |
| BL-31 | Centralize config (single source) | Architecture | P2 | M | 🟢 | ⬜ to do |
| BL-32 | Type hints + docstrings `counting.py` | Architecture | P2 | M | 🟢 | ⬜ to do |
| BL-33 | GPU prefetch (decode + preprocess) | Performance | P2 | M | 🟡 | ⬜ to do |
| BL-34 | numpy vectorization `counting.py` | Performance | P2 | S | 🟢 | ⬜ to do |
| BL-35 | Headless mode (no `cv2.imshow`) | Performance | P2 | S | 🟢 | ⬜ to do |
| BL-36 | Profiling (py-spy) | Performance | P2 | S | 🟢 | ⬜ to do |
| BL-37 | SSH keys (replace `sshpass`) | Security | P1 | S | 🟢 | ⬜ to do |
| BL-38 | Secrets via vault / K8s Secret | Security | P2 | M | 🟢 | ⬜ to do |
| BL-39 | Guards flow diagram | Documentation | P2 | S | 🟢 | ⬜ to do |
| BL-40 | README runbook | Documentation | P2 | M | 🟢 | ⬜ to do |
| BL-41 | Validation matrix (video → fix) | Documentation | P2 | S | 🟢 | ⬜ to do |
| BL-42 | Counter persistence (snapshot + reload) | Robustness | P0 | M | 🟡 | ⬜ to do |
| BL-43 | `stop()` finalizes `video_writer` (release) | Robustness | P0 | S | 🟡 | ⬜ to do |
| BL-44 | Fragmented MP4 (power-cut resistance) | Robustness | P1 | M | 🟡 | ⬜ to do |
| BL-45 | `livenessProbe` HTTP `/health` | Robustness | P1 | S | 🟢 | ⬜ to do |
| BL-46 | `terminationGracePeriodSeconds` 0→30 s | Robustness | P0 | S | 🟢 | ⬜ to do |
| BL-47 | Reduce `privileged` + remove `docker.sock` | Security | P2 | M | 🟡 | ⬜ to do |
| BL-48 | Filebrowser creds `admin/admin` → strong password | Security | P2 | S | 🟢 | ⬜ to do |
| BL-49 | Pin `ffmpeg:latest` | Ops | P2 | S | 🟢 | ⬜ to do |
| BL-50 | External access to countingapp (externalIP/ingress) | Ops | P2 | S | 🟢 | ⬜ to do |
| BL-51 | Video cleanup restricted to `.mp4` | Robustness | P2 | S | 🟢 | ✅ done |

## 1. Robustness / Production (24/7)

### ✅ BL-01 — OC-SORT tuning
OC-SORT params calibrated on the reference videos: `lost_track_buffer=20`,
`high_conf_det_threshold=0.6`, `minimum_iou_threshold=0.3`,
`minimum_consecutive_frames=5` (was 3), `delta_t=3`,
`direction_consistency_weight=0.25`. All configurable via `settings.py` +
`app/.env`. *Commit `8382e0e`.*

### ✅ BL-02 — Bidirectional ID-switch recovery guard
Detects tracks lost on one side of the line; when a new ID appears on the other
side, fuses them and fires the crossing (+1 or −1 by direction).
`want_side = "in" if element[0] <= x else "out"` unifies both directions.
*Commits `8382e0e` (+1) + `f84d36a` (−1 mirror).*

### ✅ BL-03 — GUARD_MAX_AGE
`COUNTING_GUARD_MAX_AGE=15` decoupled from `COUNTING_LOST_BUFFER_FRAMES=60`:
long occlusions (#35) and stale-fusion avoidance (#30) coexist. *Commit
`8382e0e`.*

### ✅ BL-04 — `lost_tracks` cleanup on ID return
When an ID reappears, its `lost_tracks` entry is consumed → prevents ghost
"lost in" reuse. Fix #11. *Commit `8382e0e`.*

### ✅ BL-05 — REID-SUPPRESS (both +1 and −1)
Suppresses a false +1 (resp. −1) when a known ID reappears after a short
absence while **another** ID that appeared during the absence recently crossed.
Signature = crossing history, not position jump/age alone. Fix #35 (+1). The −1
mirror was added in `f84d36a` (inactive on the 4 test videos). *Commits
`8382e0e` + `f84d36a`.*

### ✅ BL-06 — Resurrection guard (Pattern B safety net)
Detects a jump > 150 px + age > 5 frames. Never triggered on real cases, but
harmless. *Commit `8382e0e`.*

### ✅ BL-07 — Mirror guard (`log` mode)
3 modes (off/log/enforce). 0 candidates found → left in `log` (inert). *Commit
`8382e0e`.*

### ❌ BL-08 — Counting-line hysteresis
Tested at H=25 → **regressed #18** (swallowed a legitimate crossed RIGHT →
over-count). Disabled (H=0). *Abandoned.*

### ✅ BL-09 — `result.json` flush fix
`result.json` was written too early (`infer_thread.join(timeout=300)` +
`display_thread.join(timeout=300)` timed out on long videos → the last crossing
was lost, fix #32). New sequence in validation mode: `infer_thread.join()` (no
timeout) → `frame_queue.join()` (drain) → `stop_event.set()` →
`display_thread.join(60)` → `write_result_json()`. Camera mode unchanged.
*Commit `f84d36a`.*

### ✅ BL-10 — GC `first_seen`/`last_seen`/`trails`
Periodic purge (every 30 frames) of auxiliary dicts for IDs absent longer than
`lost_buffer_frames`. Safe: these structures are only consulted by guards with
a short window (≤ 15 frames). `detections`/`area_in_list`/`area_out_list` are
**not** purged (BL-17). *Commit `c3f8fdf`.*

### ⬜ BL-17 — Residual GC `detections`/`area_in_list`/`area_out_list`
**P0 · M · 🟡.** Follow-up to BL-10: these structures still grow (one entry per
disappeared ID, never purged). Slow growth, but over weeks/months in 24/7 it
adds up.

**Difficulty**: purging too early risks swallowing a legitimate return (a pig
that comes back after a long absence → `crossed RIGHT`/`-1` lost).

**Approach**: very high purge threshold (e.g. 1800 frames = 60 s absence, where
a return is unlikely) + only purge IDs **neither visible nor in `lost_tracks`**.
Validate on videos with returns (#18, #30, #24) before activating.

### ⬜ BL-18 — Graceful shutdown (SIGTERM)
**P1 · S · 🟢.** SIGTERM handler → `stop_event.set()` + thread `join()` +
`result.json` flush + `video_writer.release()`. Avoids result corruption and
zombies on a K3s stop (rolling update, scale-down). Umbrella for BL-43
(code) and BL-46 (manifest).

### ⬜ BL-19 — Memory watch (RSS alert)
**P1 · S · 🟢.** Log + metric if RSS > threshold. Catches a residual leak (BL-17)
before OOM. Pair with BL-21 (`/metrics`).

### ⬜ BL-20 — Auto camera reconnect
**P1 · M · 🟡.** On stream loss / timeout, retry with backoff + reset tracker +
persist the counter. Today a camera crash loses the cumulative count.

## 2. Observability / Operability

### ⬜ BL-21 — Prometheus `/metrics` endpoint
**P1 · M · 🟢.** Expose: `count_total`, `count_net`, `fps`, inference latency,
active tracks, `rss_bytes`, frames processed. Lets K3s/Grafana follow counting
live and eases prod debugging.

### ⬜ BL-22 — Structured JSON logging
**P1 · S · 🟢.** Replace `INFO:[TRACK] ID=1.0 crossed LEFT // Count 1` strings
with JSON (`{"event":"crossed","tid":1,"direction":"left","count":1,"frame":...}`).
ELK/Loki ingestion and filtering get easier.

### ⬜ BL-23 — Counter exposed via API (`/count`)
**P1 · S · 🟢.** `GET /count` →
`{"count":42,"frames_processed":18143,"uptime_s":...}`. Simple read for a
dashboard or orchestrator. Pair with BL-21.

### ⬜ BL-24 — Real-time dashboard
**P2 · L · 🟢.** Simple web page (or Grafana) consuming `/metrics` + `/count`:
live counter, FPS, counting curve, camera stream. Depends on BL-21/BL-23.

## 3. Quality / Testability

### ⬜ BL-25 — `counting.py` unit tests ⭐
**P1 · M · 🟢.** Replay the ID sequences of cases `#35` (REID-SUPPRESS), `#30`
(GUARD_MAX_AGE), `#11` (lost_tracks cleanup) as unit tests, with no video and no
Jetson. Catches counting-logic regressions **in seconds** instead of ~15 min
per video on the Jetson. **High ROI**: safety net for every future `counting.py`
change.

**Approach**: mock `Counting.count()` by injecting a per-frame list
`(track_id, x, y, class_id)` and assert the final `counter_to_right`. Capture
sequences from the `counting_events` logs of validated videos.

### ⬜ BL-26 — Local validation mode
**P1 · M · 🟢.** Run inference on the dev machine (GPU if present) and write
`result.json`, skipping the Jetson K8s/SCP. Speeds up the dev→test loop. Reuse
`validate_on_jetson.sh` in `--local` mode.

### ⬜ BL-27 — CI (lint + compile + tests)
**P1 · S · 🟢.** Pre-commit: `ruff` (lint/format), `py_compile` over
`app/src/`, `pytest` on BL-25. Prevents broken commits (syntax, imports) and
counting regressions.

### ⬜ BL-28 — Track fixtures (ID replay)
**P2 · M · 🟢.** Serialize the ID sequences of validated videos into JSON
fixtures replayable by the tests (BL-25). Allows synthetic scenarios
(ID-switch, long occlusion, return).

## 4. Architecture / Tech debt

### ✅ BL-12 — `settings.py` defaults aligned
`OFFSET 0→10`, `PIG_CONFIDENCE 0.7→0.6`, `DRAW_TRACKING True→False`,
`LOG_LEVEL DEBUG→INFO`, `CAPTURE_INTERVAL 5→1`. `.env` still wins on the Jetson.
*Commit `c3f8fdf`.*

### ✅ BL-13 — Remove `process_for_tracking`
143 lines of dead code (never called). *Commit `c3f8fdf`.*

### ⬜ BL-29 — Refactor `main.py` (658 lines)
**P1 · L · 🟡.** Split into `infer_thread.py`, `display_thread.py`,
`validate.py`, `cli.py`. Each module becomes testable and readable. Big job,
plan once counting logic is stable (post-BL-25).

### ⬜ BL-30 — Align all defaults (paths)
**P2 · S · 🟢.** Follow-up to BL-12: `DATASET_DIR`, `OUTPUT_VIDEO_PATH` depend on
the environment (local vs Jetson). Decide on a single default or auto-detection.

### ⬜ BL-31 — Centralize config (single source)
**P2 · M · 🟢.** Today validated values exist in `.env`, `.env.example`,
`settings.py` (defaults). A single source of truth (e.g. `config.py` + injected
`.env`) avoids drift.

### ⬜ BL-32 — Type hints + docstrings `counting.py`
**P2 · M · 🟢.** `counting.py` is dense (~470 lines, several interleaved guards).
Type hints + per-guard docstrings ease review and onboarding. After BL-25
(tests lock behavior).

## 5. Performance

### ✅ BL-11 — `trails` as `deque(maxlen=60)`
O(1) append + auto-rotation instead of O(n) `pop(0)`. *Commit `c3f8fdf`.*

### ⬜ BL-33 — GPU prefetch (decode + preprocess)
**P2 · M · 🟡.** Decode/preprocess frame N+1 while inferring frame N. Gain if
CPU decode is a bottleneck on the Jetson. Confirm with BL-36 (profiling) first.

### ⬜ BL-34 — numpy vectorization `counting.py`
**P2 · S · 🟢.** The `tracking_boxes` loops are pure Python. Marginal: YOLO
inference dominates. Only if BL-36 shows `counting.py` in the profile.

### ⬜ BL-35 — Headless mode (no `cv2.imshow`)
**P2 · S · 🟢.** Avoids the X11 dependency / display error on a headless
Jetson. Gate `cv2.imshow` behind a `DISPLAY_PREVIEW` flag (default False).

### ⬜ BL-36 — Profiling (py-spy)
**P2 · S · 🟢.** Profile a run on the Jetson to find the real bottlenecks (decode?
inference? counting? rendering?) before investing in BL-33/BL-34.

## 6. Security / Ops

### ✅ BL-14 — `.env.example` + `.gitignore`
`.env` gitignored, `.env.example` versioned (documented defaults). *Commit
`8382e0e`.*

### ⬜ BL-37 — SSH keys (replace `sshpass`) ⭐
**P1 · S · 🟢.** `validate_on_jetson.sh` and the Ansible inventory use `sshpass`
with `JETSON_PASSWORD` in clear text (`.env.local`). Switching to a dedicated
SSH key (deposited once on the Jetson) removes the password and simplifies auth.
**Immediate quick win.**

### ⬜ BL-38 — Secrets via vault / K8s Secret
**P2 · M · 🟢.** Password in an env var = potential leak. Migrate to K8s Secret
(or vault) for prod. Depends on the deployment context.

## 7. Documentation

### ✅ BL-15 — Rename videos + manifest
Convention `validation-<seq>-#<count>.mp4`. *Commit `8382e0e`.*

### ✅ BL-16 — `docs/05_counting_pipeline.md`
Full pipeline: architecture, counting line, OC-SORT tuning, all guards, flush,
parameter table, validation (30/30 pass), limits. *Commit `f84d36a`.*

### ⬜ BL-39 — Guards flow diagram
**P2 · S · 🟢.** ASCII / mermaid diagram of the guards' order
(ID-switch recovery → GUARD_MAX_AGE → REID-SUPPRESS → resurrection → mirror) in
`05_counting_pipeline.md`. Makes the pipeline visual.

### ⬜ BL-40 — README runbook
**P2 · M · 🟢.** Camera startup / validation / debugging, step by step, with the
exact commands and known pitfalls. Currently spread across
`01_quickstart.md` + `05_counting_pipeline.md` + scripts.

### ⬜ BL-41 — Validation matrix (video → fix)
**P2 · S · 🟢.** Table linking each test video to the fix(es) that resolve it
(e.g. `#35` → BL-05 REID-SUPPRESS, `#30` → BL-03 GUARD_MAX_AGE, `#11` → BL-04
cleanup, `#32` → BL-09 flush). Helps debugging and choosing regression videos.

## 8. Production K3s deployment

> **Important recadrage (2026-07-05).** The **real prod manifests** are the
> Jinja2 templates in `k3s/templates/`, deployed via Ansible
> (`ansible/playbooks/app/deploy_countingapp.yml`). The files
> `examples/deploy/k3s_conf/*` are **legacy and not applied in prod** — an
> earlier analysis was wrongly based on them.
>
> **Claims from the earlier analysis INVALIDATED by the recadrage** (do not
> re-create as items):
> - ❌ "No `resources` limits on countingapp" → **false**, `countingapp-dep.j2`
>   already has `requests 2Gi / limits 4Gi` (+ `nvidia.com/gpu: 1`, cpu 500m/2).
> - ❌ "Manifest env inert (`INPUT`/`FILE`/`DRAWTRACKING`)" → **false**, the real
>   template only passes `DISPLAY`; the wrong names existed only in the legacy
>   `examples/deploy/k3s_conf/countingapp-rs.yaml`.
> - ❌ "Ingress broken (port 30501 vs 31501, missing `apiVersion`)" → the legacy
>   `examples/deploy/` ingress is **not deployed** in prod. Reframed as BL-50
>   (add external access, optional).
> - ❌ "`video-compress-fast` not versioned" → **false**, it is in
>   `k3s/templates/cronvideo-dep.j2`.
> - ❌ "`filebrowser:latest` not pinned" → **false**, image
>   `ghcr.io/gtsteffaniak/filebrowser:stable` (pinned). Only `ffmpeg:latest`
>   remains unpinned (BL-49).
> - ❌ "`hostPath /app` live code" → **intentional** (user choice, enables rsync
>   + hot restart for iterations). Do not "fix".
>
> **Observed state on the Jetson (Orin Nano 8 Gi, "Super" 25 W):** RAM 7.4 Gi,
> 5.5 Gi available. The `countingapp` pod is a **DaemonSet** `countingapp-dep.j2`,
> pausable via `nodeSelector: validate-paused=true` (a pause mechanism during
> validations — intentional). `filebrowser` (78 Mi) + `video-compress-fast`
> (411 Mi) run continuously. RESTARTS=50 over 40 days ≈ daily power cut.

### ⬜ BL-42 — Counter persistence (snapshot + reload) ⭐⭐
**P0 · M · 🟡.** `shared_state.counter_to_right` is **strictly in memory**, never
written to disk. `stop()` does not save it. On a pod restart (crash, OOM, K3s
update, **daily power cut**), the counter **falls back to 0** → the operator
loses the cumulative count since morning. `restartPolicy: Always` restarts the
app automatically → the screen comes back, counter at 0, **without the operator
necessarily noticing** → end-of-day reading is wrong. This is **prod risk #1**.

**Fix**: periodic snapshot (e.g. every 30 s or every 10 pigs) into
`/files/count_snapshot.json` (already-mounted volume); on startup, **reload the
day's snapshot** if present. Preserve the "0 in the morning" behavior via a
manual reset (button/flag) or an auto-reset at midnight. **Discuss with the
user**: voluntary morning reset vs reload after crash.

### ⬜ BL-43 — `stop()` finalizes `video_writer` (release)
**P0 · S · 🟡.** `stop()` (called by the SIGTERM handler) **does not release
`video_writer`** (the `release()` is in the `DisplayThread` loop, `main.py:274`,
not in `stop()`). On a K3s SIGTERM → mp4 not finalized (missing moov atom) →
**video unreadable**. Code fix: in `stop()`,
`if self.video_writer: self.video_writer.release()` before the join. Completes
BL-46 (manifest) and BL-18 (umbrella).

### ⬜ BL-44 — Fragmented MP4 (power-cut resistance)
**P1 · M · 🟡.** The power cut (daily stop) hard-cuts the mp4 write → missing
moov atom → corrupt video. `cv2.VideoWriter` does not write the moov at the
start/in fragments. Mitigation: **fragmented / faststart** mp4 (moov at the file
start, or regular fragments) → video recoverable even if cut. Either a native
fragmented muxer, or a periodic ffmpeg remux, or `ffmpeg -movflags +faststart`
post-processing by `video-compress-fast`. Evaluate vs `cv2.VideoWriter`.

### ⬜ BL-45 — `livenessProbe` HTTP `/health`
**P1 · S · 🟢.** `countingapp-dep.j2` has **no probe**. If the app **freezes**
(camera stuck, thread deadlock, severe leak) without crashing, K3s does not
restart → frozen screen, dead counting, operator not alerted. Fix:
`livenessProbe` HTTP `GET /health` returning 200 when inference runs
(FPS > 0 / `counter` recently updated). Needs BL-23 (a `/count` endpoint) or a
minimal `/health` endpoint.

### ⬜ BL-46 — `terminationGracePeriodSeconds` 0→30 s
**P0 · S · 🟢.** `countingapp-dep.j2` has
`terminationGracePeriodSeconds: 0` → K3s sends SIGTERM and **kills immediately**.
`stop()` therefore has **no time** to call `video_writer.release()` → the
in-progress video is corrupted at **every pod stop**. Manifest fix: set to `30`
(gives BL-43 time to finalize). Apply in `k3s/templates/countingapp-dep.j2`.

### ⬜ BL-47 — Reduce `privileged` + remove `docker.sock`
**P2 · M · 🟡.** `countingapp-dep.j2` runs with
`securityContext: privileged: true` **and** mounts `/var/run/docker.sock` → the
pod has access to the host's Docker (can start/kill any container on the node).
Large attack surface. Reduction: go headless (BL-35 removes X11/`DISPLAY`),
`devices` for `/dev/video0` instead of `privileged`, **remove the `docker.sock`
mount** (check why it was there). Acceptable on a dedicated Jetson but to
harden.

### ⬜ BL-48 — Filebrowser creds `admin/admin` → strong password
**P2 · S · 🟢.** `filebrowser-sct.j2` + Ansible defaults (`group_vars/all.yml`:
`admin_username=admin`, `admin_password=admin`) → weak default credentials.
Anyone on the local network can access filebrowser as admin (delete videos).
Fix: strong password via `FILEBROWSER_ADMIN_PASSWORD` in env (not in clear in
the repo), and do not default to `admin`. Secret already in place
(`filebrowser-sct.j2`) — just a weak default to harden.

### ⬜ BL-49 — Pin `ffmpeg:latest`
**P2 · S · 🟢.** `cronvideo-dep.j2` uses `lscr.io/linuxserver/ffmpeg:latest`
(non-reproducible — an image update can break compression). Fix: pin a precise
tag/digest (e.g. `:7.x` or `@sha256:...`).

### ⬜ BL-50 — External access to countingapp (externalIP/ingress)
**P2 · S · 🟢.** `countingapp-svc.j2` is `ClusterIP` **with no externalIP** →
reachable only inside the cluster (`10.43.222.223:31501`). To expose a
dashboard / future API, add either `externalIPs` (the Jetson IP) or a Traefik
Ingress (k3s default). Optional — depends on the external-access need (today
the operator reads the counter on the Jetson's local X11 screen, not over the
network).

### ✅ BL-51 — Video cleanup restricted to `.mp4`
**P2 · S · 🟢.** `cronvideo-dep.j2` did
`find . -type f -size +2G -delete` → deleted **any file >2 GiB** (including an
eventual dataset/model in `/videos`). Restricted to
`find . -maxdepth 1 -type f -name '*.mp4' -size +2G -delete` (only oversized
mp4). The `ls -t count* | awk 'NR>50'` is kept (already scoped to `count*`).
*Commit `61c2e3a`.*

## Recommended order (decreasing ROI)

**Production tier (protects the daily morning→evening + power-cut workflow):**

1. **BL-42** Counter persistence — P0, M, 🟡 — **prod risk #1**: a restart
   (crash/OOM/power cut) resets the counter to 0; snapshot + reload.
2. **BL-43 + BL-46** Finalize the video (`stop().release()` +
   `terminationGracePeriodSeconds` 0→30 s) — P0, S, 🟡/🟢 — finalizes the mp4 at
   pod stop; without it, **every stop = corrupt video**.
3. **BL-25** `counting.py` unit tests — P1, M, 🟢 — safety net for every future
   change; removes systematic Jetson revalidation.
4. **BL-37** SSH keys — P1, S, 🟢 — immediate security quick win.
5. **BL-18** Graceful shutdown (umbrella) — P1, S, 🟢 — covers BL-43/BL-46.
6. **BL-21 + BL-23** `/metrics` + `/count` endpoints — P1, M, 🟢 — prod
   observability; unblocks 24/7 monitoring + BL-45 (`livenessProbe`).
7. **BL-44** Fragmented MP4 — P1, M, 🟡 — video resistance to power cut.
8. **BL-17** Residual GC — P0, M, 🟡 — closes the long-term memory leak.
9. **BL-29** Refactor `main.py` — P1, L, 🟡 — plan post-BL-25.

**BL-42 + BL-43 + BL-46** are the minimum to harden the daily workflow
(persistent counter + non-corrupt videos). The quick wins **BL-37 + BL-25**
then add security + testability without touching the validated counting logic
(🟢 risk).

## Delivery history

| Commit | Items shipped | Summary |
|---|---|---|
| `8382e0e` | BL-01, BL-02 (+1), BL-03, BL-04, BL-05 (+1), BL-06, BL-07, BL-10¹, BL-14, BL-15 | Fix ID-switch (27/27 pass) |
| `f84d36a` | BL-02 (−1 mirror), BL-05 (−1 mirror), BL-09, BL-16 | Bidirectional + flush + docs |
| `c3f8fdf` | BL-10, BL-11, BL-12, BL-13 | 4 quick wins (GC, deque, defaults, dead code) |
| `119501b` | — (initial backlog BL-01..BL-41) | docs: living backlog |
| `61c2e3a` | BL-51 | cronvideo-dep.j2: video cleanup restricted to `.mp4` |

¹ BL-10 sketched in `8382e0e`, finalized in `c3f8fdf`.

**Current state:** 30/30 videos validated (4/4 priority re-validated after the
quick wins, REID-SUPPRESS #35 unchanged). Backlog up to date (BL-01..BL-51: 16
done, 1 abandoned BL-08, 34 to do). Prod manifests recadrage (`k3s/templates/`
via Ansible, not the legacy `examples/deploy/`). Commits local, not pushed.