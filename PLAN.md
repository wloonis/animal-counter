# Plan: BL-93 — Per-model configurable input (CAMERA / STREAM RTSP) + decoupled I/O res + per-model output_fps + STREAM session lifecycle

## Summary

Make the frame input configurable **per-model** in `runtime-settings.json` (CAMERA V4L2 for pig `my_model`, STREAM RTSP 720p for sheep `sheep_template` drone), decouple the capture resolution (per-model `input_*`) from the recording resolution (`OUTPUT_*` 640×480, writer resize via merged PR #129), add a per-model `output_fps` that fixes the "recording plays 2× too fast" bug (writer@30fps vs 15fps FP16@1280 inference = time-compressed), add a low-latency grab-discard buffer (CAMERA + STREAM only), and give STREAM a session lifecycle (drone off = idle/save/reset/wait, reconnect = new session). Input config is read at startup only (no hot-reload; switching camera↔drone = restart), reusing the BL-89 per-model resolver pattern. No counting/tracking logic changes; standard validation only.

## In Scope

- `frame_source.py`: add `STREAM` type (`cv2.VideoCapture(rtsp_url)`); set `CAP_PROP_FRAME_WIDTH/HEIGHT` to `input_*` (NOT `OUTPUT_*`) for CAMERA; `CAP_PROP_BUFFERSIZE=1` + bounded grab-while-available/keep-last for CAMERA + STREAM only; RTSP reconnect+retry inside FrameSource (transparent `ret=False` while drone off).
- Per-model input config (`input_source`/`input_url`/`input_device`/`input_width`/`input_height`) under `models.<name>`; read at STARTUP only (NOT hot-reload), reusing BL-89 per-model resolver pattern in `state.py`.
- Per-model `output_fps` under `models.<name>`: `display_thread.py` writer init uses it (fallback to `settings.FPS_OUTPUT` env=30 for retrocompat); fixes the writer@30fps vs 15fps time-compression bug.
- STREAM session lifecycle: `infer_thread.py` does NOT break on `not ret` for `input_type=="STREAM"` (idle + retry); CAMERA keeps `break` (hardware disconnect → pod restart); FILE keeps `break` (EOF = validation done). Existing DisplayThread idle/finalize cycle saves recording + resets; reconnect = new recording.
- Input-source precedence: CLI `-m`/`-f` (validation/test) > per-model `runtime-settings.json` > env `INPUT_SOURCE`/`VIDEO_PATH` fallback.
- `settings.py` + `state.py`: per-model input + `output_fps` resolvers (startup path only — NOT in `RuntimeSettingsWatcher._build_pending`).
- `docs/IPC_CONTRACT.md`: document new `models.<name>` input keys + `output_fps` (companion byte-identical sync is a separate follow-up).

## Out of Scope

- OC-SORT / counting decision logic (crossing/guards/tracker params) — unchanged.
- `app/model/`, engine rebuilds, build-config.json/entrypoint.sh FP16 changes — already done separately (working tree).
- Companion repo (`animal-counter-companion`) API + Android UI — separate follow-up.
- `--full` validation — standard only.
- Runtime auto-detection of inference FPS (option B, §7) — deferred; static per-model `output_fps` (option A) for v1.

## Architecture Decisions

- **No-frame handling splits by input_type** (not a single global rule):
  - `STREAM` = idle + reconnect inside FrameSource (InferThread loops, does NOT break; FrameSource auto-reconnects RTSP, returns `ret=False` while drone off). The existing DisplayThread idle/finalize cycle (`_finalize_recording` on `status==0`/timeout at `display_thread.py:~442`) naturally saves the recording + resets; when frames resume, status transitions back to detecting → new recording starts. No new lifecycle code in DisplayThread.
  - `CAMERA` = `break` (hardware disconnect → DaemonSet restarts pod, today's behavior — a camera disconnect is a hardware event, not expected idle).
  - `FILE` = `break` (EOF = validation done; byte-identical to today).
- **Grab-discard is CAMERA + STREAM only**, bounded (grab up to N times, retrieve the last frame). FILE is excluded — validation must process every frame sequentially with no drops (byte-identical). The bound (N) prevents an unbounded grab loop from starving the queue; default N small (e.g. 5).
- **Input config is startup-only** — added to `_PER_MODEL_SETTINGS_KEYS` so `load_runtime_settings()` returns them in the flat dict, but NOT extracted by `RuntimeSettingsWatcher._build_pending()` (which only processes hot-reload keys: draw_tracking/box_tracking/centroid_tracking/draw_mask_zones/offset/orientation/counting_class_ids/mask_zones/counting_direction). A camera↔drone switch = restart (no hot-swap of a physical sensor).
- **`output_fps` is a static per-model estimate** (option A from §7), not runtime auto-detection (option B). Fallback to `settings.FPS_OUTPUT` (env=30) when `output_fps` absent in the active model's section — retrocompat for legacy deploys.
- **Input/output resolution decoupling**: `CAP_PROP_FRAME_WIDTH/HEIGHT` in FrameSource use `input_*` (per-model); the writer stays at `OUTPUT_*` 640×480 with the existing PR #129 resize (`display_thread.py:480-481,648-649`). STREAM uses native flux resolution (720p) — width/height props are hints, not forced (RTSP negotiates natively).
- **Precedence resolution lives across cli.py + main.py**: cli.py resolves the top-level `input_source`/`video_path` (CLI `-m`/`-f` > per-model `input_source`/`input_url`/`input_device` > env), since that's where `-m`/`-f` are parsed. main.py's `start()` reads the remaining per-model params (`input_width`/`input_height`/`output_fps`) and plumbs them to InferThread/DisplayThread/FrameSource constructors.

## Tasks

- [x] Task 1: EXTEND `app/src/state.py` — add input keys + output_fps to per-model resolution + new resolvers (startup path only).
  - Add `input_source`, `input_url`, `input_device`, `input_width`, `input_height`, `output_fps` to `_PER_MODEL_SETTINGS_KEYS` so `load_runtime_settings()` includes them in the flat dict (they are available at startup but ignored by the hot-reload watcher).
  - Add `resolve_input_config(rt, settings)`: validates + returns a dict `{input_source, input_url, input_device, input_width, input_height}` from the flat runtime-settings dict, falling back to `settings.INPUT_SOURCE`/`settings.VIDEO_PATH`/env defaults when absent/invalid. Validate `input_source` ∈ {CAMERA, STREAM, FILE}; `input_width`/`input_height` are positive ints (reject bool); `input_url` is a non-empty string (required when STREAM); `input_device` is a string (required when CAMERA). Log warnings on invalid values; never raise (fail-open → env fallback).
  - Add `resolve_output_fps(rt, settings)`: returns `models.<active>.output_fps` (positive int, reject bool) when present, else `settings.FPS_OUTPUT` (env=30). Log warning on invalid; never raise.
  - Do NOT touch `RuntimeSettingsWatcher._build_pending()` — input keys stay out of the hot-reload path (startup-only by design).

- [x] Task 2: ADD `app/src/settings.py` — env fallback defaults for input resolution + (already-present) FPS_OUTPUT.
  - Add `INPUT_WIDTH = int(os.getenv("INPUT_WIDTH", 640))` and `INPUT_HEIGHT = int(os.getenv("INPUT_HEIGHT", 480))` as legacy env fallbacks (used when per-model `input_width`/`input_height` are absent — retrocompat for pre-BL-93 deploys). `FPS_OUTPUT` already exists (line 71, default 30) — no change needed there.
  - These are fallbacks only; the per-model resolver in state.py overrides them at startup when the active model's section has the keys.

- [x] Task 3: REWRITE `app/src/utils/frame_source.py` — add STREAM type, decouple capture res to input_*, buffer+grab-discard, RTSP reconnect.
  - Extend `__init__` signature to accept `input_width`, `input_height`, `input_url=None` (in addition to `source`, `input_type`). Keep backward compat (default args so existing callers without the new params still work during migration).
  - `CAMERA` branch: replace `settings.OUTPUT_WIDTH/HEIGHT` with `input_width`/`input_height` for `CAP_PROP_FRAME_WIDTH/HEIGHT`; add `self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)`. Keep FOURCC + FPS=30 settings.
  - `STREAM` branch (new): `self.cap = cv2.VideoCapture(rtsp_url)` (no `CAP_V4L2`); set `CAP_PROP_BUFFERSIZE=1`; do NOT force FRAME_WIDTH/HEIGHT (RTSP negotiates native 720p). Store `self.rtsp_url` for reconnect. On `isOpened()` failure, do NOT raise immediately — set a `self._stream_disconnected=True` flag so `read()` can attempt reconnect (graceful: the drone may not be streaming yet).
  - `FILE` branch: unchanged (plain `cv2.VideoCapture(source)`, no buffer, no discard — byte-identical).
  - `read()`: for CAMERA + STREAM, implement bounded grab-discard: loop `self.cap.grab()` up to N times (default 5) while it returns True, keeping only the last; then `self.cap.retrieve()` returns the last grabbed frame. This drops stale frames so InferThread always processes the latest. For FILE, keep the single `self.cap.read()` (byte-identical, no drops).
  - `read()` STREAM reconnect: when `grab()`/`read()` fails (drone off), attempt to reopen the RTSP stream (close + `cv2.VideoCapture(rtsp_url)` + wait briefly); return `(False, None)` while disconnected so InferThread idles. Reconnect is transparent — InferThread keeps calling `read()`, gets `ret=False`, loops; when the drone restarts, reconnect succeeds and frames resume.

- [x] Task 4: MODIFY `app/src/infer_thread.py` — plumb input config to FrameSource + STREAM no-frame → idle (no break).
  - Extend `InferThread.__init__` to accept `input_width`, `input_height`, `input_url=None` (passed from main.py startup resolution). Store them.
  - Line 76: construct `FrameSource(self.video_path, self.input_type, input_width=self.input_width, input_height=self.input_height, input_url=self.input_url)`.
  - No-frame handling (lines 84-92): replace the unconditional `break` with a branch:
    - `if not ret:` → if `self.input_type == "STREAM"`: set `shared_state.status = 0` (idle), log "no frame (STREAM idle — reconnecting)", `time.sleep(1)` (brief backoff), `continue` (loop — FrameSource reconnects transparently). Do NOT break.
    - else (CAMERA / FILE): keep existing `shared_state.status = 0; break` (EOF fatal / hardware disconnect).

- [x] Task 5: MODIFY `app/src/display_thread.py` — writer init uses `output_fps` instead of hardcoded `30`.
  - Extend `DisplayThread.__init__` to accept `output_fps` param (passed from main.py startup resolution). Store as `self.output_fps`.
  - Line ~601: replace the hardcoded `30` in `cv2.VideoWriter(self.filename, cv2.VideoWriter_fourcc(*'mp4v'), 30, (settings.OUTPUT_WIDTH, settings.OUTPUT_HEIGHT))` with `self.output_fps`. The frame size stays `OUTPUT_WIDTH/HEIGHT` (PR #129 resize already handles input→output).
  - No change to the idle/finalize lifecycle — it already saves recordings on `status==0`/timeout, which is the STREAM session boundary.

- [x] Task 6: MODIFY `app/src/main.py` — read per-model input config + output_fps once at startup, plumb through to InferThread/DisplayThread.
  - In `start()` boot block (after the existing `load_runtime_settings()` call): call `resolve_input_config(rt, settings)` and `resolve_output_fps(rt, settings)`. These are startup-only reads (not re-read on hot-reload).
  - Resolve the effective input config: if the caller passed an explicit `input_source`/`video_path` via CLI override (validation/test), use those; otherwise use the per-model resolved values. Map: `CAMERA` → video_path = `input_device`; `STREAM` → video_path = `input_url`; `FILE` → video_path as passed.
  - Pass `input_width`, `input_height`, `input_url` to the `InferThread(...)` constructor (line ~298).
  - Pass `output_fps` to the `DisplayThread(...)` constructor (line ~306).
  - Log the resolved input config + output_fps at INFO for operability (which model, which source, which res, which fps).

- [x] Task 7: MODIFY `app/src/cli.py` — input-source precedence (CLI > per-model > env).
  - Lines 76-77: keep `input_source = settings.INPUT_SOURCE; video = settings.VIDEO_PATH` as the env fallback baseline.
  - When NO `-m` arg is passed (serve mode): resolve from per-model runtime-settings — read `model_name` (via `load_classes_yaml`) + `load_runtime_settings()`, then `resolve_input_config()` to get `input_source` + the matching path (`input_device` for CAMERA, `input_url` for STREAM). Override the env baseline. This is the per-model-driven prod path.
  - When `-m`/`-f` IS passed (validation/test): use them as-is (CLI override — FILE + file path). Skip per-model resolution.
  - The full input config (input_width/height/output_fps) is read inside `start()` (Task 6) — cli.py only resolves the top-level input_source/video_path since that's where `-m`/`-f` live.

- [x] Task 8: UPDATE `docs/IPC_CONTRACT.md` — document the new `models.<name>` input keys + `output_fps`.
  - Add to the `models.<model_name>` section documentation (after the existing per-model keys table): the 5 input keys (`input_source`, `input_url`, `input_device`, `input_width`, `input_height`) + `output_fps`, with type/range/default/effect columns matching the existing table style.
  - Note these are **startup-only** (not hot-reloaded — changing camera↔drone = pod restart), distinct from the hot-reloaded counting/visual keys.
  - Add a runtime-settings.json example snippet showing the full `my_model` (CAMERA) + `sheep_template` (STREAM) sections with the new keys (matching the issue §1 example).
  - Note the companion byte-identical sync is a separate follow-up (NOT this run) — add a "BL-93 — additive, companion sync pending" note like the existing BL-92 notes.

- [x] Task 9: ADD unit tests in `tests/` — cover the new resolvers + FrameSource STREAM/FILE/CAMERA branches.
  - `tests/test_resolve_input_config.py`: test `resolve_input_config()` — valid CAMERA config, valid STREAM config (input_url required), missing keys → env fallback, invalid input_source → fallback, invalid input_width (bool/zero/negative) → fallback, STREAM without input_url → fallback. Mirror the existing `tests/test_resolve_*.py` style.
  - `tests/test_resolve_output_fps.py`: test `resolve_output_fps()` — per-model value used, absent → `settings.FPS_OUTPUT` fallback, invalid (bool/zero/negative) → fallback.
  - `tests/test_frame_source.py` (or extend existing): test FrameSource construction for STREAM (no fatal on isOpen fail → reconnect flag), FILE read byte-identical (single read, no grab-discard), CAMERA uses input_width/height (not OUTPUT_*). Mock `cv2.VideoCapture` where needed (avoid real hardware).
  - Ensure the hot-reload watcher does NOT pick up input keys: add an assertion in an existing watcher test that `_build_pending()` output keys do not include input_source/input_url/etc.

## Documentation Impact

- `docs/IPC_CONTRACT.md` — directly edited (Task 8); the authoritative shared-file contract. Must stay byte-identical with the sister repo `animal-counter-companion` — but the companion sync is a separate follow-up (note in the doc + a co-issue).
- `docs/04_configuration.md` — documents `app/.env` env vars + the settings.py parameter table. Goes stale on: `INPUT_WIDTH`/`INPUT_HEIGHT` new env fallbacks (Task 2), `output_fps` per-model key, the input/output decoupling (CAP_PROP_FRAME_WIDTH/HEIGHT now uses input_* not OUTPUT_*). Needs a new section: per-model input config (startup-only) + the output_fps writer fix.
- `README.md` — the "Configuration at a glance" section lists `INPUT_SOURCE=CAMERA` / `VIDEO_PATH=/dev/video0` / `FPS_OUTPUT=30`. These remain valid as env fallbacks, but the README should mention per-model input config is now the prod source (runtime-settings.json `models.<name>`). The "Runtime features (hot-reloaded via /conf)" bullet list should clarify input config is NOT hot-reloaded (startup-only). The `Camera` requirements row (`USB webcam /dev/video0`) should note RTSP drone is now supported for the sheep model.
- `AGENTS.md` §7 — validation rules reference; unchanged (standard validation stays the bar). Verify no stale claim that input is always CAMERA.
- `docs/01_quickstart.md` / `docs/03_deployment.md` — may reference `/dev/video0` as the only input; goes stale for sheep deploys (RTSP). Low priority (the per-model config is the new path), but enumerate for the docs-sync phase.
- `app/.env.example` — if `INPUT_WIDTH`/`INPUT_HEIGHT` env vars are added (Task 2), the versioned `.env.example` should document them (fallbacks, overridden by per-model config). Enumerate for docs-sync.

## Validation

- **Standard validation** (per AGENTS.md §7): `bash scripts/validate_on_jetson.sh` — runs `validation-1-#9.mp4` (pig 640×480, expected 9) via the validate Job (`--input=FILE`). FILE mode is byte-identical (no grab-discard, no reconnect, single `read()`), and `output_fps` for `my_model` is 30 (= today's hardcoded 30), so the count result is unchanged. Expected: count = 9 (within tolerance 0).
- **Unit tests**: `cd app && python -m pytest ../tests/ -v` — the new resolver tests (Task 9) pass; existing tests unaffected (no counting logic touched).
- **Manual STREAM smoke test** (deferred — requires a live drone; not in this run's validation bar): verify the sheep model reconnects when the drone stops + resumes = new recording. Documented as a follow-up; the standard pig validation is the gate for this run.

## Risks

- **STREAM reconnect starvation**: if `read()` reconnects in a tight loop with no backoff, it burns CPU while the drone is off. Mitigation: brief `time.sleep(1)` backoff in InferThread's STREAM idle branch + capped reconnect attempts in FrameSource.
- **Grab-discard bound too high**: an unbounded or large N grab loop could stall when frames arrive faster than inference. Mitigation: bounded N (default 5) — grabs at most N frames per `read()`, always processing the latest; FILE is excluded entirely.
- **output_fps mismatch with actual inference cadence**: the static per-model estimate may drift under load (e.g. 15fps set but inference drops to 12fps under heavy occlusion). Mitigation: documented as a v1 tradeoff (option A); option B (runtime auto-detect) is a documented future enhancement. The recording stays real-time (no time-compression) even if the fps estimate is slightly off.
- **Validation regression from writer fps change**: if `output_fps` resolves wrong in FILE/validation mode, the writer fps changes and could affect the validate result. Mitigation: `my_model` per-model `output_fps=30` = today's hardcoded 30; env fallback `FPS_OUTPUT=30` when per-model absent. Validation is byte-identical by construction.
- **Backward compat for legacy deploys without per-model input keys**: pre-BL-93 `runtime-settings.json` files have no `input_source`/`input_width`/etc. Mitigation: resolvers fall back to `settings.INPUT_SOURCE`/`VIDEO_PATH`/`INPUT_WIDTH`/`INPUT_HEIGHT` env defaults → byte-identical pre-BL-93 behavior (CAMERA /dev/video0 640×480 @ 30fps).