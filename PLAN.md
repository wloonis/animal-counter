# Plan: BL-87 — Mask Zones (detection-level exclusion)

## Summary

Add **detection-level exclusion zones** (`mask_zones`): normalized axis-aligned
rects `{x,y,w,h}` in `[0..1]`. Detections whose centroid `((x1+x2)/2,
(y1+y2)/2)` falls inside any rect are dropped in `post_process` **before**
OC-SORT (no track → no count). Hot-reloaded via the existing BL-86 watcher at
idle (no pod restart), additive to the IPC contract, generic across species. A
new `draw_mask_zones` toggle (default `true`, independent of `draw_tracking`)
controls a semi-transparent overlay of the masked rects for visual feedback.

## In Scope
- `post_process` centroid-in-rect pre-filter (after `counting_class_ids` filter, before NMS).
- `mask_zones` + `draw_mask_zones` fields on `shared_state`; defaults in `settings.py`.
- `resolve_mask_zones(rt)` strict validator in `state.py`; wired into the BL-86 watcher `_build_pending()` + boot block in `main.py`.
- Idle apply in `display_thread.py` (no counter reset).
- `infer_thread.py` passes `mask_zones` to `post_process`.
- Semi-transparent overlay in `ui/rendering.py` (gated on `draw_mask_zones`, independent of `draw_tracking`).
- `docs/IPC_CONTRACT.md` additive schema rows + example.
- `docs/04_configuration.md` + `docs/05_counting_pipeline.md` doc updates.

