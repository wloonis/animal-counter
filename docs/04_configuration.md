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
parameters come from `.env`. (The legacy `examples/deploy/k3s_conf/*.yaml`
injected `INPUT`/`FILE`/`DRAWTRACKING` with wrong names — those are unused and
inert; do not rely on them.)

## Parameter reference

### Input & output

| Key | Default | Meaning |
|-----|---------|---------|
| `INPUT_SOURCE` | `CAMERA` | `CAMERA` (live `/dev/video0`) or `FILE` (a video file) |
| `VIDEO_PATH` | `/dev/video0` | Device (CAMERA) or file path (FILE) |
| `OUTPUT_WIDTH` / `OUTPUT_HEIGHT` | 640 / 480 | Inference/processing frame size |
| `OUTPUT_SCREEN_WIDTH` / `OUTPUT_SCREEN_HEIGHT` | 1024 / 600 | Display window size |
| `FPS_OUTPUT` | 30 | Camera/video frame rate — do not change |
| `OUTPUT_VIDEO_PATH` | `/files` | Where annotated output videos are written |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

### Counting line & detection

| Key | Default | Meaning |
|-----|---------|---------|
| `OFFSET_PERCENT_COUNTING_LINE` | 10 | Line at `x = width/2 + width*OFFSET/100` → ≈ 384 px on a 640 px frame |
| `PIG_CONFIDENCE_THRESHOLD` | 0.6 | Min confidence to count a pig |
| `PIG_CONFIDENCE_THRESHOLD_START_VIDEO` | 0.8 | Higher threshold for the first frames of a recording |
| `CONF_THRESH` | 0.5 | YOLO raw confidence (pre-tracker) |
| `IOU_THRESHOLD` | 0.45 | YOLO NMS IoU |
| `TOP_IGNORE` / `BOTTOM_IGNORE` | 100 / 50 | Ignore detections in the top/bottom bands (px) |
| `DRAW_TRACKING` | `False` | Draw tracking boxes/IDs on the output |
| `CENTROID_TRACKING` / `BOX_TRACKING` | True / True | What to draw when `DRAW_TRACKING=True` |

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

- **Runtime parameter change** (no rebuild): edit `app/.env` on the Jetson and
  restart the pod:
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