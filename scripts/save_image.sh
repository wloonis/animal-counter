#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# save_image.sh — Save a Docker image from the test Jetson to the PC
#
# Sources .env.local, resolves the test Jetson IP via jetson_discover.sh
# (or accepts a JETSON_IP override), streams `sudo docker save | gzip` over
# SSH to save/<image>-<tag>.tar.gz on the PC (single pass, no intermediate
# temp on the Jetson). Verifies the gzip integrity and prints a size recap.
#
# Usage:
#   ./scripts/save_image.sh
#
# Required .env.local vars:
#   JETSON_PASSWORD   — sudo/SSH password on the Jetson
#   IMAGE_NAME        — Docker image name (default: countingapp)
#   IMAGE_TAG         — Docker image tag  (default: local)
#   JETSON_USER       — SSH user (default: nano-counter)
#
# Optional overrides:
#   JETSON_IP         — skip discovery, connect to this IP directly
#
# Exit codes:
#   0 — image saved and verified
#   1 — configuration error, discovery failure, SSH failure, or gzip corruption
# ─────────────────────────────────────────────────────────────────────────────

# ─── 0. Load .env.local ──────────────────────────────────────────────────────
if [ -f ".env.local" ]; then
  set -a
  source .env.local
  set +a
fi

# ─── 1. Defaults + validation ───────────────────────────────────────────────
IMAGE_NAME="${IMAGE_NAME:-countingapp}"
IMAGE_TAG="${IMAGE_TAG:-local}"
JETSON_USER="${JETSON_USER:-nano-counter}"
TAR_FILE="save/${IMAGE_NAME}-${IMAGE_TAG}.tar.gz"

if [ -z "${JETSON_PASSWORD:-}" ]; then
  echo "❌ Error: JETSON_PASSWORD is not set"
  echo "   Please set JETSON_PASSWORD in .env.local"
  exit 1
fi

if ! command -v sshpass &> /dev/null; then
  echo "❌ Error: sshpass is not installed. Install it first:"
  echo "   sudo apt install sshpass"
  exit 1
fi

# ─── 2. Resolve test Jetson IP ──────────────────────────────────────────────
# If JETSON_IP is already set (env or .env.local), use it directly.
# Otherwise, run jetson_discover.sh (nmap scan + SSH credential test).
# A successful discovery is cached in /tmp/jetson_env.sh.
if [ -z "${JETSON_IP:-}" ]; then
  echo "🔎 JETSON_IP not set — running jetson_discover.sh..."
  bash scripts/jetson_discover.sh
  set -a
  source /tmp/jetson_env.sh
  set +a
fi

if [ -z "${JETSON_IP:-}" ]; then
  echo "❌ Error: Could not determine Jetson IP"
  exit 1
fi

echo "🎯 Test Jetson IP: $JETSON_IP"

# ─── 3. Prepare save/ directory + clean up stale files ──────────────────────
mkdir -p save

# Remove any existing output tar (stale from a previous run)
if [ -f "$TAR_FILE" ]; then
  echo "🧹 Removing stale $TAR_FILE from a previous run..."
  rm -f "$TAR_FILE"
fi

# Remove any *.tmp partial files from an interrupted run
if ls save/*.tmp 1>/dev/null 2>&1; then
  echo "🧹 Removing leftover .tmp partial files..."
  rm -f save/*.tmp
fi

# ─── 4. Stream docker save | gzip over SSH ──────────────────────────────────
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
echo "📦 Saving ${IMAGE_NAME}:${IMAGE_TAG} from $JETSON_USER@$JETSON_IP..."
echo "   → $TAR_FILE (streaming, single pass)"

# Stream: sudo docker save IMG | gzip → PC file. No intermediate temp on Jetson.
# The sudo password is piped via stdin to `sudo -S`.
sshpass -p "$JETSON_PASSWORD" ssh $SSH_OPTS \
  "$JETSON_USER@$JETSON_IP" \
  "echo '$JETSON_PASSWORD' | sudo -S docker save ${IMAGE_NAME}:${IMAGE_TAG} 2>/dev/null | gzip" \
  > "$TAR_FILE"

# Check exit status of the SSH pipeline
SAVE_RC=$?
if [ $SAVE_RC -ne 0 ]; then
  echo "❌ Error: SSH/docker save failed (exit code: $SAVE_RC)"
  echo "   Partial file may exist at $TAR_FILE — re-run to replace it."
  exit 1
fi

# ─── 5. Verify gzip integrity ───────────────────────────────────────────────
echo "🔍 Verifying gzip integrity..."
if ! gzip -t "$TAR_FILE" 2>/dev/null; then
  echo "❌ Error: gzip -t failed — the tar.gz is corrupt"
  echo "   The file at $TAR_FILE is unusable. Re-run the script."
  exit 1
fi
echo "✅ gzip integrity OK"

# ─── 6. Size recap ──────────────────────────────────────────────────────────
FILE_SIZE=$(du -h "$TAR_FILE" | cut -f1)
echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ Image saved successfully"
echo "   Source : ${JETSON_USER}@${JETSON_IP}:${IMAGE_NAME}:${IMAGE_TAG}"
echo "   File  : ${TAR_FILE}"
echo "   Size  : ${FILE_SIZE}"
echo "════════════════════════════════════════════════════════════"
