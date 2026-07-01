#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# validate_on_jetson.sh — Single-shot validation helper
#
# SSH → rsync code+video → stop existing services → K8s Job → poll →
# fetch result.json → compare count (derived from filename) → write report JSON
#
# Modes:
#   standard (default) — validates only the reference_video from config
#   full                — validates all *.mp4 files in validation/videos/
#                        (enable via config "mode": "full" or CLI arg --full)
#
# Exit codes:
#   0 — validation succeeded (pass OR count_mismatch — check JSON for details)
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

# Load discovered JETSON_IP if available from previous discovery
if [ -f /tmp/jetson_env.sh ]; then
  set -a
  source /tmp/jetson_env.sh
  set +a
fi

CONFIG_FILE="validation/config.json"
TOLERANCE=$(jq -r '.tolerance' "$CONFIG_FILE")
TIMEOUT_SEC=$(jq -r '.timeout_seconds' "$CONFIG_FILE")
MAX_ITERATIONS=$(jq -r '.max_iterations' "$CONFIG_FILE")
MODE=$(jq -r '.mode' "$CONFIG_FILE")

# Allow CLI override: --full flag
if [ "${1:-}" = "--full" ]; then
  MODE="full"
fi

REPORT_FILE="validation-report.json"
VALIDATION_START=$(date +%s)

# ─── 1. Discover Jetson IP (reuse existing scripts pattern) ──────────────────
# Priority: JETSON_IP (from /tmp/jetson_env.sh) > JETSON_ETH_IP (.env.local) > discovery
if [ -z "${JETSON_IP:-}" ]; then
  # Strip CIDR suffix from JETSON_ETH_IP if present
  JETSON_IP="${JETSON_ETH_IP%%/*}"
fi

if [ -z "${JETSON_IP:-}" ]; then
  echo "JETSON_IP not set, running jetson_discover.sh..."
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

