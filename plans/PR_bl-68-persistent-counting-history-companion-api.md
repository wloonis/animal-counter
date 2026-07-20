# Plan: BL-68 — Persistent counting history + companion API

## Summary

Add an append-only JSONL counting-session history to the production (`serve`-mode)
countingapp, resilient to the Jetson's frequent power cuts via a periodic
heartbeat thread + fsync, plus read-only history API endpoints added to the
existing host-level `jetson-companion` service (port 8090, stdlib Python) for
the downstream Android app (BL-69, out of scope). Counting/tracking/guards
**decision logic is untouched** — only read-only instrumentation and
persistence are added around it.

## In Scope

- **JSONL history** on persistent volume (`/files` hostPath → `/data/orin/files`
  on host): line types `session_start`, `heartbeat`, `event`, `session_end`;
  append + fsync, tolerate partial lines on restart; secondary index by `session_id`.
- **Session schema A–G**: lifecycle (A), counting/tracking health (B),
  perf/thermal sampled (C), config snapshot at startup (D), video metadata (E),
  system health (F), event timeline (G).
- **Startup history**: `boot_at`, `image_tag`, `git_commit`, `mode`, `config_notable`.
- **Power-cut-resilient end date**: periodic heartbeat thread (separate,
  non-blocking, no per-frame I/O); on next boot, last heartbeat of an unfinished
  session → estimated `end_at` + `end_reason=power-loss` (or `unknown` if too old);
  clean shutdown (BL-62 `stop()`) → real `end_at` + `end_reason=clean`; crash/oom
  detection at boot via `journalctl -b -1` / `dmesg`.
- **Read-only instrumentation** on the `Counting` class (`app/src/core/counting.py`):
  `self._emit_event(type, detail)` (no-op by default) at each guard/crossing
  site + counter accumulators (guard_interventions by type, unique_track_ids,
  max_concurrent_tracks, id_switch_recoveries) — **no counting decision branch
  changed**. Recorder in `main.py` subscribes to events.
- **Volumetry/retention**: bounded ~200–250 Mo; 2-level compaction (startup +
  daily, in-process thread): hot ≤30j keeps raw, cold >30j compacts to 1
  summary/session + significant events, drops heartbeats; size rotation to gz
  archives; disk guards (<2Go → slow heartbeat 5s→30s, <500Mo → suspend history
  writes, counting continues, alert).
- **Config** in `app/src/settings.py`, env-overridable: `HISTORY_RETENTION_DAYS(30)`,
  `HISTORY_MAX_BYTES(209715200)`, `HISTORY_HEARTBEAT_S(5)`, `HISTORY_DISK_WARN_GB(2)`,
  `HISTORY_DISK_CRIT_GB(0.5)`.
- **Companion API** (extend BL-64 `jetson-companion`, host, port 8090, stdlib
  `http.server`): `GET /api/history`, `GET /api/sessions/<id>`,
  `GET /api/history/summary`, `GET /api/startups` — reads `/data/orin/files/<history>.jsonl`.
- **Exclude** the history file from the rsync `--delete` in `scripts/validate_on_jetson.sh`
  (like `model/`, `video/`).

## Out of Scope

- Android app display (BL-69).
- Any change to counting/tracking/guards **decision logic** (OC-SORT, guard
  params, counting branches).
- `result.json` (stays validation-only; history is the prod-mode analog).
- New external Python deps (stdlib only).
- Separate sidecar/CronJob pod for compaction (in-process instead).

## Architecture Decisions

- **One writer, one reader, shared hostPath.** The countingapp pod (in-process
  thread in `main.py`) is the sole writer of the JSONL to `/files/<history>.jsonl`
  (hostPath → `/data/orin/files`). The host `jetson-companion` is the sole
  reader of the same file on the host. No DB, no socket, no separate service.
  Rationale: simplest robust data path; companion already on the host reading
  the host volume; avoids a new pod/service.
