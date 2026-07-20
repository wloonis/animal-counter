# Plan: BL-70 — Per-video delta in the video filename (issue #74)

## Summary
The video clip filename must carry the **per-video delta** (net pigs counted *during that recording*) instead of the global cumulative counter. The on-screen global counter (`counter_to_right`) and its reset logic are left completely untouched. Snapshot the global counter at recording start, compute `delta = final − start` at release, and put `delta` in the `#{...}` slot of the final filename.

## In Scope
- `DisplayThread` (app/src/main.py): capture `record_start_count` snapshot of `shared_state.counter_to_right` at recording start; compute delta in `_finalize_recording` and substitute it into the final filename.
- New lightweight unit test asserting the renamed file uses the delta (positive, zero, negative cases).
- Verify `k3s/templates/cronvideo-dep.j2` compatibility with the new filename (verify-only — no edit).

## Out of Scope
- Any change to the global counter `counter_to_right` or its reset logic (boot reset / manual user reset unchanged).
- Any code edit to `k3s/templates/cronvideo-dep.j2`.
- Changes to `app/src/core/counting.py` or `app/src/core/history.py` (history `last_segment` flows the new filename automatically; heartbeat `count` stays global — no edit needed).

## Architecture Decisions
- **Per-video counter derived as a zero-point from the global counter** (issue #74 suggested approach — capture at start, compute delta at release). We capture `record_start_count = shared_state.counter_to_right` at recording start, which establishes a **zero-point** for this video; the per-video count is then `counter_to_right - record_start_count`, which is `0` at recording start and grows by exactly the line crossings during this recording. This is the natural "pigs counted during this recording" semantic.

  **Why snapshot+delta rather than a separate independent sub-counter starting at 0?** The two are mathematically identical: the global `counter_to_right` changes *only* via line crossings, so `delta = end − start` is exactly the crossings during the recording — i.e. the same value an independent from-0 counter would hold. The snapshot approach is the **minimal, lowest-risk** change: it touches only `DisplayThread` (2 lines), reuses the existing recording-start snapshot block (which already captures `record_start_time`), and requires **no edit to `counting.py`** (out of scope) and **no per-frame loop modification**. A genuinely independent sub-counter would require either (a) refactoring `Counting.count()` to maintain/return a second counter — a `counting.py` change that is explicitly out of scope and risks the validated counting invariants, or (b) per-frame bookkeeping in the run-loop (track the per-frame global delta `new − old` and accumulate into `self.video_count`) — more code, more surface for off-by-one bugs at the recording-start frame, and no behavioral benefit. The reviewer's point that the triggering pig hasn't crossed the line yet at the first detected frame is exactly what makes the snapshot sound: `counter_to_right` at recording start does **not** include the triggering pig (it is only *detected*, not *crossed*), so the zero-point is correct.
- **Raw delta, no clamping**: filename shows `#-1`, `#0` as-is, consistent with the bidirectional counting logic (LEFT crossings decrement the global counter, so the delta can go negative within a clip). No special-casing.
- **Defensive guard for missing snapshot**: if `record_start_count is None` (shouldn't happen in normal flow, but the finalize path is called from multiple exit points including the safety-net at loop exit), fall back to `delta = 0` so the filename is always well-formed. Never read a stale snapshot across recordings — reset to `None` after finalize, mirroring `record_start_time`/`record_duration` lifecycle.
- **J2 verify-only**: the `tocompress-*` / `count*` globs and `sed 's/^tocompress-//'` rename in `cronvideo-dep.j2` match on the literal `tocompress-`/`counting-` prefixes and are agnostic to the numeric value in `#{...}`. New filename `tocompress-counting-{ts}-#{delta}.mp4` → `counting-{ts}-#{delta}.mp4` still matches both globs, so no template edit is required.
- **Global counter untouched**: the per-video count is computed *read-only* from `counter_to_right`; we never write to it, never reset it, and never alter its boot/manual-reset logic.

## Tasks
- [x] Task 1: ADD `self.record_start_count = None` to `DisplayThread.__init__` in `app/src/main.py` (~line 270, alongside `self.record_start_time`/`self.record_duration`) — new instance attribute to hold the per-recording counter snapshot.
- [x] Task 2: CAPTURE the snapshot in the recording-start block of `app/src/main.py` (~line 492, alongside `self.record_start_time = time.monotonic()`) — set `self.record_start_count = shared_state.counter_to_right` so it reflects the count *before* the triggering frame's `counting.count()` runs.
- [x] Task 3: COMPUTE delta and use it in the final filename in `_finalize_recording` in `app/src/main.py` (~line 289) — replace `#{shared_state.counter_to_right}` with `#{delta}` where `delta = (shared_state.counter_to_right - self.record_start_count) if self.record_start_count is not None else 0`.
- [x] Task 4: RESET `self.record_start_count = None` at the end of `_finalize_recording` in `app/src/main.py` (mirror the `record_start_time`/`record_duration` lifecycle so a stale snapshot never leaks into the next recording).
- [ ] Task 5: ADD a lightweight unit test (e.g. `tests/test_finalize_recording_filename.py`) asserting the renamed file uses the delta — mock `shared_state` (with `recording=True`, `counter_to_right`, `status`) + a dummy `video_writer` whose `isOpen()` is True, covering positive delta (start 5 → end 12 → `#7`), zero delta (start 5 → end 5 → `#0`), and negative delta (start 5 → end 4 → `#-1`). Assert the global `counter_to_right` is unchanged by finalize.
- [ ] Task 6: VERIFY `k3s/templates/cronvideo-dep.j2` compatibility (read-only inspection, no edit) — confirm `tocompress-counting-{ts}-#{delta}.mp4` matches the `for f in /videos/tocompress-*` glob, that `sed 's/^tocompress-//'` yields `counting-{ts}-#{delta}.mp4`, and that the pruned `counting-...` output still matches `ls -t count*`. Document the verification result in the PR description.

## Validation
- `cd app && python -m pytest tests/test_finalize_recording_filename.py -q` — new test passes (positive/zero/negative delta cases + global counter unchanged).
- `cd app && python -m pytest tests/test_counting_invariance.py tests/test_history_writer.py -q` — existing regression suite still green (no behavior change to counting or history).
- Static grep check: `grep -n "counter_to_right" app/src/main.py` confirms the global counter is still only assigned at line ~511 (`shared_state.counter_to_right = self.counting.count(...)`) and never reset/altered by the new delta logic.
- Manual on-device (Jetson): run a counting session, confirm (a) the on-screen global counter still accumulates across clips and resets only at boot/manual reset, and (b) each produced `tocompress-counting-*#N.mp4` carries `N` = pigs counted during that clip (delta), not the cumulative total.

## Risks
- **Stale snapshot leaking across recordings** — mitigated by resetting `record_start_count = None` after finalize (Task 4) and the existing `recording` guard at the top of `_finalize_recording`.
- **Finalize called from an exit path that skipped recording-start** (e.g. safety-net finalize at loop exit) — mitigated by the `record_start_count is None → delta = 0` defensive guard (Task 3); filename stays well-formed.
- **Companion/history assuming the filename holds the global count** — verified: `app/src/core/history.py` stores `last_segment` as an opaque string and `count` from the heartbeat (global), neither parses `#{...}`, so the change is transparent. No edit needed.
- **J2 glob regression** — mitigated by Task 6 verify-only inspection; globs match on prefixes, not the numeric token.