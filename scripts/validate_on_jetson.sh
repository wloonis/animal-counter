#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 LOONIS Wennaël

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# validate_on_jetson.sh — Single-shot validation helper
#
# SSH → cross-check classes.yaml↔engine → rsync code+video → stop services →
# K8s Job → poll → fetch result.json → compare count → write report JSON
#
# Validation is anchored to the DEPLOYED model (BL-96):
#   • the active model_name is read from the Jetson's app/model/classes.yaml
#     (the engine actually loaded by the countingapp is <model_name>.engine);
#   • the reference video + expected count come from the per-model bundle
#     validation/models/<model_name>/validation.json (standard) or
#     validation/models/<model_name>/manifest.json (full);
#   • classes.yaml nc/names are cross-checked against the class names embedded
#     in the deployed <model_name>.onnx — a drift (hand-written classes.yaml
#     vs the real engine, e.g. a .pt retrained to a different nc without
#     re-exporting the .onnx) aborts validation with a clear diff instead of
#     silently producing a meaningless count_mismatch;
#   • the results JSONL is scoped per active model so a pig run never inherits
#     a stale sheep result (and vice-versa).
#
# Modes:
#   standard (default) — validates only the reference video from the per-model
#                        bundle (validation/models/<active>/validation.json).
#   full                — validates the videos declared in the per-model
#                        manifest (validation/models/<active>/manifest.json).
#                        Videos present in validation/videos/ but not in the
#                        manifest are ignored. (enable via config "mode": "full"
#                        or CLI arg --full)
#
# Exit codes:
#   0 — validation succeeded (pass OR count_mismatch OR classes_drift — check
#        JSON for details)
#   1 — execution error (infra failure: SSH, kubectl, timeout, crash)
#
# The looping/feedback is handled by the Archon workflow, not this script.
# ─────────────────────────────────────────────────────────────────────────────

# ─── 0. Load config + env ────────────────────────────────────────────────────
if [ -f ".env.local" ]; then
  set -a
  source .env.local
  set +a
fi

CONFIG_FILE="validation/config.json"
TOLERANCE=$(jq -r '.tolerance' "$CONFIG_FILE")
MAX_ITERATIONS=$(jq -r '.max_iterations' "$CONFIG_FILE")
MODE=$(jq -r '.mode' "$CONFIG_FILE")

# Allow CLI overrides:
#   --full            validate the per-model full manifest instead of just the
#                     standard reference video.
#   --clear-results   truncate the per-model results JSONL before running.
#                     By default results are APPENDED so a re-run/resume of the
#                     sweep does not lose prior per-video results (BL-60). The
#                     summary dedupes by video_file, last entry wins.
MODE="standard"
CLEAR_RESULTS=false
while [ $# -gt 0 ]; do
  case "$1" in
    --full) MODE="full" ;;
    --clear-results) CLEAR_RESULTS=true ;;
  esac
  shift
done

REPORT_FILE="validation-report.json"
VALIDATION_START=$(date +%s)

# ─── 1. Discover Jetson IP via jetson_discover.sh ───────────────────────────
# The Jetson IP MUST come from jetson_discover.sh (nmap scan + SSH credential
# test). Do NOT trust JETSON_ETH_IP blindly: it may point at a stale or wrong
# interface (the Jetson may be on WiFi/hotspot, not Ethernet).
# A successful discovery is cached in /tmp/jetson_env.sh; we reuse the cache
# only if the cached IP still answers SSH, otherwise we re-discover.
USE_CACHE=false
if [ -f /tmp/jetson_env.sh ]; then
  set -a
  source /tmp/jetson_env.sh
  set +a
  if [ -n "${JETSON_IP:-}" ]; then
    if sshpass -p "$JETSON_PASSWORD" ssh -o StrictHostKeyChecking=no \
         -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 \
         "$JETSON_USER@$JETSON_IP" "true" 2>/dev/null; then
      USE_CACHE=true
      echo "✅ Reusing cached Jetson IP: $JETSON_IP"
    else
      echo "⚠️  Cached JETSON_IP=$JETSON_IP not reachable — re-discovering..."
      JETSON_IP=""
    fi
  fi
fi

if [ "$USE_CACHE" = "false" ]; then
  echo "🔎 Running jetson_discover.sh..."
  bash scripts/jetson_discover.sh
  set -a
  source /tmp/jetson_env.sh
  set +a
fi

if [ -z "${JETSON_IP:-}" ]; then
  echo '{"validation_status": "execution_error", "error_type": "jetson_not_found"}'
  echo "ERROR: Could not determine Jetson IP"
  exit 1
fi