- **Read-only instrumentation, not log-parsing.** `Counting` gets a no-op
  `_emit_event` + accumulator attributes; the recorder in `main.py` subscribes
  (sets a callback) and persists. No existing `count()` decision branch is
  altered — only additive observations at existing log/branch sites. Rationale:
  more robust than parsing log strings; captures det_per_frame/max_concurrent
  directly; behavior preservation provable by standard validation.
- **Heartbeat + compaction in-process.** A single daemon thread in `main.py`
  handles heartbeat flush (periodic), compaction (startup + daily timer), disk
  guards, and rotation. Rationale: shares the `/files` mount and live count state
  directly; "comptage continue" holds even if history writes are suspended; no
  extra pod/CronJob to operate.
- **JSONL append-only + fsync, partial-line tolerance.** Each record is one
  JSON line written with `f.write(line+"\n"); f.flush(); os.fsync(f.fileno())`.
  On boot, the loader skips any trailing line that fails `json.loads` (torn write
  from power loss) before replay/indexing. Rationale: power-cut resilience is the
  hard requirement; append+fsync + tolerant loader is the proven pattern.
- **Bounded by compaction + rotation, not by dropping counting.** Disk guard
  tiers degrade history writes (slow → suspend) but never stop counting.
  Compaction cold-tier drops heartbeats (end_at already frozen) keeping
  summary+significant events; total bytes capped by gz rotation.

## Tasks

### Phase 1 — Config & storage primitives

- [ ] **Task 1: ADD history config** `app/src/settings.py` — add
  `HISTORY_*` settings (RETENTION_DAYS=30, MAX_BYTES=209715200, HEARTBEAT_S=5,
  DISK_WARN_GB=2, DISK_CRIT_GB=0.5) via `os.getenv` with defaults, plus
  `HISTORY_DIR` default `/files/history` and `HISTORY_FILE` default
  `counting-sessions.jsonl`, all env-overridable.
- [ ] **Task 2: CREATE** `app/src/utils/history_store.py` — the JSONL store module:
  - `HistoryStore(path)`: open in append-binary mode, append+fsync writer
    `append(record_dict)` (one JSON line per call, `json.dumps` compact,
    `flush()` + `os.fsync`).
  - `load_index(path)` -> `(sessions, partial_dropped_count)`: stream-read
    lines, `json.loads` each, group by `session_id`; skip + count trailing lines
    that fail to parse (torn write). Returns ordered list of session records
    (start/heartbeat/event/end merged by session_id) and the dropped count.
  - `estimate_end_at(session)`: last heartbeat `ts` if session has no
    `session_end`; `None` if no heartbeats.
  - Pure stdlib; no deps. No counting.py dependency.

### Phase 2 — Read-only instrumentation on Counting

- [ ] **Task 3: ADD read-only instrumentation** `app/src/core/counting.py` —
  additive only, **no decision branch changed**:
  - `__init__`: add accumulator attrs (`guard_interventions` dict by type,
    `unique_track_ids` set, `max_concurrent_tracks=0`, `id_switch_recoveries=0`,
    `crossed_left_count`, `crossed_right_count`), and `self._event_cb = None`
    (subscriber callback), `self._det_counts_window` for det_per_frame aggregation.
  - `_emit_event(self, type, detail)`: if `self._event_cb` is set, call it with
    `{"ts": time.time(), "type": type, "detail": detail}`; else no-op. Default
    no-op keeps behavior identical when no recorder subscribed.
  - At each existing guard/crossing log site (crossed LEFT/RIGHT, ID-SWITCH
    recovery, mirror guard, resurrection, reid rebind, lost_buffer expired),
    add **one line** `self._emit_event(<type>, {...})` and increment the relevant
    accumulator (`guard_interventions[type] += 1`, `id_switch_recoveries += 1`,
    etc.). Do NOT touch the surrounding `if`/`counter_to_right += 1` logic.
  - Per-frame cheap aggregation only: update `max_concurrent_tracks` from
    `len(result_trackid)`, accumulate det count/confidence into a rolling
    window for avg/min/max (no per-frame I/O, no logging). `unique_track_ids`
    updated from seen track ids.
  - Add `subscribe_events(callback)` to set `self._event_cb`.
  - Add `snapshot_metrics()` returning a dict of current B-fields
    (count_net, left_to_right, right_to_left, unique_track_ids count,
    guard_interventions, max_concurrent_tracks, det_per_frame avg/min/max,
    det_confidence_avg) for the recorder to persist at heartbeat/end.
  - **Self-check (implementer):** diff the `count()` method — confirm every
    `counter_to_right += 1` / `-= 1` branch is byte-identical to before; only
    pure additions inserted.

