# Reset Procedure Guide

## Overview

This guide provides procedures for resetting Jetson Orin Nano devices to various states, from partial resets to complete factory resets.

## Types of Resets

### 1. Soft Reset

**Purpose**: Restart services without rebooting the system

**Use Case**: When services are misbehaving but system is otherwise stable

**Procedure**:

```bash
# Restart SSH service
sudo systemctl restart ssh

# Restart NetworkManager
sudo systemctl restart NetworkManager

# Restart containerd
sudo systemctl restart containerd

# Restart k3s
sudo systemctl restart k3s
```

### 2. System Reboot

**Purpose**: Restart the entire system

**Use Case**: When multiple services need restart or system is unstable

**Procedure**:

```bash
# Graceful reboot
sudo reboot

# Force reboot if system is unresponsive
sudo reboot -f
```

### 3. Network Configuration Reset

**Purpose**: Reset network configuration to defaults

**Use Case**: When network configuration is corrupted or misconfigured

**Procedure**:

```bash
# Remove all NetworkManager connections
nmcli con show | awk '{print $1}' | grep -v NAME | xargs -I {} nmcli con del {}

# Restart NetworkManager
sudo systemctl restart NetworkManager

# Reconfigure network using Ansible
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/network_setup.yml
```

### 4. Container Runtime Reset

**Purpose**: Reset container runtime and configuration

**Use Case**: When container runtime is corrupted or misconfigured

**Procedure**:

```bash
# Stop containerd
sudo systemctl stop containerd

# Remove containerd
sudo apt remove --purge containerd.io

# Remove configuration files
sudo rm -rf /etc/containerd
sudo rm -rf /var/lib/containerd

# Reinstall containerd
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/install_container_runtime.yml
```

### 5. k3s Reset

**Purpose**: Reset k3s Kubernetes installation

**Use Case**: When k3s is corrupted or misconfigured

**Procedure**:

```bash
# Stop k3s service
sudo systemctl stop k3s

# Uninstall k3s
sudo /usr/local/bin/k3s-uninstall.sh

# Remove k3s data
sudo rm -rf /var/lib/rancher/k3s
sudo rm -rf /etc/rancher/k3s

# Reinstall k3s
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/install_k3s.yml
```

### 6. Application Reset

**Purpose**: Reset all deployed applications

**Use Case**: When applications are misconfigured or need complete reinstallation

**Procedure**:

```bash
# Delete all namespaces except system namespaces
kubectl get ns | grep -v "kube-system\|argocd\|default" | awk '{print $1}' | xargs -I {} kubectl delete ns {}

# Delete all resources in default namespace
kubectl delete all --all
kubectl delete cm --all
kubectl delete secret --all
kubectl delete pvc --all

# Re-deploy applications via Argo CD
argocd app sync jetson-apps
```

### 7. Complete System Reset

**Purpose**: Reset entire system to factory defaults

**Use Case**: When system is severely corrupted or needs complete reinstallation

**Procedure**:

```bash
# WARNING: This will erase all data on the Jetson

# Step 1: Backup important data (if possible)
# - SSH keys
# - Configuration files
# - Custom scripts

# Step 2: Power off Jetson
sudo shutdown -h now

# Step 3: Remove microSD card from Jetson

# Step 4: Flash new JetPack 6.1 image
# - Use Balena Etcher or similar tool
# - Download latest JetPack 6.1 image from NVIDIA
# - Flash to microSD card

# Step 5: Reinsert microSD card

# Step 6: Power on Jetson

# Step 7: Perform initial setup
# - Connect to WiFi
# - Set up user account
# - Enable SSH

# Step 8: Re-run bootstrap process
./scripts/prepare_jetson.sh
```

## Recovery Procedures

### Recovery from Failed Bootstrap

If the bootstrap process fails and leaves the system in an inconsistent state:

```bash
# Step 1: Identify which phase failed
# Check logs in /var/log/ansible/

# Step 2: Reset affected components
# If network failed:
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/network_setup.yml

# If container runtime failed:
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/install_container_runtime.yml

# If k3s failed:
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/install_k3s.yml

# Step 3: Resume bootstrap from failed point
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --start-at-task="<failed-task>"
```

### Recovery from Unbootable System

If the Jetson fails to boot:

```bash
# Step 1: Power off Jetson
# Hold power button for 10 seconds

# Step 2: Remove microSD card

# Step 3: Insert microSD card into another computer

# Step 4: Check filesystem
# On Linux:
sudo fsck /dev/sdX1
# On Windows:
Use chkdsk tool

# Step 5: Reflash if necessary
# Use Balena Etcher to flash new JetPack image

# Step 6: Reinsert and power on
```

### Recovery from SSH Lockout

If you're locked out of SSH access:

```bash
# Option 1: Use serial console
# Connect via USB-to-serial adapter
# Access console at 115200 baud

# Option 2: Use HDMI console
# Connect monitor and keyboard
# Login via local console

# Option 3: Reflash microSD card
# Last resort if other methods fail
```

