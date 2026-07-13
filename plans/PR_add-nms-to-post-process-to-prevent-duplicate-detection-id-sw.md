# Plan: Add NMS to post_process to prevent duplicate-detection ID switches (BL-59)

## Summary

Add per-class (pig) non-maximum suppression to `post_process` in `app/src/core/inference.py` so that when the detector emits near-identical duplicate boxes for a single pig (IoU ~0.97–1.0), only the highest-score box survives. This prevents competing tracklets from spawning in OC-SORT, which is the root cause of ~70% of observed ID switches. All 5 priority+reference videos currently PASS; this is a robustness/visual-readability improvement (stable per-ID color), not a count fix.

## In Scope
- Add a module-level `NMS_IOU_THRESHOLD = 0.6` constant in `inference.py`
- Implement a pure-numpy NMS helper (vectorized IoU, greedy suppress, keep-max) — no new imports (`numpy` already imported as `np`)
- Apply NMS inside `post_process` after the score≥0.5 / class==1 filtering, before the `np.column_stack` return
- Verify all 5 videos still PASS via `scripts/validate_on_jetson.sh --full`

## Out of Scope
- No changes to counting logic (`counting.py`), tracker params (`tracking.py`), or guard params
- No changes to `settings.py` or any config file — threshold is a module-level constant in `inference.py`
- No changes to `validation/config.json` mode (stays `standard`; `--full` is a per-run CLI override, no revert needed)
- No diagnostic/debug logging changes committed
- The ~30% pure OC-SORT anomalies (stationary pigs, OCM direction-consistency instability) — tracked separately

## Architecture Decisions

- **Pure-numpy NMS, no new imports** — `numpy` is already imported; avoids adding torchvision/torch dependencies to the TensorRT inference path. Vectorized IoU keeps it fast (detection counts per frame are small, typically <50, so even a Python-level greedy loop is negligible cost).
- **Module-level constant `NMS_IOU_THRESHOLD = 0.6`** — per the user's decision, the threshold lives in `inference.py` (not `settings.py`). This keeps the NMS tuning co-located with the code that uses it and avoids touching the config surface.
- **Keep-max (standard NMS convention)** — among overlapping boxes with IoU > threshold, keep the highest-score box and suppress the rest. For co-located duplicates (IoU ~0.99 = same pig, same position), which box survives doesn't matter for OC-SORT track re-association; what matters is reducing 2 boxes → 1 so no competing tracklet spawns.
- **IoU threshold = 0.6** — merges near-identical duplicates (IoU ~0.97–1.0) while keeping genuinely distinct pigs that overlap slightly (IoU < 0.6). This is a conservative threshold that only suppresses true duplicates.
- **NMS applied after class filtering, not before** — since `post_process` already filters to class==1 (pig) only, all remaining boxes are the same class. NMS is effectively per-class by construction; no need to group by class first.

## Tasks

- [ ] **Task 1: ADD** `NMS_IOU_THRESHOLD` constant — `app/src/core/inference.py`
  - Add `NMS_IOU_THRESHOLD = 0.6` at module level, after the imports / before the class definition (near line 14, after `logger = logging.getLogger(__name__)`).
  - Add a brief inline comment: `# IoU threshold for non-maximum suppression of duplicate pig detections (BL-59)`.