echo "🎯 Jetson IP: $JETSON_IP"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH_CMD="sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS $JETSON_USER@$JETSON_IP"
SCP_CMD="sshpass -p $JETSON_PASSWORD scp $SSH_OPTS"

# Resume the countingapp DaemonSet after validation. The pause/resume mechanism
# is a `validate-paused` nodeSelector patch (DaemonSets are NOT scaled by
# `kubectl scale --replicas` — that is a no-op that returns rc 0, which would
# short-circuit a `scale || patch remove` and leave the DaemonSet paused).
resume_countingapp() {
  if [ -n "${APP_NAME:-}" ] && [ -n "${APP_NAMESPACE:-}" ] && [ -n "${SSH_CMD:-}" ]; then
    $SSH_CMD "kubectl patch daemonset $APP_NAME -n $APP_NAMESPACE --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/template/spec/nodeSelector/validate-paused\"}]'" 2>/dev/null || true
  fi
}
# Always resume on exit — covers interrupted/aborted runs (Ctrl-C, SSH drop)
# that never reach the explicit resume block, so the countingapp never stays
# paused in camera mode after a validation.
trap resume_countingapp EXIT

# ─── 1b. Discover the active model_name (BL-89 follow-up) ───────────────────
# The validate Job runs with the Jetson's CURRENT model (the code rsync
# excludes model/), so the reference video + expected count MUST match that
# model — a pig reference is meaningless for a sheep model (false mismatch).
# Read model_name from the Jetson's app/model/classes.yaml (source of truth);
# fall back to the local worktree's classes.yaml; fall back to 'my_model'
# (legacy pig, pre-model-naming).
ACTIVE_MODEL=""
ACTIVE_MODEL=$($SSH_CMD "grep -E '^model_name:' $APP_PATH/model/classes.yaml 2>/dev/null | head -1 | awk '{print \$2}'" 2>/dev/null | tr -d '[:space:]')
if [ -z "$ACTIVE_MODEL" ] && [ -f "app/model/classes.yaml" ]; then
  ACTIVE_MODEL=$(grep -E '^model_name:' app/model/classes.yaml 2>/dev/null | head -1 | awk '{print $2}' | tr -d '[:space:]')
fi
if [ -z "$ACTIVE_MODEL" ]; then
  ACTIVE_MODEL="my_model"
fi
echo "🏷️  Active model: $ACTIVE_MODEL"

MODEL_BUNDLE_DIR="validation/models/$ACTIVE_MODEL"

# Emit a report (NA — not a mismatch, not an error) when the active model has no
# per-model validation bundle, or a precheck failure, then exit 0/1.
# The Archon workflow treats validation_skipped as VALIDATED (N/A for model).
emit_report_and_exit() {
  local STATUS="$1"; local EXIT_CODE="$2"; local MSG="$3"; local MODE_LABEL="${4:-$MODE}"
  jq -n --arg status "$STATUS" --arg m "$ACTIVE_MODEL" --arg mode "$MODE_LABEL" --arg msg "$MSG" --arg ts "$(date -Iseconds)" \
    '{validation_status:$status, model_name:$m, mode:$mode, message:$msg, total_videos:0, pass_count:0, mismatch_count:0, error_count:0, skipped:1, timestamp:$ts, results:[]}' \
    > "$REPORT_FILE"
  echo ""
  echo "=== Validation Report ==="
  cat "$REPORT_FILE"
  echo ""
  echo "========================="
  echo "Overall: $STATUS (model '$ACTIVE_MODEL')"
  exit "$EXIT_CODE"
}

