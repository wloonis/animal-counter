# Plan: Bounding Box Visual Readability (BL-58)

## Summary
The track ID and detection score are barely visible on the output video: the
label text is tiny (fontScale 0.33), drawn quasi-white on a green box with no
outline, the box color is a fixed green for all tracks, and the centroid is a
1px ring. This plan refactors the cv2 drawing in `tracking.py` (boxes, labels,
centroids) and adds render settings in `settings.py` — purely visual, zero
impact on counting/tracking logic.

Issue: https://github.com/wloonis/animal-counter/issues/53 (BL-58)

## In Scope
- `Tracking.plot_one_box` — thicker box, larger outlined label, semi-opaque
  background, luminance-adaptive text color, padding, smart placement.
- `Tracking.draw_counter` — new label format `ID:12 0.87`, deterministic
  per-track-id box color (hash→HSV→BGR, cached), larger filled centroid.
- `Tracking.__init__` — plumb new render settings; add a per-id color cache.
- `app/src/settings.py` — add `DRAW_LABEL_FONT_SCALE`, `DRAW_LABEL_THICKNESS`,
  `DRAW_BOX_LINE_THICKNESS`, `DRAW_CENTROID_RADIUS` via `os.getenv` with defaults.
- Plumbage of the new settings from `Settings` → `shared_state` → `Tracking`.
- Validation: `python3 -m py_compile` + `scripts/validate_on_jetson.sh` (standard).

## Out of Scope
- Counting logic, OC-SORT, guard/hysteresis params (`COUNTING_LOST_BUFFER_FRAMES`,
  `COUNTING_GUARD_MAX_AGE`, `COUNTING_HYSTERESIS_PX=0`).
- K3s infra, entrypoint, templates.
- `Rendering.draw_ui` buttons (only minor visual coherence if needed).
- GUI/window dependencies — cv2-only ops on the numpy frame (headless-safe).
- Issue #48 (BL-56) — related but handled independently.

## Architecture Decisions
- **cv2-only, headless-safe (D9)** — every draw op stays on the numpy frame via
  `cv2`; the annotated frame is written to the output video as today. No new deps.
- **Settings-driven with sensible defaults (D8)** — all new tunables are
  `os.getenv`-backed in `Settings` with defaults that reproduce the improved
  look out-of-the-box (no `.env` edit required). Existing settings untouched.
- **Settings plumbed via shared_state** — `Tracking` already reads
  `self.shared_state.box_tracking` / `centroid_tracking`; the new render
  values are added to the same `shared_state` object (or `Settings` instance it
  wraps), so `plot_one_box`/`draw_counter` consume them without changing call
  signatures of `plot_one_box` (kept generic) beyond reading cached attributes.
- **Deterministic color per track id (D6)** — **primary purpose: visually
  detect ID jumps (ID switches) on the same pig.** When a pig keeps the same ID
  its box stays one color; if OC-SORT re-IDs it mid-crossing, the box color
  changes abruptly — an at-a-glance cue for ID-switch defects. A small helper
  maps `track_id → stable BGR` via a hue hash (HSV→BGR) with fixed S/V, cached
  in a dict on `Tracking` so the same id always gets the same color. Hue is
  spread across the full 0–180° range (not sequential ids → adjacent hues) so
  neighboring ids get visibly different colors, making switches obvious. S/V
  chosen for good contrast against a typical barn/floor background.
- **Label readability stack (D3)** — draw a semi-opaque rounded background
  rectangle (alpha blend via a temporary overlay), then a black text outline
  (`cv2.putText` in black, 1px offset in 4 directions) under the foreground
  text. Text color chosen by luminance of the background box color (white on
  dark, black on light).
- **Single-line label `ID:12 0.87` (D4)** — one line keeps the implementation
  simple and the background-rectangle math trivial; ID first (bold visual
  weight via larger text), score second. Two-line is deferred (option only).
- **Smart placement (D7)** — label defaults above the box; if the box top is
  within ~the label height of the frame top, flip it below the box.

## Tasks
- [ ] Task 1: ADD render settings `app/src/settings.py` — add four `os.getenv`
  settings to `Settings.__init__`: `DRAW_BOX_LINE_THICKNESS` (default `2`),
  `DRAW_LABEL_FONT_SCALE` (default `0.6`), `DRAW_LABEL_THICKNESS` (default
  `2`), `DRAW_CENTROID_RADIUS` (default `3`). Keep all existing settings intact.
