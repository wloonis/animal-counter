#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# load_image.sh — Load a Docker image from the PC to the offline Jetson
#
# Targets the offline production Jetson via its WiFi hotspot (JETSON_HOTSPOT_IP).
# The hotspot IP in .env.local has a CIDR suffix (e.g. 192.168.100.1/24) which
# is stripped to get the raw IP. Rsyncs the tar.gz to a dedicated backup
# directory on the target (/data/orin/save/), loads it via docker load, verifies
# the image is present, and restarts the countingapp DaemonSet pod.
#
# Usage:
#   ./scripts/load_image.sh              # uses JETSON_HOTSPOT_IP from .env.local
#   ./scripts/load_image.sh --cleanup    # delete tar on target + PC after load
#
# Required .env.local vars:
#   JETSON_HOTSPOT_IP  — Jetson hotspot IP with CIDR (e.g. 192.168.100.1/24)
#   JETSON_PASSWORD    — sudo/SSH password on the Jetson
#   JETSON_USER        — SSH user (default: nano-counter)
#   IMAGE_NAME         — Docker image name (default: countingapp)
#   IMAGE_TAG          — Docker image tag  (default: local)
#   APP_NAMESPACE      — K8s namespace (default: countingapp-dev)
#
# Exit codes:
#   0 — image loaded, verified, and pod restarted
#   1 — configuration error, transfer failure, load failure, or pod restart failure
# ─────────────────────────────────────────────────────────────────────────────

# ─── 0. Parse CLI args ───────────────────────────────────────────────────────
CLEANUP=false
for arg in "$@"; do
  case "$arg" in
    --cleanup)
      CLEANUP=true
      ;;
    *)
      echo "❌ Error: unknown argument '$arg'"
      echo "   Usage: ./scripts/load_image.sh [--cleanup]"
      exit 1
      ;;
  esac
done

# ─── 1. Load .env.local ──────────────────────────────────────────────────────
if [ -f ".env.local" ]; then
  set -a
  source .env.local
  set +a
fi

# ─── 2. Defaults + validation ───────────────────────────────────────────────
IMAGE_NAME="${IMAGE_NAME:-countingapp}"
IMAGE_TAG="${IMAGE_TAG:-local}"
JETSON_USER="${JETSON_USER:-nano-counter}"
APP_NAMESPACE="${APP_NAMESPACE:-countingapp-dev}"
REMOTE_SAVE_DIR="/data/orin/save"
TAR_FILE="save/${IMAGE_NAME}-${IMAGE_TAG}.tar.gz"
TAR_NAME="${IMAGE_NAME}-${IMAGE_TAG}.tar.gz"

if [ -z "${JETSON_PASSWORD:-}" ]; then
  echo "❌ Error: JETSON_PASSWORD is not set"
  echo "   Please set JETSON_PASSWORD in .env.local"
  exit 1
fi

if [ -z "${JETSON_HOTSPOT_IP:-}" ]; then
  echo "❌ Error: JETSON_HOTSPOT_IP is not set"
  echo "   Please set JETSON_HOTSPOT_IP in .env.local (e.g. 192.168.100.1/24)"
  exit 1
fi

if ! command -v sshpass &> /dev/null; then
  echo "❌ Error: sshpass is not installed. Install it first:"
  echo "   sudo apt install sshpass"
  exit 1
fi

if ! command -v rsync &> /dev/null; then
  echo "❌ Error: rsync is not installed. Install it first:"
  echo "   sudo apt install rsync"
  exit 1
fi

# ─── 3. Strip CIDR suffix from JETSON_HOTSPOT_IP ─────────────────────────────
# e.g. "192.168.100.1/24" → "192.168.100.1"
TARGET_IP="${JETSON_HOTSPOT_IP%%/*}"
echo "🎯 Target (offline) Jetson IP: $TARGET_IP (from JETSON_HOTSPOT_IP=$JETSON_HOTSPOT_IP)"

# ─── 4. Validate local tar exists ────────────────────────────────────────────
if [ ! -f "$TAR_FILE" ]; then
  echo "❌ Error: $TAR_FILE not found on the PC"
  echo "   Run ./scripts/save_image.sh first to save the image from the test Jetson."
  exit 1
fi

LOCAL_SIZE=$(du -h "$TAR_FILE" | cut -f1)
echo "📦 Local tar: $TAR_FILE ($LOCAL_SIZE)"

# ─── 5. Create remote backup directory ──────────────────────────────────────
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH_CMD="sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS $JETSON_USER@$TARGET_IP"