# ─── 1c. Cross-check classes.yaml vs the deployed .onnx (BL-96) ─────────────
# The deployed engine's class names are embedded in the .onnx metadata
# (names: {0: 'human', 1: 'pig'}) — that is the source of truth for what the
# engine actually outputs. classes.yaml (the countingapp's nc/names) is
# hand-written and can drift from the engine — e.g. a .pt retrained to a
# different nc without re-exporting the .onnx/rebuilding the engine leaves
# classes.yaml stale vs the deployed engine → counting_class_ids filters the
# wrong class → a silent, meaningless miscount. This check reads the .onnx
# names by grep on the binary (the names dict is a verbatim UTF-8 string in
# the protobuf — no onnx lib needed) and compares to classes.yaml. On drift
# it aborts validation with a clear diff so the drift is surfaced, not buried
# as a confusing count_mismatch=0.
echo "🔍 Cross-checking classes.yaml vs deployed $ACTIVE_MODEL.onnx ..."
set +e
CROSSCHECK=$($SSH_CMD "python3 - '$ACTIVE_MODEL' '$APP_PATH/model'" <<'PY' 2>&1
import sys, ast, os, re
model, model_dir = sys.argv[1], sys.argv[2]
# --- read classes.yaml (nc + names list; tiny stdlib parser, no PyYAML) ---
yp = os.path.join(model_dir, 'classes.yaml')
if not os.path.exists(yp):
    print('SKIP classes.yaml not found on Jetson'); sys.exit(0)
nc = None; names = []; in_names = False
for ln in open(yp, 'r', errors='replace').read().splitlines():
    s = ln.strip()
    if s.startswith('nc:'):
        try: nc = int(s.split(':', 1)[1].strip())
        except: pass
        in_names = False
    elif s == 'names:':
        in_names = True
    elif in_names and s.startswith('- '):
        names.append(s[2:].strip())
    elif in_names and not s.startswith('-'):
        in_names = False
# --- read .onnx names via grep on the binary (no onnx lib) ---
op = os.path.join(model_dir, model + '.onnx')
if not os.path.exists(op):
    print('SKIP .onnx not found on Jetson'); sys.exit(0)
raw = open(op, 'rb').read()
# Ultralytics embeds the class names as an ONNX metadata string of the form
# {0: 'human', 1: 'pig'} (a python-dict repr). It is the only such dict in
# the file, so the first match is the names. (The 'names' key precedes it in
# the protobuf but is separated by length bytes — matching the dict directly
# is simpler + robust.)
m = re.search(rb"\{[0-9]+: '[^']+'(, [0-9]+: '[^']+')*\}", raw)
if not m:
    print('SKIP .onnx names metadata not found'); sys.exit(0)
onnx_names = ast.literal_eval(m.group(0).decode('utf-8', 'replace'))  # {0: 'human', 1: 'pig'}
onnx_nc = len(onnx_names)
onnx_list = [onnx_names[i] for i in range(onnx_nc)]
# --- compare ---
if nc != onnx_nc or names != onnx_list:
    print('DRIFT model=' + model
          + ' classes.yaml nc=' + str(nc) + ' names=' + repr(names)
          + ' | .onnx nc=' + str(onnx_nc) + ' names=' + repr(onnx_list))
    sys.exit(1)
print('OK nc=' + str(nc) + ' names=' + repr(names))
PY
)
CROSSCHECK_RC=$?
set -e
# Parse the cross-check result. The python prints exactly one status line
# (OK/SKIP/DRIFT); SSH may prepend a "Permanently added" host-key notice, so
# grep the status line out instead of matching the whole captured string.
if [ "$CROSSCHECK_RC" -eq 1 ]; then
  # python exited 1 → DRIFT is the only rc=1 path
  DRIFT_LINE=$(printf '%s\n' "$CROSSCHECK" | grep -E '^DRIFT' | head -1)
  echo "   ${DRIFT_LINE:-$CROSSCHECK}" >&2
  echo "❌ classes.yaml ↔ deployed .onnx class drift — validation aborted." >&2
  echo "   A wrong-class count would be meaningless. Fix classes.yaml to match" >&2
  echo "   the deployed engine, or redeploy the engine matching classes.yaml." >&2
  emit_report_and_exit "classes_drift" 1 \
    "classes.yaml nc/names do not match the deployed .onnx class names (see stderr). Validation aborted." "precheck"
else
  CK_LINE=$(printf '%s\n' "$CROSSCHECK" | grep -E '^(OK|SKIP) ' | head -1)
  if [ -z "$CK_LINE" ]; then
    echo "   ⚠️  Cross-check inconclusive (rc=$CROSSCHECK_RC): $CROSSCHECK — continuing" >&2
  elif printf '%s' "$CK_LINE" | grep -q '^OK'; then
    echo "   $CK_LINE"
  else  # SKIP
    echo "   ⚠️  $CK_LINE — cross-check skipped (continuing)" >&2
  fi
fi

