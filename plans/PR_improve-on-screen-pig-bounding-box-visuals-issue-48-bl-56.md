# Plan: Improve on-screen pig bounding-box visuals (Issue #48 / BL-56)

## Summary
Rewrite the bounding-box drawing in `app/src/core/tracking.py` so boxes are clearly visible on any background (especially green/grass footage), with a readable dark-badge label that emphasizes the track ID at a glance and shows the match score as secondary. Pure visual change — zero impact on counting, tracking, or guard logic.

## In Scope
- `plot_one_box()` — full rewrite of the drawing routine: thicker anti-aliased stroke, dark semi-transparent rounded badge label with frame-edge clamping, light high-contrast text, subtle dark outline behind the colored stroke.
- `draw_counter()` — replace fixed green `(0,255,0)` with a track-id-keyed stable color palette (HSV hash → BGR); split the single `"pig:12:0.87"` label into a two-part hierarchy (`#12` larger/bold + `0.87` smaller/secondary); color the centroid `cv2.circle` dot with the same track-id palette color and bump its radius.
- Add a small helper method `_track_color(track_id)` for the deterministic palette (stable per ID across frames, high-contrast hues, no green-dominant values that camouflage on grass).
- Keep the `self.shared_state.box_tracking` gate unchanged — drawing only when enabled.
- All drawing must remain pure-OpenCV (`cv2` primitives only, no new imports) so headless FILE mode (no `cv2.imshow`, output via `video_writer`) continues to work.

## Out of Scope
- Any change to `app/src/counting.py`, OC-SORT tracker tuning, or `main.py` tracking/counting flow.
- `app/src/ui/rendering.py` (counter display, UI buttons, counting line overlay).
- `app/src/settings.py` parameter values — no new settings or env vars.
- `requirements.txt` / build-time dependency changes — OpenCV-only, code-rsync deploy.
- Docker image rebuild, k3s/ansible/docs infra.
- `--full` validation (counting code unchanged; standard mode only).

## Architecture Decisions
- **Track-id-keyed stable color palette** (`_track_color(track_id)`) — deterministic hash of track_id → HSV hue (full hue range, fixed saturation/value for vibrancy) → BGR conversion. Each track keeps the same color across all frames (visual consistency), and the palette avoids clustering near pure green (H≈60°) to prevent camouflage on grass. Rationale: the issue's primary complaint is "same green on green/grass background makes boxes disappear."
- **Label hierarchy via two `cv2.putText` calls** — `#ID` rendered with larger fontScale + thicker stroke (simulated bold), `score` rendered smaller/thinner, both inside one dark badge. Rationale: the single colon-separated string `"pig:12:0.87"` gives no visual hierarchy; the ID is the most useful info at a glance and must dominate.
- **Dark semi-transparent rounded badge** — filled dark rectangle (e.g. `(0,0,0)` at ~60% opacity via `cv2.addWeighted` on a sub-ROI) with small corner radius (simulated via `cv2.rectangle` + `cv2.circle` corners or `cv2.fillPoly`). Placed above the box top edge; if the box top is too close to the frame top (badge would overflow), flip the badge below the box. Rationale: the current label is a tiny filled-green patch with near-white text overlapping the box edge — illegible at normal viewing distance.
- **Anti-aliased stroke, thickness 2–3, with dark outline** — draw a 1px dark `(0,0,0)` rectangle first, then the colored rectangle on top at `thickness=2` (or 3 on larger frames), both with `cv2.LINE_AA`. Rationale: a 1px green line has no contrast on grass; the dark outline guarantees visibility on any background.
- **Centroid dot** — radius bumped from 1 to ~3–4, filled (`thickness=-1`), colored with the track-id palette color. Rationale: the current 1px cyan dot is nearly invisible and inconsistent with the box color.
- **Performance** — all drawing uses `cv2.rectangle`, `cv2.putText`, `cv2.circle`, `cv2.addWeighted` — no new imports, no GPU/CUDA calls. The per-detection cost is negligible at 30fps with typical pig counts (≤25).

