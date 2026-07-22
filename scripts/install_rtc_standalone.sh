#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# install_rtc_standalone.sh — Configure the DS3231 RTC (HW-084) + boot service
# (BL-74) on an already-prepared Jetson, without re-running the full
# prepare_system.yml stack.
#
# Unlike install_companion_standalone.sh (which targets the fixed hotspot IP),
# this script finds the Jetson via scripts/jetson_discover.sh (nmap scan of
# WIFI_NETWORK, SSH probe) so it works when the Jetson is on its regular LAN/
# WAN IP, not just the hotspot. An explicit JETSON_IP in .env.local short-
# circuits discovery; JETSON_HOTSPOT_IP is a last-resort fallback. The RTC
# playbook itself only touches files + a systemd unit + installs i2c-tools —
# the i2c-tools apt install needs internet, so if the Jetson is offline you
# must already have i2c-tools installed (or run this over a connection with
# uplink).
#
# Prereq (MANUAL): the Jetson must be reachable over SSH from this PC, and the
# DS3231 module must be wired to the 40-pin header (see docs/13_rtc_install.md).
# The script pauses for your confirmation, like load_image.sh /
# install_companion_standalone.sh.
#
# Usage:
#   ./scripts/install_rtc_standalone.sh              # configure the RTC service
#   ./scripts/install_rtc_standalone.sh --check      # ansible dry-run
#   ./scripts/install_rtc_standalone.sh --tags rtc   # extra ansible args
#
# Required .env.local vars:
#   JETSON_PASSWORD     — sudo/SSH password on the Jetson
#   WIFI_NETWORK       — CIDR to nmap-scan for the Jetson (e.g. 192.168.0.0/24)
#                         used by jetson_discover.sh when JETSON_IP is not set
#   JETSON_USER         — SSH user (default: nano-counter)
# Optional .env.local vars (override discovery):
#   JETSON_IP          — plain IP, no CIDR — skip discovery, deploy here
#   JETSON_HOTSPOT_IP  — hotspot IP with CIDR — last-resort fallback target
#
# Exit codes:
#   0 — RTC configured (playbook succeeded)
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

# Resolve the Jetson target IP:
#   1. Explicit JETSON_IP in .env.local → use it directly (fast path, no scan).
#   2. Else run scripts/jetson_discover.sh (nmap WIFI_NETWORK + SSH probe) →
#      it writes JETSON_IP to /tmp/jetson_env.sh; source that.
#   3. Else fall back to JETSON_HOTSPOT_IP (CIDR stripped) as a last resort.
DISCOVER_SCRIPT="$(dirname "$0")/jetson_discover.sh"
if [ -n "${JETSON_IP:-}" ]; then
  JETSON_IP="${JETSON_IP%%/*}"
  echo "→ Using explicit JETSON_IP=${JETSON_IP} from .env.local (discovery skipped)"
elif [ -f "$DISCOVER_SCRIPT" ] && [ -n "${WIFI_NETWORK:-}" ]; then
  echo "→ JETSON_IP not set — discovering the Jetson on WIFI_NETWORK=${WIFI_NETWORK}..."
  # jetson_discover.sh sources .env.local itself, scans WIFI_NETWORK, probes SSH,
  # and writes 'JETSON_IP=<ip>' to /tmp/jetson_env.sh on success (exit 0).
  if bash "$DISCOVER_SCRIPT"; then
    # shellcheck disable=SC1091
    source /tmp/jetson_env.sh
  else
    echo "❌ Error: jetson_discover.sh did not find a reachable Jetson."
    echo "   Check WIFI_NETWORK in .env.local and that the Jetson is on the LAN,"
    echo "   or set JETSON_IP / JETSON_HOTSPOT_IP explicitly in .env.local."
    exit 1
  fi
  JETSON_IP="${JETSON_IP%%/*}"
elif [ -n "${JETSON_HOTSPOT_IP:-}" ]; then
  JETSON_IP="${JETSON_HOTSPOT_IP%%/*}"
  echo "→ No discover script / WIFI_NETWORK — falling back to JETSON_HOTSPOT_IP=${JETSON_IP}"
else
  echo "❌ Error: cannot resolve the Jetson IP."
  echo "   Set WIFI_NETWORK (for discovery) or JETSON_IP / JETSON_HOTSPOT_IP in .env.local."
  exit 1
fi

if ! command -v ansible-playbook &> /dev/null; then
  echo "❌ Error: ansible-playbook is not installed."
  echo "   Run ./scripts/install_ansible.sh first (from the WiFi-internet setup)."
  exit 1
fi

# ─── 3. Manual checkpoint: Jetson reachable + DS3231 wired ───────────────────
echo "=========================================="
echo "Jetson DS3231 RTC — Standalone Configure"
echo "=========================================="
echo "Prereq: the DS3231 (HW-084) module is wired to the 40-pin header"
echo "        (VCC→pin1 3.3V, GND→pin6, SDA→pin3, SCL→pin5)."
echo "        See docs/13_rtc_install.md for wiring + safety notes."
echo "Target: ${JETSON_USER}@${JETSON_IP}"
echo
read -r -p "Confirm the Jetson is reachable and the DS3231 is wired? [y/N] " ans
case "$ans" in
  y|Y|yes|YES) ;;
  *) echo "Aborted — wire the DS3231, ensure the Jetson is reachable, then re-run."; exit 1 ;;
esac

# Quick reachability check (ssh port) before invoking ansible.
if ! sshpass -p "$JETSON_PASSWORD" ssh -n \
     -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
     -o ConnectTimeout=5 \
     "$JETSON_USER@$JETSON_IP" 'echo reachable' >/dev/null 2>&1; then
  echo "❌ Error: cannot reach ${JETSON_USER}@${JETSON_IP} over SSH."
  echo "   Check that the Jetson is reachable, the DS3231 is wired,"
  echo "   and JETSON_IP / JETSON_HOTSPOT_IP is correct in .env.local."
  exit 1
fi

# ─── 4. Export for the env-based inventory + run the playbook ────────────────
export JETSON_IP JETSON_USER JETSON_PASSWORD
export ANSIBLE_HOST_KEY_CHECKING=False

echo
echo "→ Configuring DS3231 RTC on ${JETSON_USER}@${JETSON_IP}..."
ansible-playbook -i ansible/inventory/jetsons.yml \
  ansible/playbooks/system/configure_rtc.yml "$@"

echo
echo "✅ RTC configured. Verify on the Jetson:"
echo "   sudo i2cdetect -y 7            # should show '68' at row 0x60, col 8"
echo "   systemctl is-active rtc-ds3231 # 'active' (RemainAfterExit=oneshot)"
echo "   ls /dev/rtc1                    # the registered DS3231 RTC device"
echo "   sudo hwclock -r --rtc=/dev/rtc1 # reads a sane date/time"