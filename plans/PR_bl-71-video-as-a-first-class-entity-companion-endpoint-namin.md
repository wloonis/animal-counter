# Plan: BL-71 — Video as a first-class entity + companion endpoint naming (sessions vs videos)

## Summary

Make the recorded VIDEO a first-class entity in the counting-history JSONL by
emitting a per-video `video` line at recording release (`_finalize_recording`),
and clarify the Jetson companion's HTTP API: add `/api/videos` (paginated list,
one row per video including the currently-running recording as a synthetic
first row) and `/api/video/<id>` (Range-streamed compressed MP4), and cleanly
rename `/api/history` → `/api/sessions` and `/api/history/summary` → `/api/summary`
with **no** compatibility alias. Expose `record_start_count` in heartbeats so
the companion can compute the running recording's live count delta. This is
instrumentation + endpoints only — no counting/tracking/guard logic changes.

## In Scope

- `app/src/core/history.py`: new `video()` writer (append-only `video` JSONL line
  type) + add `record_start_count` to the `heartbeat()` line.
- `app/src/main.py`: emit the `video` entry in `_finalize_recording()` after the
  successful rename to `tocompress-counting-{ts}-#{delta}.mp4`.
- `ansible/playbooks/system/configure_companion.yml` (embedded stdlib HTTP server
  + `HistoryIndex`):
  - Rename route `/api/history` → `/api/sessions` and `/api/history/summary` →
    `/api/summary` (clean break; old paths return 404 — no alias).
  - New `/api/videos`: paginated list (`limit`/`offset`, newest first) built from
    `video` JSONL lines, with the running recording as a synthetic first row.
  - New `/api/video/<id>`: serve the compressed `counting-{id}-*.mp4` only, with
    full HTTP Range / 206 partial streaming; 404 if absent.
  - Update the endpoint-listing comment blocks (playbook header + script header).

## Out of Scope

- No OC-SORT / counting / tracking / guard decision-logic changes (instrumentation only).
- No `requirements.txt` change (no image rebuild) — companion stays stdlib-only.
- Compression cron (`k3s/templates/cronvideo-dep.j2`) unchanged — it already
  produces H.264/AAC `counting-*.mp4` readable on the phone.
- No `config.json` mode flip (validation mode = STANDARD, reference video only).
- No compatibility alias for old `/api/history` / `/api/history/summary` (clean
  break — the Android app is the only consumer and is updated in lockstep).
- No fallback to raw `tocompress-*` / `tmp-*` files in `/api/video/<id>`.

## Architecture Decisions

- **`video_id` = the timestamp stem `counting-{YYYYMMDD-HHMMSS}`** (e.g.
  `counting-20250608-100000`), WITHOUT the `#N` delta suffix. Unique per
  recording, human-readable, no UUID. `/api/video/<id>` resolves the file by
  globbing `counting-{id}-*.mp4` in `/data/orin/files` — the same host directory
  the JSONL lives in and the compression cron writes `counting-*.mp4` into (the
  cron strips the `tocompress-` prefix), so no new mount is needed.
  - Rationale: the on-disk filename is `tocompress-counting-{ts}-#{delta}.mp4`
    at release, then the cron rewrites it to `counting-{ts}-#{delta}.mp4`. The
    stable, compression-independent key is the `{ts}` stem; the `#N` is metadata
    carried in the JSONL `video` line, not part of the id.
- **Running recording id** = `counting-{ts}` with no `#N` (delta not finalized
  until release); surfaced as the synthetic first row of `/api/videos` with
  `status:"running"`. There is no compressed file to serve for it yet, so
  `/api/video/<id>` on a running id returns 404 (no `tocompress`/`tmp` fallback).
- **`/api/video/<id>`** serves compressed `counting-*.mp4` only; 404 if absent
  (not yet compressed, or deleted by the budget guard). Range/206 streaming is
  required so the Android player can seek/resume large files.
- **`/api/videos`** mirrors `/api/sessions` (`limit`/`offset`, newest first); the
  running recording is a synthetic first row in one unified list — NOT a separate
  top-level `recording` field.
