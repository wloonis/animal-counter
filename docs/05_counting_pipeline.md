# 05 — Counting pipeline

This document describes the full counting processing and the techniques used
to obtain a reliable count, along with the parameters and trade-offs validated
on 30 reference videos.

## 1. Overview

The system counts pigs crossing a vertical line, in the **right → left**
direction (fixed camera, 30 fps). Each pig that crosses right→left counts
**+1**; a left→right return counts **−1** (the net counter reflects the real
number of pigs that have passed).

The main challenge is **ID-switch**: OC-SORT sometimes loses a pig's track near
the line (occluded by another pig) and assigns it a new ID on the other side.
Depending on when and on which side the switch happens, this can
**under-count** (the crossed pig is never seen crossing) or **over-count** (the
pig is counted twice, once under each ID). The counting logic detects and
corrects these cases with a series of **complementary guards**, without
changing the tracker (OC-SORT is kept).

## 2. Pipeline architecture

Two threads cooperate through a `frame_queue` (max size 3, backpressure):

```
InferThread (capture + detection)
  ├── read frame (camera /dev/video0 or video file)
  ├── YOLO detection (TensorRT) → bounding boxes + scores + classes
  ├── post_process (NMS, conf filter, mask_zones centroid pre-filter) → boxes_pp
  └── frame_queue.put([image, boxes_pp, ...])

DisplayThread (tracking + counting + rendering)
  ├── frame_queue.get()
  ├── rebuild detections (xyxy, confidence, class_id)
  ├── OC-SORT .update(detections) → tracked boxes/IDs/classes
  ├── filter tracker_id == -1 (no track associated)
  ├── Counting.count(image, boxes, trackids, classids, ...)
  └── render / video write
```

- **Detection**: YOLO (TensorRT), confidence `PIG_CONFIDENCE_THRESHOLD` (0.6),
  stronger threshold on the first frames
  `PIG_CONFIDENCE_THRESHOLD_START_VIDEO` (0.8). YOLO NMS `IOU_THRESHOLD`
  (0.45), `CONF_THRESH` (0.5). **(BL-87)** `post_process` also applies an
  optional `mask_zones` centroid pre-filter: after the `counting_class_ids`
  class filter and before NMS, any detection whose centroid
  `((x1+x2)/2, (y1+y2)/2)` falls inside a normalized exclusion rect is dropped.
  Dropping the detection before the tracker means no track is ever created for a
  masked region → it can never cross the line → it can never be counted
  (no-track→no-count). Default `[]` = no-op (byte-identical behavior).

  > **Design note — why the mask is post-inference, not a GPU parameter.**
  > The TensorRT engine is a compiled YOLO network with a **single input
  >  binding** (the preprocessed image tensor, fixed shape `input_w × input_h`);
  > it has no "mask zones" input. This is not a missing feature but a
  >  structural property of dense conv networks: a forward pass's compute is
  >  **determined by the input shape, not by the pixel content**. The
  >  convolutions sweep the entire spatial grid regardless of whether the
  >  pixels are real or blacked-out, so **masking the input would not speed up
  >  the GPU at all** (same FLOPs) — and it would add a per-frame fill cost plus
  >  risk detection artifacts at the sharp mask/real boundary (YOLO can
  >  hallucinate partial objects there; contextual features leak across the
  >  edge). TensorRT has no API to "skip a spatial region" of a standard YOLO
  >  backbone (that would be a sparse/masked-conv architecture, i.e. a
  >  different network to retrain + recompile). Tiling (inferring only on
  >  unmasked tiles) is also counter-productive on a single Jetson: multiple
  >  small inferences under-utilize the GPU (kernel-launch overhead) and are
  >  usually slower than one full-frame pass, while breaking the counting-line
  >  geometry. The real efficiency lever is therefore necessarily
  >  **post-inference (CPU)**, where the cost scales with the **number of
  >  detections**: NMS (O(n²)) and especially OC-SORT tracking (the dominant
  >  CPU cost). Dropping masked detections **after decode, before NMS and
  >  before tracking** (vectorized numpy over detections, Python loop only over
  >  the few zones) minimizes exactly those costs, and is a **no-op when
  >  `mask_zones` is empty** (zero overhead in the default production case).
- **Tracking**: `OCSORTTracker` (lib `trackers`), see §4.
- **Counting**: `Counting.count()`, see §3 and §5.

## 3. The counting line and basic counting

### Line position

