# 04 — Configuration

The app is configured by **`app/.env`** (gitignored), loaded by
`app/src/settings.py`. Copy the versioned `app/.env.example` and adjust:

```bash
cp app/.env.example app/.env
```

> The values in `.env.example` are the **validated production values** for the
> pig-counting use case (fixed camera, 30 fps, pigs counted right→left) and are
> also the `settings.py` defaults, so a missing `.env` still boots sane. `.env`
> overrides the defaults at runtime.

## Precedence

1. `app/.env` (present on the Jetson at
   `/data/orin/git/animal-counting/app/.env`, the hostPath mounted into the pod)
2. `settings.py` built-in defaults (aligned with `.env.example`)

The K3s manifest `countingapp-dep.j2` only injects `DISPLAY=:0`; all other
parameters come from `.env`.

## Shared hostPaths: `/files` (data) vs `/conf` (config/control)

The countingapp pod mounts two hostPaths for companion⇄countingapp IPC
(see [`IPC_CONTRACT.md`](IPC_CONTRACT.md)):

- **`/files`** (hostPath `/data/orin/files`) — **data**: the append-only
  event log (`counting-history.jsonl`), recorded clips (`counting-*.mp4`),
  and the learning dataset (`dataset/`). These files are owned by the
  countingapp; the companion reads them read-only.
- **`/conf`** (hostPath `/data/orin/conf`) — **config/control**: live
  runtime settings (`runtime-settings.json`, hot-reloaded by the companion
  via `PUT /api/settings`) and the power-off sentinel (`.arret_requested`,
  written by the companion via `POST /api/power`). These are written by the
  companion and read by the countingapp.

> **BL-79:** `runtime-settings.json` and `.arret_requested` were
> previously in `/files`. They are now in a dedicated `/conf` hostPath to
> separate config/control from data. The companion (sister repo) must be
> updated to write to `/data/orin/conf` (coordinated in a separate BL).

Both hostPaths are created by the Ansible deployment
(`ansible/playbooks/app/deploy_countingapp.yml`), which also migrates
existing `runtime-settings.json` and `.arret_requested` from `/files` to
`/conf` on first deploy (idempotent).

## Parameter reference

### Input & output

| Key | Default | Meaning |
|-----|---------|---------|
| `INPUT_SOURCE` | `CAMERA` | `CAMERA` (live `/dev/video0`) or `FILE` (a video file) |
| `VIDEO_PATH` | `/dev/video0` | Device (CAMERA) or file path (FILE) |
| `OUTPUT_WIDTH` / `OUTPUT_HEIGHT` | 640 / 480 | Recording (writer) frame size |
| `OUTPUT_SCREEN_WIDTH` / `OUTPUT_SCREEN_HEIGHT` | 1024 / 600 | Display window size |
| `FPS_OUTPUT` | 30 | Camera/video frame rate — do not change |
| `OUTPUT_VIDEO_PATH` | `/files` | Where annotated output videos are written |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

> **BL-93 — per-model input override (startup-only).** The `INPUT_SOURCE`,
> `VIDEO_PATH`, `INPUT_WIDTH`, `INPUT_HEIGHT`, `FPS_OUTPUT` env defaults above
> are the **fallback**. At startup, the active model's section in
> `/conf/runtime-settings.json` may override them per-model with:
> `input_source` (`CAMERA`/`STREAM`/`FILE`), `input_url` (RTSP URL, required for
> `STREAM` — e.g. sheep drone 720p), `input_device` (V4L2 path, required for
> `CAMERA`), `input_width`/`input_height` (capture resolution, decoupled from
> the recording `OUTPUT_WIDTH/HEIGHT`), `output_fps` (writer frame rate,
> replaces the hardcoded 30 — fixes the 30fps-writer vs 15fps-FP16@1280
> time-compression bug). These are read **once at startup** (not hot-reloaded);
> switching the physical sensor (camera ↔ drone) is a restart, not a hot-swap.
> Invalid/absent values log a WARNING and fall back to the env defaults above.
> Precedence: CLI `-m`/`-f` (validation/test) > per-model `input_source` > env
> `INPUT_SOURCE`. See `docs/IPC_CONTRACT.md`.

### Build precision (per-model)

`app/build-config.json` selects the TensorRT engine **build precision + imgsz**
per model (read by `app/entrypoint.sh` `build-engine` path, keyed by
> `MODEL_NAME`):