# ─── 2. Build video list (per-model bundle) ─────────────────────────────────
# Per-model bundle (BL-96): validation/models/<active>/{validation.json,
# manifest.json}. The active model MUST have a bundle — no bundle →
# validation_skipped (N/A for that model — add a bundle to validate it).
if [ "$MODE" = "full" ]; then
  # Full mode: per-model manifest.json (videos + disabled). Videos listed by
  # filename are resolved against validation/videos/ (shared pool). Videos
  # present in validation/videos/ but NOT in the manifest are ignored — the
  # manifest is the single source of truth for which videos to validate.
  MANIFEST_FILE="$MODEL_BUNDLE_DIR/manifest.json"
  if [ ! -f "$MANIFEST_FILE" ]; then
    emit_report_and_exit "validation_skipped" 0 \
      "No full-mode manifest for model '$ACTIVE_MODEL' ($MANIFEST_FILE). Add validation/models/$ACTIVE_MODEL/manifest.json with a 'videos' map, or use standard mode." "full"
  fi
  VIDEO_LIST=""
  while IFS= read -r MF; do
    [ -z "$MF" ] && continue
    MP="validation/videos/$MF"
    if [ ! -f "$MP" ]; then
      echo "WARNING: '$MF' is declared in the manifest but not found in validation/videos/ — skipping" >&2
      continue
    fi
    VIDEO_LIST="${VIDEO_LIST}${MP}"$'\n'
  done < <(jq -r '.videos | keys[]' "$MANIFEST_FILE" 2>/dev/null)
  VIDEO_LIST=$(printf '%s' "$VIDEO_LIST" | sed '/^$/d')
  if [ -z "$VIDEO_LIST" ]; then
    echo '{"validation_status": "execution_error", "error_type": "no_videos_found"}'
    echo "ERROR: No manifest-declared videos found in validation/videos/ (check $MANIFEST_FILE)"
    exit 1
  fi
else
  # Standard mode: per-model validation.json — reference_video (filename in
  # validation/videos/) + explicit expected_count (+ optional tolerance
  # override). expected_count is EXPLICIT here (NOT derived from the #<N>
  # filename) so the count is decoupled from the filename.
  VALIDATION_JSON="$MODEL_BUNDLE_DIR/validation.json"
  if [ ! -f "$VALIDATION_JSON" ]; then
    emit_report_and_exit "validation_skipped" 0 \
      "No validation bundle for model '$ACTIVE_MODEL' ($VALIDATION_JSON). Add validation/models/$ACTIVE_MODEL/validation.json with a 'reference_video' + 'expected_count', or deploy a model that has one."
  fi
  VIDEO_FILE=$(jq -r '.reference_video // empty' "$VALIDATION_JSON")
  if [ -z "$VIDEO_FILE" ] || [ "$VIDEO_FILE" = "null" ]; then
    emit_report_and_exit "validation_skipped" 0 \
      "validation.json for model '$ACTIVE_MODEL' has no 'reference_video'. Add it (a filename in validation/videos/)."
  fi
  VIDEO_PATH="validation/videos/$VIDEO_FILE"
  if [ ! -f "$VIDEO_PATH" ]; then
    emit_report_and_exit "validation_skipped" 0 \
      "Reference video for model '$ACTIVE_MODEL' not found at $VIDEO_PATH. Place it in validation/videos/ before running validation." "$VIDEO_FILE"
  fi
  echo "📹 Reference video: $VIDEO_FILE (model: $ACTIVE_MODEL)"
  VIDEO_LIST="$VIDEO_PATH"
fi

# ─── 3. Rsync code to Jetson (same pattern as build_countingapp.yml) ─────────
echo "📦 Rsyncing app code to Jetson..."
# Sync CODE only — exclude gitignored runtime assets (model weights, .env,
# validation video scratch, legacy img/old) so a fresh worktree missing them
# does NOT wipe them on the Jetson via --delete (BL-60). Weights/.env are
# deployed via their own pipeline, not this code rsync.
rsync -avz --delete --no-owner --no-group \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='model/' --exclude='.env' --exclude='video/' --exclude='img/old/' \
  --exclude='counting-history*.jsonl*' \
  -e "sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS" \
  app/ \
  $JETSON_USER@$JETSON_IP:$APP_PATH/ \
  || { rc=$?; [ "$rc" -eq 23 ] && echo "⚠️  rsync partial transfer (code 23) — continuing (unrelated old files skipped)" || exit "$rc"; }

# ─── 4. Stop existing countingapp services (free GPU) ────────────────────────
DEP_WAS_RUNNING=false
DEP_PODS=$($SSH_CMD "kubectl get pods -l app=$APP_NAME -n $APP_NAMESPACE -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo ''" 2>/dev/null)
if [ -n "$DEP_PODS" ]; then
  echo "⏸️  Stopping countingapp-dep (DaemonSet) to free GPU resources..."
  DEP_WAS_RUNNING=true
  $SSH_CMD "kubectl patch daemonset $APP_NAME -n $APP_NAMESPACE -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"validate-paused\":\"true\"}}}}}'" 2>/dev/null || true
  $SSH_CMD "kubectl wait --for=delete pod -l app=$APP_NAME -n $APP_NAMESPACE --timeout=30s" 2>/dev/null || true
fi

