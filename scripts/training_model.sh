#!/bin/bash

# Jetson Training Script
# One-shot script to discover Jetson and run bootstrap

set -e

echo "=========================================="
echo "Jetson Training Script"
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

#Step 3: Run Ansible system training (commented for now)
echo ""
echo "Step 3: Running Ansible system training..."
echo "This may take several minutes depending on network speed and Jetson performance..."

# Set environment variables for Ansible
if [ -z "${JETSON_USER}" ]; then
    export JETSON_USER="nano-counter"
fi

if [ -z "${JETSON_PASSWORD}" ]; then
    echo "Warning: JETSON_PASSWORD not set. Using SSH key authentication."
fi

export ANSIBLE_HOST_KEY_CHECKING=False

# Run Ansible playbook for system training
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/model/build_model.yml; then
    echo ""
    echo "✅ Training completed successfully!"
    echo ""
else
    echo ""
    echo "❌ Error: Training failed"
    echo "Check the logs above for details"
    exit 1
fi
