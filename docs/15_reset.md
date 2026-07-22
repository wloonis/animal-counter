# 15 — Reset Procedure

## Overview

This guide provides procedures for resetting a Jetson Orin Nano running the
animal-counter to various states, from partial resets to a complete factory
reflash. The stack on the device is: **K3s (single-node, using Docker as the
container runtime)** + the `countingapp` DaemonSet, deployed with **Ansible**
(there is **no GitOps/Argo CD** layer — apps are applied with `kubectl apply`
from rendered `k3s/templates/*.j2`).

> The Ansible playbooks and scripts referenced below are the ones that
> actually exist in this repo (under `ansible/playbooks/` and `scripts/`).
> Deployment is driven by `scripts/prepare_jetson.sh`, which runs
> `ansible/playbooks/app/deploy_app.yml` → `deploy_countingapp.yml`
> (renders the `k3s/templates/*.j2` and `kubectl apply`s them).

## Types of Resets

### 1. Soft Reset

**Purpose**: Restart services without rebooting the system.

**Use Case**: When a service is misbehaving but the system is otherwise stable.

**Procedure**:

```bash
# Restart SSH
sudo systemctl restart ssh

# Restart NetworkManager (WiFi hotspot / Ethernet)
sudo systemctl restart NetworkManager

# Restart Docker (the K3s container runtime)
sudo systemctl restart docker

# Restart K3s
sudo systemctl restart k3s
```

### 2. System Reboot

**Purpose**: Restart the entire system.

**Use Case**: When multiple services need a restart or the system is unstable.

**Procedure**:

```bash
# Graceful reboot
sudo reboot

# Force reboot if the system is unresponsive
sudo reboot -f
```

### 3. Network Configuration Reset

**Purpose**: Reset the network configuration (WiFi hotspot / Ethernet) to defaults.

**Use Case**: When the network configuration is corrupted or misconfigured.

**Procedure**:

```bash
# Remove all NetworkManager connections
nmcli con show | awk 'NR>1 {print $1}' | xargs -I {} nmcli con del {}

# Restart NetworkManager
sudo systemctl restart NetworkManager

# Reconfigure the network with the project playbooks
#   - SSH + base packages:  ansible/playbooks/system/network_ssh.yml
#   - WiFi hotspot:         ansible/playbooks/system/hotspot_setup.yml
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/network_ssh.yml
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/hotspot_setup.yml
```

### 4. K3s Reset

**Purpose**: Reset the K3s installation (and its Docker runtime).

**Use Case**: When K3s is corrupted or misconfigured.

**Procedure**:

```bash
# Stop K3s
sudo systemctl stop k3s

# Uninstall K3s (K3s-provided uninstaller)
sudo /usr/local/bin/k3s-uninstall.sh

# Remove K3s data
sudo rm -rf /var/lib/rancher/k3s
sudo rm -rf /etc/rancher/k3s

# Reinstall K3s (with Docker) using the project playbook
ansible-playbook -i ansible/inventory/jetsons.yml \
  ansible/playbooks/system/install_k3s_with_docker_tasks.yml
```

> The container runtime is **Docker** (configured by
> `install_k3s_with_docker_tasks.yml`, with its data-root on the external
> disk). If Docker itself is wedged, `sudo systemctl restart docker` is
> usually enough; a full Docker purge/reinstall is done as part of the K3s
> playbook above.

### 5. Application Reset

**Purpose**: Reset the deployed `countingapp` (and its K8s resources) and
redeploy it.

**Use Case**: When the application is misconfigured or needs a clean
re-deployment.

**Procedure**:

There is **no Argo CD / GitOps sync** in this project — applications are
applied from the rendered `k3s/templates/*.j2`. To reset the app, delete its
K8s resources and re-apply the templates:

```bash
# Delete the countingapp resources in its namespace (countingapp-dev)
kubectl delete all -n countingapp-dev -l app=countingapp
kubectl delete cm -n countingapp-dev --all

# Re-deploy: re-render and apply all templates
# (either via the one-shot wrapper or directly with the playbook)
bash scripts/prepare_jetson.sh
#   — or —
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/app/deploy_countingapp.yml
```

