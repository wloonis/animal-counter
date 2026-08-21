# Plan: BL-86 — In-process hot-reload of runtime settings (idle-gated, no pod restart)

## Summary
Add a lightweight mtime-polling watcher thread that validates `/conf/runtime-settings.json`
changes and stores them thread-safe as "pending"; `DisplayThread.run()` applies them via
setters / `shared_state` writes **only at an idle window** (`reload_pending AND not
shared_state.recording`). Nothing ever applies mid-recording. This lets the companion
(`PUT /api/settings` → writes `/conf/runtime-settings.json`) take effect without restarting
the pod, replacing the current boot-only read in `start()`.

## In Scope
- Watcher thread polling `mtime` of `/conf/runtime-settings.json` (~2 s): on change, re-read +
  validate (reuse existing `load_runtime_settings` / `resolve_counting_line_orientation` /
  `resolve_counting_class_ids`); if valid, store thread-safe on `shared_state.pending_settings` +
  set `shared_state.reload_pending=True`. Never applies.
- Idle checkpoint inside `DisplayThread.run()`: when `reload_pending AND not recording`, apply
  ALL pending settings (toggles + line offset/orientation + counting_class_ids) → clear
  `reload_pending`. Single applier thread → no setter race.
- Apply all runtime settings uniformly gated to idle: `draw_tracking`/`box_tracking`/
  `centroid_tracking` (write `shared_state`), `offset_counting_line` + `counting_line_orientation`
  (setters on `Counting` + `Rendering`, incl. `PLUS_DIR`/`MINUS_DIR` re-derivation in `Counting`),
  `counting_class_ids` (write `shared_state.counting_class_ids` + reset `shared_state.sub_counts`).
- Reset semantics: `counting_class_ids` change at idle → reset `counter_to_right` + `sub_counts` to
  0 (fresh-session, matches boot). Line-only (offset/orientation) or toggle-only change → NO reset.
  BL-70 per-video delta snapshot (`record_start_count`) is separate and unaffected.
- Boot unchanged: `start()` still reads `/conf` once at startup; the watcher is purely additive
  (started after threads launch, joined in `stop()`).

## Out of Scope
- Any change to counting *decision* logic (crossing/guards/tracker params) — standard validation
  (1 reference video), not `--full`.
- Companion changes (it already writes `/conf` via `PUT /api/settings`).
- Mid-recording application of any setting (hard non-negotiable constraint).
- Optional "en attente/appliqué" status display (follow-up, not required).

## Architecture Decisions
- **Watcher stores only; DisplayThread applies** — the watcher never touches `Counting`/
  `Rendering` instances (owned by DisplayThread). Applying setters from the watcher would race a
  mid-frame read in DisplayThread. One thread (DisplayThread) is the single applier.
- **Uniform idle gating for ALL settings** — even purely-visual toggles (zero counting impact)
  wait for idle, for consistency and to keep one code path.
- **Setter approach (not per-frame shared_state re-read)** — applies atomically at the idle
  boundary. `Counting.update_line(offset, orientation)` re-derives `PLUS_DIR`/`MINUS_DIR` because
  those direction labels are set in `__init__` from orientation.
- **`counting_class_ids` change resets counters to 0** (fresh-session semantics, matching boot).
  Line-only / toggle-only changes preserve the running total — only a class-set change makes the
  old total semantically incoherent.
- **Boot path unchanged** — `start()` keeps its one-shot `/conf` read (L173-236); the watcher is
  additive and only picks up *subsequent* changes after boot.

## Reuse
- `state.load_runtime_settings()` (`app/src/state.py`) — best-effort read of
  `/conf/runtime-settings.json` → dict (never raises).
- `state.resolve_counting_line_orientation(rt)` / `state.resolve_counting_class_ids(rt,
  model_classes)` (`app/src/state.py`) — existing validators, already imported in `main.py` L66-67.
- `SharedState` (`app/src/utils/shared_state.py`) — add the pending-state fields here.
- `Counting.offset_counting_line` / `counting_line_orientation` / `PLUS_DIR` / `MINUS_DIR`
  (`app/src/core/counting.py` L62-79) — read per-frame; a setter hot-swaps them.
