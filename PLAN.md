# Plan: BL-54 — Fix orphan tmp-counting-*.mp4 at the source in DisplayThread

## Summary

The `tmp-counting-*` → `tocompress-counting-*` rename only runs inside the `DisplayThread` loop body (main.py ~284-302). When the `InferThread` reaches end-of-source in FILE mode, it sets `status=0` then immediately calls `stop_event.set()` in its `finally` block — if `DisplayThread` is blocked in `frame_queue.get(timeout=1)` at that moment, the loop exits via the `while not stop_event` check without ever reaching the rename block, leaving the `.mp4` as an orphan `tmp-counting-*`. The fix extracts the finalize logic into an idempotent `_finalize_recording()` helper and adds a single unconditional safety-net call immediately after the loop, guaranteeing the rename runs on every exit path.

## In Scope
- Add `_finalize_recording(self)` method to the `DisplayThread` class in `app/src/main.py`, encapsulating the existing inline release+rename+state-reset logic with an idempotent guard and robust error handling.
- Replace the inline rename block body (~284-302) with a call to `self._finalize_recording()`, preserving the existing FILE-mode `self.stop_event.set(); break`.
- Add one `self._finalize_recording()` call immediately after the `while not self.stop_event.is_set():` loop exits.
- Remove the 'q' key handler in CAMERA mode (`self.stop_event.set(); break` at main.py ~495-496) — the 'q' exit path must no longer exist.
- Modify `stop()` (main.py ~58-79) to call `_finalize_recording()` on `shared_state.display_thread` instead of releasing+nulling the writer directly, so SIGTERM / pod-restart / web-UI-stop during an active recording renames the file to `tocompress-counting-*` instead of leaving an orphan.

## Out of Scope
- No startup-recovery sweep / scan of `OUTPUT_VIDEO_PATH` (user explicitly rejected this rustine).
- No changes to `requirements.txt` (pure Python in main.py).
- No changes to `InferThread` or the compression pipeline (tocompress → counting).
- No recovery/salvage of the 4 existing Jetson orphans (the source fix prevents new ones).
- No changes to TRIM_TAIL / BL-53 logic, tracker config, or `settings.py` defaults.

## Architecture Decisions

- **Idempotent guard on `_finalize_recording`**: `if self.video_writer is None or not self.video_writer.isOpened() or not shared_state.recording: return`. This makes the helper safe to call from both the in-loop path and the post-loop safety-net without risk of double-release or double-rename. When the in-loop call already finalized (writer nulled), the post-loop call is a no-op.
- **`os.rename` wrapped in try/except OSError**: The current inline code calls `os.rename` unguarded — if it raises (e.g., destination exists, permission error), the exception kills the `DisplayThread`. The helper catches `OSError`, logs a warning, and returns gracefully, keeping the thread alive.
- **In-loop block retains FILE-mode `self.stop_event.set(); break`**: After calling `_finalize_recording()` in the in-loop block, the existing `if self.input_type == "FILE": self.stop_event.set(); break` is preserved, so end-of-source FILE behavior is unchanged.
- **Post-loop safety-net is a single unconditional call**: No conditionals needed — the guard inside `_finalize_recording` handles all no-op cases (writer already None from `stop()`, writer already finalized by in-loop call, no active recording).
- **'q' key handler removed from CAMERA mode**: The `cv2.waitKey(1) & 0xFF == ord('q')` block (main.py ~495-496) that calls `self.stop_event.set(); break` is removed entirely. This eliminates a loop exit path that could bypass the in-loop rename. The post-loop safety-net still covers any remaining exit paths.
- **`stop()` now calls `_finalize_recording()` instead of raw release+null**: `stop()` (main.py ~58-79) currently releases + nulls the writer without renaming. The fix changes this to call `shared_state.display_thread._finalize_recording()` (the same idempotent helper), so SIGTERM / pod-restart / web-UI-stop during an active recording produces a `tocompress-counting-*` file instead of an orphan. The sequence in `stop()` must be: (1) `stop_event.set()` first (to make the DisplayThread loop exit), (2) call `_finalize_recording()` on the display thread (release + rename), (3) join threads. This preserves the existing moov-atom guarantee (release before join to tolerate join timeout) while adding the rename. The idempotent guard prevents double-finalize if the loop already finalized before `stop()` runs.