For a quick app-only restart without a full redeploy, scale the DaemonSet
down and back up:

```bash
kubectl scale daemonset countingapp -n countingapp-dev --replicas=0
# wait for the pod to terminate, then:
kubectl scale daemonset countingapp -n countingapp-dev --replicas=1
```

> If `app/requirements.txt` (or another build-time dependency) changed, the
> `countingapp:local` image must be **rebuilt** on the Jetson before
> redeploying — the deploy only rsyncs code, it does not rebuild the image:
> ```bash
> cd ansible/playbooks/app
> ansible-playbook -i ../../inventory/jetsons.yml deploy_app.yml --tags build
> ```

### 6. Complete System Reset

**Purpose**: Reset the entire device to factory defaults (re-flash JetPack).

**Use Case**: When the system is severely corrupted or needs a complete
reinstallation.

**Procedure**:

```bash
# WARNING: This will erase all data on the Jetson.

# Step 1: Backup important data (if possible) — SSH keys, config files, custom scripts
# Step 2: Power off the Jetson
sudo shutdown -h now
# Step 3: Remove the microSD card from the Jetson
# Step 4: Flash a new JetPack image to the microSD card
#   - Use Balena Etcher or similar tool
#   - Download the latest JetPack image from NVIDIA
#   - Flash to the microSD card
# Step 5: Reinsert the microSD card
# Step 6: Power on the Jetson
# Step 7: Perform initial setup — connect to WiFi, set up the user account, enable SSH
# Step 8: Re-run the project bootstrap from your workstation
./scripts/prepare_jetson.sh
```

## Recovery Procedures

### Recovery from a failed bootstrap

If `scripts/prepare_jetson.sh` (which drives the Ansible deployment) fails and
leaves the system in an inconsistent state:

```bash
# Step 1: Identify which phase failed (check the Ansible output / logs)
# Step 2: Reset only the affected component, then resume:
#   - Network failed:
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/network_ssh.yml
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/hotspot_setup.yml
#   - K3s failed:
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/install_k3s_with_docker_tasks.yml
#   - App deployment failed:
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/app/deploy_countingapp.yml
# Step 3: Re-run the one-shot wrapper to converge everything
bash scripts/prepare_jetson.sh
```

### Recovery from an unbootable system

If the Jetson fails to boot:

```bash
# Step 1: Power off the Jetson (hold the power button for 10 seconds)
# Step 2: Remove the microSD card
# Step 3: Insert the microSD card into another computer
# Step 4: Check the filesystem
#   On Linux:   sudo fsck /dev/sdX1
#   On Windows: use the chkdsk tool
# Step 5: Reflash if necessary (Balena Etcher → new JetPack image)
# Step 6: Reinsert the microSD card and power on
```

### Recovery from an SSH lockout

If you are locked out of SSH access:

```bash
# Option 1: serial console — USB-to-serial adapter, 115200 baud
# Option 2: HDMI console — connect a monitor and keyboard, log in locally
# Option 3: reflash the microSD card (last resort)
```

## Backup and Restore

### Backup important data

Before any reset, back up important data:

```bash
mkdir -p ~/backups

# SSH keys
cp -r ~/.ssh ~/backups/ssh_backup_$(date +%Y%m%d)

# Ansible configuration
cp -r ansible/group_vars ~/backups/
cp ansible/inventory/jetsons.yml ~/backups/

# K3s kubeconfig
sudo cp /etc/rancher/k3s/k3s.yaml ~/backups/k3s_config.yaml

# Project scripts
cp -r scripts ~/backups/
```

### Restore from backup

```bash
# SSH keys
cp -r ~/backups/ssh_backup_*/.ssh ~/
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys

# Ansible configuration
cp -r ~/backups/group_vars ansible/
cp ~/backups/jetsons.yml ansible/inventory/

# K3s kubeconfig
sudo cp ~/backups/k3s_config.yaml /etc/rancher/k3s/k3s.yaml

# Scripts
cp -r ~/backups/scripts ./
```

## Troubleshooting Reset Issues

### Issue: reset procedure fails