### Phase 3 — Recorder + heartbeat + compaction thread (main.py)

- [ ] **Task 4: CREATE** `app/src/utils/history_recorder.py` — the recorder +
  daemon thread:
  - `HistoryRecorder(store, settings, shared_state, counting)`: subscribes to
    `counting` events (`counting.subscribe_events(self._on_event)`); maintains an
    in-memory event buffer for the current session.
  - `start_session()`: generate `session_id` (uuid4), read `prev_session_id`
    from the last session in the store index, detect prior-session end
    (see Task 5), build the `session_start` record (schema A + D + E stub +
    F disk_free_start), append it. Also append a `startup` record
    (boot_at, image_tag, git_commit, mode, config_notable).
  - `_heartbeat_loop()`: daemon thread; every `HISTORY_HEARTBEAT_S` (adapted by
    disk guard tier), append a `heartbeat` line `{ts, session_id, count_net,
    last_video_segment}`; flush+fsync. Checks disk free each tick; tier:
    warn → 30s, crit → stop writing (continue loop but skip append) + log alert.
    Cheap: reads `shared_state.counter_to_right` + last segment from
    `shared_state.display_thread`; no per-frame I/O.
  - `_on_event(evt)`: buffer event for current session; the recorder flushes the
    buffer into `event` lines on the heartbeat tick (batched, not per-event I/O).
  - `end_session(reason)`: append `session_end` with real `end_at`, `end_reason`,
    final `snapshot_metrics()` (B), perf/thermal (C), video metadata (E), system
    (F); flush+fsync.
  - `compact()`: 2-level: hot ≤ RETENTION_DAYS keep raw; cold > RETENTION_DAYS
    rewrite to 1 `session_summary` line per session (A–F) + significant events
    only, drop heartbeats. Size rotation: if file > some chunk threshold, gzip
    the compacted cold prefix to a timestamped archive in `HISTORY_DIR/archives/`,
    bound archive count. Enforce total bytes ≤ MAX_BYTES.
  - `run_compaction_now()`: called on startup (after prior-session repair) and
    by a daily timer inside the heartbeat thread.
  - Perf/thermal (C) + system (F) sampled in the heartbeat tick (soc temp via
    `/sys/class/thermal/thermal_zone*/temp`, gpu util via `nvidia-smi --query-gpu`
    or jetson_stats if available, fallback N/A); aggregated to avg/min/max/peak
    over the session, flushed at end.
  - Graceful: `stop()` sets a stop event, the thread writes a final heartbeat +
    flushes the event buffer before exiting.
- [ ] **Task 5: WIRE** `app/src/main.py` — lifecycle integration:
  - Early in `__main__` (serve mode only — guard on `RESULT_JSON_PATH` unset OR
    an explicit `APP_MODE==serve`), after `settings` load: instantiate
    `HistoryStore`, call `load_index()`. If the last session has no `session_end`,
    repair it: estimate `end_at` from last heartbeat; set `end_reason`:
    `power-loss` (heartbeat recent) or `unknown` (heartbeat older than a
    threshold, e.g. > 7d); if `journalctl -b -1`/`dmesg` shows an OOM/crash
    signature for the countingapp, set `crash`/`oom`; append a retroactive
    `session_end` line. Then `recorder.start_session()` with
    `start_reason=boot-autostart` (or `manual-restart`/`config-change` if
    detectable).
  - Subscribe the recorder to the `Counting` instance.
  - Start the heartbeat daemon thread.
  - In `stop()` (clean shutdown path, BL-62): before joining threads, call
    `recorder.end_session("clean")` (real end_at).
  - On uncaught exception in `__main__`: `recorder.end_session("crash")` in a
    `finally`/except.
  - Pass `git_commit`/`image_tag` env (set in k3s templates, Task 8) into the
    startup record.