- **Renames are clean breaks** — old `/api/history` and `/api/history/summary`
  paths fall through to the existing 404 handler; no alias is added.
- **`video` entry emit point** = `_finalize_recording` after the successful
  `os.rename` (best-effort, never raises; history is best-effort per the existing
  `_append` contract). It is NOT emitted on the rename-failure early return.
- **`video` JSONL line is a new first-class type** alongside `session_start`,
  `heartbeat`, `event`, `session_end`, `summary`. The companion's `HistoryIndex`
  gains a parallel `video`-line index (rebuilt on file-size change, same
  invalidation strategy as the session index). Compaction (`summary` lines) does
  not need to fold `video` lines for BL-71 — videos are per-recording facts that
  remain valid after a session is compacted; the compactor re-emits `video` lines
  verbatim (like it already does for `startup` lines).

## Reuse

- `app/src/core/history.py:321` `_append(self, obj)` — the single atomic
  append+fsync writer; `video()` will call it exactly like `emit_event` does.
- `app/src/core/history.py:538` `heartbeat()` — already reads
  `shared_state.counter_to_right`, `shared_state.display_thread.filename`,
  `status`, `auto_mode`; adding `record_start_count` follows the same
  `getattr(self.shared_state.display_thread, "record_start_count", None)` pattern.
- `app/src/main.py:300-304` — `delta` and `output_path` are already computed in
  `_finalize_recording`; the `video` entry reuses both (no recompute). The
  timestamp stem is already in `output_path` (`tocompress-counting-{ts}-#{delta}.mp4`).
- `ansible/.../configure_companion.yml:197` `HistoryIndex` — `_build()` scans the
  JSONL once and keeps `_sessions`/`_session_order`/`_latest_hb`; a `video` index
  (`_videos`/`_video_order`) is added the same way, keyed on `type == "video"`.
- `ansible/.../configure_companion.yml:379` `session_summaries(limit, offset)` —
  the pagination pattern (`ids = self._session_order[offset:offset+limit]`) is
  reused verbatim for `video_summaries()`.
- `ansible/.../configure_companion.yml:553+` route dispatch — the new routes are
  additional `if path == ...` / `if path.startswith(...)` blocks mirroring the
  existing `/api/history` and `/api/sessions/<id>` handlers.
- Stdlib only: `http.server`, `os`, `glob`, `stat`, `re` — all already imported
  by the companion script; Range parsing is stdlib string work (no new deps).

## Tasks