## Tasks
- [ ] Task 1: ADD `_track_color(self, track_id)` method to `Tracking` class in `app/src/core/tracking.py` — deterministic HSV-hash → BGR color palette keyed by track_id. Avoid hues near pure green (40°–80°) or shift them to ensure contrast on grass. Returns a BGR tuple. No new imports (use `cv2.cvtColor` on a 1×1 numpy array for HSV→BGR, or manual conversion).
- [ ] Task 2: REWRITE `plot_one_box(self, x, img, color, label_id, label_score, line_thickness)` in `app/src/core/tracking.py` — change signature to accept separate `label_id` (e.g. `"#12"`) and `label_score` (e.g. `"0.87"`) strings instead of one `label`. Draw: (a) 1px dark outline rectangle, (b) colored anti-aliased rectangle at `thickness=line_thickness` (default 2), (c) dark semi-transparent rounded badge above the box (flip below if near frame top), (d) `#ID` text in larger fontScale + thicker stroke, (e) `score` text smaller/thinner to the right of the ID, (f) optional 1px shadow offset on text for contrast. Use `cv2.getTextSize` to size the badge from the combined text width + padding. Clamp all coordinates to frame bounds.
- [ ] Task 3: UPDATE `draw_counter()` in `app/src/core/tracking.py` — replace `color = (0, 255, 0)` with `color = self._track_color(track_id)`. Replace the single label string `"{}:{}:{:.2f}".format(...)` with two separate arguments: `label_id="#{}".format(track_id)` and `label_score="{:.2f}".format(result_scores[j])`. Pass `line_thickness=2` (or scaled to frame size). Update the centroid dot: `color = self._track_color(track_id)`, `radius=3`, `thickness=-1` (filled). Keep the `if self.shared_state.box_tracking:` gate unchanged. Keep the trails/centroid_tracking block unchanged (only change the dot color + radius in the unconditional centroid circle draw).
- [ ] Task 4: VERIFY no regressions — run `cd app && python -m pytest ../tests/ -v` to ensure existing tracking/rendering unit tests still pass (if any test asserts specific drawing output, update the test expectation to match new visuals — but do NOT change any counting/tracking logic tests).

## Validation
- **Unit tests**: `cd app && python -m pytest ../tests/ -v` — all existing tests must pass.
- **Standard validation on Jetson**: `bash scripts/validate_on_jetson.sh` (standard mode, single reference video) — must return `pass` or `count_mismatch` with the SAME count as before the change (visual-only, no counting impact). Exit code 0.
- **Visual inspection**: Run `validate` mode on the reference video and check the output video (`/files/` on the Jetson or fetched via the validation job) — confirm: boxes are clearly visible on grass footage, track ID is readable at a glance, score is readable as secondary, colors are distinct per track, no label overflows the frame edge, headless output video has the new visuals (no `cv2.imshow` dependency).
- **FPS check**: Confirm the validation job completes within normal time bounds (no measurable FPS regression vs. baseline — the validation report's `duration_seconds` should be comparable to pre-change runs).

## Risks
- **Semi-transparent badge via `cv2.addWeighted` may be slow if called per-pixel** — mitigation: operate on the badge sub-ROI only (small rectangle), not the full frame. The ROI is tiny (label-sized), so cost is negligible.
- **`plot_one_box` signature change breaks callers** — mitigation: `plot_one_box` is only called from `draw_counter` in the same file (verified via grep). No external callers. Update both in the same task.
- **Color palette could still produce low-contrast colors on specific backgrounds** — mitigation: use high saturation (≥200) and mid-to-high value (≥150) in HSV; avoid the green hue band. The dark outline on the box + dark badge background provide contrast independent of the box color.
- **Existing unit tests may assert specific drawing calls (e.g. mock `cv2.rectangle`)** — mitigation: Task 4 explicitly checks for and updates test expectations for visual output only; counting/tracking logic tests must remain green without modification.
- **Rounded rectangle without `cv2.roundedRectangle` (OpenCV < 4.5)** — mitigation: simulate rounded corners with `cv2.fillPoly` or skip rounding if the OpenCV version is too old (the badge is still a dark rectangle — rounding is cosmetic, not functional). Prefer `cv2.rectangle` fill as the safe fallback.