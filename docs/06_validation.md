# 06 — Validation

The developer loop for checking that counting logic still matches reality.
Driven by `scripts/validate_on_jetson.sh` against the reference videos in
`validation/`.

## Why

Counting logic is sensitive (ID-switch near the line, occlusions, re-ID). A
change in `counting.py`, tracker tuning, or the model can silently regress the
count. Validation runs the app on each reference video and compares the count
against the expected (visually confirmed) value.

## Reference videos

`validation/videos/validation-<seq>-#<count>.mp4`

- `<seq>` = chronological sequence number (1, 2, 3 …)
- `<count>` = the confirmed pig count (by app output + visual inspection)

The count is the single source of truth — some original filenames were
misleading (e.g. a video named `#24` actually contained 42 pigs); the
`#<count>` in the name was corrected after visual confirmation.

## Manifest — `validation/expected_counts.json`

```json
{
  "_comment": "...",
  "videos": {
    "validation-13-#12.mp4": 12,
    "validation-14-#30.mp4": 30,
    "validation-22-#42.mp4": 42,
    "validation-27-#35.mp4": 35
  },
  "disabled": {
    "validation-1-#9.mp4": 9,
    "...": "..."
  }
}
```

- `videos` — videos to validate in `--full` mode. **This is the single source
  of truth** for which videos run and their expected count.
- `disabled` — videos excluded from a run (kept for record; the validator
  ignores them). JSON has no comments, so excluded videos are preserved here
  rather than deleted.

> Convention: filenames follow `validation-<seq>-#<count>.mp4`. If a video is
> not in the manifest, the validator falls back to deriving the count from the
> filename (`#<N>` → N) — but prefer declaring it explicitly so the expected
> count is decoupled from the name.

## Config — `validation/config.json`

```json
{
  "reference_video": "validation-1-#9.mp4",
  "tolerance": 0,
  "max_iterations": 5,
  "mode": "full"
}
```

- `reference_video` — video used in **standard** mode.
- `tolerance` — allowed difference (0 = exact match required).
- `max_iterations` — used by the Archon workflow wrapper (not the script
  itself).
- `mode` — `standard` (single reference video) or `full` (manifest videos).

## Running

```bash
# Full mode: validate only the videos in expected_counts.json (.videos)
bash scripts/validate_on_jetson.sh --full

# Standard mode: single reference video from config.json
bash scripts/validate_on_jetson.sh
```

CLI `--full` overrides `config.json`'s `mode`.

## What the script does (per video)

1. **Discover** the Jetson IP (cache in `/tmp/jetson_env.sh`, reused if it
   still answers SSH; otherwise re-scan with `jetson_discover.sh`).
2. **rsync** the app code to the Jetson (excluding `model/old/`,
   `__pycache__`).
3. **Pause the live app**: patch the `countingapp` DaemonSet with
   `nodeSelector: { validate-paused: "true" }` so it schedules 0 pods and frees
   the camera/GPU.
4. **SCP** the video to `$APP_PATH/video/`.
5. **Render** `k3s/templates/countingapp-validate.j2` → a one-shot K8s Job that
   runs the app in `validate` mode on that video and writes `result.json`.
6. **Poll** the Job to completion; on success **fetch** `$FILES_PATH/result.json`.
7. **Compare** the actual count to the expected (manifest lookup by filename,
   fallback to filename-derivation).
8. **Write** a per-video result line to `/tmp/validation-results.jsonl` and a
   summary `validation-report.json`.
9. Move to the next manifest video; restore the live DaemonSet at the end.

## Exit codes

- `0` — validation finished (pass **or** count mismatch; inspect the report).
- `1` — execution error (infra failure: SSH, kubectl, timeout, crash).

## Report — `validation-report.json`

```json
{
  "timestamp": "2026-07-05T22:49:21+02:00",
  "total_videos": 4,
  "pass_count": 4,
  "mismatch_count": 0,
  "validation_status": "pass",
  "results": [
    { "video_file": "validation-13-#12.mp4", "expected_count": 12,
      "actual_count": 12, "diff": 0, "validation_status": "pass" },
    "..."
  ]
}
```

Per-video lines are also appended to `/tmp/validation-results.jsonl`. The
report also embeds the captured `counting_events` log (crossed LEFT/RIGHT,
REID-SUPPRESS, etc.) for each video.

## Tips

- **Don't run all 30 videos** for a quick check — keep only the 4 priority
  (defect-prone) videos in `.videos` and the rest in `.disabled`. A full run
  is ~1 h 30; a 4-video run is ~15–20 min.
- **Don't "fix" code on a mismatch** without visually confirming the ground
  truth first — historically several "mismatches" were wrong ground truth, not
  app bugs (e.g. #11, #24, #27, #51).
- **Verify the report is fresh**: check `timestamp` and `total_videos` — a
  stale report from a previous run can be misleading.
- The live DaemonSet is **paused during validation** and **restored at the
  end**; if a run is interrupted, resume it with
  `kubectl label node <node> validate-paused-`.

## Adding a new reference video

1. Copy the video to `validation/videos/validation-<seq>-#<count>.mp4`.
2. Add it to `validation/expected_counts.json` → `videos` (with its confirmed
   count) — or to `disabled` to keep it on record but exclude it from a run.
3. Run `bash scripts/validate_on_jetson.sh --full` to validate.

> `.gitignore` ignores `validation/videos/*.mp4` **except**
> `validation-1-#9.mp4` (the standard-mode reference video, ~11 MB). Large
> videos are not committed; keep them locally on the Jetson / your machine.