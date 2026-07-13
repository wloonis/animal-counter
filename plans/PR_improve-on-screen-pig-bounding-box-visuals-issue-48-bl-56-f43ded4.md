# Plan: Improve on-screen pig bounding-box visuals (Issue #48 / BL-56)

## Summary
Replace the single fixed-green 1px bounding boxes and tiny illegible labels in `app/src/core/tracking.py` with deterministic per-track-id colors, a dark semi-transparent label badge showing a bold track ID and secondary score, and a filled colored centroid dot. Visual-only change — no counting, tracking, or guard logic is touched.

## In Scope
- Add `_track_color(self, track_id)` to `Tracking` class — deterministic HSV→BGR hash per track ID, avoids green band (OpenCV H ~35–85), high saturation/value, cached per track_id in a dict.
- Rewrite `plot_one_box(self, x, img, color, label_id=None, label_score=None, line_thickness=None)` with dark outline, colored AA rectangle (thickness 2), dark semi-transparent badge, bold ID text, secondary score text, text shadow.
- Update `draw_counter()` to use `_track_color()` for box and centroid dot, call `plot_one_box` with new label_id/label_score signature, and enlarge the centroid dot (radius 3, filled).
- Conditionally update `validation/config.json` `reference_video` to `validation-13-#12.mp4` if `validation-1-#9.mp4` fails with `no_expected_count` on the branch.

## Out of Scope
- `app/src/counting.py` — untouched
- `app/src/main.py` tracking/counting flow — untouched
- `app/src/core/*` beyond `tracking.py` drawing functions — untouched
- Tracker/guard params (OC-SORT, `COUNTING_LOST_BUFFER_FRAMES=60`, `COUNTING_GUARD_MAX_AGE=15`, Hysteresis H=0) — untouched
- `requirements.txt` (no Docker rebuild) — untouched
- `k3s/`, `ansible/`, `docs/` — untouched
- `--full` validation — not used

## Architecture Decisions
- **Deterministic per-track-id color (HSV hash → BGR)**: A stable color per track ID makes individual pigs visually distinguishable. Hashing the track_id to an HSV value (avoiding the green band H 35–85 that camouflages on grass) and converting to BGR ensures a change of ID for the same pig produces a visible color change. Cached per track_id for stability across frames.
- **Drop `pig:` prefix, split label into ID + score**: The current `pig:12:0.87` crams everything into one tiny string. Using `#12` (bold, larger) and `0.87` (smaller, secondary) makes the track ID readable at a glance and the score available but not dominant.
- **Dark semi-transparent badge via `cv2.addWeighted`**: Instead of a solid color-filled rectangle behind the label (low contrast with near-white text), use a dark semi-transparent badge so white/bright text is legible on any background. Badge flips below the box if near the frame top and clamps to frame bounds.
- **Pure OpenCV only (no new imports)**: The annotated frame goes to both `cv2.imshow` and `video_writer` (output video). Headless FILE mode (no display window) must still work — all drawing is pure cv2 ops on the numpy frame with no window dependencies.
- **No Docker image rebuild**: No `requirements.txt` change — just code rsync to the Jetson.
- **Standard validation only**: `scripts/validate_on_jetson.sh` in standard mode (single reference video). Do NOT use `--full` since no counting code changed.

