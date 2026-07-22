#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# install_rtc_standalone.sh — Configure the DS3231 RTC (HW-084) + boot service
# (BL-74) on an already-prepared Jetson, without re-running the full
# prepare_system.yml stack.
#
# Mirrors install_companion_standalone.sh's offline-friendly pattern: the
# Jetson can be reached either via its WiFi hotspot (JETSON_HOTSPOT_IP) or its
# regular LAN/WAN IP (JETSON_IP). The hotspot IP is fixed and known, so no
# nmap scan is needed. The RTC playbook itself only touches files + a systemd
# unit + installs i2c-tools — the i2c-tools apt install needs internet, so if
# the Jetson is offline you must already have i2c-tools installed (or run this
# over a connection with uplink).
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
#   JETSON_HOTSPOT_IP   — Jetson hotspot IP with CIDR (e.g. 192.168.100.1/24)
#                         OR JETSON_IP (plain IP, no CIDR) for a LAN/WAN deploy
#   JETSON_USER         — SSH user (default: nano-counter)
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

# Prefer the explicit JETSON_IP if set; otherwise fall back to the hotspot IP.
# JETSON_HOTSPOT_IP carries a CIDR suffix that we strip for the inventory lookup.
if [ -n "${JETSON_IP:-}" ]; then
  JETSON_IP="${JETSON_IP%%/*}"
elif [ -n "${JETSON_HOTSPOT_IP:-}" ]; then
  JETSON_IP="${JETSON_HOTSPOT_IP%%/*}"
else
  echo "❌ Error: neither JETSON_IP nor JETSON_HOTSPOT_IP is set"
  echo "   Set JETSON_HOTSPOT_IP (e.g. 192.168.100.1/24) or JETSON_IP in .env.local"
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
if [ -n "${JETSON_HOTSPOT_IP:-}" ] && [ "${JETSON_IP}" = "${JETSON_HOTSPOT_IP%%/*}" ]; then
  echo "        (from JETSON_HOTSPOT_IP=${JETSON_HOTSPOT_IP})"
fi
echo
read -r -p "Confirm the Jetson is reachable and the DS3231 is wired? [y/N] " ans
case "$ans" in
  y|Y|yes|YES) ;;
  *) echo "Aborted — wire the DS3231, ensure the Jetson is reachable, then re-run."; exit 1 ;;
esac

# Quick reachability check (ssh port) before invoking ansible.
if ! sshpass -p "$JETSON_PASSWORD" ssh \
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