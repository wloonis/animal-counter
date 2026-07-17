#!/bin/bash

# Jetson Preparation Script
# One-shot script to discover Jetson and run bootstrap

set -e

echo "=========================================="
echo "Jetson Preparation Script"
echo "=========================================="

# Load environment variables
if [ -f ".env.local" ]; then
    echo "Loading environment variables from .env.local..."
    set -a
    source .env.local
    set +a
fi

# Step 1: Discover Jetson
echo ""
echo "Step 1: Discovering Jetson device..."
if ! bash scripts/jetson_discover.sh; then
    echo "Error: Failed to discover Jetson device"
    exit 1
fi

# Export JETSON_IP if not already set
if [ -f /tmp/jetson_env.sh ]; then
    set -a
    source /tmp/jetson_env.sh
    set +a
fi

echo "Discovered Jetson at: $JETSON_IP"

# Step 2: Test SSH access
echo ""
echo "Step 2: Testing SSH access..."
if ! bash scripts/jetson_first_access.sh; then
    echo "Error: Failed to establish SSH connection"
    echo "Please ensure:"
    echo "  - Jetson is powered on and connected to network"
    echo "  - SSH is enabled on the Jetson"
    echo "  - Credentials are correct"
    exit 1
fi

echo "SSH access successful!"

#Step 2.5: Grow root partition to fill the whole disk
# A Jetson migrated to NVMe/SD often boots from a rootfs partition smaller
# than the physical disk (e.g. 58G on a 128G SSD). Grow it to use all the
# space before installing anything big (docker images). Idempotent: no-op
# if the partition already fills the disk.
echo ""
echo "Step 2.5: Growing root partition to fill the whole disk (if needed)..."
if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi
export ANSIBLE_HOST_KEY_CHECKING=False
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/grow_root_partition.yml; then
    echo ""
    echo "✅ Root partition grown (or already at full size)"
    echo ""
else
    echo ""
    echo "❌ Error: Growing root partition failed"
    echo "Check the logs above for details"
    exit 1
fi

#Step 3: Run Ansible system preparation (commented for now)
echo ""
echo "Step 3: Running Ansible system preparation..."
echo "This may take several minutes depending on network speed and Jetson performance..."

# Set environment variables for Ansible
if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi

if [ -z "${JETSON_PASSWORD}" ]; then
    echo "Warning: JETSON_PASSWORD not set. Using SSH key authentication."
fi

export ANSIBLE_HOST_KEY_CHECKING=False

# Run Ansible playbook for system preparation
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/prepare_system.yml; then
    echo ""
    echo "✅ System preparation completed successfully!"
    echo ""
else
    echo ""
    echo "❌ Error: System preparation failed"
    echo "Check the logs above for details"
    exit 1
fi

# Step 4: Build and deploy countingapp
echo ""
echo "Step 4: Building and deploying countingapp..."
echo "This may take several minutes..."

# Set environment variables for Ansible
if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi

if [ -z "${JETSON_PASSWORD}" ]; then
    echo "Warning: JETSON_PASSWORD not set. Using SSH key authentication."
fi

export ANSIBLE_HOST_KEY_CHECKING=False

# Run Ansible playbook for application deployment
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/app/deploy_app.yml; then
    echo ""
    echo "=========================================="
    echo "SUCCESS: Application deployment completed!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. Connect to Jetson hotspot: $JETSON_HOTSPOT_SSID"
    echo "2. Access Jetson via SSH: ssh $JETSON_USER@$JETSON_IP"
    echo "3. Access Jetson via SSH: ssh $JETSON_USER@$JETSON_ETH_IP"
    echo "4. Access countingapp: http://$JETSON_IP:31501"
    echo ""
else
    echo ""
    echo "❌ Error: Application deployment failed"
    echo "Check the logs above for details"
    exit 1
fi

