# PRD: Splash Screen LXDE Protection

## Overview
Empêcher l'accès au bureau LXDE du Jetson Nano Orin tant que l'application de comptage (countingapp) n'est pas démarrée sous k3s. Afficher l'image splash.png pendant le chargement.

## Context
Au démarrage du Jetson Nano Orin, l'application de comptage ne démarre que lorsque le service countingapp est en état 'running' sous k3s. Pendant ce temps, un utilisateur peut accéder au bureau LXDE du Jetson Orin. Il faut donc empêcher cet accès pendant le chargement de l'application.

## Tasks

- [x] Task 1: Create Ansible playbook configure_splash_screen.yml
- [x] Task 1.1: Add task to copy splash.png to Jetson (/opt/splash-screen/)
- [x] Task 1.2: Create splash guard monitoring script that checks k3s countingapp status
- [x] Task 1.3: Create systemd service for splash guard
- [x] Task 1.4: Configure LightDM to show splash image during lockdown
- [x] Task 1.5: Add task to enable and start the splash guard service
- [x] Task 2: Update prepare_jetson.sh to call the new playbook

## Files to Change

- [x] ansible/playbooks/system/configure_splash_screen.yml (new file)
- [x] scripts/prepare_jetson.sh (modified to add Step 6)

## Acceptance Criteria

- [x] splash.png is displayed during countingapp startup
- [x] LXDE access is blocked until countingapp is running in k3s
- [x] Automatic unlock when countingapp pod reaches Running state
- [x] All configuration done via Ansible playbook
- [x] Integrated into prepare_jetson.sh workflow

## Technical Details

### Service Monitoring
- The splash guard script checks: `k3s kubectl get pod -n countingapp-dev -l app=countingapp --no-headers | grep Running`
- Polling interval: 10 seconds

### LightDM Configuration
- When locked: Creates `/etc/lightdm/lightdm.conf.d/60-splash-lock.conf` with splash.png as greeter background
- When unlocked: Removes the conf file and restarts LightDM

### Files Created
- `/opt/splash-screen/splash.png` - Copied from local
- `/usr/local/bin/countingapp-splash-guard.sh` - Monitoring script
- `/etc/systemd/system/countingapp-splash-guard.service` - Systemd service
- `/var/run/countingapp-splash.lock` - Lock file for state
- `/var/log/countingapp-splash.log` - Log file

### Service Commands
```bash
# Check status
systemctl status countingapp-splash-guard

# View logs
journalctl -u countingapp-splash-guard -f

# Manual lock
touch /var/run/countingapp-splash.lock
systemctl restart lightdm

# Manual unlock
rm -f /var/run/countingapp-splash.lock
systemctl restart lightdm
```