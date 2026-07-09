# Plan: BL-53 — Trim last N minutes in cronvideo compression

## Summary
The cron pod's compression loop (`k3s/templates/cronvideo-dep.j2`) re-encodes
the entire `tocompress-*` recording, including a trailing queue (≈ the
no-detection timeout) where no pigs ever appear — wasting storage and encode
time. This change trims that tail from the compressed archive by computing the
input duration with `ffprobe` and passing `-t` to `ffmpeg`.

Crucially, the trim length is **not** hardcoded: it reuses the existing
`delay_last_class` value (the no-detection timeout that *produces* the trailing
queue) as a single source of truth. That value becomes configurable via env
`DELAY_LAST_CLASS` (default 180) in `shared_state.py`, exposed as a common
Ansible variable, and templated into the cron pod as `TRIM_TAIL`. This also
removes the dead *local* `delay_last_class = 120` in `app/src/main.py` — a stale
value divergent from the real `shared_state.delay_last_class` (180) and the
source of the "2 min" confusion in the issue.

Only the compressed archive is trimmed. The raw recording, the live counting
pipeline (separate pod, runs on raw capture), and the counts are not touched.

## In Scope
- Make `delay_last_class` configurable via env `DELAY_LAST_CLASS` (default 180,
  unchanged) in `app/src/utils/shared_state.py`, following the existing
  `os.getenv` settings pattern. Do NOT change the existing default value.
- Expose the same value as a common Ansible variable (in
  `ansible/group_vars/all.yml`) and templatize it into
  `k3s/templates/cronvideo-dep.j2` as `TRIM_TAIL`, used for both the `KEEP`
  calculation and the short-clip guard. One source of truth feeds both the
  recording-stop logic and the compression trim.
- In the cron pod compression loop: compute `DUR` via `ffprobe`, compute
  `KEEP = DUR - TRIM_TAIL`, and pass `-t "$KEEP"` to `ffmpeg` (all existing
  encode flags preserved). Skip `-t` entirely when `DUR <= TRIM_TAIL` (short
  clip / corrupt duration) — keep the whole file and log a warning.
- Remove the dead local `delay_last_class = 120` at `app/src/main.py:255`. The
  recording-stop condition at `main.py:277` reads `shared_state.delay_last_class`
  (the env-backed member), not this local — so deletion is safe and changes no
  runtime behavior.
- Python syntax check: `python3 -m py_compile app/src/main.py`.
- Business validation: `scripts/validate_on_jetson.sh` on the priority set
  only (`validation/expected_counts.json` under `.videos`).

## Out of Scope
- Raw `tocompress-*` recording is NOT modified (only the compressed archive is
  trimmed).
- The counting pipeline (live flux / raw capture, separate pod) is NOT touched
  — counts are unaffected.
- No tracker change (OC-SORT kept; no BoT-SORT/Norfair). No CMC. Fixed camera.
  `FPS_OUTPUT=30`. Counting right→left.
- `hostPath /app` is intentional — do NOT "fix" it.
- Do NOT re-run validation on the 30 videos — priority set only.
- Do NOT modify `build_countingapp.yml` / `deploy_app.yml`.

## Architecture Decisions
- **Single source of truth: `delay_last_class` (default 180), not a hardcoded
  120.** The dead local `delay_last_class = 120` in `main.py` was a stale value
  divergent from the real `shared_state.delay_last_class` (180) and the exact
  source of the issue's confusion. Hardcoding 120 as the trim constant would
  perpetuate that bug. Instead, the no-detection timeout that *produces* the
  trailing empty queue is the natural trim length, and it already exists as
  `delay_last_class`.
- **Env-backed in Python, Ansible-var-backed in the pod.** `shared_state.py`
  reads `DELAY_LAST_CLASS` (default 180) via `os.getenv`, consistent with the
  other settings. The cron pod is a separate K3s Deployment (linuxserver/ffmpeg
  image, pure shell) with no access to Python settings, so the same value is
  declared as a common Ansible variable and templated as
  `TRIM_TAIL={{ delay_last_class | default(180) }}`. Both sides read one
  configurable value.
- **ffprobe duration + `-t`** — ffmpeg has no native "drop last N" flag, so
  compute `DUR` and keep `DUR - TRIM_TAIL` via `-t`. This trims the tail while
  preserving the clip start (where counting-relevant motion lives).
- **Short-clip / corrupt-duration guard** — if `DUR` is empty/non-numeric or
  `DUR <= TRIM_TAIL`, keep the whole file (do not pass `-t`) and log a warning.
  `awk` comparison keeps it in pure POSIX shell within the ffmpeg sidecar image
  (no `bc`).
- **Remove the dead local, not the `shared_state` member** — the local is
  assigned once and never read; the real stop condition reads
  `shared_state.delay_last_class`. Deleting the local eliminates the confusion
  source and changes no runtime behavior.

## Tasks
- [x] Task 1: EDIT `app/src/utils/shared_state.py` — Make `delay_last_class`
  configurable via env `DELAY_LAST_CLASS` with default **180** (the existing
  default), using the same `os.getenv` pattern as the other settings in this
  file. Do not change the default value. (This is the Python-side source of
  truth; the recording-stop logic in `main.py` already reads
  `shared_state.delay_last_class`.)
