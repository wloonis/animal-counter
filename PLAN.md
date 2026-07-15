# Plan: BL-62 — Bouton « Arrêt » à l'écran (finalise vidéos + poweroff Jetson)

## Summary

Add a permanent « Arrêt » (power-off) button at the top-left of the counting screen (x=20, y=20) that finalizes any in-progress recording (flush moov atom, rename `tmp-counting` → `tocompress-counting`), stops the app cleanly, then powers off the Jetson via `nsenter` → `systemctl poweroff`. This replaces the current brutal power-cut (which corrupts mp4s and leaves K3s in an error state) with a graceful shutdown: the user clicks Arrêt, the machine halts cleanly, then they cut the electric power on an already-off machine.

## In Scope
- New asset `app/img/arret.png` (~30×90 BGRA, power/stop icon, same style as `reset.png`)
- `app/src/ui/rendering.py`: load `btn_arret`; draw it permanently at (20, 20) in all states; shift the play/pause/stop sprite right to avoid overlap; `handle_click` sets `shared_state.arret_requested = True`; show on-screen message "Le compteur va s'arrêter..." when `arret_requested` is True
- `app/src/utils/shared_state.py`: add `self.arret_requested = False` and `self.poweroff_requested = False`
- `app/src/main.py`: `DisplayThread.run` detects `arret_requested` → status=0/auto_mode=False/learning_mode=False → `_finalize_recording()` (CRITICAL, synchronous, BEFORE poweroff) → `stop_event.set()` → `poweroff_requested=True`; `__main__` CAMERA/serve mode adds wait loop → `stop()` → `nsenter systemctl poweroff`
- `k3s/templates/countingapp-dep.j2`: add `hostPID: true`; change `terminationGracePeriodSeconds: 0` → `15`

## Out of Scope
- Any counting/tracking/params logic (OC-SORT, FPS_OUTPUT=30, config.json mode='standard' untouched)
- The `--full` validation mode
- Committing `.env.local` or `.archon-relay/`

## Architecture Decisions

- **Button Arrêt standalone at x=20, y=20; sprite shifted right** — The Arrêt button occupies the top-left corner alone (x=20), and the existing play/pause/stop sprite is shifted right to `x = 20 + (base_width // 3) + 30` (gap=30px). Both aligned on the same row at y=20 (no vertical offset). This keeps the Arrêt at the ~20px-from-edge position per spec while avoiding overlap with the sprite (currently at `margin_x = 0.03*w` ≈ 38px).