- `Rendering.offset_counting_line` / `counting_line_orientation` (`app/src/ui/rendering.py`
  L66-71) — read per-frame; a setter hot-swaps them.

## Tasks

- [x] **Task 1: Add pending-state fields to `SharedState`** — `app/src/utils/shared_state.py`
  - Add to `SharedState.__init__`: `self.pending_settings = None` (dict or None),
    `self.reload_pending = False`, and `self.reload_lock = threading.Lock()` (import `threading`).
  - These hold the validated pending payload + the flag the DisplayThread polls + the lock that
    serializes the watcher write vs the DisplayThread read-and-clear.
  - No behavior change at boot (fields are None/False until the watcher first fires).

- [x] **Task 2: Add `Counting.update_line(offset, orientation)` setter** — `app/src/core/counting.py`
  - New method: validates `orientation` (lowercase, `"vertical"|"horizontal"`, else → `"vertical"`)
    and clamps `offset` to `-300..300` (mirror the `main.py` sanity cap); sets `self.offset_counting_line`
    and `self.counting_line_orientation`; re-derives `self.PLUS_DIR` / `self.MINUS_DIR` from the new
    orientation (same logic as `__init__` L77-79) so direction labels don't go stale on a mid-life
    orientation swap.
  - Pure attribute write — no counting-decision logic changes. Per-frame reads in `cross_pos()` /
    line-position computation pick up the new values on the next frame.

- [x] **Task 3: Add `Rendering.update_line(offset, orientation)` setter** — `app/src/ui/rendering.py`
  - New method: normalizes orientation (lowercase, `"horizontal"` else `"vertical"`, mirroring
    `__init__` L70-71) and sets `self.offset_counting_line` + `self.counting_line_orientation`.
  - No button/reload logic; pure attribute write.

- [x] **Task 4: Add `RuntimeSettingsWatcher` thread class** — `app/src/state.py`
  - New `threading.Thread` subclass: `__init__(self, shared_state, stop_event, poll_interval=2.0)`.
    Polls `os.path.getmtime(RUNTIME_SETTINGS_PATH)` every `poll_interval` seconds; on mtime change,
    calls `load_runtime_settings()` + `resolve_counting_line_orientation(rt)` +
    `resolve_counting_class_ids(rt, {names, default_counting_class})` (same model catalog resolution
    as `main.py` boot block), assembles a validated pending dict, then under
    `shared_state.reload_lock` sets `shared_state.pending_settings = <dict>` and
    `shared_state.reload_pending = True`. On any read/parse error, logs a WARNING and does NOT set
    pending (fail-open: keep current settings). Exits when `stop_event.is_set()`.
  - Add a module-level `settings_watcher = None` holder in `state.py` so `main.start()`/`stop()`
    can reach the instance.