# Also clean up any leftover test job
$SSH_CMD "kubectl delete job countingapp-test -n $APP_NAMESPACE --ignore-not-found 2>/dev/null || true"

# ─── 5. Define single-validation function ────────────────────────────────────
# $1 = video path, $2 = optional explicit expected_count override (standard
# mode: from the per-model validation.json). When empty, the count is derived
# from the full-mode manifest / #<N> filename / legacy (full mode).
run_single_validation() {
  local VIDEO_PATH="$1"
  local EXPECTED_OVERRIDE="${2:-}"
  local VIDEO_FILE
  VIDEO_FILE=$(basename "$VIDEO_PATH")
  local VIDEO_START
  VIDEO_START=$(date +%s)

  # Resolve expected_count:
  #   0. Explicit override (standard mode, from per-model validation.json)
  #   1. Per-model full-mode manifest (validation/models/<active>/manifest.json)
  #   2. Global legacy manifest (validation/expected_counts.json) if present
  #   3. #<N> filename parse: validation-<seq>-#<expected_count>.mp4 -> <expected_count>
  #   4. Give up with no_expected_count
  local EXPECTED_COUNT="$EXPECTED_OVERRIDE"
  if [ -z "$EXPECTED_COUNT" ]; then
    local PM_MANIFEST="$MODEL_BUNDLE_DIR/manifest.json"
    if [ -f "$PM_MANIFEST" ]; then
      EXPECTED_COUNT=$(jq -r --arg f "$VIDEO_FILE" '.videos[$f] // empty' "$PM_MANIFEST")
    fi
  fi
  if [ -z "$EXPECTED_COUNT" ] && [ -f "validation/expected_counts.json" ]; then
    EXPECTED_COUNT=$(jq -r --arg f "$VIDEO_FILE" '.videos[$f] // empty' "validation/expected_counts.json")
  fi
  if [ -z "$EXPECTED_COUNT" ]; then
    # #<N> filename parse: extract the trailing digits between the final '#'
    # and '.mp4' (e.g. validation-1-#9.mp4 -> 9, validation-13-#12.mp4 -> 12).
    EXPECTED_COUNT=$(printf '%s' "$VIDEO_FILE" | sed -n 's/.*#\([0-9][0-9]*\)\.mp4$/\1/p')
  fi
  if [ -z "$EXPECTED_COUNT" ]; then
    echo "WARNING: No expected_count for $VIDEO_FILE (not in override/manifest, not derivable from filename) — skipping" >&2
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"no_expected_count\"}"
    return 1
  fi

  # Per-model tolerance override (optional)
  local VIDEO_TOLERANCE="$TOLERANCE"
  if [ -f "$MODEL_BUNDLE_DIR/validation.json" ]; then
    local PM_TOL
    PM_TOL=$(jq -r '.tolerance // empty' "$MODEL_BUNDLE_DIR/validation.json" 2>/dev/null || true)
    [ -n "$PM_TOL" ] && VIDEO_TOLERANCE="$PM_TOL"
  fi

  echo "" >&2
  echo "─── Validating: $VIDEO_FILE (expected: $EXPECTED_COUNT, model: $ACTIVE_MODEL) ───" >&2

  # Rsync this video to Jetson
  $SSH_CMD "mkdir -p $APP_PATH/video"
  $SCP_CMD "$VIDEO_PATH" "$JETSON_USER@$JETSON_IP:$APP_PATH/video/$VIDEO_FILE"

  # Render K8s Job template with this video
  sed -e "s|{{ app_namespace }}|$APP_NAMESPACE|g" \
      -e "s|{{ app_name }}|$APP_NAME|g" \
      -e "s|{{ app_version }}|$APP_VERSION|g" \
      -e "s|{{ app_path }}|$APP_PATH|g" \
      -e "s|{{ files_path }}|$FILES_PATH|g" \
      -e "s|{{ validate_video }}|./video/$VIDEO_FILE|g" \
      k3s/templates/countingapp-validate.j2 > /tmp/countingapp-validate.yaml

  # Delete stale result.json before launching new job (prevents false positive
  # if the new job crashes and doesn't write a new result.json)
  $SSH_CMD "rm -f $FILES_PATH/result.json" 2>/dev/null || true

  # Delete old job + apply new one
  $SSH_CMD "kubectl delete job countingapp-validate -n $APP_NAMESPACE --ignore-not-found 2>/dev/null || true" >/dev/null
  $SSH_CMD "kubectl apply -f /dev/stdin" < /tmp/countingapp-validate.yaml >/dev/null

  # Poll for job completion. Guard against an app hang (the container won't
  # exit after counting, result.json never written -- see BL-61): break at
  # MAX_VIDEO_SECONDS, capture the job logs for salvage, and delete the hung
  # job so the GPU frees up and the next video can run. Legit videos finish
  # well under this (densest #51 ~10min).
  local MAX_VIDEO_SECONDS="${MAX_VIDEO_SECONDS:-1200}"
  echo "Waiting for validation job to complete (timeout ${MAX_VIDEO_SECONDS}s)..." >&2
  local JOB_STATUS=""
  local TIMEOUT_LOG="/tmp/timeout-${VIDEO_FILE}.log"
  rm -f "$TIMEOUT_LOG"
  while true; do
    local ELAPSED=$(( $(date +%s) - VIDEO_START ))
    local COND
    COND=$($SSH_CMD "kubectl get job countingapp-validate -n $APP_NAMESPACE -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo ''" 2>/dev/null)
    case "$COND" in
      Complete|SuccessCriteriaMet) JOB_STATUS="complete"; break ;;
      Failed|FailureTarget)   JOB_STATUS="failed"; break ;;
      *)
        if [ "$ELAPSED" -ge "$MAX_VIDEO_SECONDS" ]; then
          echo "  TIMEOUT after ${ELAPSED}s -- capturing logs and deleting hung job..." >&2
          $SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1" > "$TIMEOUT_LOG" 2>/dev/null || echo "Could not fetch logs" > "$TIMEOUT_LOG"
          $SSH_CMD "kubectl delete job countingapp-validate -n $APP_NAMESPACE --ignore-not-found 2>/dev/null" >/dev/null || true
          JOB_STATUS="timeout"
          break
        fi
        echo "  Job status: ${COND:-pending} (${ELAPSED}s)..." >&2; sleep 5
        ;;
    esac
  done

  # If the app hung (timeout), salvage the final count from the captured logs
  # before falling through. The app prints "ID=N crossed LEFT // Count N" up to
  # the final count, so the last "Count N" is the real result even though
  # result.json was never persisted (BL-61).
  if [ "$JOB_STATUS" = "timeout" ] && [ -s "$TIMEOUT_LOG" ]; then
    local SALVAGED_COUNT
    SALVAGED_COUNT=$(grep -oE 'Count [0-9]+' "$TIMEOUT_LOG" | tail -1 | grep -oE '[0-9]+' || true)
    if [ -n "$SALVAGED_COUNT" ]; then
      local S_DIFF=$(( SALVAGED_COUNT - EXPECTED_COUNT ))
      local S_ABS=$(( S_DIFF < 0 ? -S_DIFF : S_DIFF ))
      local S_STATUS; if [ "$S_ABS" -le "$VIDEO_TOLERANCE" ]; then S_STATUS="pass"; else S_STATUS="count_mismatch"; fi
      echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"$S_STATUS\", \"count_salvaged_from_logs\": true, \"actual_count\": $SALVAGED_COUNT, \"expected_count\": $EXPECTED_COUNT, \"diff\": $S_DIFF, \"job_status\": \"timeout\", \"tolerance\": $VIDEO_TOLERANCE, \"logs\": $(tail -80 "$TIMEOUT_LOG" | jq -Rs .)}"
      return 0
    fi
  fi

  # Fetch result.json
  local RESULT_FILE="/tmp/result-$VIDEO_FILE.json"
  $SCP_CMD "$JETSON_USER@$JETSON_IP:$FILES_PATH/result.json" "$RESULT_FILE" 2>/dev/null || {
    local JOB_LOGS
    if [ -s "$TIMEOUT_LOG" ]; then
      JOB_LOGS=$(tail -80 "$TIMEOUT_LOG")
    else
      JOB_LOGS=$($SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1 | tail -50" 2>/dev/null || echo "Could not fetch logs")
    fi
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"result_json_missing\", \"expected_count\": $EXPECTED_COUNT, \"job_status\": \"$JOB_STATUS\", \"logs\": $(echo "$JOB_LOGS" | jq -Rs .)}"
    return 1
  }

  # Compare count
  local ACTUAL_COUNT
  ACTUAL_COUNT=$(jq -r '.count' "$RESULT_FILE")
  local DIFF=$(( ACTUAL_COUNT - EXPECTED_COUNT ))
  local ABS_DIFF=$(( DIFF < 0 ? -DIFF : DIFF ))
  local VSTATUS
  if [ "$ABS_DIFF" -le "$VIDEO_TOLERANCE" ]; then
    VSTATUS="pass"
  else
    VSTATUS="count_mismatch"
  fi

  local JOB_LOGS_FULL
  JOB_LOGS_FULL=$($SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1" 2>/dev/null || echo "Could not fetch logs")

  # Extract counting events for diagnosis. The full job log is huge and the
  # interesting lines (crossings, ID-switch recovery, tracks lost on the "in"
  # side near the line) get buried under thousands of routine lines. We grep
  # them out and also count them so the report shows at a glance how many
  # +1/-1/ID-switch events occurred.
  local COUNTING_EVENTS
  COUNTING_EVENTS=$(echo "$JOB_LOGS_FULL" | grep -E "crossed (LEFT|RIGHT|UP|DOWN)|ID-SWITCH recovery|MIRROR|track lost:.*side=in" || true)
  local CROSSED_LEFT_COUNT CROSSED_RIGHT_COUNT ID_SWITCH_COUNT LOST_IN_COUNT MIRROR_COUNT
  CROSSED_LEFT_COUNT=$(echo "$COUNTING_EVENTS" | grep -c "crossed LEFT" || true)
  CROSSED_RIGHT_COUNT=$(echo "$COUNTING_EVENTS" | grep -c "crossed RIGHT" || true)
  ID_SWITCH_COUNT=$(echo "$COUNTING_EVENTS" | grep -c "ID-SWITCH recovery" || true)
  LOST_IN_COUNT=$(echo "$COUNTING_EVENTS" | grep -c "track lost:.*side=in" || true)
  MIRROR_COUNT=$(echo "$COUNTING_EVENTS" | grep -c "MIRROR" || true)
  [ -z "$CROSSED_LEFT_COUNT" ] && CROSSED_LEFT_COUNT=0
  [ -z "$CROSSED_RIGHT_COUNT" ] && CROSSED_RIGHT_COUNT=0
  [ -z "$ID_SWITCH_COUNT" ] && ID_SWITCH_COUNT=0
  [ -z "$LOST_IN_COUNT" ] && LOST_IN_COUNT=0
  [ -z "$MIRROR_COUNT" ] && MIRROR_COUNT=0

  # Keep a short tail for general context (startup/cleanup).
  local JOB_LOGS
  JOB_LOGS=$(echo "$JOB_LOGS_FULL" | tail -50)
  local VDURATION=$(( $(date +%s) - VIDEO_START ))

  # Output single-video result as JSON (to be collected by caller)
  jq -c -n \
    --arg status "$VSTATUS" \
    --argjson expected "$EXPECTED_COUNT" \
    --argjson actual "$ACTUAL_COUNT" \
    --argjson tolerance "$VIDEO_TOLERANCE" \
    --arg video "$VIDEO_FILE" \
    --arg job_status "$JOB_STATUS" \
    --argjson duration "$VDURATION" \
    --arg timestamp "$(date -Iseconds)" \
    --arg result_json "$(cat "$RESULT_FILE")" \
    --arg logs "$JOB_LOGS" \
    --arg counting_events "$COUNTING_EVENTS" \
    --argjson crossed_left "$CROSSED_LEFT_COUNT" \
    --argjson crossed_right "$CROSSED_RIGHT_COUNT" \
    --argjson id_switch_recoveries "$ID_SWITCH_COUNT" \
    --argjson lost_in "$LOST_IN_COUNT" \
    --argjson mirror "$MIRROR_COUNT" \
    '{
      video_file: $video,
      validation_status: $status,
      expected_count: $expected,
      actual_count: $actual,
      tolerance: $tolerance,
      diff: ($actual - $expected),
      job_status: $job_status,
      duration_seconds: $duration,
      timestamp: $timestamp,
      result: ($result_json | fromjson),
      counting_events: $counting_events,
      crossed_left_count: $crossed_left,
      crossed_right_count: $crossed_right,
      id_switch_recoveries: $id_switch_recoveries,
      lost_in_count: $lost_in,
      mirror_count: $mirror,
      logs: $logs
    }'
}

