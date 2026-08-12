#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 LOONIS Wennaël


# Jetson First Access Script
# Establishes SSH connection to Jetson device and exports JETSON_IP

set -e

# Load environment variables
if [ -f ".env.local" ]; then
    source .env.local
fi

# Export JETSON_IP if not already set
if [ -f /tmp/jetson_env.sh ]; then
    source /tmp/jetson_env.sh
fi

# Check if JETSON_IP is set
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

# Supprimer l'entrée connue pour cette IP pour éviter les conflits
ssh-keygen -f "$HOME/.ssh/known_hosts" -R "${JETSON_IP}" 2>/dev/null

# Try SSH connection
if [ -n "${JETSON_PASSWORD}" ]; then
    # Use sshpass for password authentication
    if sshpass -p "${JETSON_PASSWORD}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "${JETSON_USER}@${JETSON_IP}" "echo '✅ CONNECTÉ à $JETSON_IP'"; then
        echo "🎯 SSH connection successful with password authentication"
        export JETSON_IP="$JETSON_IP"
        echo "JETSON_IP=$JETSON_IP" > /tmp/jetson_env.sh
        exit 0
    else
        echo "❌ SSH connection failed with password authentication"
        exit 1
    fi
else
    # Try SSH without password (key-based authentication)
    if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "${JETSON_USER}@${JETSON_IP}" "echo '✅ CONNECTÉ à $JETSON_IP'"; then
        echo "🎯 SSH connection successful with key-based authentication"
        export JETSON_IP="$JETSON_IP"
        echo "JETSON_IP=$JETSON_IP" > /tmp/jetson_env.sh
        exit 0
    else
        echo "❌ SSH connection failed"
        echo "Please ensure:"
        echo "  1. SSH is enabled on the Jetson"
        echo "  2. Password is correct (set JETSON_PASSWORD)"
        echo "  3. SSH keys are configured (or sshpass is installed)"
        exit 1
    fi
fi