# Step 4.5: Pin a static IP on the internet WiFi (TP-Link) connection.
# Run BEFORE hotspot_setup: the discovery needs the active infrastructure WiFi
# connection, which goes away once the Jetson switches to hotspot (AP) mode.
# `nmcli connection modify` only rewrites the profile — it does NOT drop the
# current SSH session. The static IP (192.168.0.180) applies on the next
# activation of the TP-Link connection (i.e. when the hotspot is cut and the
# Jetson rejoins the internet WiFi).
echo ""
echo "Step 4.5: Pinning static IP on internet WiFi (192.168.0.180)..."
if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi
export ANSIBLE_HOST_KEY_CHECKING=False
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/configure_static_wifi.yml; then
    echo ""
    echo "✅ Static WiFi IP configured (applies when Jetson rejoins internet WiFi)"
    echo ""
else
    echo ""
    echo "❌ Error: Static WiFi configuration failed"
    echo "Check the logs above for details"
    exit 1
fi

#Step 5: Configure Splash Screen and LXDE Protection
# Run BEFORE hotspot_setup: the splash step runs `apt install feh`, which needs
# internet, so it must run while the Jetson is still on the internet WiFi.
# hotspot_setup reboots the Jetson into hotspot mode (no internet) as its last
# action, so it must be the FINAL step.
echo ""
echo "Step 5: Configuring Splash Screen and LXDE Protection..."
echo "This will:"
echo "- Display splash.png while countingapp is loading"
echo "- Block LXDE access until countingapp service is running in k3s"
echo ""

# Set environment variables for Ansible
if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi

if [ -z "${JETSON_PASSWORD}" ]; then
    echo "Warning: JETSON_PASSWORD not set. Using SSH key authentication."
fi

export ANSIBLE_HOST_KEY_CHECKING=False

# Run Ansible playbook for splash screen configuration
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/configure_splash_screen.yml; then
    echo ""
    echo "✅ Splash Screen Configuration completed successfully!"
    echo ""
else
    echo ""
    echo "❌ Error: Splash Screen Configuration failed"
    echo "Check the logs above for details"
    exit 1
fi

#Step 6: Run Ansible HotSpot Setup (MUST be last — it reboots the Jetson)
# hotspot_setup.yml schedules a delayed reboot (systemd-run --on-active=3 reboot)
# into hotspot mode. After it, the Jetson reboots onto the hotspot network
# (192.168.100.1) and is unreachable from the internet WiFi, so no further SSH
# steps can run. It must be the final action.
echo ""
echo "Step 6: Running Ansible HotSpot Setup (final step — reboots the Jetson)..."
echo "The Jetson will reboot into hotspot mode when this completes."

if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi
export ANSIBLE_HOST_KEY_CHECKING=False

if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/hotspot_setup.yml; then
    echo ""
    echo "✅ HotSpot Setup completed successfully — Jetson is rebooting."
    echo ""
else
    echo ""
    echo "❌ Error: HotSpot Setup failed"
    echo "Check the logs above for details"
    exit 1
fi


echo ""
echo "=========================================="
echo "ALL STEPS COMPLETED SUCCESSFULLY!"
echo "=========================================="
echo ""
echo "Summary:"
echo "1. ✅ Root partition grown to fill the disk"
echo "2. ✅ System preparation"
echo "3. ✅ Application deployment"
echo "4. ✅ Static WiFi IP (192.168.0.180 on internet WiFi)"
echo "5. ✅ Splash Screen & LXDE Protection"
echo "6. ✅ HotSpot Setup (Jetson rebooting into hotspot mode)"
echo ""
echo "The Jetson is now ready!"
echo "- Splash screen will show during countingapp startup"
echo "- LXDE is blocked until countingapp is running"
echo ""
echo "Next steps:"
echo "1. Connect to Jetson hotspot: $JETSON_HOTSPOT_SSID"
echo "2. Access Jetson via SSH (hotspot): ssh $JETSON_USER@$JETSON_HOTSPOT_IP"
echo "3. Access Jetson via SSH (internet WiFi, static): ssh $JETSON_USER@192.168.0.180"
echo "4. Access countingapp: http://$JETSON_HOTSPOT_IP:31501"
echo ""

exit 0