- [ ] Task 2: PLUMB render settings into `shared_state` — wherever
  `shared_state` is constructed (follow the existing `box_tracking`/
  `centroid_tracking` assignment pattern), expose the four new settings so
  `Tracking` can read `self.shared_state.draw_box_line_thickness`, etc. (If
  `shared_state` is a thin object, add the attributes; if it wraps `Settings`,
  ensure they pass through.)
- [ ] Task 3: ADD per-id color helper + cache in `app/src/core/tracking.py` —
  add a method (e.g. `_track_color(self, track_id)`) that hashes the id to a
  hue spread across the full 0–180° hue range (so adjacent ids differ visibly
  and ID switches on the same pig are easy to spot), converts HSV→BGR with
  fixed S/V, caches the result in `self._color_cache` (dict init in `__init__`).
  Returns a stable, well-contrasted BGR tuple.
- [ ] Task 4: REWRITE `Tracking.plot_one_box` `app/src/core/tracking.py` —
  consume the new settings (default to `shared_state` values, fallback to the
  `Settings` defaults): `tl = line_thickness or self.shared_state.draw_box_line_thickness`;
  `fontScale = self.shared_state.draw_label_font_scale`; `tf = self.shared_state.draw_label_thickness`.
  Draw the box with `cv2.LINE_AA`. If label: compute text size with the new
  fontScale/thickness, add ~2px padding, draw a semi-opaque background
  rectangle (alpha overlay) sized to the label; choose text color by luminance
  of the box color; draw black outline text then foreground text; place label
  above the box, or below if too close to the frame top (needs frame height —
  use `img.shape[0]`).
- [ ] Task 5: REWRITE label format + color + centroid in `Tracking.draw_counter`
  `app/src/core/tracking.py` — replace the box color `(0,255,0)` with
  `self._track_color(track_id)`; replace the label
  `"{}:{}:{:.2f}".format(categories[...], str(track_id), score)` with
  `"ID:{} {:.2f}".format(int(track_id), float(score))`; pass
  `line_thickness=self.shared_state.draw_box_line_thickness` to `plot_one_box`;
  replace the centroid `cv2.circle(center, 1, (255,255,0), thickness=1)` with
  `cv2.circle(center, radius=self.shared_state.draw_centroid_radius,
  self._track_color(track_id), thickness=-1)` (filled, contrasted).
- [ ] Task 6: ENSURE visual coherence in `app/src/ui/rendering.py` — review
  `Rendering.draw_ui`; if it draws labels/text that clash with the new box
  style (e.g. same tiny fontScale), align its text size to the new
  `DRAW_LABEL_FONT_SCALE`/`DRAW_LABEL_THICKNESS` settings. Only touch text
  sizing — no UI button logic changes.
- [ ] Task 7: VALIDATE — `python3 -m py_compile app/src/core/tracking.py
  app/src/settings.py app/src/ui/rendering.py`; then run
  `scripts/validate_on_jetson.sh` (standard mode, no `--full`) to confirm
  counting results are unchanged.

## Validation
- `python3 -m py_compile app/src/core/tracking.py app/src/settings.py app/src/ui/rendering.py` — syntax/type import sanity.
- `scripts/validate_on_jetson.sh` (standard) — confirm net counts on reference videos are unchanged (UI-only branch).
- Visual spot-check (manual): run the app on a sample clip; confirm boxes are
  thicker, each track has a distinct stable color, the label reads `ID:xx 0.xx`
  clearly with a semi-opaque background and outline, and the centroid is a
  visible filled dot.

## Risks
- **shared_state shape unknown for new attributes** — `shared_state` is built
  elsewhere; if adding attributes there is invasive, fall back to reading the
  new settings directly from a `Settings` instance passed/available to
  `Tracking`. Mitigation: follow the exact existing pattern used for
  `box_tracking`/`centroid_tracking`.
- **Alpha overlay performance** — per-frame `cv2.addWeighted` on a small label
  region is cheap, but on a Jetson with many boxes keep the overlay limited to
  the label rectangle (not the full frame). Mitigation: only allocate the
  overlay on the label bounding box.
- **Color contrast on varied barn backgrounds** — deterministic hue could land
  on a low-contrast color for some backgrounds. Mitigation: fixed S/V and a
  luminance-adaptive text color; box color is decorative (tracking is by id),
  so contrast is a nicety not a correctness risk.
- **`plot_one_box` used elsewhere with different expectations** — it is a
  generic helper; new defaults change its look everywhere it's called.
  Mitigation: the only caller is `draw_counter` (confirmed in the clarify
  read), so the blast radius is contained.