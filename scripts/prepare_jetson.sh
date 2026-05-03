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

#Step 5: Run Ansible HotSpot Setup (commented for now)
echo ""
echo "Step 3: Running Ansible HotSpot Setup..."
echo "This may take several minutes depending on network speed and Jetson performance..."

# Run Ansible playbook for system preparation
if ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/hotspot_setup.yml; then
    echo ""
    echo "✅ HotSpot Setup completed successfully!"
    echo ""
else
    echo ""
    echo "❌ Error: HotSpot Setup failed"
    echo "Check the logs above for details"
    exit 1
fi


exit 0