**Symptoms**: commands fail during the reset; the system becomes unstable;
services fail to restart.

**Solutions**:
1. Read the error messages carefully.
2. Verify prerequisites are met (disk mounted, network reachable).
3. Try a more targeted reset (soft → K3s → complete).
4. Check service logs (`journalctl -u <service>`).
5. Escalate to a complete reflash if issues persist.

### Issue: the system doesn't boot after a reset

**Symptoms**: the Jetson doesn't power on; no display output; hangs during boot.

**Solutions**:
1. Check the power supply.
2. Verify the microSD card is properly inserted.
3. Test with a different microSD card.
4. Try a different power adapter.
5. Check for hardware issues.

### Issue: network not working after a reset

**Symptoms**: no connectivity; hotspot unavailable; Ethernet not working.

**Solutions**:
1. Verify network cables.
2. Check the WiFi interface.
3. Restart NetworkManager.
4. Re-run `network_ssh.yml` and `hotspot_setup.yml`.
5. Check for hardware issues.

### Issue: services fail to start after a reset

**Symptoms**: services fail to start, crash immediately, or hang during startup.

**Solutions**:
1. Check service logs (`journalctl -u k3s`, `journalctl -u docker`).
2. Verify dependencies are installed.
3. Check configuration files.
4. Reinstall the affected component via its playbook.
5. Check for resource constraints.

## Best Practices for Resets

### 1. Plan ahead
- Always back up important data before resetting.
- Document the current configuration.
- Test reset procedures on a staging device first.
- Have a recovery plan in place.

### 2. Minimize downtime
- Schedule resets during maintenance windows.
- Use soft resets when possible.
- Test changes before applying to production.
- Monitor the system after the reset.

### 3. Document changes
- Record what was reset and when.
- Document the reasons.
- Track configuration changes.
- Maintain change logs.

### 4. Test after reset
- Verify all services are running.
- Test network connectivity.
- Check application functionality.
- Monitor system resources.

### 5. Rollback plan
- Have a rollback procedure ready.
- Keep previous configuration backups.
- Test the rollback procedure.
- Know when to escalate to a complete reflash.

## Automated Reset Procedures

### Automated network reset

```bash
#!/bin/bash
set -e
echo "Starting network reset..."

# Remove all connections
nmcli con show | awk 'NR>1 {print $1}' | xargs -I {} nmcli con del {}

# Restart NetworkManager
sudo systemctl restart NetworkManager
sleep 10

# Reconfigure via the project playbooks
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/network_ssh.yml
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/hotspot_setup.yml

echo "Network reset and reconfigure completed."
```

### Automated K3s reset

```bash
#!/bin/bash
set -e
echo "Starting K3s reset..."

# Stop and uninstall K3s
sudo systemctl stop k3s
sudo /usr/local/bin/k3s-uninstall.sh

# Remove data
sudo rm -rf /var/lib/rancher/k3s /etc/rancher/k3s

# Reinstall K3s (with Docker) via the project playbook
ansible-playbook -i ansible/inventory/jetsons.yml \
  ansible/playbooks/system/install_k3s_with_docker_tasks.yml

echo "K3s reset and reinstall completed."
```

## Recovery ISO / USB

For severe system issues, create a recovery USB:

1. Download the JetPack recovery image from NVIDIA.
2. Flash it to a USB drive using Balena Etcher.
3. Boot the Jetson from USB.
4. Use the recovery tools to reflash the microSD card, repair the filesystem,
   recover data, or reinstall the system.

## Support and Resources

- [NVIDIA Jetson Recovery Documentation](https://developer.nvidia.com/embedded/learn/jetson-recovery-mode)
- [Jetson Forums](https://forums.developer.nvidia.com/c/jetson)
- [Ansible Documentation](https://docs.ansible.com/)
- [K3s Documentation](https://docs.k3s.io/)

For additional information, refer to:
- [Quick Start Guide](01_quickstart.md)
- [Jetson Setup](02_setup.md)
- [Deployment](03_deployment.md)
- [Configuration](04_configuration.md)
- [Troubleshooting Guide](14_troubleshooting.md)