## Tasks
- [ ] Task 1: ADD `_track_color()` method to `Tracking` class in `app/src/core/tracking.py` — Deterministic HSV→BGR color per track_id. Initialize `self._track_color_cache = {}` in `__init__`. Method hashes `track_id` to an int, maps to HSV hue avoiding green band (H in [0,30] ∪ [85,180]), high saturation (200–255), high value (200–255), converts to BGR via `cv2.cvtColor`, caches and returns the BGR tuple.
- [ ] Task 2: ADD `self._track_color_cache = {}` to `Tracking.__init__()` in `app/src/core/tracking.py` — Initialize the color cache dict alongside existing instance attributes (after `self.frame_counter = 0`).
- [ ] Task 3: REWRITE `plot_one_box()` in `app/src/core/tracking.py` — Change signature from `(self, x, img, color=None, label=None, line_thickness=None)` to `(self, x, img, color=None, label_id=None, label_score=None, line_thickness=None)`. Implementation: (a) draw 1px dark outline rectangle `[0,0,0]` at `c1,c2` for contrast; (b) draw colored rectangle thickness 2 with `cv2.LINE_AA`; (c) if label_id: compute text sizes via `cv2.getTextSize` for ID (fontScale ~0.6, thickness 2) and score (fontScale ~0.4, thickness 1), size the badge to fit both with padding; (d) draw dark semi-transparent badge: fill a dark rect on a sub-ROI copy, `cv2.addWeighted` to blend (alpha ~0.6); flip below box if `c1[1] - badge_h < 0`, clamp to frame bounds; (e) draw `#ID` text with 1px shadow offset (dark at offset, then bright color on top); (f) draw score text to the right of ID, smaller fontScale, thinner stroke, with shadow.
- [ ] Task 4: UPDATE `draw_counter()` in `app/src/core/tracking.py` — Change the box color from `color = (0, 255, 0)` to `color = self._track_color(track_id)`. Change the `plot_one_box` call from `self.plot_one_box(box, image, color, "{}:{}:{:.2f}".format(...), line_thickness=1)` to `self.plot_one_box(box, image, color, label_id='#'+str(track_id), label_score='{:.2f}'.format(result_scores[j]), line_thickness=2)`. Change the unconditional centroid dot from `color = (255, 255, 0); radius = 1; cv2.circle(image, center, radius, color, thickness=1)` to `color = self._track_color(track_id); radius = 3; cv2.circle(image, center, radius, color, thickness=-1)`. Keep `if self.shared_state.box_tracking:` gate and the entire trails/centroid_tracking block unchanged.
- [ ] Task 5: CONDITIONALLY UPDATE `validation/config.json` — Check if `validation-1-#9.mp4` validates on the branch (the #<N> filename parser fix from PR #51). If it errors with `no_expected_count`, change `"reference_video"` from `"validation-1-#9.mp4"` to `"validation-13-#12.mp4"` (expected 12, listed in `expected_counts.json` `videos` key). If `validation-1-#9.mp4` works, leave config unchanged.
- [ ] Task 6: VERIFY worktree setup prerequisites — Ensure gitignored files are copied (not symlinked) from the main repo: `.env.local`, `validation/videos/*.mp4`, `app/model/`, `app/.env`. Use `cp -r` from the main worktree path (from `git worktree list`). Confirm `app/entrypoint.sh` is mode 100755. Confirm `build_countingapp.yml` rsync excludes `model/old/`.

## Validation
- Run `bash scripts/validate_on_jetson.sh` (standard mode, single reference video from `validation/config.json`) — verify the count matches the expected count (PASS). This proves the visual-only change did not alter counting behavior.
- Visually inspect the output video from the validation run — confirm: boxes are clearly visible (colored, 2px, with dark outline), track IDs are readable at a glance (bold, larger), scores are secondary (smaller, thinner), centroid dots are filled and colored per track ID, badge flips below box at frame top without going out of bounds.
- Confirm headless FILE mode works (validation runs `--input=FILE` without `cv2.imshow`) — no crashes or window-dependent errors.
- Run `cd app && python -m pytest ../tests/ -v` — confirm no test regressions.

## Risks
- **Badge overflow at frame edges** — Badge position must clamp to frame bounds and flip below the box when near the top edge. Mitigate: compute badge position with explicit boundary checks against `img.shape`.
- **Color collision between two track IDs** — Two different IDs could hash to similar hues. Mitigate: spread hues across the full non-green range [0,30] ∪ [85,180] using modular arithmetic; visual difference is acceptable for a demo.
- **Performance impact of `addWeighted` per box** — `cv2.addWeighted` on a small sub-ROI per detection adds a small per-frame cost. Mitigate: badge sub-ROI is tiny (label-sized), and typical frame has <30 detections; negligible vs. inference cost.
- **`validation-1-#9.mp4` no_expected_count on branch** — If PR #51 is not merged, the #<N> parser fix may be missing. Mitigate: fall back to `validation-13-#12.mp4` (in manifest `videos` key, expected 12) as `reference_video`.
- **Worktree missing gitignored files** — Fresh worktree lacks `.env.local`, videos, model weights, `app/.env`. Mitigate: `cp -r` from main repo (not symlinks — symlinks break rsync to Jetson).