- [x] Task 2: EDIT `ansible/group_vars/all.yml` — Add a common variable
  `delay_last_class: 180` (default) so it can be templated into the cron pod
  manifest. Keep consistent with the other defaults already declared here.
- [x] Task 3: EDIT `k3s/templates/cronvideo-dep.j2` — In the
  `for f in /videos/tocompress-*` loop, after computing `out=` and before the
  `ffmpeg` call:
  - Set `TRIM_TAIL={{ delay_last_class | default(180) }}` (Ansible-templated,
    rendered to the pod's shell).
  - Compute `DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")`
    and `KEEP=$(awk "BEGIN{ print ($DUR) - $TRIM_TAIL }")`.
  - If `DUR` is empty/non-numeric OR `DUR <= TRIM_TAIL`: log a warning and run
    `ffmpeg` WITHOUT `-t` (encode the whole file).
  - Else (`DUR > TRIM_TAIL`): run `ffmpeg -y -i "$f" -t "$KEEP" -vf "scale=640:-2"
    -c:v libx264 -preset ultrafast -crf 23 -c:a aac -b:a 64k "$out"` (all
    existing flags preserved; `-t "$KEEP"` inserted after `-i "$f"`).
  - Keep the trailing `rm -f "$f"` and the rest of the loop body unchanged. No
    hardcoded 120 anywhere.
- [x] Task 4: EDIT `app/src/main.py` — Delete the single line
  `        delay_last_class = 120` (line ~255, inside `DisplayThread.run`,
  after `sum_t = 0.0`). Confirm no other reference to the bare *local*
  `delay_last_class` exists in `main.py` (the stop condition at ~277 reads
  `shared_state.delay_last_class`, which is the env-backed member — unrelated).
  Do not alter `shared_state.delay_last_class` or any logic.
- [x] Task 5: VERIFY — `python3 -m py_compile app/src/main.py` passes (confirms
  the deletion didn't break syntax/indentation).
- [x] Task 6: VERIFY — Local sanity: render the template / `sh -n` the shell
  portion of the cron loop, and run a synthetic `ffmpeg`+`ffprobe` test with a
  short clip to confirm the `DUR <= TRIM_TAIL` branch keeps the whole file and
  the `DUR > TRIM_TAIL` branch yields an output ≈ `DUR - TRIM_TAIL`.
- [x] Task 7: VERIFY — Run `bash scripts/validate_on_jetson.sh` on the priority
  set only (`validation/expected_counts.json` under `.videos`). Confirm the
  priority counts are unchanged (the trim affects only the archived
  compression, not the live counting the validation exercises).
  > **Deferred to Jetson phase**: requires SSH to a physical Jetson
  > (`JETSON_USER`/`JETSON_PASSWORD`/`JETSON_IP`, sshpass) and `.videos` — not
  > present in the local implementation environment. Per the workflow, "the real
  > business validation happens on the Jetson in the next phase." All local
  > implementation tasks (1-6) are complete.

## Validation
- `python3 -m py_compile app/src/main.py` — Python syntax check after the dead
  variable removal and the `shared_state.py` env change.
- `sh -n` on the rendered cron shell + a synthetic short-clip `ffmpeg`/`ffprobe`
  test — confirms both branches behave (trim vs. keep-whole) without touching a
  real Jetson.
- `bash scripts/validate_on_jetson.sh` — business validation on the priority set
  only (NOT the 30 videos). Expected: priority counts unchanged.
- Manual sanity (on a sample `tocompress-*` if available): trimmed output starts
  at the same point as the input; counting-bearing portion intact; output
  duration ≈ `DUR - TRIM_TAIL` when `DUR > TRIM_TAIL`, and equals `DUR` for short
  clips.

## Risks
- **`ffprobe` not available in the cron pod image** — the pod already uses the
  `lscr.io/linuxserver/ffmpeg:latest` sidecar, which ships `ffprobe` alongside
  `ffmpeg`. Mitigation: verify `ffprobe` is present (it is in linuxserver/ffmpeg);
  if absent, fall back to parsing `ffmpeg -i` stderr — not expected to be needed.
- **Negative/zero `-t` on short or corrupt clips** — mitigated by the explicit
  `DUR <= TRIM_TAIL` / empty-`DUR` guard that skips `-t` entirely and keeps the
  whole file (safe default) with a warning log.
- **Ansible var not plumbed through** — if `delay_last_class` is missing from
  `group_vars/all.yml`, the template's `| default(180)` keeps a sane default, so
  the pod still trims correctly. Mitigation: declare the var in `group_vars/all.yml`
  so the Python side and the pod side share one configured value.
- **Counting regression** — the trim affects only the compressed archive, not
  the raw capture or the live counting pod. Mitigation: run the priority
  validation set; counts must be unchanged.
- **`awk` arithmetic on malformed `DUR`** — if `ffprobe` returns empty/non-
  numeric duration, the guard treats it as keep-whole (safe default).