- [ ] **Task 1: ADD `video()` writer + `record_start_count` to heartbeat** `app/src/core/history.py` — Add a `video(self, video_id, filename, duration, count_delta, session_id=None)` method that builds a `{"type":"video","video_id":...,"filename":...,"duration":...,"count_delta":...,"session_id":...,"ts":_utcnow_iso()}` line and appends it via the existing `self._append(line)` (best-effort, guards on `self._stopped`/`self.session_id is None` like `emit_event`). In `heartbeat()`, add `"record_start_count": <int or None>` sourced from `getattr(self.shared_state.display_thread, "record_start_count", None)` alongside the existing `count`/`last_segment`/`status`/`auto_mode` reads, so the companion can compute `live_delta = heartbeat.count - heartbeat.record_start_count`.
- [ ] **Task 2: EMIT `video` entry in `_finalize_recording`** `app/src/main.py` — After the successful `os.rename(self.filename, output_path)` (and before/after the `shared_state.status`/`recording` reset), call the history writer's new `video()` with: `video_id` = the timestamp stem `counting-{time.strftime('%Y%m%d-%H%M%S')}` (strip the `tocompress-` prefix and the `-#{delta}` suffix from `output_path`), `filename` = `os.path.basename(output_path)`, `duration` = `self.record_duration`, `count_delta` = `delta`, `session_id` = the current session id from `shared_state.history.session_id` (best-effort via getattr; None if unavailable). Wrap in try/except so a history write failure never breaks recording finalization (mirrors the "history is best-effort" contract). Do NOT emit on the rename-failure `return` path. Derive the `time.strftime` stem from the SAME `time.strftime('%Y%m%d-%H%M%S')` call already used to build `output_path` (capture it into a local once, reuse for both the filename and the `video_id`), so the id and the on-disk filename stay in lockstep.
- [ ] **Task 3: RENAME companion routes (clean break)** `ansible/playbooks/system/configure_companion.yml` — In the embedded script's `do_GET` dispatch, change `if path == "/api/history":` → `if path == "/api/sessions":` and `if path == "/api/history/summary":` → `if path == "/api/summary":`. Leave the bodies (pagination/daily-aggregate logic) unchanged. Do NOT add any handler for the old paths — they fall through to the existing `GET {} -> 404` line. Update the two endpoint-listing comment blocks (the playbook top-of-file `# What it does:` block and the script-header `# Endpoints:` block) to list `/api/sessions`, `/api/summary`, and the two new routes from Tasks 4-5.
- [ ] **Task 4: ADD `/api/videos` list endpoint** `ansible/playbooks/system/configure_companion.yml` — Extend `HistoryIndex` with a `video` index: in `_build()`, collect `type == "video"` lines into `self._videos` (a dict keyed by `video_id`) and `self._video_order` (newest-first by the line's `ts`). Add a `video_summaries(self, limit=50, offset=0)` method mirroring `session_summaries` that returns `(rows, total)` where each row is `{"video_id","filename","duration","count_delta","session_id","ts","status":"ready"}`. Add a `_running_video_row()` helper that, from `self.latest_count()` (the newest heartbeat), synthesizes a first row when a recording is in progress: `status:"running"`, `video_id` = the `counting-{ts}` stem derived from the heartbeat's `last_segment` filename (parse the `tocompress-counting-{ts}-#N.mp4` / `tmp-counting-{ts}.mp4` stem; if `last_segment` is absent or unparseable, omit the running row), `count_delta` = `hb["count"] - hb["record_start_count"]` (only when `record_start_count` is present and non-None; else omit), `filename` = `counting-{ts}.mp4` (no `#N`), `session_id`/`ts` from the heartbeat. Add a new `if path == "/api/videos":` route that reads `limit`/`offset` via the existing `_int_arg`, calls `video_summaries`, prepends the running row (so it is index 0 and excluded from pagination offset math — i.e. `total` includes it, and `offset=0` returns it first), and returns `{"videos": rows, "limit":..., "offset":..., "total":...}`. Newest-first ordering: the running row is always first, then finalized videos newest-first.
- [ ] **Task 5: ADD `/api/video/<id>` Range-streaming endpoint** `ansible/playbooks/system/configure_companion.yml` — Add a new `if path.startswith("/api/video/"):` route (note: must be checked AFTER `/api/videos` so the plural isn't shadowed — actually `startswith` vs `==` are distinct, but place the `/api/videos` `==` check first for clarity). Extract `vid = path[len("/api/video/"):]`; reject empty/missing with 404. Resolve the file by `glob.glob(os.path.join(FILES_DIR, "counting-" + vid + "-*.mp4"))` (where `FILES_DIR` is the directory of `HISTORY_FILE_HOST`, i.e. `/data/orin/files`); if no match → 404 `{"error":"video not found"}`. If multiple matches (shouldn't happen, but defensively) pick the lexicographically first / newest by mtime. Implement HTTP Range support: read `self.headers.get("Range")`, `os.stat` the file for size, and respond with either 200 (full file, `Content-Length`, `Accept-Ranges: bytes`) when no Range header, or 206 (`Content-Range: bytes {start}-{end}/{size}`, `Content-Length: {end-start+1}`, `Accept-Ranges: bytes`) for a single `bytes=start-end` / `bytes=start-` range. Stream in chunks (e.g. 64 KiB) via `self.wfile.write` to avoid loading large files into memory. On malformed Range, respond 416 `Range Not Satisfiable` with `Content-Range: bytes */{size}`. Set `Content-Type: video/mp4`. Log the request (`GET /api/video/<id> -> 200/206/404/416`). Multi-range is NOT required (single-range resumable download suffices for the Android player).
- [ ] **Task 6: SYNC the doc reference** `docs/09_jetson_companion.md` — If the companion doc lists the endpoint table, update `/api/history`→`/api/sessions`, `/api/history/summary`→`/api/summary`, and add `/api/videos` + `/api/video/<id>` rows so the docs match the implementation. (This is a doc-only touch; if no such table exists, skip.) [Planner note: implementer should grep `docs/` for `/api/history` and update any stale references.]

## Validation

- **Syntax (per AGENTS.md, Python only — NEVER bun):**
  - `python3 -m py_compile app/src/core/history.py app/src/main.py`
  - The companion script is embedded in a YAML `copy.content` block; extract-check with `python3 - <<'PY'` pulling the block, or simply `python3 -m py_compile` the rendered script on the Jetson after `ansible-playbook` re-runs (idempotent — `changed` only on content change, then the notify handler restarts the service).
- **Unit/local (no Jetson needed):**
  - Append a fake `video` line + `heartbeat` (with `record_start_count`) to a scratch JSONL and point the companion's `HistoryIndex` at it; assert `video_summaries()` returns the row and `_running_video_row()` computes the delta. (Best-effort manual check; there is no formal Python test harness in this repo.)
- **End-to-end on Jetson (STANDARD validation mode, reference video only):**
  - `scripts/validate_on_jetson.sh` runs the reference video and parses `validation-report.json`. This change is instrumentation + endpoints, NOT counting logic, so the pig count must remain unchanged (no regression). `pass` → ship; `count_mismatch` → HITL pause (do NOT auto-correct).
  - Manual companion checks over the hotspot after deploy:
    - `curl http://<jetson>:8090/api/sessions?limit=5` → 200, `{sessions:[...],total}` (old `/api/history` → 404).
    - `curl http://<jetson>:8090/api/summary?days=7` → 200 (old `/api/history/summary` → 404).
    - `curl http://<jetson>:8090/api/videos?limit=10` → 200, running recording as first row (`status:"running"`) when a recording is active.
    - `curl -H "Range: bytes=0-1023" http://<jetson>:8090/api/video/<id> -o /tmp/head.mp4` → 206, `Content-Range: bytes 0-1023/<size>`; full `curl ... -o file.mp4` → 200 playable on Android.
    - `curl http://<jetson>:8090/api/video/nonexistent` → 404.

## Risks

- **`video` line vs compaction** — The 1x/day compactor collapses ended sessions into `summary` lines. `video` lines are per-recording facts that must survive compaction. Mitigation: the compactor already re-emits `startup` lines verbatim; do the same for `video` lines (do not fold them into `summary`). If the implementer finds the compactor drops unknown line types, explicitly pass `video` lines through.
- **video_id ↔ filename drift** — The `video_id` stem is captured at finalize from the same `time.strftime` call that builds the filename, so they cannot drift at write time. The cron later rewrites `tocompress-counting-{ts}-#N.mp4` → `counting-{ts}-#N.mp4` (same `{ts}`), so the glob `counting-{id}-*.mp4` still resolves post-compression. Risk: if two recordings finalize in the same wall-clock second, the stems collide. Mitigation: acceptable for this single-camera, ~2-min-recording use case; the glob would return both and the endpoint picks one (defensive). No counter change needed.
- **Range parsing edge cases** — Malformed `Range` headers could crash the handler. Mitigation: parse defensively, respond 416 (not 500) on unparseable ranges, and wrap the whole file-serving path in try/except → 500 with a JSON error body so a bad request never kills the companion thread (matches the best-effort logging style of the other handlers).
- **`/api/video/<id>` shadowing `/api/videos`** — The `startswith("/api/video/")` route must not swallow `/api/videos`. Mitigation: check the exact `== "/api/videos"` route FIRST, then `startswith("/api/video/")` (the trailing slash in the prefix means `/api/videos` — no trailing slash — never matches `startswith("/api/video/")` anyway, but ordering removes all doubt).
- **Running-row synthesis when no recording is active** — `latest_count()` may return the last heartbeat of an ended session where `record_start_count` is stale/None. Mitigation: only synthesize the running row when `record_start_count` is present and non-None AND the heartbeat is "recent" (the existing `latest_count()` already prefers the running session); otherwise omit the row. This keeps a phantom running row from appearing when the app is idle.