#!/bin/bash

# Ansible Installation Script
# Installs Ansible on Ubuntu/Debian systems

set -e

echo "🔧 Starting Ansible installation..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Please run this script as root or with sudo"
    echo "   Example: sudo bash $0"
    exit 1
fi

# Check Ubuntu/Debian
if ! grep -q "Ubuntu\|Debian" /etc/os-release 2>/dev/null; then
    echo "❌ This script is designed for Ubuntu/Debian systems only"
    exit 1
fi

echo "📋 Checking system requirements..."

# Install required packages
apt update
apt install -y software-properties-common

# Add Ansible repository
echo "📦 Adding Ansible repository..."
apt-add-repository --yes --update ppa:ansible/ansible

# Install Ansible
echo "📥 Installing Ansible..."
apt install -y ansible

# Install additional useful packages
echo "📥 Installing additional packages..."
apt install -y sshpass nmap curl wget git

# Verify installation
echo "✅ Verifying Ansible installation..."
if command -v ansible &> /dev/null; then
    echo "✅ Ansible installed successfully!"
    echo ""
    echo "📊 Ansible version:"
    ansible --version
    echo ""
    echo "🎯 Installation completed!"
    echo ""
    echo "Next steps:"
    echo "1. Configure your .env.local file with Jetson credentials"
    echo "2. Run ./scripts/prepare_jetson.sh to bootstrap your Jetson"
    exit 0
else
    echo "❌ Ansible installation failed"
    exit 1
fi