### Guarantee matrix

| Exit path | In-loop rename ran? | Post-loop safety-net | Result |
|---|---|---|---|
| Race won (in-loop rename fired, FILE mode) | ✅ writer=None | no-op (guard) | ✅ single rename, no double |
| Race lost (stop_event pre-empted, FILE end-of-source) | ❌ writer still open | release + rename | ✅ orphan prevented |
| SIGTERM / pod-restart / web-UI-stop via `stop()` | depends on timing | stop() calls _finalize_recording directly (release + rename) | ✅ orphan prevented, tocompress-counting-* produced |
| `stop()` after loop already finalized (race won) | ✅ writer=None | stop()'s _finalize sees writer is None → no-op | ✅ single rename, no double |
| End-of-source, no active recording | N/A (writer is None) | no-op (guard) | ✅ app exits normally |

## Tasks

- [x] **Task 1: ADD** `app/src/main.py` — Add `_finalize_recording(self)` method to the `DisplayThread` class. The method must:
  - Guard: `if self.video_writer is None or not self.video_writer.isOpened() or not shared_state.recording: return` (idempotent, prevents double-release/rename).
  - Release: `self.video_writer.release(); self.video_writer = None`.
  - Build output path: `output_path = os.path.join(settings.OUTPUT_VIDEO_PATH, f"tocompress-counting-{time.strftime('%Y%m%d-%H%M%S')}-#{shared_state.counter_to_right}.mp4")`.
  - Rename with error handling: `try: os.rename(self.filename, output_path) except OSError as e: logger.warning(f"Failed to rename {self.filename} -> {output_path}: {e}"); return`.
  - State transitions: `if shared_state.status == 1: shared_state.status = 0`; `shared_state.recording = False`; `shared_state.reset = False`.
  - Log: `logger.info(f"------->Record Stop; Value Status: {shared_state.status}: Store:{output_path}")`.
  - Place the method logically near the top of the `DisplayThread` class body (e.g., after `__init__` / before `run`).

- [x] **Task 2: REPLACE** `app/src/main.py` (~284-302) — Replace the inline rename block body with a call to `self._finalize_recording()`, keeping the FILE-mode exit. The current block is the `if self.video_writer is not None and self.video_writer.isOpened() and shared_state.recording and (...)` conditional that does inline `release()`, `os.rename`, state transitions, and `if self.input_type == "FILE": self.stop_event.set(); break`. The replacement should:
  - Keep the outer `if` condition (so the finalize only fires when the recording-stop criteria are met — the post-loop safety-net covers the other exit paths).
  - Replace the inline body with `self._finalize_recording()`.
  - Keep `if self.input_type == "FILE": logger.info(f"------->MODE TEST. STOP."); self.stop_event.set(); break` after the finalize call.

- [x] **Task 3: ADD** `app/src/main.py` (immediately after the `while not self.stop_event.is_set():` loop body ends) — Add a single unconditional `self._finalize_recording()` call as the first statement after the loop exits. This is the safety-net that covers: race-lost (stop_event pre-empted the in-loop rename) and any other loop exit path. The guard inside `_finalize_recording` makes it a no-op when the writer is already finalized or None.

- [x] **Task 4: REMOVE** `app/src/main.py` (~495-496) — Remove the 'q' key handler in CAMERA mode. The current code block is:
  ```python
  if cv2.waitKey(1) & 0xFF == ord('q'):
      self.stop_event.set()
      break
  ```
  Delete this entire `if` block. The CAMERA loop should no longer have a keyboard-based early exit. The `cv2.waitKey(1)` call itself may remain if needed for OpenCV event processing, but the 'q' check and the `stop_event.set(); break` must be removed.

