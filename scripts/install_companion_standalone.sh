#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# install_companion_standalone.sh — Deploy the Jetson companion service (BL-64)
# over the Jetson's WiFi hotspot (OFFLINE — no internet needed).
#
# Why a standalone: the companion is stdlib-only Python (http.server, json,
# subprocess, datetime) with NO apt/pip/docker-pull, so unlike the install /
# build / model playbooks it can be deployed with no internet — exactly the
# situation once the Jetson is in WiFi HotSpot mode (isolated LAN, no uplink).
# This is the ONLY system playbook that needs an offline standalone; the rest
# go through prepare_jetson.sh (install) or require internet (build/model).
#
# Mirrors load_image.sh's offline pattern: uses JETSON_HOTSPOT_IP (CIDR
# stripped) as the target, NOT jetson_discover.sh — the hotspot IP is fixed and
# known, so an nmap scan would be pointless and slow.
#
# Prereq (MANUAL): the Jetson must be switched to HotSpot mode and this PC
# connected to that hotspot. The script cannot switch the Jetson to hotspot
# itself — it pauses for your confirmation, like load_image.sh.
#
# Usage:
#   ./scripts/install_companion_standalone.sh              # deploy / reconfigure
#   ./scripts/install_companion_standalone.sh --check      # ansible dry-run
#   ./scripts/install_companion_standalone.sh --tags <t>   # extra ansible args
#
# Required .env.local vars:
#   JETSON_HOTSPOT_IP  — Jetson hotspot IP with CIDR (e.g. 192.168.100.1/24)
#   JETSON_PASSWORD    — sudo/SSH password on the Jetson
#   JETSON_USER         — SSH user (default: nano-counter)
#
# Exit codes:
#   0 — companion deployed/reconfigured (playbook succeeded)
#   1 — missing config, user aborted the checkpoint, or ansible failed
# ─────────────────────────────────────────────────────────────────────────────

# ─── 1. Load .env.local ──────────────────────────────────────────────────────
if [ -f ".env.local" ]; then
  set -a
  source .env.local
  set +a
fi

# ─── 2. Defaults + validation ───────────────────────────────────────────────
JETSON_USER="${JETSON_USER:-nano-counter}"

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

# Strip CIDR suffix (192.168.100.1/24 -> 192.168.100.1) for the inventory lookup.
JETSON_IP="${JETSON_HOTSPOT_IP%%/*}"

if ! command -v ansible-playbook &> /dev/null; then
  echo "❌ Error: ansible-playbook is not installed."
  echo "   Run ./scripts/install_ansible.sh first (from the WiFi-internet setup)."
  exit 1
fi

# ─── 3. Manual checkpoint: Jetson must be in HotSpot mode + PC connected ────
echo "=========================================="
echo "Jetson Companion — Hotspot (offline) Deploy"
echo "=========================================="
echo "Prereq: the Jetson is in WiFi HotSpot mode and this PC is connected to it."
echo "Target: ${JETSON_USER}@${JETSON_IP}  (from JETSON_HOTSPOT_IP=${JETSON_HOTSPOT_IP})"
echo
read -r -p "Confirm the Jetson is in hotspot mode and this PC is connected? [y/N] " ans
case "$ans" in
  y|Y|yes|YES) ;;
  *) echo "Aborted — switch the Jetson to hotspot, connect this PC, then re-run."; exit 1 ;;
esac

# Quick reachability check (ssh port) before invoking ansible.
if ! sshpass -p "$JETSON_PASSWORD" ssh \
     -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
     -o ConnectTimeout=5 \
     "$JETSON_USER@$JETSON_IP" 'echo reachable' >/dev/null 2>&1; then
  echo "❌ Error: cannot reach ${JETSON_USER}@${JETSON_IP} over SSH."
  echo "   Check that the Jetson is in hotspot mode, this PC is on that hotspot,"
  echo "   and JETSON_HOTSPOT_IP is correct in .env.local."
  exit 1
fi

# ─── 4. Export for the env-based inventory + run the playbook ────────────────
export JETSON_IP JETSON_USER JETSON_PASSWORD
export ANSIBLE_HOST_KEY_CHECKING=False

echo
echo "→ Deploying jetson-companion to ${JETSON_USER}@${JETSON_IP} (offline)..."
ansible-playbook -i ansible/inventory/jetsons.yml \
  ansible/playbooks/system/configure_companion.yml "$@"

echo
echo "✅ Companion deployed/reconfigured. Verify:"
echo "   curl http://${JETSON_IP}:8090/api/identify"
echo "   ssh ${JETSON_USER}@${JETSON_IP} 'systemctl is-active jetson-companion'"