echo "📁 Creating remote backup directory ($REMOTE_SAVE_DIR)..."
# /data/orin/ is root-owned on the Jetson — create the dir via sudo, then
# chown it to JETSON_USER so the (non-sudo) rsync in step 6 can write into it.
$SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S sh -c 'mkdir -p $REMOTE_SAVE_DIR && chown $JETSON_USER:$JETSON_USER $REMOTE_SAVE_DIR'" || {
  echo "❌ Error: could not create $REMOTE_SAVE_DIR on $TARGET_IP"
  echo "   Check SSH connectivity to $JETSON_USER@$TARGET_IP"
  exit 1
}

# ─── 6. Rsync tar to target (resumable) ─────────────────────────────────────
echo "📡 Rsyncing $TAR_FILE to $JETSON_USER@$TARGET_IP:$REMOTE_SAVE_DIR/ ..."
echo "   (resumable via --partial — re-run if wifi drops)"

sshpass -p "$JETSON_PASSWORD" rsync -P --partial \
  -e "ssh $SSH_OPTS" \
  "$TAR_FILE" \
  "$JETSON_USER@$TARGET_IP:$REMOTE_SAVE_DIR/" || {
  echo "❌ Error: rsync failed (exit code: $?)"
  echo "   Re-run the script — rsync --partial will resume the transfer."
  exit 1
}

echo "✅ Rsync complete"

# ─── 7. Load image on target via docker load ────────────────────────────────
echo "🐳 Loading image on target via docker load..."
REMOTE_TAR="$REMOTE_SAVE_DIR/$TAR_NAME"

$SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S sh -c 'gunzip -c $REMOTE_TAR | docker load'" || {
  echo "❌ Error: docker load failed on $TARGET_IP"
  echo "   Check disk space on the target: ssh $JETSON_USER@$TARGET_IP 'df -h'"
  exit 1
}

echo "✅ Image loaded"

# ─── 8. Verify image is present ───────────────────────────────────────────────
echo "🔍 Verifying image presence on target..."
IMAGE_CHECK=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S docker images 2>/dev/null | grep '${IMAGE_NAME}' | grep '${IMAGE_TAG}'" 2>/dev/null || true)

if [ -z "$IMAGE_CHECK" ]; then
  echo "❌ Error: ${IMAGE_NAME}:${IMAGE_TAG} not found in docker images on $TARGET_IP"
  echo "   Check docker images manually: ssh $JETSON_USER@$TARGET_IP 'sudo docker images'"
  exit 1
fi

echo "✅ Image verified on target:"
echo "   $IMAGE_CHECK"

# ─── 8b. Prune old dangling image (reclaim disk) ────────────────────────────
# docker load moved the :local tag to the new image; the OLD image is now
# untagged (dangling) and still consumes ~20 GB. Remove dangling images so the
# target does not fill up /data (old + new + tar ≈ 60 GB at peak).
echo "🧹 Pruning old dangling images (reclaim disk)..."
PRUNE_OUT=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S docker image prune -f" 2>/dev/null) || {
  echo "⚠️  Warning: docker image prune failed (non-fatal) — old image may still occupy space"
}
echo "   $PRUNE_OUT"

# Capture the image ID now tagged :local (the one we just loaded).
LOADED_IMAGE_ID=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S docker image inspect ${IMAGE_NAME}:${IMAGE_TAG} --format '{{.Id}}'" 2>/dev/null)
echo "🏷️  ${IMAGE_NAME}:${IMAGE_TAG} -> $LOADED_IMAGE_ID"

# ─── 9. Restart countingapp pod ─────────────────────────────────────────────
echo "🔄 Restarting countingapp DaemonSet (rollout restart)..."
$SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl rollout restart daemonset countingapp -n $APP_NAMESPACE" || {
  echo "❌ Error: rollout restart failed"
  echo "   Check k3s status: ssh $JETSON_USER@$TARGET_IP 'sudo k3s kubectl get pods -n $APP_NAMESPACE'"
  exit 1
}