## Backup and Restore

### Backup Important Data

Before performing any reset, backup important data:

```bash
# Backup SSH keys
mkdir -p ~/backups
cp -r ~/.ssh ~/backups/ssh_backup_$(date +%Y%m%d)

# Backup Ansible configuration
cp -r ansible/group_vars ~/backups/
cp ansible/inventory/jetsons.yml ~/backups/

# Backup k3s configuration
sudo cp /etc/rancher/k3s/k3s.yaml ~/backups/k3s_config.yaml

# Backup custom scripts
cp -r scripts ~/backups/
```

### Restore from Backup

```bash
# Restore SSH keys
cp -r ~/backups/ssh_backup_*/.ssh ~/
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys

# Restore Ansible configuration
cp -r ~/backups/group_vars ansible/
cp ~/backups/jetsons.yml ansible/inventory/

# Restore k3s configuration
sudo cp ~/backups/k3s_config.yaml /etc/rancher/k3s/k3s.yaml

# Restore scripts
cp -r ~/backups/scripts ./
```

## Troubleshooting Reset Issues

### Issue: Reset procedure fails

**Symptoms:**
- Commands fail during reset
- System becomes unstable
- Services fail to restart

**Solutions:**
1. Check error messages carefully
2. Verify prerequisites are met
3. Try more targeted reset
4. Check logs for specific errors
5. Consider complete reflash if issues persist

### Issue: System doesn't boot after reset

**Symptoms:**
- Jetson doesn't power on
- No display output
- System hangs during boot

**Solutions:**
1. Check power supply
2. Verify microSD card is properly inserted
3. Test with different microSD card
4. Try different power adapter
5. Check for hardware issues

### Issue: Network not working after reset

**Symptoms:**
- No network connectivity
- Hotspot not available
- Ethernet not working

**Solutions:**
1. Verify network cables
2. Check WiFi interface
3. Restart NetworkManager
4. Reconfigure network
5. Check for hardware issues

### Issue: Services fail to start after reset

**Symptoms:**
- Services fail to start
- Services crash immediately
- Services hang during startup

**Solutions:**
1. Check service logs
2. Verify dependencies are installed
3. Check configuration files
4. Reinstall affected services
5. Check for resource constraints

## Best Practices for Resets

### 1. Plan Ahead

- Always backup important data before resetting
- Document current configuration
- Test reset procedures on staging device first
- Have recovery plan in place

### 2. Minimize Downtime

- Schedule resets during maintenance windows
- Use soft resets when possible
- Test changes before applying to production
- Monitor system after reset

### 3. Document Changes

- Record what was reset and when
- Document reasons for reset
- Track configuration changes
- Maintain change logs

### 4. Test After Reset

- Verify all services are running
- Test network connectivity
- Check application functionality
- Monitor system resources

### 5. Rollback Plan

- Have rollback procedure ready
- Keep previous configuration backups
- Test rollback procedure
- Know when to escalate to complete reflash

## Automated Reset Procedures

### Automated Network Reset

Create a reset script:

```bash
#!/bin/bash

# Automated network reset script

echo "Starting network reset..."

# Remove all connections
nmcli con show | awk '{print $1}' | grep -v NAME | xargs -I {} nmcli con del {}

# Restart NetworkManager
sudo systemctl restart NetworkManager

# Wait for NetworkManager to stabilize
sleep 10

# Reconfigure network
echo "Network reset completed. Reconfiguring..."
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/network_setup.yml

echo "Network reset and reconfigure completed."
```

### Automated k3s Reset

Create a reset script:

```bash
#!/bin/bash

# Automated k3s reset script

echo "Starting k3s reset..."

# Stop k3s
sudo systemctl stop k3s

# Uninstall k3s
sudo /usr/local/bin/k3s-uninstall.sh

# Remove data
sudo rm -rf /var/lib/rancher/k3s
sudo rm -rf /etc/rancher/k3s

# Reinstall k3s
echo "k3s reset completed. Reinstalling..."
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/install_k3s.yml

echo "k3s reset and reinstall completed."
```

## Recovery ISO/USB

For severe system issues, create a recovery USB:

1. Download JetPack recovery image from NVIDIA
2. Flash to USB drive using Balena Etcher
3. Boot Jetson from USB
4. Use recovery tools to:
   - Reflash microSD card
   - Repair filesystem
   - Recover data
   - Reinstall system

## Support and Resources

- [NVIDIA Jetson Recovery Documentation](https://developer.nvidia.com/embedded/learn/jetson-recovery-mode)
- [Jetson Forums](https://forums.developer.nvidia.com/c/jetson)
- [Ansible Documentation](https://docs.ansible.com/)
- [k3s Documentation](https://docs.k3s.io/)

For additional information, refer to:
- [Quick Start Guide](01_quickstart.md)
- [Bootstrap Detail](02_bootstrap_detail.md)
- [Multi-Device Deployment](03_multi_jetson.md)
- [Troubleshooting Guide](04_troubleshooting.md)