| Model | `precision` | `imgsz` | Why |
|-------|------------|--------|-----|
| `my_model` (pig, legacy) | `fp32` | 640 | 30 FPS on Orin Nano — pigs at 640 need no quantization |
| `sheep_template` / `sheep_goat_template` | `fp16` | 1280 | ~13–15 FPS at 1280 (FP32 would be too slow); recall needs the 1280 resolution |

Default `fp32` (backward compat — unknown models build FP32). The engine
> artifact is named after the dataset dir: `model_name = basename(TRAINING_PROJECT_DIR)`
> (e.g. `sheep_goat_template.engine`), fallback `my_model` for legacy deploys.
> The build-engine k3s Job runs the hostPath `/app/entrypoint.sh` (always current
> via rsync — no image rebuild needed for `entrypoint.sh` changes); see
> `docs/03_deployment.md`.

### Snapshot writer (BL-88)

These are **boot params** (read once at startup from `app/.env` via
`settings.py`) — they are **not** hot-reloaded via `/conf/runtime-settings.json`
and require a pod restart to change. The writer itself lives in
`app/src/display_thread.py` and runs inside the existing display loop (no new
thread): it encodes the raw counting-resolution frame to JPEG and writes it
atomically (tmp + `os.replace`) so the companion's `GET /api/snapshot`
(BL-88, PR #19) can serve a live preview to the Android mask-zone editor.

| Key | Default | Meaning |
|-----|---------|---------|
| `SNAPSHOT_ENABLED` | `true` | Master toggle for the raw-frame JPEG snapshot writer |
| `SNAPSHOT_INTERVAL_SECONDS` | 5.0 | Min wall-clock seconds between snapshot writes (time-gated, not per-frame) |
| `SNAPSHOT_PATH` | `/files/snapshot.jpg` | Destination path (atomic tmp+rename; the companion serves this file) |
| `SNAPSHOT_JPEG_QUALITY` | 85 | JPEG encode quality (0–100, passed to `cv2.imencode`) |

### Counting line & detection

| Key | Default | Meaning |
|-----|---------|---------|
| `OFFSET_PERCENT_COUNTING_LINE` | 10 | Line at `x = width/2 + width*OFFSET/100` → ≈ 384 px on a 640 px frame |
| `PIG_CONFIDENCE_THRESHOLD` | 0.6 | Min confidence to count a pig |
| `PIG_CONFIDENCE_THRESHOLD_START_VIDEO` | 0.8 | Higher threshold for the first frames of a recording |
| `CONF_THRESH` | 0.5 | YOLO raw confidence (pre-tracker) |
| `IOU_THRESHOLD` | 0.45 | YOLO NMS IoU |
| `DRAW_TRACKING` | `False` | Draw tracking boxes/IDs on the output |

> **Migration (BL-94):** the old fixed top/bottom band pixel crops were removed. Use `MASK_ZONES` below (normalized rects) — e.g. `{x:0,y:0,w:1,h:100/H}` for the top band, `{x:0,y:(H-50)/H,w:1,h:50/H}` for the bottom band — editable from the companion UI (BL-88).
| `CENTROID_TRACKING` / `BOX_TRACKING` | True / True | What to draw when `DRAW_TRACKING=True` |
| `MASK_ZONES` | `[]` | **(BL-87)** normalized axis-aligned exclusion rects `{x,y,w,h}` in `[0..1]`; detections whose centroid falls inside any rect are dropped before tracking (no track → no count). Default `[]` = no-op |
| `DRAW_MASK_ZONES` | `True` | **(BL-87)** draw a semi-transparent overlay of the `mask_zones` rects (independent of `DRAW_TRACKING`) |
| `COUNTING_DIRECTION_MODE` | `auto` | **(BL-92)** `auto` (default) auto-detects the dominant crossing direction per run via a warm-up (N=3 crossings or T=10s, then lock), or `manual` for an operator-set +1. Boot default for the runtime-settings key `counting_direction_mode` |
| `COUNTING_DIRECTION` | `null` | **(BL-92, manual only)** the +1 direction, one of `up`/`down`/`left`/`right`, validated vs the active `COUNTING_LINE_ORIENTATION` (horizontal → `up`/`down`, vertical → `left`/`right`); `null` = auto/default. Boot default for the runtime-settings key `counting_direction` |

### Learning mode (optional)

| Key | Default | Meaning |
|-----|---------|---------|
| `DATASET_DIR` | `/files/dataset` | Captured dataset output |
| `CAPTURE_INTERVAL` | 1 | Capture every N frames |
| `MAX_LEARNING_DURATION` | 600 | Max learning session (s) |
| `MAX_VIDEO_DURATION` | 3600 | Max recording duration (s) |

### OC-SORT tracker tuning (anti-ID-switch)

| Key | Default | Meaning |
|-----|---------|---------|
| `TRACKER_LOST_TRACK_BUFFER` | 20 | Frames a lost track is kept alive (~0.67 s @ 30 fps) |
| `TRACKER_FRAME_RATE` | 30.0 | Used to scale the lost buffer into time |
| `TRACKER_MIN_CONSECUTIVE_FRAMES` | 5 | Frames before a stable tracker_id is assigned (filters ephemeral tracks) |
| `TRACKER_MIN_IOU_THRESHOLD` | 0.3 | Detection/track association IoU |
| `TRACKER_HIGH_CONF_THRESHOLD` | 0.6 | Detections below this are dropped by the tracker before association |
| `TRACKER_DIRECTION_CONSISTENCY_WEIGHT` | 0.25 | OCM direction-term weight |
| `TRACKER_DELTA_T` | 3 | OCM velocity-direction temporal window |
| `COUNTING_TRACKER_IOU` | `giou` | Association similarity function (`iou`/`giou`, trackers ≥ 2.5.0). See [GIoU activation](#giou-association-counting_tracker_iou) below. |

### Counting guards (see [`05_counting_pipeline.md`](05_counting_pipeline.md))

| Key | Default | Meaning |
|-----|---------|---------|
| `COUNTING_LOST_BUFFER_FRAMES` | 60 | Global expiration age of `lost_tracks` (long, ~2 s) |
| `COUNTING_GUARD_MAX_AGE` | 15 | Max age (frames) of a lost track eligible for guard fusion (short, ~0.5 s) |
| `COUNTING_REASSOC_LINE_BAND` | 200 | Lost track must be within this band (px) of the line |
| `COUNTING_REASSOC_MAX_DIST_X` / `_Y` | 120 / 80 | Max distance (px) for fusion |
| `COUNTING_REID_WINDOW` | 15 | Max age (frames) of a crossing to be "recent" |
| `COUNTING_REID_MIN_AGE` | 3 | Min absence (frames) for an ID to be suspicious |
| `COUNTING_RESURRECTION_MIN_JUMP` | 150 | Min position jump (px) for the resurrection guard |
| `COUNTING_RESURRECTION_THRESHOLD` | 5 | Min absence age (frames) for the resurrection guard |
| `COUNTING_HYSTERESIS_PX` | 0 | Dead-band around the line — **keep 0** (non-zero regressed #18) |
| `COUNTING_MIRROR_GUARD` | `log` | `off` / `log` / `enforce` (0 candidates found → left inert in `log`) |
| `COUNTING_MIRROR_MAX_AGE` | 15 | Max age of a lost "out" track |
| `COUNTING_MIRROR_LINE_BAND` / `_NEW_BAND` | 100 / 120 | Band (px) of the line for lost "out" / new right ID |
| `COUNTING_MIRROR_MAX_DIST_Y` | 60 | Max vertical distance (px) for fusion |

## Applying changes

- **Live runtime-settings change** (BL-86, no pod restart): the fields in
  `/conf/runtime-settings.json` — `draw_tracking`, `box_tracking`,
  `centroid_tracking`, `offset_counting_line`, `counting_line_orientation`,
  `counting_class_ids`, `mask_zones`, `draw_mask_zones`,
  `counting_direction_mode`, `counting_direction` — are **hot-reloaded in-process**. Write them from the
  companion via `PUT /api/settings` (or edit `/conf/runtime-settings.json`
  directly). A lightweight `RuntimeSettingsWatcher` thread in the countingapp
  polls the file mtime (~2 s); on a valid change it stores the new values as
  **pending** and applies them **only at the next idle window** (when no
  recording is in progress) — never mid-recording. So a settings change takes
  effect at the end of the current recording (or immediately if already idle),
  with no pod restart.
  - `counting_class_ids` change at idle resets the running counter +
    per-species sub-counters to 0 (fresh-session semantics); a line-only
    (`offset_counting_line` / `counting_line_orientation`), toggle-only, or
    `mask_zones` change does **not** reset (a mask change alters *where* we
    count, not *what* we count — analogous to the line offset). A
    `counting_direction` change (BL-92) resets likewise — a +1 flip
    invalidates already-counted crossings; a mode-only
    (`counting_direction_mode` `auto`↔`manual`) change with no effective +1
    change does **not** reset.
  - This does **not** cover `app/.env` (build/boot params) — those still need
    a pod restart (see next).
- **Boot/build parameter change** (no rebuild): edit `app/.env` on the Jetson
  and restart the pod:
  ```bash
  ssh $JETSON_USER@$JETSON_IP "kubectl delete pod -n countingapp-dev -l app=countingapp"
  ```
  The hostPath `/app` mount picks up the new `.env` immediately on restart.
- **Manifest change** (resources, image, probes…): edit `k3s/templates/*.j2`
  and re-run `ansible/playbooks/app/deploy_countingapp.yml`.

## Validation config

Separate from the app: `validation/config.json` and
`validation/expected_counts.json` drive the validation script — see
[`06_validation.md`](06_validation.md).

## GIoU association (`COUNTING_TRACKER_IOU`)

Starting with `trackers` 2.5.0, `OCSORTTracker` accepts an `iou=` kwarg that
selects the detection/track association similarity function. The app exposes
this as `COUNTING_TRACKER_IOU` (default `giou`).

### Why GIoU is activated by default

ID-switch at the counting line — our primary defect — happens when OC-SORT
loses a pig's track during an occlusion and assigns a new ID on the other
side. **Generalized IoU** (`giou`) rewards geometric overlap **and** penalizes
non-overlapping boxes, which helps keep a pig's ID through partial occlusions.
This targets the root cause directly, so it is activated by default to measure
the benefit on the 4 ID-switch-prone priority validation videos.

### Score range: [-1, 1] vs [0, 1]

Standard IoU scores live in `[0, 1]`. GIoU scores live in `[-1, 1]` (a negative
score means the boxes don't overlap and are far apart). Because the scales
differ, `TRACKER_MIN_IOU_THRESHOLD` (0.3, tuned for standard IoU) **may not
transfer directly** to GIoU. The validation gate is **4/4 strict**: if a
count mismatch appears under GIoU, lower `TRACKER_MIN_IOU_THRESHOLD` toward
**0.2–0.3** and re-run `bash scripts/validate_on_jetson.sh --full`. Repeat
until 4/4 pass or the search range is exhausted. **Do not auto-correct a
count mismatch** — report it; the user decides.

### HITL fallback

If 4/4 cannot hold after re-tuning, revert to **`COUNTING_TRACKER_IOU=iou`**
(standard IoU = identical pre-2.5.0 association behavior, the safe baseline)
and re-validate 4/4 to confirm the IoU path still passes. Document in
[`05_counting_pipeline.md`](05_counting_pipeline.md) that GIoU is **not
beneficial** on this dataset. The user decides whether to keep GIoU off or
investigate further; no automatic count correction.

### Free fixes in 2.5.0 (independent of `iou=`)

The upgrade also picks up robustness fixes that apply regardless of the
association function:

- **Per-instance tracker IDs** — each `OCSORTTracker` instance now has its own
  ID counter (previously shared/global); avoids cross-instance ID collisions.
- **NaN/inf coordinate handling** — detections with non-finite coordinates no
  longer crash the tracker.
- **`py.typed`** — the package ships a PEP 561 marker, enabling static type
  checking for future type-hint work.

### Accepted values

| Value | Behavior |
|-------|----------|
| `iou` | Standard IoU `[0,1]` — identical to pre-2.5.0; safe revert target |
| `giou` | Generalized IoU `[-1,1]` — activated, targets occlusions/ID-switch (default) |

Other variants (`ciou`, `diou`, `eiou`) exist but are not evaluated for this
use case.

> **OCR OC-SORT caveat**: the OCR (2nd-chance) path inside the library always
> uses standard IoU regardless of `iou=`. We use `OCSORTTracker`, not OCR, so
> this is informational only.