# ─── 10. Verify pod is Running on the NEW image ─────────────────────────────
# Guard: if the DaemonSet schedules 0 pods (e.g. a leftover nodeSelector like
# validate-paused=true from an interrupted validation), rollout restart will
# NOT bring a pod back — fail fast with an actionable message instead of a
# silent 60s timeout.
DESIRED=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl get daemonset countingapp -n $APP_NAMESPACE -o jsonpath='{.status.desiredNumberScheduled}'" 2>/dev/null)
if [ -z "$DESIRED" ] || [ "$DESIRED" = "0" ]; then
  echo "❌ Error: countingapp DaemonSet has DESIRED=0 pods on $TARGET_IP"
  echo "   rollout restart cannot schedule a pod. Likely a leftover nodeSelector"
  echo "   (e.g. validate-paused=true from an interrupted validation). Inspect:"
  echo "     ssh $JETSON_USER@$TARGET_IP 'sudo k3s kubectl get daemonset countingapp -n $APP_NAMESPACE -o jsonpath=\"{.spec.template.spec.nodeSelector}\"'"
  echo "   Remove it, e.g.:"
  echo "     sudo k3s kubectl patch daemonset countingapp -n $APP_NAMESPACE --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/template/spec/nodeSelector/validate-paused\"}]'"
  exit 1
fi

echo "⏳ Waiting for the countingapp pod to be Running (up to 60s)..."
POD_RUNNING=false
POD_NAME=""
POD_IMAGE_ID=""
for _ in $(seq 1 12); do
  sleep 5
  POD_NAME=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl -n $APP_NAMESPACE get pod -l app=countingapp -o jsonpath='{.items[0].metadata.name}'" 2>/dev/null)
  if [ -n "$POD_NAME" ]; then
    POD_PHASE=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl -n $APP_NAMESPACE get pod $POD_NAME -o jsonpath='{.status.phase}'" 2>/dev/null)
    if [ "$POD_PHASE" = "Running" ]; then
      POD_RUNNING=true
      POD_IMAGE_ID=$($SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl -n $APP_NAMESPACE get pod $POD_NAME -o jsonpath='{.status.containerStatuses[0].imageID}'" 2>/dev/null)
      break
    fi
  fi
done

if [ "$POD_RUNNING" != "true" ]; then
  echo "❌ Error: countingapp pod did not reach Running within 60s on $TARGET_IP"
  echo "   Inspect: ssh $JETSON_USER@$TARGET_IP 'sudo k3s kubectl -n $APP_NAMESPACE get pods -l app=countingapp'"
  exit 1
fi
echo "✅ Pod Running: $POD_NAME"

# Compare the pod's running image ID with the :local image ID just loaded.
# kubectl reports imageID as "docker-pullable://countingapp@sha256:<id>";
# docker inspect returns "sha256:<id>". Normalize both to "sha256:<id>".
POD_SHA=$(echo "$POD_IMAGE_ID" | sed 's/.*sha256:/sha256:/')
LOCAL_SHA=$(echo "$LOADED_IMAGE_ID" | sed 's/^sha256:/sha256:/')
echo "🔍 Pod imageID: $POD_IMAGE_ID"
if [ "$POD_SHA" != "$LOCAL_SHA" ]; then
  echo "❌ Error: pod image ID ($POD_SHA) != loaded ${IMAGE_NAME}:${IMAGE_TAG} ID ($LOCAL_SHA)"
  echo "   The pod is NOT running the newly loaded image."
  exit 1
fi
echo "✅ Pod is running the newly loaded image (ID match)"

echo "📋 Pod status:"
$SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl -n $APP_NAMESPACE get pods -l app=countingapp" || true

# ─── 11. Optional cleanup ───────────────────────────────────────────────────
if [ "$CLEANUP" = true ]; then
  echo ""
  echo "🧹 Cleanup: removing tar files..."
  # Remove tar on target
  $SSH_CMD "echo '$JETSON_PASSWORD' | sudo -S rm -f $REMOTE_TAR" || {
    echo "⚠️  Warning: could not remove $REMOTE_TAR on target"
  }
  echo "   ✅ Removed $REMOTE_TAR on $TARGET_IP"

  # Remove tar on PC
  rm -f "$TAR_FILE" || {
    echo "⚠️  Warning: could not remove $TAR_FILE on PC"
  }
  echo "   ✅ Removed $TAR_FILE on PC"
fi

# ─── 12. Recap ──────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ Image loaded and pod restarted"
echo "   Target : ${JETSON_USER}@${TARGET_IP}"
echo "   Image  : ${IMAGE_NAME}:${IMAGE_TAG}"
echo "   Namespace : ${APP_NAMESPACE}"
if [ "$CLEANUP" = true ]; then
  echo "   Cleanup : tar files removed on target + PC"
else
  echo "   Tar on target : $REMOTE_TAR (use --cleanup to remove)"
  echo "   Tar on PC     : $TAR_FILE"
fi
echo "════════════════════════════════════════════════════════════"