# ─── 2. Build video list ─────────────────────────────────────────────────────
if [ "$MODE" = "full" ]; then
  # Full mode: all *.mp4 files in validation/videos/
  VIDEO_LIST=$(ls validation/videos/*.mp4 2>/dev/null || true)
  if [ -z "$VIDEO_LIST" ]; then
    echo '{"validation_status": "execution_error", "error_type": "no_videos_found"}'
    echo "ERROR: No mp4 files found in validation/videos/"
    exit 1
  fi
else
  # Standard mode: single reference video from config
  VIDEO_FILE=$(jq -r '.reference_video' "$CONFIG_FILE")
  VIDEO_PATH="validation/videos/$VIDEO_FILE"
  if [ ! -f "$VIDEO_PATH" ]; then
    echo "{\"validation_status\": \"execution_error\", \"error_type\": \"video_not_found\", \"video_file\": \"$VIDEO_FILE\", \"message\": \"Reference video not found at $VIDEO_PATH. Place it before running validation.\"}"
    echo "ERROR: Reference video not found at $VIDEO_PATH"
    exit 1
  fi
  VIDEO_LIST="$VIDEO_PATH"
fi

# ─── 3. Rsync code to Jetson (same pattern as build_countingapp.yml) ─────────
echo "📦 Rsyncing app code to Jetson..."
rsync -avz --delete --no-owner --no-group \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='model/old/' \
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
  $SSH_CMD "kubectl scale daemonset $APP_NAME -n $APP_NAMESPACE --replicas=0 2>/dev/null || \
    kubectl patch daemonset $APP_NAME -n $APP_NAMESPACE -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"validate-paused\":\"true\"}}}}}'" 2>/dev/null || true
  $SSH_CMD "kubectl wait --for=delete pod -l app=$APP_NAME -n $APP_NAMESPACE --timeout=30s" 2>/dev/null || true
fi

# Also clean up any leftover test job
$SSH_CMD "kubectl delete job countingapp-test -n $APP_NAMESPACE --ignore-not-found 2>/dev/null || true"

# ─── 5. Define single-validation function ────────────────────────────────────
run_single_validation() {
  local VIDEO_PATH="$1"
  local VIDEO_FILE
  VIDEO_FILE=$(basename "$VIDEO_PATH")
  local VIDEO_START
  VIDEO_START=$(date +%s)

  # Resolve expected_count:
  #   1. Manifest lookup by filename (validation/expected_counts.json) — allows
  #      arbitrary/descriptive filenames (no collision when 2 videos share a count)
  #   2. Fallback: derive from filename template-validation-<N>.mp4 -> N (legacy)
  local EXPECTED_COUNT
  local EXPECTED_MANIFEST="validation/expected_counts.json"
  if [ -f "$EXPECTED_MANIFEST" ]; then
    EXPECTED_COUNT=$(jq -r --arg f "$VIDEO_FILE" '.videos[$f] // empty' "$EXPECTED_MANIFEST")
  fi
  if [ -z "$EXPECTED_COUNT" ]; then
    EXPECTED_COUNT=$(echo "$VIDEO_FILE" | sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p')
  fi
  if [ -z "$EXPECTED_COUNT" ]; then
    echo "WARNING: No expected_count for $VIDEO_FILE (not in manifest, not derivable from filename) — skipping" >&2
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"no_expected_count\"}"
    return 1
  fi

  echo "" >&2
  echo "─── Validating: $VIDEO_FILE (expected: $EXPECTED_COUNT) ───" >&2

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

  # Poll for job completion
  echo "Waiting for validation job to complete (timeout: ${TIMEOUT_SEC}s)..." >&2
  local JOB_STATUS=""
  while true; do
    local ELAPSED=$(( $(date +%s) - VIDEO_START ))
    if [ $ELAPSED -gt $TIMEOUT_SEC ]; then
      JOB_STATUS="timeout"
      break
    fi
    local COND
    COND=$($SSH_CMD "kubectl get job countingapp-validate -n $APP_NAMESPACE -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo ''" 2>/dev/null)
    case "$COND" in
      Complete|SuccessCriteriaMet) JOB_STATUS="complete"; break ;;
      Failed)   JOB_STATUS="failed"; break ;;
      *) echo "  Job status: ${COND:-pending} (${ELAPSED}s)..." >&2; sleep 5 ;;
    esac
  done

  if [ "$JOB_STATUS" = "timeout" ]; then
    echo "TIMEOUT: Validation job did not complete within ${TIMEOUT_SEC}s" >&2
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"timeout\", \"expected_count\": $EXPECTED_COUNT, \"job_status\": \"timeout\", \"elapsed_seconds\": $(( $(date +%s) - VIDEO_START ))}"
    return 1
  fi

  # Fetch result.json
  local RESULT_FILE="/tmp/result-$VIDEO_FILE.json"
  $SCP_CMD "$JETSON_USER@$JETSON_IP:$FILES_PATH/result.json" "$RESULT_FILE" 2>/dev/null || {
    local JOB_LOGS
    JOB_LOGS=$($SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1 | tail -50" 2>/dev/null || echo "Could not fetch logs")
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"result_json_missing\", \"expected_count\": $EXPECTED_COUNT, \"job_status\": \"$JOB_STATUS\", \"logs\": $(echo "$JOB_LOGS" | jq -Rs .)}"
    return 1
  }

  # Compare count
  local ACTUAL_COUNT
  ACTUAL_COUNT=$(jq -r '.count' "$RESULT_FILE")
  local DIFF=$(( ACTUAL_COUNT - EXPECTED_COUNT ))
  local ABS_DIFF=$(( DIFF < 0 ? -DIFF : DIFF ))
  local VSTATUS
  if [ "$ABS_DIFF" -le "$TOLERANCE" ]; then
    VSTATUS="pass"
  else
    VSTATUS="count_mismatch"
  fi

  local JOB_LOGS
  JOB_LOGS=$($SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1 | tail -100" 2>/dev/null || echo "Could not fetch logs")
  local VDURATION=$(( $(date +%s) - VIDEO_START ))

  # Output single-video result as JSON (to be collected by caller)
  jq -c -n \
    --arg status "$VSTATUS" \
    --argjson expected "$EXPECTED_COUNT" \
    --argjson actual "$ACTUAL_COUNT" \
    --argjson tolerance "$TOLERANCE" \
    --arg video "$VIDEO_FILE" \
    --arg job_status "$JOB_STATUS" \
    --argjson duration "$VDURATION" \
    --arg timestamp "$(date -Iseconds)" \
    --arg result_json "$(cat "$RESULT_FILE")" \
    --arg logs "$JOB_LOGS" \
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
      logs: $logs
    }'
}

# ─── 6. Run validation(s) ────────────────────────────────────────────────────
RESULTS_FILE="/tmp/validation-results.jsonl"
> "$RESULTS_FILE"

for VIDEO_PATH in $VIDEO_LIST; do
  run_single_validation "$VIDEO_PATH" >> "$RESULTS_FILE" || true
done

# ─── 7. Restart countingapp-dep if it was stopped ────────────────────────────
if [ "$DEP_WAS_RUNNING" = "true" ]; then
  echo ""
  echo "▶️  Restarting countingapp-dep (DaemonSet)..."
  $SSH_CMD "kubectl scale daemonset $APP_NAME -n $APP_NAMESPACE --replicas=1 2>/dev/null || \
    kubectl patch daemonset $APP_NAME -n $APP_NAMESPACE --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/template/spec/nodeSelector/validate-paused\"}]'" 2>/dev/null || true
fi

# ─── 8. Aggregate results into final report ──────────────────────────────────
TOTAL_DURATION=$(( $(date +%s) - VALIDATION_START ))
VIDEO_COUNT=$(jq -s 'length' "$RESULTS_FILE")
PASS_COUNT=$(jq -s '[.[] | select(.validation_status == "pass")] | length' "$RESULTS_FILE")
MISMATCH_COUNT=$(jq -s '[.[] | select(.validation_status == "count_mismatch")] | length' "$RESULTS_FILE")
ERROR_COUNT=$(jq -s '[.[] | select(.validation_status == "execution_error")] | length' "$RESULTS_FILE")

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

# Build final report
jq -n \
  --arg status "$OVERALL_STATUS" \
  --argjson video_count "$VIDEO_COUNT" \
  --argjson pass_count "$PASS_COUNT" \
  --argjson mismatch_count "$MISMATCH_COUNT" \
  --argjson error_count "$ERROR_COUNT" \
  --argjson duration "$TOTAL_DURATION" \
  --arg timestamp "$(date -Iseconds)" \
  --arg mode "$MODE" \
  --slurpfile results "$RESULTS_FILE" \
  '{
    validation_status: $status,
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
echo "Overall: $OVERALL_STATUS ($PASS_COUNT pass, $MISMATCH_COUNT mismatch, $ERROR_COUNT error / $VIDEO_COUNT total)"
exit $EXIT_CODE