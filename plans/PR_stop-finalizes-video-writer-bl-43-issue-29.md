# Plan: stop() finalizes video_writer (BL-43 / issue #29)

## Summary
`stop()` in `app/src/main.py` is the SIGTERM entrypoint but does not release `DisplayThread.video_writer`, so a K3s pod kill leaves the mp4 without its `moov` atom → unreadable video. Fix: release the writer in `stop()` *before* joining `display_thread` so the file is finalized even when the 5s join times out and the thread is killed mid-write.

## In Scope
- Add a `video_writer` release block to `stop()` in `app/src/main.py` (after `shared_state.stop_event.set()`, before `shared_state.display_thread.join(timeout=5)`).
- Add a brief code comment explaining why release happens before `join`.
- Validate via `scripts/validate_on_jetson.sh` (priority videos only) — rsync code only, NO Docker rebuild.

## Out of Scope
- OC-SORT, `FPS_OUTPUT=30`, `H=0` — leave untouched (do not reintroduce `H=25` hysteresis).
- Guard params and any other `DisplayThread.run()` run-loop logic (write/release paths at lines ~274-280, 306-307, 411-422, 467-468) — leave intact.
- K3s manifests / templates / `entrypoint.sh` (BL-46/BL-18 are umbrella references, not additional edits here).
- No dependency changes → no Docker image rebuild.

## Architecture Decisions
- **Release before join, not after.** The `display_thread.join(timeout=5)` can time out and the thread gets killed mid-write; releasing *after* the join would never run in that case. Releasing before the join guarantees the mp4 `moov` atom is flushed/finalized regardless of whether the join succeeds.
- **Access via `shared_state.display_thread.video_writer`.** The `DisplayThread` instance is held on `shared_state`, and `video_writer` is a public attribute on it (init `None` at line 226, opened at line 422). Reaching in from `stop()` mirrors how the existing run-loop release at 279-280 already manages it.
- **Safe to release while the thread is alive.** The `run()` loop gates writes on `shared_state.recording` / `shared_state.stop_event`; `cv2.VideoWriter.release()` only flushes/finalizes the file — it does not deadlock the loop. After setting the writer to `None`, the loop's existing `is not None` guards (lines 274, 306, 467) short-circuit cleanly.
- **Set writer to `None` after release** so the run loop's `self.video_writer is not None` guards don't double-release or write to a closed writer.
- **Minimal scope: one new block + comment in `stop()` only.** No new helpers, no run-loop edits.

## Tasks
- [ ] Task 1: EDIT `app/src/main.py` — In `stop()` (~line 58-71), after `shared_state.stop_event.set()` and *before* the `if shared_state.display_thread and shared_state.display_thread.is_alive(): shared_state.display_thread.join(timeout=5)` block, insert a release block guarded by existence + non-None:
  ```python
  # Finalize the mp4 before joining display_thread: on a K3s SIGTERM the
  # 5s join may time out and the thread can be killed mid-write, leaving
  # the file without a moov atom (unreadable). Releasing here flushes/
  # finalizes the writer even if the join times out. Safe to release while
  # the loop is still running — it gates writes on shared_state.recording /
  # stop_event and the 'is not None' guards short-circuit once we null it.
  if shared_state.display_thread is not None and shared_state.display_thread.video_writer is not None:
      shared_state.display_thread.video_writer.release()
      shared_state.display_thread.video_writer = None
  ```
- [ ] Task 2: VERIFY `app/src/main.py` — Confirm no other edits were made: the `infer_thread.join`, `display_thread.join`, and `cv2.destroyAllWindows()` lines are unchanged; the run-loop write/release paths (274-280, 306-307, 411-422, 467-468) are untouched; `FPS_OUTPUT=30`, `H=0`, and guard params are unchanged.
- [ ] Task 3: VALIDATE via `scripts/validate_on_jetson.sh` — Run with priority videos only to (a) confirm counting still works, (b) confirm the app shuts down cleanly on SIGTERM (check the produced mp4 is playable / has a `moov` atom, e.g. `ffprobe` or `mp4info`). Rsync code only — do NOT rebuild the Docker image (no dependency change).

## Validation
- `scripts/validate_on_jetson.sh` (priority videos): counts match baseline and the recorded mp4 from a SIGTERM-terminated run is openable with `ffprobe <file>` (moov atom present).
- Manual: send SIGTERM mid-recording and verify `Stopped cleanly` log line appears and the mp4 is playable.
- Static: `python -c "import ast; ast.parse(open('app/src/main.py').read())"` (syntax sanity) if a quick lint is desired without running on-device.

## Risks
- **Double-release if the run loop also releases between our release and the join.** Mitigated: we set `video_writer = None` immediately after `release()`, and the run-loop release at 279-280 is itself guarded by `is not None` / `isOpened()`, so a racing release becomes a no-op. `cv2.VideoWriter.release()` is also safe to call on an already-released writer.
- **Release races with an in-flight `video_writer.write(img)`.** `release()` flushes/finalizes; the worst case is one frame dropped, which is acceptable and strictly better than a corrupt moov-less file. No deadlock risk since `release()` doesn't block on the loop.
- **`shared_state.display_thread` is `None` at very early startup SIGTERM.** Guarded by the `is not None` check; no `AttributeError`.