```
x = img_width / 2 + img_width * OFFSET_PERCENT_COUNTING_LINE / 100
```

With `OFFSET_PERCENT_COUNTING_LINE = 10` and `img_width = 640`, the line is at
`x = 384`. The regions are:

- **"in" side (right)**: `cx > x`  → `area_in_list`
- **"out" side (left)**: `cx ≤ x` → `area_out_list`

(`cx` = x of the bbox centroid.)

### Basic counting (crossed LEFT / RIGHT)

For each already-known ID, the current position is compared to the previous:

- **crossed LEFT** (`cx ≤ x_low` and ID was in `area_in_list`) →
  `counter += 1`, ID moves to `area_out_list`.
- **crossed RIGHT** (`cx ≥ x_high` and ID was in `area_out_list`) →
  `counter -= 1`, ID moves to `area_in_list`.

`x_low = x − H` and `x_high = x + H` with `H = COUNTING_HYSTERESIS_PX`
(hysteresis, see §5.7).

### Why this is not enough

If a pig crosses the line but OC-SORT loses its ID just before and assigns a
new one just after, **neither ID visibly crosses the line**: the old ID
disappears on the "in" side, the new ID appears on the "out" side. Basic
counting sees no `crossed LEFT` → **under-count by 1**. This is what the
**ID-switch recovery** guard fixes (§5.1).

Conversely, if an ID is lost on the "in" side and then **re-attributed**
(OC-SORT reattaches a left detection to the old ID), that ID reappears on the
"out" side and fires a `crossed LEFT` while **another ID** already crossed for
the same pig during the absence → **over-count by 1**. This is what
**REID-SUPPRESS** fixes (§5.4).

## 4. OC-SORT tracker (anti-ID-switch tuning)

OC-SORT (`OCSORTTracker`) is configured via `settings.py`:

