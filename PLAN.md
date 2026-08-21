# Plan: BL-88 follow-up — countingapp snapshot writer

## Summary

The countingapp's `DisplayThread` periodically writes a JPEG snapshot of the
**raw** counting-resolution frame to `/files/snapshot.jpg` (atomic tmp+rename,
~every 5 s), so the already-deployed companion `GET /api/snapshot` (BL-88, PR
#19) can serve a live preview to the Android app's visual mask-zone editor.
This is pure display/infrastructure — no counting-decision logic is touched.

## In Scope
- `app/src/settings.py` — 4 new boot params (`SNAPSHOT_ENABLED`,
  `SNAPSHOT_INTERVAL_SECONDS`, `SNAPSHOT_PATH`, `SNAPSHOT_JPEG_QUALITY`).
- `app/src/display_thread.py` — time-gated raw-frame JPEG encode + atomic write
  inside the existing `run()` loop (no new thread).
- `app/.env.example` — document the 4 new env vars (versioned config example).
- `docs/04_configuration.md` — add the snapshot params to the parameter
  reference table.
- `docs/IPC_CONTRACT.md` — document `/files/snapshot.jpg` as a new shared data
  file (countingapp writes, companion reads via `GET /api/snapshot`).
- Standard validation (1 reference video, expect count 9 / PASS 9/9).

## Out of Scope
- Any change to counting-decision logic (franchissement / guards / tracker /
  OC-SORT) — the snapshot writer only reads the raw frame, never alters it.
- Companion side (BL-88 already deployed — `GET /api/snapshot` serves
  `/files/snapshot.jpg`, returns 404 if absent).
- Hot-reload of snapshot settings — boot params only, not `/conf`
  `runtime-settings.json` (this is display infra, not a runtime setting).
- `--full` validation (display/infra change, not counting logic).
- Resizing the snapshot — the raw counting-resolution frame is written as-is;
  the Android app normalizes mask-zone coords to `[0..1]`.

## Architecture Decisions
- **Raw frame, no overlays** — the snapshot is captured *before* any
  `tracking.draw_counter` / `rendering.display_counter` call, giving a clean
  canvas. The Android app draws its own mask-zone rectangles on top; pre-drawn
  tracking boxes/counter would clutter the editor. This also matches the
  coordinate space mask_zones normalize against (`[0..1]` of the counting
  frame).
- **Capture at top of loop, right after `img` is pulled from `frame_queue`** —
  `img` there is the raw counting-resolution frame, input-type-agnostic (FILE
  and CAMERA snapshot the same frame). Capturing here avoids a per-frame
  `.copy()` (the overlay calls mutate `img` in place later in the loop).
- **Wall-clock interval gating, not per-frame** — a `last_snapshot_time`
  timestamp is checked each iteration; the encode+write runs at most once per
  `SNAPSHOT_INTERVAL_SECONDS` (~5 s). The encode (`cv2.imencode`) + single
  binary write is sub-millisecond-scale and runs inside the existing display
  loop — no new thread, no blocking.
- **Atomic write (tmp + `os.replace`)** — encode to bytes, write to
  `SNAPSHOT_PATH + ".tmp"`, then `os.replace(tmp, SNAPSHOT_PATH)`. This
  prevents the companion from ever serving a half-written JPEG (the companion
  reads `/files/snapshot.jpg` directly via `send_file`).
- **Status-agnostic** — the snapshot is written every interval regardless of
  `shared_state.status` (idle/counting/pause/auto), as long as frames flow
  from the queue. The editor needs a live preview even when idle.
- **Best-effort, never fatal** — any encode/write failure is logged at WARNING
  and swallowed; it must never break the display loop or counting.
- **Boot-param toggle, default on** — `SNAPSHOT_ENABLED=true` by default so the
  feature works out-of-the-box; env-driven in `settings.py` (same pattern as
  `HISTORY_FILE`), not in `/conf`.

## Tasks
- [x] Task 1: ADD boot params `app/src/settings.py` — add 4 env-driven
  settings in `Settings.__init__` (alongside the existing `HISTORY_FILE` block
  near line 273): `SNAPSHOT_ENABLED = os.getenv("SNAPSHOT_ENABLED", "true").lower() == "true"`,
  `SNAPSHOT_INTERVAL_SECONDS = float(os.getenv("SNAPSHOT_INTERVAL_SECONDS", 5.0))`,
  `SNAPSHOT_PATH = os.getenv("SNAPSHOT_PATH", "/files/snapshot.jpg")`,
  `SNAPSHOT_JPEG_QUALITY = int(os.getenv("SNAPSHOT_JPEG_QUALITY", 85))`. Add a
  brief inline comment noting these are display-infra boot params (not
  `/conf` runtime-settings) and that the writer lives in `display_thread.py`.
- [x] Task 2: ADD snapshot writer `app/src/display_thread.py` — in `run()`:
  (a) init `last_snapshot_time = 0.0` near the other loop-locals (e.g. next to
  `last_capture_time = time.time()` ~line 180); (b) right after `img` is
  extracted from `self.results` (after the `if len(self.results) > 1: ... else:
  img = self.results[0]` block, before the "Recording without tracking" block),
  add a guarded block: `if settings.SNAPSHOT_ENABLED and (time.time() -
  last_snapshot_time) >= settings.SNAPSHOT_INTERVAL_SECONDS:` that calls a new
  small helper (e.g. `self._write_snapshot(img)`) and updates
  `last_snapshot_time = time.time()`. The helper encodes via
  `cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY,
  settings.SNAPSHOT_JPEG_QUALITY])`, writes the bytes to
  `settings.SNAPSHOT_PATH + ".tmp"` (binary, `open(...,"wb")`), then
  `os.replace(tmp, settings.SNAPSHOT_PATH)`. Wrap the whole helper body in
  `try/except Exception` logging at `logger.warning(...)` and returning
  silently — never raise. Do NOT touch any counting/tracking/rendering logic.
- [x] Task 3: DOCUMENT env vars `app/.env.example` — add the 4 new vars with
  their defaults and a one-line comment each (matching the existing
  `OUTPUT_VIDEO_PATH` / `HISTORY_FILE` style), so a fresh deploy from the
  versioned example gets the feature on by default.
- [ ] Task 4: UPDATE param table `docs/04_configuration.md` — add a new
  "Snapshot writer (BL-88)" subsection (or rows in the Input & output table)
  listing `SNAPSHOT_ENABLED` (true), `SNAPSHOT_INTERVAL_SECONDS` (5.0),
  `SNAPSHOT_PATH` (`/files/snapshot.jpg`), `SNAPSHOT_JPEG_QUALITY` (85), noting
  they are boot params (not hot-reloaded) and that the writer is in
  `display_thread.py`.
- [ ] Task 5: UPDATE shared-file contract `docs/IPC_CONTRACT.md` — in the
  `/files` (data) "Files" section, add a new entry for `snapshot.jpg`:
  countingapp **writes** it periodically (atomic tmp+rename, ~5 s, raw
  counting-resolution JPEG q85), companion **reads** it via
  `GET /api/snapshot` (BL-88, PR #19) and serves it to the Android mask-zone
  editor. Note it may be absent (404) before the first write / if
  `SNAPSHOT_ENABLED=false`.

## Documentation Impact
- `docs/IPC_CONTRACT.md` — the authoritative shared-file contract lists
  `/files` contents (`counting-history.jsonl`, `counting-*.mp4`, `dataset/`).
  `snapshot.jpg` is a NEW shared data file and is not yet listed → Task 5 adds
  it (writer = countingapp, reader = companion `GET /api/snapshot`).
- `docs/04_configuration.md` — the parameter reference table has no
  `SNAPSHOT_*` rows → Task 4 adds them. The "Applying changes" section
  distinguishes hot-reloaded `/conf` fields from boot params; the new
  `SNAPSHOT_*` are boot params and must NOT be listed as hot-reloadable.
- `app/.env.example` — versioned config example; no `SNAPSHOT_*` entries yet
  → Task 3 adds them so a fresh deploy enables the feature by default.
- `README.md` — the "Configuration at a glance" block lists a few key env
  vars but is intentionally non-exhaustive (points to `docs/04_configuration.md`);
  no edit needed (the snapshot params are infra, not operator-tuned).
- `docs/11_counting_history.md` — mentions "config snapshot" in the JSONL
  schema sense (unrelated to the JPEG snapshot); no edit needed.

## Validation
- **No-regression (standard):** `bash scripts/validate_on_jetson.sh` (single
  reference video, `validation/config.json` → `reference_video`). Expect
  `PASS 9/9` — the snapshot writer only reads the raw frame and writes a JPEG;
  it does not touch counting/tracking/guards, so the count must be unchanged.
- **Writer smoke check (on-Jetson, manual):** after a `serve`-mode pod boot,
  confirm `/files/snapshot.jpg` appears within ~5 s and its mtime updates
  every ~5 s (`stat -c %y /files/snapshot.jpg` polled). Confirm
  `GET /api/snapshot` on the companion returns `200 image/jpeg` (was 404 before
  the writer). Confirm toggling `SNAPSHOT_ENABLED=false` (env, pod restart)
  stops the writes.
- **Atomicity:** the companion must never observe a truncated file — verify no
  `snapshot.jpg.tmp` lingers on disk during steady-state (it is renamed
  atomically).

## Risks
- **Disk fill on `/files`** — a single ~50–150 KB JPEG overwritten every 5 s
  is negligible (one file, constant size, atomic replace). No retention logic
  needed. Mitigation: none beyond the single-file overwrite design.
- **Encode blocking the display loop** — `cv2.imencode` on a 640×480 frame is
  sub-millisecond; gated to once per 5 s. Mitigation: the time gate ensures it
  never runs per-frame; if ever a concern, the helper is isolated and could be
  moved to a thread later (not needed now).
- **`/files` not mounted / read-only** — if the hostPath is absent, the write
  fails; the `try/except` swallows it and logs WARNING. Mitigation: best-effort
  design; the companion already returns 404 when the file is absent, so a
  write failure degrades gracefully (no snapshot, no crash).
- **Half-written file served by companion** — mitigated by the atomic
  tmp+`os.replace` (the companion only ever sees the fully-renamed file).