# ─── 6. Run validation(s) ────────────────────────────────────────────────────
# Per-model results JSONL (BL-96): scoped by active model so a pig run never
# inherits a stale sheep result (and vice-versa). Append by default (BL-60): a
# re-run/resume of the sweep must not lose prior per-video results. Use
# --clear-results to start fresh. The summary dedupes by video_file (last
# entry wins), so appended duplicates/retries don't inflate the counts.
RESULTS_FILE="/tmp/validation-results-${ACTIVE_MODEL}.jsonl"
if [ "$CLEAR_RESULTS" = "true" ]; then
  : > "$RESULTS_FILE"
fi

# Standard mode: explicit expected_count from the per-model validation.json.
STANDARD_EXPECTED=""
if [ "$MODE" = "standard" ] && [ -f "$MODEL_BUNDLE_DIR/validation.json" ]; then
  STANDARD_EXPECTED=$(jq -r '.expected_count // empty' "$MODEL_BUNDLE_DIR/validation.json")
fi

for VIDEO_PATH in $VIDEO_LIST; do
  run_single_validation "$VIDEO_PATH" "$STANDARD_EXPECTED" >> "$RESULTS_FILE" || true
done

# ─── 7. Restart countingapp-dep if it was stopped ────────────────────────────
if [ "$DEP_WAS_RUNNING" = "true" ]; then
  echo ""
  echo "▶️  Restarting countingapp-dep (DaemonSet)..."
  resume_countingapp