- [x] **Task 5: MODIFY** `app/src/main.py` (~58-79) — Modify `stop()` to call `_finalize_recording()` on the display thread instead of the raw release+null. The current code is:
  ```python
  def stop():
      logger.info("Stopping threads...")
      shared_state.stop_event.set()
      if shared_state.display_thread is not None and shared_state.display_thread.video_writer is not None:
          shared_state.display_thread.video_writer.release()
          shared_state.display_thread.video_writer = None
      if shared_state.infer_thread and shared_state.infer_thread.is_alive():
          shared_state.infer_thread.join(timeout=5)
      if shared_state.display_thread and shared_state.display_thread.is_alive():
          shared_state.display_thread.join(timeout=5)
      cv2.destroyAllWindows()
      logger.info("Stopped cleanly")
  ```
  Replace the inline `release() + = None` block with `shared_state.display_thread._finalize_recording()`. The `stop_event.set()` stays first (to make the loop exit). The `_finalize_recording` call then does release + rename + state transitions (idempotent guard handles the case where the loop already finalized). The joins stay after the finalize. This guarantees: SIGTERM / pod-restart / web-UI-stop during active recording produces a `tocompress-counting-*` file, and the moov atom is flushed before the join (preserving the existing tolerance for join timeout).

## Validation

1. **Syntax check** (required by AGENTS.md convention):
   ```bash
   python3 -m py_compile app/src/main.py
   ```
   Must exit 0 with no errors.

2. **Priority validation on Jetson** (4 videos only — do NOT relaunch all 30):
   ```bash
   # Ensure worktree has gitignored validation assets (copy/symlink from main repo):
   #   .env.local, validation/videos/*.mp4, app/model/, app/.env
   bash scripts/validate_on_jetson.sh --full
   ```
   Expected results:
   - **4/4 counting pass** (validation-13-#12, validation-14-#30, validation-22-#42, validation-27-#35) — counts must remain exact (fix must not alter counting logic).
   - **Zero orphan `tmp-counting-*.mp4`** in `OUTPUT_VIDEO_PATH` — all 4 videos must produce `tocompress-counting-*` files (renamed successfully).
   - TRIM_TAIL (BL-53) must still work on the resulting `counting-*` files (no regression in the compression cycle).

3. **Smoke test — CAMERA mode** (optional but recommended):
   - Run briefly in CAMERA mode, trigger a recording (detect a pig or start counting), then stop via the Flask web UI (which triggers `stop()`).
   - Verify: the recording file is renamed to `tocompress-counting-*` (not left as `tmp-counting-*`) — the `stop()` path now renames via `_finalize_recording`.
   - Verify: pressing 'q' no longer exits the app (the handler is removed).

## Risks
- **Double-rename if guard is insufficient** — Mitigated by the idempotent guard checking `video_writer is None` (set to None after release in `_finalize_recording`), `not isOpened()`, and `not shared_state.recording` (set to False after finalize). Any two calls to `_finalize_recording` are safe: the second always hits the guard and returns.
- **Rename fails (destination already exists from a prior call with same timestamp/counter)** — Mitigated by try/except OSError → logger.warning + return. The thread survives; the file stays as `tmp-counting-*` (degraded but not a crash). This is strictly better than current behavior (thread death).
- **Behavioral change in CAMERA mode: 'q' exit removed** — Previously pressing 'q' in CAMERA mode would `stop_event.set(); break` and could leave a `tmp-counting-*` orphan. Now this exit path no longer exists — the CAMERA loop has no keyboard-based early exit. This is the intended fix per reviewer feedback. If the operator needs to stop the app, they use the Flask web UI stop endpoint (which triggers `stop()`), not the 'q' key.
- **Concurrency between `stop()` and DisplayThread loop both calling `_finalize_recording`** — `stop()` runs in the signal handler / main thread, while the DisplayThread loop may also call `_finalize_recording` (in-loop or post-loop). The existing code already releases the writer from `stop()` while the loop runs (same race). The idempotent guard (`video_writer is None`) prevents double-release/double-rename: whichever call runs first nulls the writer, the second sees `None` and returns. Python's GIL serializes the guard check + null assignment sufficiently for this pattern. If extreme paranoia is desired, `stop()` sets `stop_event` first so the loop exits before `stop()` calls `_finalize_recording` — but the loop may still be blocked in `frame_queue.get(timeout=1)` for up to 1s, so the guard is the real safety.
- **`stop()` finalize before join preserves moov atom** — The existing `stop()` releases the writer before joining the display thread (to tolerate join timeout). The fix preserves this: `_finalize_recording` releases first, then renames, all before the join. Even if the join times out and the thread is killed, the file has been released (moov flushed) and renamed.