- [ ] **Task 6: ADD perf/thermal/system samplers** `app/src/utils/sys_sample.py`
  — small stdlib helpers: `disk_free_gb(path)` (shutil.disk_usage), `cpu_load()`
  (os.getloadavg), `mem_used()` (/proc/meminfo), `soc_temp()` (thermal_zone),
  `gpu_util()`/`inference_ms()` (best-effort, N/A fallback). No deps.

### Phase 4 — Companion API (host)

- [ ] **Task 7: EXTEND** `ansible/playbooks/system/configure_companion.yml` —
  add to the inlined `jetson-companion` Python script (reuse the existing
  `BaseHTTPRequestHandler` + `_send_json` structure from BL-64):
  - Config: `HISTORY_FILE` env (default `/data/orin/files/history/counting-sessions.jsonl`),
    read from the same hostPath the pod writes.
  - A JSONL reader (stdlib): stream the file once, parse lines (skip
    unparseable), build per-session dicts (merge start/heartbeats/events/end).
    For large files, prefer reading the compacted form / a lightweight scan;
    cache the parsed index with a mtime check (re-parse only if file mtime
    changed) to keep responses fast.
  - `GET /api/history?limit=50&offset=0` → paginated summaries
    `{sessions:[{session_id,video_filename,start_at,end_at,count_net,status,duration_s,video_complete}], total,offset,limit}`
    (most recent first).
  - `GET /api/sessions/<id>` → full detail `{A,B,C,config:D,video:E,system:F,events:[{ts,type,detail}]}`.
  - `GET /api/history/summary?days=7` → daily aggregates
    `{days:[{date,total_counted,uptime_s,restarts,sessions_clean,sessions_power_loss}]}`.
  - `GET /api/startups?limit=50` → startup history records.
  - Keep existing `/api/identify`, `/api/time` unchanged; bump `SERVICE_VERSION`
    to "2". Stdlib only, no new deps. Robust to missing/empty file (return empty
    lists, not 500).
  - The playbook handler `Restart jetson-companion service` already fires on
    content change.

### Phase 5 — K3s env + rsync exclude + docs

- [ ] **Task 8: ADD env** `k3s/templates/countingapp-dep.j2` — add env vars
  `HISTORY_DIR`, `HISTORY_FILE`, `HISTORY_RETENTION_DAYS`, `HISTORY_MAX_BYTES`,
  `HISTORY_HEARTBEAT_S`, `HISTORY_DISK_WARN_GB`, `HISTORY_DISK_CRIT_GB`,
  `GIT_COMMIT`, `IMAGE_TAG` to the countingapp container env (sourced from
  Ansible vars / build metadata). Mirror in
  `k3s/templates/countingapp-validate.j2` only if validation should also emit
  history (decision: history is **serve-only** — validate mode may set
  `HISTORY_ENABLED=false` or simply not start the recorder; confirm in
  implementation, default: validate does NOT write history to keep result.json
  the validation artifact).
- [ ] **Task 9: EXCLUDE history from rsync** `scripts/validate_on_jetson.sh` —
  add `--exclude='files/history/'` (or the chosen `HISTORY_DIR` relative path) to
  the `rsync --delete` call (line ~146), alongside the existing
  `--exclude='model/' --exclude='.env' --exclude='video/'`.
- [ ] **Task 10: DOC** `docs/04_configuration.md` — add a "Counting history
  (BL-68)" subsection: the `HISTORY_*` env table, the JSONL location, the
  compaction/retention model, the companion API endpoints, and the note that
  history is serve-mode only (result.json remains the validation artifact).

### Phase 6 — Tests

- [ ] **Task 11: CREATE** `tests/test_history_store.py` — unit tests (stdlib
  `unittest`, no deps): append+fsync writes a valid line; `load_index` recovers
  sessions from start/heartbeat/event/end lines; `load_index` skips a trailing
  torn (partial JSON) line and reports `partial_dropped_count` without
  raising; `estimate_end_at` returns last heartbeat ts when no session_end;
  returns None when no heartbeats.
