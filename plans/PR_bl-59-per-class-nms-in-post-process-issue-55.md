# Plan: BL-59 — Per-class NMS in post_process (issue #55)

## Summary
Add a greedy keep-max non-maximum suppression (IoU > 0.6) step inside
`post_process` in `app/src/core/inference.py`, applied after the score≥0.5
and class==1 (pig) filters and before the `column_stack` return. This suppresses
near-identical duplicate detections (IoU ~0.97–1.0) that seed competing OC-SORT
tracklets and drive ~70% of ID switches. Counts do not change (all already
PASS); this improves tracking robustness and visual ID-color stability.

## In Scope
- `app/src/core/inference.py` — add NMS + explanatory comment inside `post_process` only.
- `validation/config.json` stays at `mode: "standard"` — untouched. Validation of the 4 priority videos is driven by the `--full` CLI flag on `validate_on_jetson.sh`, not by mutating the config.

## Out of Scope
- `app/src/counting.py`, `app/src/main.py` tracking/counting logic, `app/src/core/tracking.py`.
- Tracker params (`TRACKER_*`), guard params (`COUNTING_*`), `app/src/settings.py`.
- The remaining ~30% of ID switches (pure OC-SORT anomaly on stationary pigs / OCM direction-consistency) — separate issue.
- Changing any expected count (NMS must not alter counts; mismatch = bug).

## Architecture Decisions
- **NMS placement: inside `post_process`, after filters, before `column_stack`.** This is the single chokepoint where every detection frame passes through, so duplicates are removed before they ever reach the OC-SORT tracker — eliminating the competing-tracklet cause at the source rather than patching downstream.
- **Keep-max, per-class (pig-only), IoU threshold 0.6, hardcoded.** Greedily keep the highest-score box, suppress same-class boxes overlapping it with IoU > 0.6. The single-class (pig) case means NMS is effectively global here; per-class framing keeps it correct if classes expand. 0.6 merges near-identical duplicates (IoU ~0.97–1.0) while keeping distinct overlapping pigs (IoU < 0.6). Hardcoding 0.6 (not a settings constant) keeps scope minimal and avoids touching `settings.py`.
- **Greedy loop, pure numpy, no new deps.** Detection counts are usually <15 per frame, so a simple readable greedy loop over indices is fine and avoids adding a dependency (e.g. torchvision NMS).
- **No debug logging.** The reverted temp instrumentation stays reverted; no `RAWDET`/`TRK` prints.

## Tasks
- [ ] Task 1: ADD NMS + comment in `app/src/core/inference.py` `post_process` — Insert, between the `pig_mask` filter block and the `len(boxes) == 0` empty-check, a greedy keep-max NMS step: (a) a concise func-level comment explaining WHY (duplicate detections → competing OC-SORT tracklets → ID switches) and the IoU=0.6 rationale (~0.6 merges near-identical duplicates IoU~0.97–1.0, keeps distinct overlapping pigs IoU<0.6); (b) sort indices by descending score, iterate keeping highest unsuppressed box, suppress remaining same-class boxes with IoU > 0.6 (pure numpy box-intersection math), collect kept indices, reindex `boxes`/`scores`/`class_ids`. The existing empty-check then guards the (now NMS'd) arrays before `column_stack`. Keep the return shape unchanged: `np.column_stack((boxes, scores, class_ids))`.
- [ ] Task 2: VERIFY no scope leak — `rg -n` confirms only `app/src/core/inference.py` was modified (no `counting.py`, `tracking.py`, `main.py`, `settings.py`, tracker/guard params changes); no new `print`/`logger.debug` calls added in `post_process`; `validation/config.json` unchanged at `mode: "standard"`.

## Validation
- Run in **standard mode** (config stays `"standard"`, no `--full`): `bash scripts/validate_on_jetson.sh` — validates the reference video `validation-1-#9`, expected count = 9.
- Pass criterion: `validation_status: pass` with the reference count matching (9). If the count MISMATCHES → STOP and surface it (do NOT auto-correct); a mismatch means an NMS bug (NMS must not alter counts).
- The 4 priority videos (`validation-13-#12`=12, `validation-14-#30`=30, `validation-22-#42`=42, `validation-27-#35`=35) may be run as an optional follow-up via `--full`, but the required gate is standard-mode reference-video pass.
- Unit tests (optional sanity): `cd app && python -m pytest ../tests/ -v` — inference tests should remain green (return shape/typing unchanged).
- `validation/config.json` is never changed (stays `mode: "standard"`); no revert step needed.

## Risks
- **NMS over-suppresses two genuinely distinct pigs (false merge) → count drops.** Mitigation: IoU threshold 0.6 is well below the duplicate band (0.97–1.0) and above the distinct-overlap band (<0.6); the standard-mode reference-video count (9) must still PASS exactly — any drop surfaces as a mismatch we stop on.
- **NMS under-suppresses (threshold too low) → duplicates survive → no improvement.** Mitigation: 0.6 is chosen from the evidence band; if validation passes but ID switches don't drop in a later visual check, the threshold can be revisited in a follow-up (out of scope here).
- **Edge case: zero or single detection.** Mitigation: NMS loop is a no-op on ≤1 detection; the existing `len(boxes) == 0` guard already handles the empty case. No behavior change for low-detection frames.