## Out of Scope
- No changes to counting decision logic (crossing/guards/tracker params) — mask is a pure detection pre-filter.
- No per-species masks (generic across all species).
- No polygons (axis-aligned rects only).
- No mask at counting level (detection-level only).
- Companion repo changes (BL-88, sister issue #16) — coordinated but separate BL.

## Architecture Decisions

- **Detection-level, not counting-level**: dropping the detection before the
  tracker means no track is ever created for a masked region → it can never
  cross the line → it can never be counted. This is simpler and safer than
  post-hoc filtering at count time (which would leave ghost tracks and corrupt
  OC-SORT state). Insertion point is **after** the `counting_class_ids` filter
  and **before** NMS in `post_process` (`core/inference.py`), so masked boxes
  never compete in NMS either.
- **Normalized rects, centroid test in pixel space**: rects are stored in
  `[0..1]` (resolution-independent, survives camera/resolution swaps). At
  filter time they are scaled to pixels by `origin_w`/`origin_h` (already in
  `post_process` scope). Centroid = `((x1+x2)/2, (y1+y2)/2)` of the detection
  box; a detection is dropped if its centroid is inside ANY rect.
- **Default `[]` = no-op**: when `mask_zones` is None/empty, the pre-filter is
  skipped entirely → byte-identical current behavior (regression bar = standard
  validation PASS 9/9).
- **Strict reject-all validation + WARN**: any single invalid rect (out-of-range
  x/y/w/h, non-positive w/h, x+w>1, y+h>1, non-dict element, non-list value)
  → the **entire** `mask_zones` array is rejected (field ignored, prior kept),
  WARNING logged. No silent clamping (matches BL-84 posture for
  offset/orientation). The companion side (BL-88) rejects the PUT; the
  countingapp side ignores the invalid field and keeps the prior value.
- **No counter reset on mask_zones change**: a mask change alters *where* we
  count (excluded regions), not *what* we count (the species set). This is
  analogous to `offset_counting_line`/`counting_line_orientation` (no reset),
  not to `counting_class_ids` (reset). `counter_to_right` + `sub_counts`
  are left untouched in the idle apply block.
- **`draw_mask_zones` is an independent toggle** (default `true`), NOT gated on
  `draw_tracking`. The operator can see the mask overlay even on raw (untracked)
  frames, because the mask is a detection-level concept that exists independent
  of tracking visualization. It is hot-reloadable like the other toggles via the
  BL-86 watcher.
- **Reuse the BL-86 watcher pattern verbatim**: `resolve_mask_zones(rt)` mirrors
  `resolve_counting_line_orientation` / `resolve_counting_class_ids` (module-level
  function, logs invalid + returns None → not added to pending). The boot block
  in `main.py` and the idle apply block in `display_thread.py` mirror the
  existing per-key guards for toggles/offset/orientation/counting_class_ids.

## Tasks

- [x] **Task 1: ADD `resolve_mask_zones(rt)` validator** `app/src/state.py` —
  New module-level function `resolve_mask_zones(rt)` returning a list of
  validated rect dicts `[{x,y,w,h},...]` or `None` (reject-all). Validation:
  `rt["mask_zones"]` must be a list; each element a dict with numeric
  `x,y,w,h` in `[0..1]`, `w>0`, `h>0`, `x+w<=1`, `y+h<=1`. Any violation →
  log WARNING + return None (caller keeps prior). Reuse the
  `resolve_counting_line_orientation` / `resolve_counting_class_ids` style
  (logger.warning + return None). No clamping.

- [x] **Task 2: ADD defaults** `app/src/settings.py` —
  Add `MASK_ZONES = []` and `DRAW_MASK_ZONES = True` module-level defaults,
  aligned with the existing `DRAW_TRACKING`/`BOX_TRACKING`/`CENTROID_TRACKING`
  defaults and the `.env`→`settings.py` fallback chain documented in
  `docs/04_configuration.md`.

- [ ] **Task 3: ADD `shared_state` fields** `app/src/utils/shared_state.py` —
  In `SharedState.__init__`, add `self.mask_zones = []` and
  `self.draw_mask_zones = True` near the existing `counting_class_ids` /
  `draw_tracking` fields (L97-130 region). These are read per-frame by
  `infer_thread.py` (mask_zones) and `rendering.py` (draw_mask_zones).

- [ ] **Task 4: ADD centroid-in-rect pre-filter** `app/src/core/inference.py` —
  Change `post_process(self, output, origin_h, origin_w, counting_class_ids=None)`
  signature to add `mask_zones=None`. After the `counting_class_ids` filter
  (current L318-330) and **before** NMS (L335), insert: if `mask_zones` is
  truthy (non-None, non-empty), compute centroids `cx=(boxes[:,0]+boxes[:,2])/2`,
  `cy=(boxes[:,1]+boxes[:,3])/2`, scale each rect to pixels
  (`px=int(r["x"]*origin_w)`, etc.), build a boolean keep mask
  (centroid NOT inside any rect), filter `boxes`/`scores`/`class_ids`. When
  `mask_zones` is None/empty → skip entirely (no-op). Docstring updated to
  describe the new param + drop semantics.

- [ ] **Task 5: PASS `mask_zones` to `post_process`** `app/src/infer_thread.py` —
  At the `self.yolo.post_process(...)` call (L111-115), add
  `mask_zones=shared_state.mask_zones` alongside the existing
  `counting_class_ids=shared_state.counting_class_ids`.

- [ ] **Task 6: WIRE `mask_zones` + `draw_mask_zones` into the watcher** `app/src/state.py` —
  In `RuntimeSettingsWatcher._build_pending()`, after the existing per-key
  blocks: (a) add `draw_mask_zones` to the bool-toggle acceptance loop
  (`for key in ("draw_tracking","box_tracking","centroid_tracking",
  "draw_mask_zones")`); (b) call `resolve_mask_zones(rt)` and if non-None add
  `pending["mask_zones"] = <validated list>`. This reuses the exact pattern
  already there for the other keys.

- [ ] **Task 7: RESOLVE at boot** `app/src/main.py` —
  In the boot block (L180-239), mirror the existing toggle/offset resolution:
  (a) `if isinstance(rt.get("draw_mask_zones"), bool): shared_state.draw_mask_zones = rt["draw_mask_zones"]`;
  (b) `_mz = resolve_mask_zones(rt); if _mz is not None: shared_state.mask_zones = _mz`.
  Placed alongside the `draw_tracking`/`box_tracking`/`centroid_tracking` and
  `counting_class_ids` boot reads.

- [ ] **Task 8: APPLY at idle (no reset)** `app/src/display_thread.py` —
  In the idle apply block (L262-320): (a) add `"draw_mask_zones"` to the toggles
  loop (`for key in (...)` + `setattr(shared_state, key, pending[key])`); (b)
  after the `counting_class_ids` reset block, add a `mask_zones` apply:
  `_mz = pending.get("mask_zones"); if isinstance(_mz, list):
  shared_state.mask_zones = _mz; changed.append("mask_zones")` — **NO** reset of
  `counter_to_right`/`sub_counts` (analogous to the line offset/orientation
  apply, not the counting_class_ids reset).

- [ ] **Task 9: DRAW overlay** `app/src/ui/rendering.py` —
  In `draw_ui` (L161+), after the existing overlay drawing and gated on
  `shared_state.draw_mask_zones and shared_state.mask_zones` (independent of
  `draw_tracking`): for each rect, scale to pixels (`x*w`, `y*h`, `rw*w`,
  `rh*h`) and draw a semi-transparent filled rect (e.g. `cv2.addWeighted` or a
  translucent overlay color) + a solid border. Skip when `mask_zones` is empty
  or `draw_mask_zones` is false. The overlay must be drawn on the frame
  *before* it is written/displayed so it appears in both the live window and
  recorded clips consistently with how `draw_tracking` overlays behave.

- [ ] **Task 10: UPDATE IPC contract** `docs/IPC_CONTRACT.md` —
  Additive to the `runtime-settings.json` section (L99-126): (a) add
  `mask_zones` and `draw_mask_zones` to the example JSON block; (b) add two
  rows to the schema table:
  - `mask_zones` | array[object] | each `{x,y,w,h}` in `[0..1]`, `w>0`, `h>0`, `x+w<=1`, `y+h<=1` | `[]` | **(BL-87)** normalized axis-aligned exclusion rects; detections whose centroid falls inside any rect are dropped before tracking (no track → no count). Strict reject-all on any invalid rect (field ignored, prior kept, WARNING). Hot-reloaded at idle. Generic (all species).
  - `draw_mask_zones` | bool | — | `true` | **(BL-87)** draw a semi-transparent overlay of the `mask_zones` rects (independent of `draw_tracking`). Hot-reloaded.
  Note that the contract MUST stay identical in both repos (AGENTS.md §9);
  the companion write side is BL-88 (sister issue #16).

- [ ] **Task 11: UPDATE config + pipeline docs** `docs/04_configuration.md` + `docs/05_counting_pipeline.md` —
  - `docs/04_configuration.md` L118-129: add `mask_zones` and `draw_mask_zones`
    to the enumerated hot-reloaded fields list + the "no reset on mask_zones
    change" note. Add `MASK_ZONES`/`DRAW_MASK_ZONES` to the settings.py
    defaults table (L67-74 region).
  - `docs/05_counting_pipeline.md` L30: extend the `post_process` description
    from "(NMS, conf filter)" to include the mask_zones centroid pre-filter
    step (after class filter, before NMS), with a one-line note on the
    no-track→no-count semantics.

## Documentation Impact

- `docs/IPC_CONTRACT.md` — **directly edited** (Task 10): the
  `runtime-settings.json` schema table + example gain two additive rows. This
  is the authoritative cross-repo contract; the companion (BL-88) must mirror
  it exactly.
- `docs/04_configuration.md` L118-129 — **goes stale**: the enumerated list of
  hot-reloaded fields (`draw_tracking`, `box_tracking`, `centroid_tracking`,
  `offset_counting_line`, `counting_line_orientation`, `counting_class_ids`)
  omits `mask_zones` + `draw_mask_zones`. Also the settings.py defaults table
  (L67-74) omits the two new defaults. Updated in Task 11.
- `docs/05_counting_pipeline.md` L30 — **goes stale**: the
  `post_process (NMS, conf filter)` description omits the new mask pre-filter
  step. Updated in Task 11.
- `docs/03_deployment.md` L86 — references `/conf` (runtime-settings) but only
  lists file names, not field-level schema; **no stale reference** (the hostPath
  is unchanged). No edit needed.
- `README.md` — references `docs/IPC_CONTRACT.md` and `docs/04_configuration.md`
  in the doc table but does not enumerate settings fields; **no stale
  reference**. No edit needed.
- `AGENTS.md` §9 (cross-repo contract invariance) — not edited, but the
  implementer must verify the `mask_zones`/`draw_mask_zones` contract text is
  byte-identical to the companion repo's copy (BL-88).

## Validation

- **Regression (default `[]`)**: run the standard validation
  (`bash scripts/validate_on_jetson.sh`) with `mask_zones` absent/empty in
  `/conf/runtime-settings.json` → result must match the reference count (9/9
  PASS), byte-identical to current behavior.
- **Functional (right-edge mask)**: set
  `/conf/runtime-settings.json` → `"mask_zones": [{"x":0.8,"y":0,"w":0.2,"h":1}]`
  → re-run validation → detections in the right 20% of the frame are dropped
  → the count should be ≤ the reference (the masked edge contains at least one
  counted animal in the reference video). Confirm via the `draw_mask_zones`
  overlay that the rect is drawn over the right edge.
- **Hot-reload**: with the pod running in `serve` mode, edit
  `/conf/runtime-settings.json` to add/remove a `mask_zones` entry → confirm
  via logs that the watcher fires (`runtime settings applied (idle): mask_zones`)
  at the next idle window, WITHOUT a pod restart, and WITHOUT a counter reset
  (`counter_to_right` unchanged).
- **Invalid rect reject**: set `"mask_zones": [{"x":0.9,"w":0.3}]` (x+w>1) →
  confirm a WARNING is logged and the prior `mask_zones` is kept (the field is
  ignored).
- **Overlay toggle**: set `"draw_mask_zones": false` with non-empty
  `mask_zones` → confirm the overlay disappears but the detection-level drop
  still applies. Set `draw_tracking: false` + `draw_mask_zones: true` → confirm
  the mask overlay still draws (independence).
- **Unit tests**: `cd app && python -m pytest ../tests/ -v` — add/extend tests
  for `post_process` with `mask_zones` (centroid-in-rect drop, empty=no-op)
  and `resolve_mask_zones` (valid/invalid/reject-all).

## Risks

- **Centroid vs box overlap ambiguity**: a detection whose box straddles a mask
  edge but whose centroid is outside is kept; one whose centroid is inside is
  dropped. This is the confirmed decision (centroid test), but an operator
  expecting "any overlap" semantics could be surprised. **Mitigation**: the
  `draw_mask_zones` overlay makes the boundary visible; documented in the IPC
  contract + config docs.
- **Strict reject-all masks a typo**: a single bad rect rejects the entire
  array, so a typo in one rect silently keeps the old mask. **Mitigation**: the
  WARNING log names the invalid rect; the companion (BL-88) rejects the PUT with
  a user-facing error so the operator sees it immediately on the phone.
- **No reset on mask change could confuse an operator** who expects a fresh
  count after repositioning masks. **Mitigation**: documented (analogous to
  line offset, which also doesn't reset); the operator can manually reset from
  the on-screen UI if they want a fresh count.
- **Performance**: the centroid-in-rect test is O(detections × rects), trivial
  for typical rect counts (≤ a handful) and detection counts (≤ tens). No
  measurable impact expected; if concerned, vectorize with NumPy
  broadcasting. **Mitigation**: vectorized NumPy implementation in Task 4.
- **Cross-repo contract drift**: the `mask_zones`/`draw_mask_zones` schema must
  be byte-identical in the companion repo (BL-88). **Mitigation**: Task 10
  explicitly flags the AGENTS.md §9 invariance; the implementer coordinates
  with BL-88.