| Parameter | Value | Role |
|---|---|---|
| `TRACKER_LOST_TRACK_BUFFER` | 20 | frames a lost track stays alive (~0.67 s @ 30 fps). Trade-off: larger survives longer occlusions but can re-bind to a wrong detection (over-count); smaller under-counts. |
| `TRACKER_HIGH_CONF_THRESHOLD` | 0.6 | detection confidence **before** association. 0.5 let noisy detections (0.5–0.6) through that spawned ghost tracks. 0.6 keeps only confident pigs; OC-SORT's 2nd-chance rescues occluded ones. |
| `TRACKER_MIN_IOU_THRESHOLD` | 0.3 | min detection/track association IoU. Too low = wrong re-binds. |
| `TRACKER_MIN_CONSECUTIVE_FRAMES` | 5 | consecutive frames before a track gets a stable `tracker_id`. Filters ephemeral tracks (a human walking through, noise) that would have an ID and could cross the line (false ±1). 3 was too permissive. |
| `TRACKER_DIRECTION_CONSISTENCY_WEIGHT` | 0.25 | direction-consistency term weight (OCM). |
| `TRACKER_DELTA_T` | 3 | velocity-direction temporal window (OCM). |
| `TRACKER_FRAME_RATE` | 30.0 | used to scale the lost buffer into a time value. |
| `COUNTING_TRACKER_IOU` | `giou` | association similarity function (trackers ≥ 2.5.0, `iou=` kwarg). `giou` = Generalized IoU, activated to target occlusions/ID-switch at the line; score range `[-1,1]` so `TRACKER_MIN_IOU_THRESHOLD` may need re-tuning. `iou` = standard IoU = identical pre-2.5.0 behavior; safe revert target. See [`04_configuration.md`](04_configuration.md#giou-association-counting_tracker_iou). |

IDs with `tracker_id == -1` (no track associated by OC-SORT) are filtered out
before counting.

### 4.1 `trackers` 2.5.0 upgrade & pluggable IoU

The library was bumped from 2.4.0 to **2.5.0**. The relevant change is the
pluggable `iou=` association function: **GIoU is activated by default**
(`COUNTING_TRACKER_IOU=giou`) to measure whether it reduces ID-switch on the
4 ID-switch-prone priority validation videos. GIoU's score range is `[-1,1]` ≠
`[0,1]` (standard IoU), so `TRACKER_MIN_IOU_THRESHOLD` may need re-tuning and
re-validation (4/4 strict). **`iou`** (standard IoU) is the safe revert target
— it reproduces the pre-2.5.0 association behavior exactly.

The upgrade also ships free robustness fixes (independent of `iou=`):
per-instance tracker IDs, NaN/inf coordinate handling, and a `py.typed`
marker (PEP 561) for future type-hint work.

> **OCR OC-SORT caveat**: the library's OCR (2nd-chance) path always uses
> standard IoU regardless of `iou=`. We use `OCSORTTracker`, not OCR, so this
> is informational only.

### 4.2 Why 2.5.0 does not simplify `counting.py`

The anti-ID-switch guards in [`counting.py`](#5-advanced-counting-techniques-anti-id-switch-guards)
— REID-SUPPRESS, bidirectional ID-switch recovery, `GUARD_MAX_AGE`,
`lost_tracks` cleanup, resurrection, and the mirror guard — are **business
line-crossing logic**: they reason about which side of the counting line a
track is on, when it crossed, and whether a re-ID double-counts. The `trackers`
library implements **track association**, not line-crossing semantics, so it
has no equivalent of these guards. **2.5.0 cannot épurer `counting.py`.**
(The dead `process_for_tracking` code was already removed.)

## 5. Advanced counting techniques (anti-ID-switch guards)

All these guards live in `Counting.count()`. They are **cumulative and
complementary**: each targets a precise ID-switch signature.

### 5.1 ID-switch recovery guard (bidirectional fusion)

**Target**: under-count when a pig crosses but is lost right before the line
and reappears with a new ID on the other side. Handles **both directions**:

- **right → left (+1)**: pig lost on the "in" side (right), new ID on the "out"
  side (left) → fusion with a lost "in" → **+1** (crossed LEFT).
- **left → right (−1)**: pig already crossed (+1) that **returns**, lost on the
  "out" side (left), new ID on the "in" side (right) → fusion with a lost "out"
  → **−1** (crossed RIGHT). Without this branch the return would be
  under-counted (the −1 lost).

**Mechanism**:
1. Each frame, detect **newly lost** IDs (`prev_visible_ids − current_ids`).
   For each, record its last position and side in
   `lost_tracks[tid] = {cx, cy, side, frame}`. Recorded **once** (at the
   visible→absent transition), not every absence frame → readable logs and
   correct age.
2. When a **new ID** appears **already on the left** (`cx ≤ x`), search
   `lost_tracks` for a track lost on the **"in"** side (right), recent
   (age ≤ `COUNTING_GUARD_MAX_AGE`), near the line (band
   `COUNTING_REASSOC_LINE_BAND`) and spatially close (dx ≤
   `COUNTING_REASSOC_MAX_DIST_X`, dy ≤ `COUNTING_REASSOC_MAX_DIST_Y`).
3. If found → **fusion**: depending on the appearance side, `counter += 1`
   (crossed LEFT, lost "in") or `counter -= 1` (crossed RIGHT, lost "out"). The
   ID is marked on the destination side (`area_out_list` for +1,
   `area_in_list` for −1), the lost track is consumed. The crossing is recorded
   in `recent_crossings` (for REID-SUPPRESS, §5.4, both directions).

> The new ID is placed in the **destination** side list (not the source) to
> avoid a spurious follow-up crossing doubling the count.

### 5.2 Decoupling GUARD_MAX_AGE vs LOST_BUFFER_FRAMES

Two distinct ages coexist:

- **`COUNTING_LOST_BUFFER_FRAMES` (60)**: **global** expiration of
  `lost_tracks` (memory cleanup). **Long** (~2 s) so the guard can fuse a lost
  "in" with a new left ID even after a long occlusion at the line (critical for
  high-occlusion videos).
- **`COUNTING_GUARD_MAX_AGE` (15)**: **eligibility** age of a lost "in" for
  fusion. **Short** (~0.5 s) so a **stale** lost "in" belonging to **another**
  pig (or one already crossed under another ID) is not fused with a new left ID
  → false +1 (cases #30/#11).

This decoupling lets two contradictory requirements coexist: long occlusions
(need a long buffer) and rejection of stale fusions (need a short age).

### 5.3 Cleanup of `lost_tracks` on ID return (fix #11)

**Target**: over-count when a lost "in" **persists** in `lost_tracks` and is
reused later by the guard to fuse with **another** new left ID (the original pig
may have already crossed under its own ID).

**Mechanism**: when an ID **reappears** (`if track_id in self.detections`
branch), its entry in `lost_tracks` is **consumed**
(`del self.lost_tracks[track_id]`). Thus a lost "in" cannot be reused by the
guard for a different new ID — the "ghost lost in" is eliminated as soon as the
ID reappears.

### 5.4 REID-SUPPRESS (fix #35)

**Target**: over-count when a known ID (on the "in" side, not yet counted)
**reappears on the left** after an absence, while **another ID** — that
**appeared during that absence** — already crossed (recent `crossed LEFT`).
That other ID is almost certainly a **re-ID of the same pig** (already
counted) → the reappeared ID's +1 would be a double-count.

**Mechanism**:
- Keep `recent_crossings = [{frame, tid, direction}]` (cleaned each frame, keep
  age ≤ `COUNTING_REID_WINDOW` = 15).
- Keep `first_seen[tid]` (first appearance frame) and `last_seen[tid]` (last
  appearance frame).
- When an "in" ID reappears on the left (`cx ≤ x_low`) with absence age ≥
  `COUNTING_REID_MIN_AGE` (3), search `recent_crossings` for a `crossed LEFT`
  by an **other** `tid` where `first_seen[other] > last_seen[current]` (the
  other ID **appeared during the current's absence**).
- If found → **suppress the +1**: the ID moves to the "out" side, lost_tracks
  cleaned, **no counter change**.

**Mirror (false −1)**: the same logic applies in the reverse direction. An
"out" ID (left, already counted +1) that reappears on the right after an
absence, while another ID that appeared during the absence recently
`crossed RIGHT`, is a re-ID of the same returning pig (the other ID already did
the −1) → the reappeared ID's −1 is **suppressed** (otherwise double −1).

**Key insight**: the signature of a re-ID double-count is **not** the position
jump or absence age alone (which can be small), but that **another ID that
appeared during the absence crossed recently**. A legitimate occluded crossing
has **no other ID appearing** during the absence → it fires normally.

### 5.5 Resurrection guard (Pattern B — safety net)

**Target**: re-ID by a large **position jump** (OC-SORT reattaches a left
detection to an old right ID; the right→left jump would fire a false
`crossed LEFT`).

**Mechanism**: if a known ID reappears with a horizontal jump
`> COUNTING_RESURRECTION_MIN_JUMP` (150 px) AND an absence
`> COUNTING_RESURRECTION_THRESHOLD` (5 frames) → **reset** its zone to the
current position, **without changing the counter**, and clean its lost track.

> Safety net: on the real cases observed the jumps were < 150 px (the real
> fix for #35 is REID-SUPPRESS). This guard never triggered on validation but
> stays harmless for huge re-ID jumps.

### 5.6 Mirror guard (`log` mode — inert)

**Target**: mirror of the ID-switch — a pig crosses (+1), is lost on the "out"
side (left), gets a new ID on the "in" side (right) that will cross again
(+1 = over-count).

**Mechanism**: 3 modes (`COUNTING_MIRROR_GUARD`):
- `off`: disabled.
- `log` (default): detect and log candidates without changing the count.
- `enforce`: suppress the new ID's next `crossed LEFT`.

> Left in `log`: **0 candidates** found on the validation set → inert. Kept for
> observation, with no count impact.

### 5.7 Hysteresis (disabled, H = 0)

A **dead-band** of `H = COUNTING_HYSTERESIS_PX` pixels around the line: a
crossing is counted only once the centroid passes `x ± H`, to absorb bbox
jitter right on the line.

> **H = 0**: tested at H = 25, hysteresis **swallowed a legitimate
> `crossed RIGHT`** (a pig going left→right but staying in the dead-band),
> leaving its later `crossed LEFT` uncompensated → over-count (demonstrated on
> #18). So disabled.

## 6. Result serialization (validation mode)

In validation mode (`RESULT_JSON_PATH` set), `main` must write `result.json`
**after** all pigs have been counted. A flush bug wrote the result too early
(joins with `timeout=300` too short for long videos → the `DisplayThread` had
not drained its last frame → the last pig was lost).

**Fix** (`cli.py`, validation mode only — moved out of `main.py` in BL-29):
```python
# 1) Wait for the InferThread to finish (full video read)
shared_state.infer_thread.join()          # no short timeout
# 2) Wait for the DisplayThread to process EVERY queued frame
shared_state.frame_queue.join()           # block until task_done() for each frame
# 3) Stop the DisplayThread (otherwise infinite loop on get(timeout=1))
shared_state.stop_event.set()
shared_state.display_thread.join(timeout=60)
# 4) Serialize
write_result_json(...)
```

> This block is under `if result_json_path:` → **does not apply to camera
> mode** (which counts continuously and serializes no end `result.json`).

## 7. Counting parameters (recap)

| Parameter | Value | Role / justification |
|---|---|---|
| `OFFSET_PERCENT_COUNTING_LINE` | 10 | line position (x ≈ 384 on 640 px) |
| `COUNTING_LOST_BUFFER_FRAMES` | 60 | global expiration of lost_tracks (long, for occlusions) |
| `COUNTING_GUARD_MAX_AGE` | 15 | eligibility age of a lost "in" for fusion (short) |
| `COUNTING_REASSOC_LINE_BAND` | 200 | horizontal band of the line for fusion (px) |
| `COUNTING_REASSOC_MAX_DIST_X` | 120 | max dx for fusion (px) |
| `COUNTING_REASSOC_MAX_DIST_Y` | 80 | max dy for fusion (px) |
| `COUNTING_REID_WINDOW` | 15 | max age of a crossing to be "recent" (REID-SUPPRESS) |
| `COUNTING_REID_MIN_AGE` | 3 | min absence (frames) for an ID to be suspicious |
| `COUNTING_RESURRECTION_MIN_JUMP` | 150 | min horizontal jump (px) for resurrection |
| `COUNTING_RESURRECTION_THRESHOLD` | 5 | min absence (frames) for resurrection |
| `COUNTING_HYSTERESIS_PX` | 0 | line dead-band (disabled, swallowed a legit crossed RIGHT) |
| `COUNTING_MIRROR_GUARD` | `log` | mirror guard, detect only (0 candidates on validation) |

All configurable via `settings.py` + `app/.env` (see `app/.env.example`).

## 8. Validation

- **30 videos validated** (naming convention `validation-<seq>-#<count>.mp4`,
  `<count>` = confirmed count).
- Result: **30/30 pass** (the app gives the expected count for each video).
- Counts confirmed by visual inspection for videos whose original name was
  misleading: `#11`→12, `#27`→12, `#24`→42, `#51`→51 (the counter was right all
  along; the original ground truth was wrong).
- Historical defects resolved:
  - `#35` (re-ID resurrection) → **REID-SUPPRESS**.
  - `#30` (fusion with a stale lost "in") → **GUARD_MAX_AGE**.
  - `#11` (ghost lost "in" reused) → **lost_tracks cleanup on return**.
  - `#32` (last pig lost) → **result.json flush fix**.
- Validation script: `scripts/validate_on_jetson.sh` (modes `standard` on the
  reference video, and `--full` on all manifest videos in
  `validation/expected_counts.json`).

## 9. Limits & considerations

### 9.1 Parameters tuned on video — validate on a real camera

The values above were **tuned empirically on videos**. The tracking/counting
logic transfers to camera mode (FPS = 30 and fixed camera confirmed), but
these parameters **depend on the installation** and must be verified/adjusted
on site:

- `OFFSET_PERCENT_COUNTING_LINE`: line position vs installation.
- `MASK_ZONES` (BL-87): regions to ignore (normalized rects, per-model via `/conf/runtime-settings.json`, editable from the companion UI) — replaces the former `TOP_IGNORE`/`BOTTOM_IGNORE` band crop. See `docs/04_configuration.md`.
- `PIG_CONFIDENCE_THRESHOLD`: lighting / distance / detection conditions.

### 9.2 Long-duration camera mode (24/7) — memory

`first_seen`, `last_seen`, and `trails` accumulate **one entry per unique ID**.
A periodic GC now purges entries for IDs absent longer than
`COUNTING_LOST_BUFFER_FRAMES`. `detections`, `area_in_list`, and
`area_out_list` still grow (one entry per disappeared ID) — slow but unbounded;
a future cleanup could purge them too. `recent_crossings` is cleaned each frame.

### 9.3 Bidirectionality, hysteresis & mirror guard

The **ID-switch recovery** (§5.1) and **REID-SUPPRESS** (§5.4) guards now handle
**both directions** (right→left +1 and left→right −1), including the rare case
of a pig that returns with a new ID and re-crosses the other way. A return
with an **ID-switch at the line** is recovered by the guard's −1 branch (lost
"out" fusion + new right ID).

Hysteresis is disabled (H = 0) because it swallows a legitimate
`crossed RIGHT`. The mirror guard is in `log` (inert, 0 candidates). Both
levers remain available if new patterns appear, **to validate** before
reactivation (H = 25 regressed #18).