- [ ] **Task 12: CREATE** `tests/test_history_compaction.py` — compaction +
  bounded-volume tests: build a fixture JSONL with N sessions spanning >
  RETENTION_DAYS, run `compact()`, assert cold sessions collapse to one summary
  line + significant events with heartbeats dropped; assert total file size ≤
  HISTORY_MAX_BYTES after compaction + rotation; assert hot sessions (<30j)
  keep raw heartbeats; assert archive count is bounded.
- [ ] **Task 13: CREATE** `tests/test_history_api.py` — companion API tests
  against a fixture JSONL using `http.client` (stdlib, no deps): pagination
  (`/api/history?limit=&offset=`), `/api/sessions/<id>` full detail,
  `/api/history/summary?days=7` aggregates, `/api/startups`, and the empty-file
  case (returns empty lists, 200). Verify existing `/api/identify` still works.
- [ ] **Task 14: CREATE** `tests/test_counting_instrumentation.py` — guard test
  that the instrumentation is read-only: run `Counting.count()` on a synthetic
  frame sequence with and without an event subscriber; assert `counter_to_right`
  is identical in both cases; assert `_emit_event` with no subscriber is a true
  no-op (no exception, no state change).

## Validation

- **Unit tests:** `python3 -m pytest tests/test_history_store.py
  tests/test_history_compaction.py tests/test_history_api.py
  tests/test_counting_instrumentation.py` (or `python3 -m unittest` if pytest
  absent) — all green.
- **Syntax:** `python3 -m py_compile app/src/main.py app/src/core/counting.py
  app/src/settings.py app/src/utils/history_store.py
  app/src/utils/history_recorder.py app/src/utils/sys_sample.py`.
- **Business validation (the gate):** `scripts/validate_on_jetson.sh` in
  **standard** mode on reference video `validation-1-#9.mp4` (NOT `--full`).
  **Pass = the reference count is unchanged AND** a `session_start` +
  heartbeats + `session_end` appear in `/data/orin/files/history/counting-sessions.jsonl`
  after the run, and a manual `compact()` call keeps total bytes ≤
  `HISTORY_MAX_BYTES`. (History writing in validate mode: if enabled, the
  count must still be unchanged — the instrumentation is read-only by
  construction; if disabled per Task 8 decision, the history file simply won't
  be written in validate mode and the count check is the sole gate.)
- **Instrumentation read-only proof:** `tests/test_counting_instrumentation.py`
  plus a `git diff app/src/core/counting.py` review confirming only additive
  lines inside existing branches (no `counter_to_right` assignment changed).
- **Companion API smoke (host):** after deploy,
  `curl http://<jetson>:8090/api/history?limit=5` and
  `curl http://<jetson>:8090/api/startups?limit=5` return valid JSON.

## Risks

- **Regressing the count** — the single most important risk. Mitigation:
  instrumentation is strictly additive (no `counter_to_right` branch touched);
  `_emit_event` is a no-op without a subscriber; a dedicated test asserts count
  identity with/without subscriber; the gate is the unchanged reference count.
- **Torn write on power loss corrupts the index** — Mitigation: append+fsync per
  line; loader skips unparseable trailing lines and reports them; the
  prior-session repair only trusts a clean `session_end` or a last heartbeat.
- **SSD fills up (seen at 80%)** — Mitigation: heartbeat is the only large
  contributor and is bounded by compaction + rotation; disk guards suspend
  history writes (never counting) below 500Mo; compaction caps total bytes.
- **Companion reads a file being appended** — Mitigation: the reader opens
  read-only and tolerates a trailing partial line (same partial-line tolerance
  as the loader); mtime-cache avoids re-parsing on every request.
- **Perf/thermal sampling overhead** — Mitigation: sampled only on the
  heartbeat tick (default 5s, 30s when degraded), never per frame; cheap
  /sys + best-effort nvidia-smi with N/A fallback.
- **History enabled in validate mode could confuse result.json** — Mitigation:
  history is serve-mode only by default; validate mode keeps result.json as the
  validation artifact (Task 8 decision enforced in main.py guard).