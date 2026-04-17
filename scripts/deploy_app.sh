#!/bin/bash

# Application Deployment Script
# Deploys countingapp to Jetson Nano Orin

set -e

echo "=========================================="
echo "Application Deployment Script"
echo "=========================================="

# Load environment variables
if [ -f ".env.local" ]; then
    echo "Loading environment variables from .env.local..."
    set -a
    source .env.local
    set +a
fi

# Check if JETSON_IP is set
if [ -f /tmp/jetson_env.sh ]; then
    source /tmp/jetson_env.sh
fi

if [ -z "${JETSON_IP}" ]; then
    echo "Error: JETSON_IP is not set"
    echo "Please run jetson_discover.sh first or set JETSON_IP environment variable"
    exit 1
fi

# Check if JETSON_USER is set
if [ -z "${JETSON_USER}" ]; then
    JETSON_USER="nano-counter"
    echo "Warning: JETSON_USER not set, using default: $JETSON_USER"
fi

# Check if sshpass is available
if [ -z "${JETSON_PASSWORD}" ] && ! command -v sshpass &> /dev/null; then
    echo "Warning: sshpass not installed and no password provided"
    echo "Attempting SSH connection without password..."
fi

echo "🔍 Attempting SSH connection to Jetson at $JETSON_IP as $JETSON_USER..."

# Try SSH connection
if [ -n "${JETSON_PASSWORD}" ]; then
    # Use sshpass for password authentication
    if sshpass -p "${JETSON_PASSWORD}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "${JETSON_USER}@${JETSON_IP}" "echo '✅ CONNECTÉ à $JETSON_IP'"; then
        echo "🎯 SSH connection successful with password authentication"
    else
        echo "❌ SSH connection failed with password authentication"
        exit 1
    fi
else
    # Try SSH without password (key-based authentication)
    if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "${JETSON_USER}@${JETSON_IP}" "echo '✅ CONNECTÉ à $JETSON_IP'"; then
        echo "🎯 SSH connection successful with key-based authentication"
    else
        echo "❌ SSH connection failed"
        echo "Please ensure:"
        echo "  1. SSH is enabled on the Jetson"
        echo "  2. Password is correct (set JETSON_PASSWORD)"
        echo "  3. SSH keys are configured (or sshpass is installed)"
        exit 1
    fi
fi

echo ""
echo "Step 1: Building and deploying countingapp..."
echo "This may take several minutes..."

# Set environment variables for Ansible
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
    echo "3. Access countingapp: http://$JETSON_IP:31501"
    echo ""
    exit 0
else
    echo ""
    echo "❌ Error: Application deployment failed"
    echo "Check the logs above for details"
    exit 1
fi