- [ ] **Task 2: ADD** `_nms` helper method — `app/src/core/inference.py`
  - Add a `@staticmethod` method `_nms(boxes, scores, iou_threshold)` on the `Inference` class (or a module-level private function `_nms(...)`).
  - Algorithm (pure numpy, greedy keep-max):
    1. Sort detection indices by score descending (`order = np.argsort(-scores)`).
    2. Initialize `keep = []`.
    3. While `order` is non-empty:
       - Take `i = order[0]`, append to `keep`.
       - Compute IoU of box `i` with all remaining boxes `order[1:]` (vectorized: areas, intersection coords, union).
       - Suppress: keep only indices where `IoU <= iou_threshold` (strictly suppress `>`).
       - `order = order[1:][iou <= iou_threshold]` (the survivors).
    4. Return `keep` (list of indices into the original arrays).
  - IoU computation (vectorized, boxes are `[x1, y1, x2, y2]`):
    - `area = (x2 - x1) * (y2 - y1)` (clamp negatives to 0 for malformed boxes).
    - Intersection: `xx1 = max(x1_i, x1_rest)`, `yy1`, `xx2`, `yy2` via `np.maximum`; `inter = max(0, xx2-xx1) * max(0, yy2-yy1)`.
    - `iou = inter / (area_i + area_rest - inter)`.
  - Handle edge case: if `len(boxes) == 0` or `len(boxes) == 1`, return immediately (no suppression needed).

- [ ] **Task 3: APPLY** NMS in `post_process` — `app/src/core/inference.py`
  - In `post_process`, after the `pig_mask` filtering and the `if len(boxes) == 0: return np.array([])` guard, insert:
    ```python
    # NMS: suppress duplicate detections (same pig, IoU > threshold) to
    # prevent competing tracklets that cause OC-SORT ID switches (BL-59).
    keep = _nms(boxes, scores, NMS_IOU_THRESHOLD)
    boxes = boxes[keep]
    scores = scores[keep]
    class_ids = class_ids[keep]
    ```
  - The existing `return np.column_stack((boxes, scores, class_ids))` remains unchanged.
  - The `if len(boxes) == 0` guard BEFORE NMS means NMS only runs when there are ≥1 detections. The `_nms` helper handles the `len == 1` case (returns the single index).

- [ ] **Task 4: VERIFY** syntax — `python3 -m py_compile app/src/core/inference.py`
  - Run `python3 -m py_compile app/src/core/inference.py` to confirm no syntax errors.
  - Commit this change (NMS-only, single file).

- [ ] **Task 5: VALIDATE** all 5 videos pass — `scripts/validate_on_jetson.sh --full`
  - Run `scripts/validate_on_jetson.sh --full` (CLI override; `config.json` stays `standard`).
  - Confirm all 5 priority+reference videos still PASS their expected counts.
  - If any video flips to `count_mismatch`, the NMS threshold or implementation needs review — do NOT auto-correct counting logic (surface to user per AGENTS.md).

## Validation

1. **Syntax check**: `python3 -m py_compile app/src/core/inference.py` — must exit 0.
2. **Business validation**: `scripts/validate_on_jetson.sh --full` — all 5 videos must report `pass` (no `count_mismatch`, no `execution_error`).
3. **Scope check**: `git diff --name-only` after implementation must show ONLY `app/src/core/inference.py` (no `settings.py`, no `config.json`, no `tracking.py`, no `counting.py`).

## Risks

- **Risk**: NMS threshold 0.6 suppresses two genuinely distinct pigs that overlap slightly (e.g., pigs passing each other at the counting line).
  - **Mitigation**: 0.6 is conservative — distinct pigs at the counting line typically have IoU well below 0.6. If validation shows a count regression, the threshold can be raised (e.g., 0.7–0.8) without changing the algorithm. Validation on all 5 videos is the gate.
- **Risk**: Box format is not `[x1, y1, x2, y2]` (e.g., YOLO outputs `[cx, cy, w, h]`), making IoU computation wrong.
  - **Mitigation**: The existing code uses `boxes = pred[:, :4]` and the downstream `tracking.py` / `counting.py` consume them directly, strongly implying xyxy format. The `_nms` helper should assert/assume xyxy (consistent with the rest of the pipeline). If validation fails, this is the first thing to check.
- **Risk**: Empty `keep` list or shape mismatch after indexing breaks the `np.column_stack` return.
  - **Mitigation**: The `if len(boxes) == 0` guard before NMS prevents the empty-input case. `_nms` always returns at least one index when input is non-empty (the first box is always kept). Add a defensive `if len(keep) == 0: return np.array([])` after NMS as a belt-and-suspenders guard.