fi

# ─── 8. Aggregate results into final report ──────────────────────────────────
TOTAL_DURATION=$(( $(date +%s) - VALIDATION_START ))
# Tolerant aggregation (BL-60): the per-video JSONL can be corrupted by a real
# newline inserted mid-entry (observed at the stdio buffer boundary) and by
# duplicate writes across restarts (we append). Repair by joining physical
# lines that don't start with '{' onto the previous entry, then dedupe by
# video_file keeping the LAST (most recent) entry. Falls back to a plain jq -s
# slurp if python3 is unavailable.
TOLERANT_RESULTS=$(python3 - "$RESULTS_FILE" <<'PY' 2>/dev/null || jq -s '.' "$RESULTS_FILE"
import json, sys
raw = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace')
phys = raw.split('\n')
entries, cur = [], None
for ln in phys:
    if ln.startswith('{'):
        if cur is not None: entries.append(cur)
        cur = ln
    elif cur is not None:
        cur += ln  # continuation of a split entry (drop the spurious newline)
if cur is not None: entries.append(cur)
parsed = []
for e in entries:
    try: parsed.append(json.loads(e))
    except Exception: pass
seen = {}
for o in parsed:
    seen[o.get('video_file')] = o  # last wins
print(json.dumps(list(seen.values())))
PY
)
VIDEO_COUNT=$(echo "$TOLERANT_RESULTS" | jq 'length')
PASS_COUNT=$(echo "$TOLERANT_RESULTS" | jq '[.[] | select(.validation_status == "pass")] | length')
MISMATCH_COUNT=$(echo "$TOLERANT_RESULTS" | jq '[.[] | select(.validation_status == "count_mismatch")] | length')
ERROR_COUNT=$(echo "$TOLERANT_RESULTS" | jq '[.[] | select(.validation_status == "execution_error")] | length')