- [x] **Task 5: Add idle checkpoint to `DisplayThread.run()`** — `app/src/display_thread.py`
  - Near the top of the per-frame loop (after the arret/powoff sentinel check, before frame
    processing), add: `if shared_state.reload_pending and not shared_state.recording:` → take the
    pending payload under `shared_state.reload_lock` (read + clear `reload_pending` + grab
    `pending_settings` and set it back to None), then apply it:
    - toggles: `shared_state.draw_tracking` / `box_tracking` / `centroid_tracking` from pending
      (only if present/bool, mirroring the boot block's guards).
    - line: `self.counting.update_line(offset, orientation)` + `self.rendering.update_line(offset,
      orientation)` (only if offset/orientation present in pending).
    - class ids: if the pending `counting_class_ids` differs from the current
      `shared_state.counting_class_ids`, set `shared_state.counting_class_ids = <new list>`,
      `self.counting.counting_class_ids = list(<new>)`, reset `shared_state.sub_counts = {cid: 0
      for cid in <new>}`, and reset `shared_state.counter_to_right = 0` (fresh-session). If only
      line/toggles changed (class set unchanged), do NOT reset counters.
  - Log at INFO: "runtime settings applied (idle)" with the changed keys; or "pending settings
    held (recording in progress)" when recording blocks application.
  - This is the SINGLE applier → no cross-thread setter race.

- [ ] **Task 6: Start/stop the watcher in `main.py`** — `app/src/main.py`
  - In `start()`, after `shared_state.infer_thread.start()` / `shared_state.display_thread.start()`
    (end of the thread-launch block), instantiate + start `RuntimeSettingsWatcher(shared_state,
    shared_state.stop_event)` and store it on `shared_state.settings_watcher` (new SharedState
    field added in Task 1 — note: add `self.settings_watcher = None` to `SharedState.__init__` as
    part of Task 1).
  - In `stop()`, before joining InferThread/DisplayThread, signal + join the watcher:
    `sw = getattr(shared_state, "settings_watcher", None); if sw and sw.is_alive(): sw.join(timeout=2)`
    (best-effort, like the HistoryThread join already in `stop()`).

- [ ] **Task 7: `py_compile` + standard validation** — `app/src/` and `scripts/validate_on_jetson.sh`
  - `python3 -m py_compile` on every changed file (no syntax errors).
  - Run `scripts/validate_on_jetson.sh` (standard mode, 1 reference video) → expect PASS with the
    same count (no regression; boot path unchanged, vertical + offset 0 default on the reference).

## Documentation Impact
The current docs describe the old "hot-reload per recording / per pod boot" semantics. After
this change the semantics become "applied at idle window, no pod restart". Stale references:
- `docs/IPC_CONTRACT.md` L99-126 — "reads at the start of every recording … hot-reload, no restart"
  and "Hot-reloaded per recording" and "Takes full effect only when a new InferThread/Counting is
  created (a mid-session change needs a recording restart)". Update to: watcher thread polls for
  changes, applied at the first idle window (not mid-recording), no pod restart. Note the
  counter-reset-on-class-id-change rule.
- `docs/04_configuration.md` L34 — "runtime settings (runtime-settings.json, hot-reloaded by the
  companion …)". Clarify idle-gated application.
- `docs/05_counting_pipeline.md` L54-57, L301, L342 — `OFFSET_PERCENT_COUNTING_LINE` line-position
  description; the "next recording" wording may imply per-recording. Align with idle-gated reload.
- `docs/11_counting_history.md` L110, L129 — `offset_counting_line` in session metadata; no
  schema change but the application timing note may need an update.
- `AGENTS.md` L558, L560 — "runtime-settings.json reader (hot-reload)" /
  "counting_class_ids reader (hot-reload)". Update to reflect the watcher + idle checkpoint.
(The downstream docs-sync phase re-verifies these; listed here so the plan is doc-aware.)

## Validation
- `python3 -m py_compile app/src/utils/shared_state.py app/src/state.py app/src/core/counting.py
  app/src/ui/rendering.py app/src/display_thread.py app/src/main.py` — no syntax errors.
- `bash scripts/validate_on_jetson.sh` (standard mode, `validation/config.json` →
  `validation-1-#9.mp4`, tolerance 0) → expect PASS, identical count (boot path unchanged, default
  vertical + offset 0 on the reference → no behavioral change).
- Manual (acceptance, on the Jetson): change `counting_line_orientation` + `offset_counting_line`
  + `counting_class_ids` via companion `PUT /api/settings` → confirm taken into account without pod
  restart at the first idle window; during a recording, confirm stored-but-not-applied; confirm
  boot is unchanged.

## Risks
- **Race on pending read/write** — the watcher writes `pending_settings` while DisplayThread reads
  + clears it. Mitigation: `shared_state.reload_lock` serializes both sides (Task 1 + Task 4 +
  Task 5).
- **Stale `PLUS_DIR`/`MINUS_DIR` after orientation swap** — if the `Counting` setter forgets to
  re-derive them, direction labels (and any log lines) report the old orientation. Mitigation:
  Task 2 explicitly re-derives them, mirroring `__init__`.
- **Spurious counter reset on a no-op class-id payload** — applying a pending payload whose
  `counting_class_ids` equals the current set would wrongly zero the counter. Mitigation: Task 5
  compares the pending set to the current set before resetting.
- **Watcher thread leak on unclean exit** — if `stop()` doesn't join it. Mitigation: Task 6 adds a
  best-effort join mirroring the existing HistoryThread join.
- **Boot regression** — accidentally changing the one-shot `/conf` read in `start()`. Mitigation:
  the watcher is purely additive; `start()`'s L173-236 block is untouched.