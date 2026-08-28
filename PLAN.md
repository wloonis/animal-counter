# Plan: BL-94 — Supprimer TOP_IGNORE/BOTTOM_IGNORE (crop pré-inférence)

## Summary
Remove the obsolete pre-inference `TOP_IGNORE`/`BOTTOM_IGNORE` crop in `infer_thread.py` (infer on the full frame instead) and fully rip out the `y_offset` plumbing. The hardcoded top/bottom band masking is superseded by `mask_zones` (BL-87/89, per-model via `/conf/runtime-settings.json`, editable from the Android companion BL-88). Drop the now-dead settings + `.env.example` entries and update docs to point at `mask_zones`. No companion or counting-pipeline changes.

## In Scope
- `app/src/infer_thread.py` — remove crop, infer on `image_raw` directly; remove `TOP_IGNORE`/`BOTTOM_IGNORE` local vars and `y_offset`; remove `y_offset` from the `results` tuple
- `app/src/display_thread.py` — drop `y_offset` from tuple unpacking (line 466) and remove the two `box[1] += y_offset` / `box[3] += y_offset` additions (lines 555-556)
- `app/src/settings.py` — remove `self.TOP_IGNORE` / `self.BOTTOM_IGNORE` (lines 55-56)
- `app/.env.example` — hard-remove lines 51-52
- `docs/04_configuration.md` — remove the `TOP_IGNORE`/`BOTTOM_IGNORE` row; add a migration pointer to `mask_zones`
- `docs/05_counting_pipeline.md` — remove the `TOP_IGNORE`/`BOTTOM_IGNORE` reference; point to `mask_zones`
- `docs/IPC_CONTRACT.md` — verify no impact (already done during clarify: `mask_zones` documented, no TOP/BOTTOM_IGNORE refs — no edit expected)

