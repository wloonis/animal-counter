# Plan: Fix standard-mode validation `#<N>` filename parser (issue #50 / BL-57)

## Summary
Add a `#<N>` filename-parser fallback to `scripts/validate_on_jetson.sh` so that standard-mode validation of a video like `validation-1-#9.mp4` (whose expected count is only encoded in the `#<N>` suffix, not in the manifest's `videos` section) resolves to a real expected count instead of returning `no_expected_count`. Also update the `expected_counts.json` `_comment` to document the new resolution order. This is a validation-infra-only fix — no counting/tracking logic changes.

## Context
`validation/config.json` sets `reference_video = "validation-1-#9.mp4"`, which is listed under `expected_counts.json`'s `disabled` key (count 9), NOT under `videos`. The standard-mode expected-count resolver (`scripts/validate_on_jetson.sh` ~line 160–176) only checks the manifest `.videos[$f]` and then falls back to the legacy `template-validation-<N>.mp4 -> N` regex (`sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p'`). That legacy regex requires a `-<digits>.mp4` suffix; `validation-1-#9.mp4` ends in `#9.mp4` (no dash before the digits), so it never matches and the script emits `no_expected_count`. Yet the `_comment` documents the convention `validation-<seq>-#<expected_count>.mp4`. The fix honors that convention with a dedicated `#<N>` parser.

## In Scope
- `scripts/validate_on_jetson.sh`: insert a `#<N>` filename parser as the second expected-count resolution step, between the manifest `videos` lookup and the legacy `template-validation-<N>.mp4 -> N` fallback.
- `validation/expected_counts.json`: update the `_comment` to document the new resolution order (manifest `videos` -> `#<N>` filename parse -> legacy `template-validation-<N>.mp4 -> N` -> give up), preserving the existing `disabled`-key and filename-convention notes.

## Out of Scope
- No disabled-section fallback in the script — every `disabled` entry already has a `#<N>` name, so the parser covers them (minimal fix = A only).
- No change to `validation/config.json` — keep `reference_video = "validation-1-#9.mp4"` and `mode = "standard"`.
- No counting/tracking logic changes (`app/src/counting.py`, `main.py` tracking/counting, `app/src/core/*`, tracker/guard params, OC-SORT, FPS_OUTPUT).
- No Docker image rebuild — code-rsync deploy only (no `requirements.txt` / build-time dep changes).
- No k3s/ansible/docs changes.

## Architecture Decisions
- **Resolution order (per user Q1)**: (1) manifest `.videos[$f]` explicit entry (most authoritative), (2) `#<N>` filename parse (documented convention), (3) legacy `template-validation-<N>.mp4 -> N` (compat fallback), (4) give up with `no_expected_count`.
- **Minimal fix = A only, no C (per user Q2)**: do NOT add a `disabled`-section lookup. The `#<N>` parser already covers all `disabled` entries (they all carry `#<N>`).
- **Config unchanged (per user Q3)**: keep `reference_video = "validation-1-#9.mp4"`; rely on the script fix to make it validatable (expected count 9 via the `#<N>` parser). Only the `_comment` is updated.
- **Parser robustness**: the `#<N>` extraction must handle filenames with multiple `-` segments (e.g. `validation-13-#12.mp4`); only the trailing `#<digits>` immediately before `.mp4` is the count. Use a bash `[[ =~ ]]` regex or `sed`/`grep` that captures digits between the final `#` and `.mp4`. The `#` is a literal character in the filename (not a shell comment, since the filename is a quoted string variable), so it is safe to match.

## Tasks
- [ ] Task 1: EDIT `scripts/validate_on_jetson.sh` — update the expected-count resolution comment block (~lines 160–164) to state the new 4-step order: manifest `videos` -> `#<N>` filename parse -> legacy `template-validation-<N>.mp4 -> N` -> give up.
- [ ] Task 2: EDIT `scripts/validate_on_jetson.sh` — insert the `#<N>` parser between the manifest lookup (~line 167–168) and the legacy fallback (~line 172). After the manifest lookup returns empty, extract the trailing count with e.g. `EXPECTED_COUNT=$(printf '%s' "$VIDEO_FILE" | sed -n 's/.*#\([0-9][0-9]*\)\.mp4$/\1/p')` (or an equivalent bash regex `[[ $VIDEO_FILE =~ #([0-9]+)\.mp4$ ]]`). Guard so an empty/non-`#` filename leaves `EXPECTED_COUNT` empty and falls through to the legacy step. Do NOT alter the legacy fallback or the final `no_expected_count` branch.
- [ ] Task 3: EDIT `validation/expected_counts.json` — update only the `_comment` value to document the new resolution order: "The validator resolves the expected count in this order: (1) manifest `videos` explicit entry, (2) `#<N>` filename parse (validation-<seq>-#<expected_count>.mp4 -> <expected_count>), (3) legacy `template-validation-<N>.mp4 -> N`, (4) give up with `no_expected_count`." Preserve the existing notes about the `disabled` key (videos excluded from a run, preserved, ignored by validator) and the filename convention / count-confirmation caveat. Do NOT touch the `videos` or `disabled` objects.

## Validation
- Standard mode only (single reference video). After the fix, from a worktree that has the gitignored files in place (`.env.local`, `validation/videos/*.mp4`, `app/model/`, `app/.env` — copy/symlink from the main repo via `git worktree list` first entry if missing):
  - `bash scripts/validate_on_jetson.sh` must complete with a real comparison result for `reference_video = validation-1-#9.mp4`: either `pass` (count == 9) or `count_mismatch` (count != 9) — NEVER `no_expected_count`.
  - Confirm the stderr line reads `─── Validating: validation-1-#9.mp4 (expected: 9) ───`, proving the `#<N>` parser resolved count 9.
- Optional unit check (no Jetson needed): `sed -n 's/.*#\([0-9][0-9]*\)\.mp4$/\1/p' <<< "validation-1-#9.mp4"` prints `9`; `... <<< "validation-13-#12.mp4"` prints `12`; `... <<< "template-validation-7.mp4"` prints nothing (correctly falls through to legacy).
- Acceptance: standard validation of any video whose count is knowable via `#<N>` or the manifest returns `pass`/`count_mismatch`, never `no_expected_count`.

## Risks
- **`#` in filenames vs. shell quoting** — mitigated by only ever handling `$VIDEO_FILE` as a quoted variable and using `printf`/`sed` on the variable (no unquoted expansion). The `#` is a filename character, not a shell comment in this context.
- **Regex over-matching** — mitigated by anchoring the `#<N>` pattern to the `.mp4$` end (`#([0-9]+)\.mp4$`), so only the final `#<digits>` is captured and multi-`-` filenames are handled.
- **Jetson model-weight wipe on rsync --delete** — mitigated by ensuring gitignored files (`app/model/`, `.env.local`, `app/.env`, `validation/videos/*.mp4`) are present in the worktree before running the validator; the plan's validation step explicitly requires this.
- **Stable count for validation-1-#9.mp4** — the reference video has an expected count of 9 (manifest `disabled`); if the live count differs, the result is `count_mismatch`, which is still a valid real comparison (not `no_expected_count`) and satisfies acceptance.