- **Bouton Arrêt is PERMANENT in ALL states** — Unlike the learning/auto buttons which have on/off states, the Arrêt button is always visible (it's a power button, not a toggle). It's drawn unconditionally in `draw_ui()` for CAMERA input, regardless of `shared_state.status` or `shared_state.learning_mode`. This ensures the user can power off at any moment.

- **`handle_click` only sets a flag; `DisplayThread.run` does the heavy sequence** — The click callback runs in the mouse callback context (on the display thread via `cv2.setMouseCallback`). Setting `shared_state.arret_requested = True` is the only action. The main loop in `DisplayThread.run` detects this flag and executes the ordered shutdown sequence. This avoids any heavy/blocking logic in the click handler.

- **`_finalize_recording()` MUST run synchronously BEFORE any poweroff** — The moov atom flush (cv2.VideoWriter.release) and the `tmp-counting` → `tocompress-counting` rename happen in `DisplayThread.run` before `stop_event.set()` and `poweroff_requested=True`. This guarantees the recording is safe on disk before the machine begins shutting down. `_finalize_recording()` is already idempotent (guards on `writer is None / not isOpened / not recording`), so it's safe even if already finalized.

- **Main thread serve mode: wait loop → stop() → poweroff** — Currently in CAMERA/serve mode (RESULT_JSON_PATH not set), the main thread stays alive via non-daemon threads after `start()`. Add a `while not shared_state.stop_event.is_set(): time.sleep(0.5)` loop after `start()`, then `stop()` (join threads, TensorRT cleanup, destroy windows), then if `poweroff_requested`: `subprocess.run(['nsenter','-t','1','-m','-u','-i','-n','--','sh','-c','sync; systemctl poweroff'], check=False)`. The `nsenter -t 1` targets PID 1 in the host's PID namespace (systemd), which requires `hostPID: true` in the pod manifest.

- **`hostPID: true` + `terminationGracePeriodSeconds: 15`** — The pod is already `privileged: true` but needs `hostPID: true` to share the host's PID namespace so `nsenter -t 1` reaches the host's systemd. The grace period is bumped from 0 to 15 to give `stop()` (~5s) time to finish during the poweroff sequence (and also helps normal K3s restarts).

- **On-screen message during shutdown** — When `arret_requested` is True, display "Le compteur va s'arrêter..." on screen during the finalization/poweroff phase so the user knows the shutdown is in progress and doesn't click again or cut power prematurely.

## Tasks

- [x] Task 1: CREATE `app/img/arret.png` — Generate a ~30×90 BGRA PNG power/stop icon matching the style of `reset.png` (30×90, ratio ~1:3, alpha channel). If a polished icon can't be generated, create a functional 30×90 BGRA PNG (the user will refine the visual later). Must load successfully via `load_button()` (which requires `cv2.IMREAD_UNCHANGED` → 4 channels).

- [x] Task 2: EDIT `app/src/utils/shared_state.py` — Add `self.arret_requested = False` and `self.poweroff_requested = False` in `__init__` (near the end, after `self.stop_event = Event()`).

- [x] Task 3: EDIT `app/src/ui/rendering.py` — In `__init__` (after the `btn_reset` load, ~line 47), add: `self.btn_arret, self.btn_arret_inv_alpha, self.btn_arret_size = self.load_button("/app/img/arret.png")`.

- [x] Task 4: EDIT `app/src/ui/rendering.py` — In `draw_ui()`: (a) Draw the Arrêt button permanently at (x=20, y=20) with `base_width // 3` width via `self._draw_button(img, self.btn_arret, self.btn_arret_inv_alpha, 20, 20, base_width // 3, button_name="arret")` — this must be drawn BEFORE the sprite so the sprite (shifted right) doesn't overlap; (b) Change the sprite x position from `margin_x` to `x = 20 + (base_width // 3) + 30` (gap=30px) so it's shifted right of the Arrêt button; (c) If `shared_state.arret_requested` is True, draw the message "Le compteur va s'arrêter..." on screen (e.g. centered, red text, via `cv2.putText`).

- [x] Task 5: EDIT `app/src/ui/rendering.py` — In `handle_click()`: add a branch for `name == "arret"` that sets `shared_state.arret_requested = True` (no other logic — no status change, no finalize, no stop here).

- [x] Task 6: EDIT `app/src/main.py` — In `DisplayThread.run()`, at the TOP of the `while not self.stop_event.is_set():` loop (before the existing recording-stop logic), add a check: if `shared_state.arret_requested` is True, execute the ordered shutdown sequence: (a) `shared_state.status = 0`, `shared_state.auto_mode = False`, `shared_state.learning_mode = False`; (b) `self._finalize_recording()` (synchronous, flushes moov atom + renames tmp→tocompress — CRITICAL before any poweroff); (c) `shared_state.stop_event.set()`; (d) `shared_state.poweroff_requested = True`; then `break` out of the loop. The existing post-loop `self._finalize_recording()` safety-net call remains (idempotent no-op).

- [x] Task 7: EDIT `app/src/main.py` — In `__main__`, in the CAMERA/serve path (the `else` branch where `result_json_path` is empty/falsy — i.e. NOT the validate mode): after `start(input_source, video)` and `logger.info("Inference Started")`, add a wait loop `while not shared_state.stop_event.is_set(): time.sleep(0.5)`, then `stop()`, then `if shared_state.poweroff_requested: subprocess.run(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "--", "sh", "-c", "sync; systemctl poweroff"], check=False)`. Add `import subprocess` at the top of the file if not already present. This must NOT affect the validate mode (RESULT_JSON_PATH set) which has its own join/wait/stop logic.

- [x] Task 8: EDIT `k3s/templates/countingapp-dep.j2` — (a) Add `hostPID: true` at the pod spec level (under `spec.template.spec`, near `terminationGracePeriodSeconds`); (b) Change `terminationGracePeriodSeconds: 0` to `terminationGracePeriodSeconds: 15`.

- [x] Task 9: VERIFY — Run `python3 -m py_compile app/src/ui/rendering.py app/src/main.py app/src/utils/shared_state.py` to confirm no syntax errors. Confirm `config.json` mode is still 'standard' (untouched). Confirm no counting/tracking/params logic was changed.

- [ ] Task 10: VALIDATE — Prepare the fresh worktree (copy gitignored files: `.env.local`, `app/model/`, `app/.env`, `validation/videos/*.mp4` from the main worktree via `git worktree list` → first worktree path; do NOT symlink `app/model` — copy files for real). Run `scripts/validate_on_jetson.sh` in STANDARD mode (validation-1-#9, expected count 9). Do NOT use `--full`.

- [ ] Task 11: PR — Create a PR with body including `Closes #60` to auto-close the GitHub issue on merge.

## Validation
- `python3 -m py_compile app/src/ui/rendering.py app/src/main.py app/src/utils/shared_state.py` — no syntax errors
- `scripts/validate_on_jetson.sh` (STANDARD mode, validation-1-#9, expected 9) — counting logic unchanged
- Confirm `config.json` mode is still 'standard'
- Confirm only the 5 allowed files were touched: `app/img/arret.png`, `app/src/ui/rendering.py`, `app/src/main.py`, `app/src/utils/shared_state.py`, `k3s/templates/countingapp-dep.j2`

## Risks
- **arret.png fails to load** — `load_button()` returns `(None, None, None)` if the PNG isn't 4-channel or can't be read. `_draw_button` already guards on `btn is not None`, so a failed load is a no-op (button invisible but no crash). Mitigation: verify the PNG is BGRA 4-channel 30×90 after creation.
- **nsenter fails on the Jetson** — If `hostPID: true` doesn't grant access to the host's systemd PID 1, `nsenter -t 1 ... systemctl poweroff` may fail. Mitigation: `check=False` means it won't raise; the app still stops cleanly (stop() already ran). The poweroff just won't happen and the user can cut power manually (same as today, but with finalized videos). To be validated on the Jetson.
- **DisplayThread doesn't get to process arret_requested before stop_event** — The arret check is at the top of the loop, before the frame queue get. If the queue is empty, the `get(timeout=1)` times out and loops back to the arret check. So the flag is detected within ~1s. Mitigation: the check is at loop top, before any blocking get.
- **Main thread serve mode blocks forever if stop_event never sets** — The `while not stop_event.is_set(): sleep(0.5)` loop exits when DisplayThread sets stop_event (in the arret sequence) or on SIGTERM (handle_sigterm calls stop() which sets stop_event). Mitigation: stop_event is set by both the arret sequence and SIGTERM, so the loop always exits.
- **Sprite shift breaks existing button click coordinates** — The sprite is shifted right, but `draw_ui()` rebuilds `self.buttons` every frame with the new x position, and `handle_click()` reads from `self.buttons`, so the click hit-boxes move with the sprite. No hardcoded coordinates in handle_click. Mitigation: the buttons dict is the single source of truth for hit areas.