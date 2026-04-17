# Jetson Automation Framework - Quick Start Guide

## Overview

This guide provides a step-by-step process for technicians to prepare and deploy a Jetson Orin Nano device with the automation framework.

## Prerequisites

### Hardware
- Jetson Orin Nano Developer Kit
- JetPack 6.1 SD card image
- MicroSD card (32GB or larger)
- Power supply
- Ethernet cable (optional)
- WiFi network access

### Software
- PC with Balena Etcher or similar SD card flashing tool
- Ubuntu 22.04 or WSL2 on Windows
- Git
- Ansible (2.10+)
- nmap (for device discovery)

## Step 1: Flash JetPack 6.1

1. Download JetPack 6.1 image from NVIDIA website
2. Flash the image to microSD card using Balena Etcher
3. Insert microSD card into Jetson
4. Power on the Jetson

## Step 2: Initial Setup

1. Connect Jetson to your WiFi network (via GUI or CLI)
2. Note the IP address assigned to the Jetson
3. Ensure SSH is enabled:
   ```bash
   sudo systemctl enable ssh
   sudo systemctl start ssh
   ```

## Step 3: Install Prerequisites

Install Ansible and required tools:

```bash
# Install Ansible and dependencies
sudo bash scripts/install_ansible.sh
```

This will install:
- Ansible (latest version)
- sshpass (for SSH password authentication)
- nmap (for device discovery)
- curl, wget, git (utility tools)

## Step 4: Clone Repository

```bash
git clone https://github.com/your-org/jetson-automation-framework.git
cd jetson-automation-framework
```

## Step 4: Configure Environment

Copy the example environment file:
```bash
cp .env.example .env.local
```

Edit `.env.local` with your Jetson credentials:
```bash
JETSON_USER="nano-counter"
JETSON_PASSWORD="your-password"
JETSON_HOTSPOT_SSID="JetsonCounter"
JETSON_HOTSPOT_PASSWORD="ChangeMe123"
```

## Step 5: Prepare Jetson

Run the one-shot preparation script:
```bash
./scripts/prepare_jetson.sh
```

This script will:
1. Discover the Jetson on your network
2. Test SSH connectivity
3. Run the complete bootstrap process

## Step 6: Monitor Progress

The script will display progress and may take 10-30 minutes depending on:
- Network speed
- Jetson performance
- Package download times

## Step 7: Connect to Jetson

After successful completion:
1. Connect to the Jetson hotspot: `JetsonCounter`
2. SSH into the Jetson:
   ```bash
   ssh nano-counter@<jetson-ip>
   ```
3. Verify k3s is running:
   ```bash
   kubectl get nodes
   ```

## Step 8: Access Argo CD

Access the Argo CD dashboard:
```bash
https://<jetson-ip>:30080
```

Username: `admin`
Password: Displayed at the end of the bootstrap process

## Troubleshooting

See [Troubleshooting Guide](04_troubleshooting.md) for common issues.

## Next Steps

- [Multi-Device Deployment](03_multi_jetson.md)
- [Application Deployment](02_bootstrap_detail.md)
- [Reset Procedure](05_reset_procedure.md)