## Out of Scope
- Companion app changes — `mask_zones` already implemented (BL-88)
- Counting pipeline (crossing/guard/tracker) — no changes
- **Pig (my_model) deployment follow-up** — the pig loses its hardcoded top/bottom masking. Before redeploying the pig, configure its `mask_zones` via the companion (normalized rects `{x:0,y:0,w:1,h:100/H}` for the top band, `{x:0,y:(H-50)/H,w:1,h:50/H}` for the bottom band — exact values depend on the pig camera resolution). This is a deliberate, known deployment follow-up (issue #133 tâche 4), NOT part of this PR. Reviewers must know this is intentional, not an oversight.
- If validation count ≠ 47, investigate `/conf` environment — do NOT auto-correct counting code (crop is already 0/0 on the sheep Jetson, so this change cannot be the cause).

## Architecture Decisions
- **Full `y_offset` rip-out (no `y_offset=0` no-op).** Rationale: a zeroed variable left in place is dead code that obscures the intent of BL-94 (remove the obsolete crop entirely). The box-to-full-frame coordinate mapping is already handled by the letterbox path (`r_scale`/`tx1`/`ty1` via `tracking.undo_letterbox` in display_thread.py), so `y_offset` was only compensating for the crop offset; with the crop gone it is genuinely unused. Cleaner to remove the tuple field and both additions.
- **Hard-remove `.env.example` lines (not comment).** Rationale: once `settings.py` no longer reads `TOP_IGNORE`/`BOTTOM_IGNORE`, the env entries are inert; leaving them (even commented) invites confusion. The migration path is documented in `docs/04_configuration.md` pointing to `mask_zones`.
- **Retrocompat by omission.** Rationale: after `settings.py` removal, the vars are never read — an existing `.env` that still contains them is simply ignored (no `AttributeError`, no crash). No explicit fallback code needed.
- **Pig deploy follow-up tracked as explicit out-of-scope.** Rationale: the reviewer must see the pig-mask loss is acknowledged and intentional, so it isn't mistaken for a missed task.

## Tasks
- [x] Task 1: EDIT `app/src/infer_thread.py` — in the per-frame loop (~lines 113-119), delete `TOP_IGNORE = settings.TOP_IGNORE`, `BOTTOM_IGNORE = settings.BOTTOM_IGNORE`, `frame_roi = image_raw[TOP_IGNORE:h-BOTTOM_IGNORE, :]`, and `y_offset = TOP_IGNORE`. Pass `image_raw` directly to `self.yolo.infer(...)` in place of `frame_roi`. Keep `h, w = image_raw.shape[:2]` (still used elsewhere if referenced; verify it's not now unused — if unused, drop it too).
- [x] Task 2: EDIT `app/src/infer_thread.py` — remove `y_offset` from the `results` list (line 137): `[image_raw, boxes_pp, output, use_time, origin_h, origin_w, self.frame_counter, r_scale, tx1, ty1, self.yolo.input_h, self.yolo.input_w]` (11 elements, was 12).
- [x] Task 3: EDIT `app/src/display_thread.py` — update the tuple unpacking at line 466 to drop `y_offset`: `img, boxes_pp, output, use_time, origin_h, origin_w, frame_counter, r_scale, tx1, ty1, input_h, input_w = self.results` (match the new 11-element order from Task 2).
- [x] Task 4: EDIT `app/src/display_thread.py` — remove the two lines at 555-556: `box[1] += y_offset` and `box[3] += y_offset`. Leave the surrounding `undo_letterbox` call and the `boxes_scaled.append(box)` intact.
- [x] Task 5: EDIT `app/src/settings.py` — delete lines 55-56 (`self.TOP_IGNORE = ...` and `self.BOTTOM_IGNORE = ...`).
- [x] Task 6: EDIT `app/.env.example` — delete lines 51-52 (`TOP_IGNORE=100 ...` and `BOTTOM_IGNORE=50 ...`).
- [x] Task 7: EDIT `docs/04_configuration.md` — remove the `TOP_IGNORE` / `BOTTOM_IGNORE` row (line 89); add a short note (e.g. under the counting/detection section) that top/bottom band masking is now done via `MASK_ZONES` (BL-87, normalized rects) and the companion UI, with a cross-reference to the existing `MASK_ZONES` row already present in this file.
- [x] Task 8: EDIT `docs/05_counting_pipeline.md` — remove the `TOP_IGNORE` / `BOTTOM_IGNORE` bullet (line 374); replace/augment with a pointer to `mask_zones` for the band-ignoring use case.
- [x] Task 9: VERIFY `docs/IPC_CONTRACT.md` — confirm no `TOP_IGNORE`/`BOTTOM_IGNORE` references (grep during clarify found none; `mask_zones` is already documented at lines 187-188, 222-239). No edit expected; if any stray reference is found, remove it.

## Documentation Impact
- `docs/04_configuration.md` — the env-var table row for `TOP_IGNORE`/`BOTTOM_IGNORE` goes stale (removed in Task 7); add migration pointer to `mask_zones`.
- `docs/05_counting_pipeline.md` — the pipeline description referencing `TOP_IGNORE`/`BOTTOM_IGNORE` (line 374) goes stale (fixed in Task 8).
- `docs/IPC_CONTRACT.md` — not impacted (mask_zones already the documented mechanism; verify-only in Task 9).
- `README.md` / `AGENTS.md` / `ansible/README.md` — grep during clarify scoped to `TOP_IGNORE|BOTTOM_IGNORE` and `y_offset` across the repo; the only matches were the code + the two docs above. No README/AGENTS/ansible references found. The downstream docs-sync phase re-verifies.

## Validation
- **Retrocompat smoke**: start the app with an existing `.env` still containing `TOP_IGNORE=100`/`BOTTOM_IGNORE=50`. Expect: app boots, no `AttributeError` (settings.py no longer references the attrs), no crash. The vars are silently ignored.
- **Standard sheep reference**: run the counting validation against `validation-sheep-1-#47.mp4`, expected count 47. On the Jetson `TOP_IGNORE=0`/`BOTTOM_IGNORE=0` was already set for sheep → the crop was already a no-op → the count must remain 47 (PASS). If a mismatch arises, it is NOT this code (crop was already 0/0): investigate the `/conf` runtime-settings environment, do NOT auto-correct counting code.
- **Grep gate**: after edits, `grep -rn "TOP_IGNORE\|BOTTOM_IGNORE\|y_offset" app/ docs/` should return zero matches (confirming full removal).

## Risks
- **Tuple-order mismatch between infer_thread and display_thread** — if the `results` list and the unpacking in display_thread drift (off-by-one position), box coordinates/`input_h`/`input_w` get crossed. Mitigation: Tasks 2 & 3 are paired; the grep gate + a runtime smoke (boxes drawn at sensible coords) catch it.
- **`h, w` now unused after crop removal** — if `h`/`w` were only used by the crop slice, leaving them is harmless but a linter may warn. Mitigation: Task 1 notes to drop them if unused.
- **Pig deployment regression** — removing the crop means the pig (my_model) loses its hardcoded top/bottom masking on next redeploy. Mitigation: explicitly out of scope here; the deploy follow-up (issue #133 tâche 4) configures pig `mask_zones` via companion before redeploy. Reviewer-visible in Out of Scope.
- **False-positive count change blamed on this PR** — since the sheep crop was already 0/0, this change is count-neutral for sheep. Mitigation: validation notes call out that any count mismatch must be traced to `/conf`, not this code.