# Determine overall status
if [ "$ERROR_COUNT" -gt 0 ] && [ "$MISMATCH_COUNT" -eq 0 ] && [ "$PASS_COUNT" -eq 0 ]; then
  OVERALL_STATUS="execution_error"
  EXIT_CODE=1
elif [ "$MISMATCH_COUNT" -gt 0 ]; then
  OVERALL_STATUS="count_mismatch"
  EXIT_CODE=0  # script succeeded, business validation failed
elif [ "$PASS_COUNT" -eq "$VIDEO_COUNT" ] && [ "$VIDEO_COUNT" -gt 0 ]; then
  OVERALL_STATUS="pass"
  EXIT_CODE=0
else
  OVERALL_STATUS="execution_error"
  EXIT_CODE=1
fi

# Build final report (model_name tagged — BL-96: a report is explicitly scoped
# to the model it validated)
jq -n \
  --arg status "$OVERALL_STATUS" \
  --arg model_name "$ACTIVE_MODEL" \
  --arg mode "$MODE" \
  --argjson video_count "$VIDEO_COUNT" \
  --argjson pass_count "$PASS_COUNT" \
  --argjson mismatch_count "$MISMATCH_COUNT" \
  --argjson error_count "$ERROR_COUNT" \
  --argjson duration "$TOTAL_DURATION" \
  --arg timestamp "$(date -Iseconds)" \
  --argjson results "$TOLERANT_RESULTS" \
  '{
    validation_status: $status,
    model_name: $model_name,
    mode: $mode,
    total_videos: $video_count,
    pass_count: $pass_count,
    mismatch_count: $mismatch_count,
    error_count: $error_count,
    duration_seconds: $duration,
    timestamp: $timestamp,
    results: $results
  }' > "$REPORT_FILE"

echo ""
echo "=== Validation Report ==="
cat "$REPORT_FILE"
echo ""
echo "========================="
echo "Overall: $OVERALL_STATUS (model '$ACTIVE_MODEL': $PASS_COUNT pass, $MISMATCH_COUNT mismatch, $ERROR_COUNT error / $VIDEO_COUNT total)"
exit $EXIT_CODE