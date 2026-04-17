# Multi-Device Deployment Guide

## Overview

This guide explains how to deploy and manage multiple Jetson Orin Nano devices using the automation framework.

## Multi-Device Architecture

The framework supports deploying multiple Jetson devices from a single administration machine. Each Jetson can be configured with unique settings while sharing common configurations.

```
Admin Machine
    |
    ├── Jetson 1 (192.168.1.50)
    ├── Jetson 2 (192.168.1.51)
    └── Jetson 3 (192.168.1.52)
```

## Prerequisites

- Multiple Jetson Orin Nano devices
- Each Jetson flashed with JetPack 6.1
- Network connectivity between admin machine and all Jetsons
- Unique IP addresses for each Jetson

## Step 1: Inventory Configuration

The framework uses Ansible inventory to manage multiple devices. The default inventory file supports environment variables:

```yaml
# ansible/inventory/jetsons.yml
all:
  hosts:
    jetson-01:
      ansible_host: "{{ lookup('env', 'JETSON_IP') }}"
      ansible_user: "{{ lookup('env', 'JETSON_USER') | default('nano-counter') }}"
      ansible_ssh_pass: "{{ lookup('env', 'JETSON_PASSWORD') | default(omit) }}"
```

### Multiple Device Inventory

For multiple devices, create a static inventory:

```yaml
# ansible/inventory/jetsons.yml
all:
  children:
    jetsons:
      hosts:
        jetson-01:
          ansible_host: 192.168.1.50
          ansible_user: nano-counter
          ansible_ssh_pass: password1
        jetson-02:
          ansible_host: 192.168.1.51
          ansible_user: nano-counter
          ansible_ssh_pass: password2
        jetson-03:
          ansible_host: 192.168.1.52
          ansible_user: nano-counter
          ansible_ssh_pass: password3
```

## Step 2: Group Variables

Use group variables to configure different settings for different devices:

```yaml
# ansible/group_vars/all.yml
jetson_hostname: nanocounter-desktop

wifi_hotspot:
  ssid: "JetsonCounter"
  password: "ChangeMe123"
  ip: "192.168.50.1/24"
  interface: "wlP1p1s0"

ethernet_static:
  interface: "enP8p1s0"
  ip: "192.168.1.50/24"
  gateway: "192.168.1.1"
  dns: "8.8.8.8"
```

### Device-Specific Configuration

Create device-specific variable files:

```yaml
# ansible/group_vars/jetson-01.yml
ethernet_static:
  ip: "192.168.1.50/24"

wifi_hotspot:
  ssid: "Jetson-01-Hotspot"
  ip: "192.168.50.1/24"
```

```yaml
# ansible/group_vars/jetson-02.yml
ethernet_static:
  ip: "192.168.1.51/24"

wifi_hotspot:
  ssid: "Jetson-02-Hotspot"
  ip: "192.168.51.1/24"
```

## Step 3: Discovery and Preparation

### Sequential Preparation

Prepare devices one at a time:

```bash
# Prepare Jetson 1
export JETSON_IP=192.168.1.50
export JETSON_PASSWORD=password1
./scripts/prepare_jetson.sh

# Prepare Jetson 2
export JETSON_IP=192.168.1.51
export JETSON_PASSWORD=password2
./scripts/prepare_jetson.sh

# Prepare Jetson 3
export JETSON_IP=192.168.1.52
export JETSON_PASSWORD=password3
./scripts/prepare_jetson.sh
```

### Parallel Preparation

Use Ansible to prepare multiple devices in parallel:

```bash
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -l jetsons
```

## Step 4: Managing Multiple Devices

### Run Playbook on Specific Devices

```bash
# Run on all jetsons
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -l jetsons

# Run on specific device
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -l jetson-01

# Run on multiple specific devices
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -l "jetson-01,jetson-02"
```

### Check Status of All Devices

```bash
# Check k3s status on all devices
ansible -i ansible/inventory/jetsons.yml jetsons -a "kubectl get nodes"

# Check GPU status on all devices
ansible -i ansible/inventory/jetsons.yml jetsons -a "nvidia-smi"

# Check system resources
ansible -i ansible/inventory/jetsons.yml jetsons -a "free -h"
```

### Update All Devices

```bash
# Update all devices
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -l jetsons
```

## Step 5: GitOps for Multi-Device

### Centralized Git Repository

Create a centralized Git repository for all Jetson configurations:

```
jetson-apps/
├── k3s/
│   ├── common/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── configmap.yaml
│   ├── jetson-01/
│   │   └── deployment.yaml
│   ├── jetson-02/
│   │   └── deployment.yaml
│   └── jetson-03/
│       └── deployment.yaml
└── argocd/
    └── applications.yaml
```

### Argo CD Multi-Device Setup

Configure Argo CD to manage multiple Jetson devices:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: jetson-01-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/jetson-apps.git
    targetRevision: main
    path: k3s/jetson-01
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## Step 6: Monitoring Multiple Devices

### Centralized Logging

Set up centralized logging for all devices:

```bash
# Install Fluent Bit on each Jetson
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/install_fluentbit.yml -l jetsons

# Configure Fluent Bit to send logs to central server
```

### Monitoring with Prometheus

Deploy Prometheus to monitor all Jetson devices:

```bash
# Install Prometheus Operator
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/bundle.yaml

# Create ServiceMonitor for k3s
kubectl apply -f monitoring/service-monitor.yaml

# Access Prometheus dashboard
kubectl port-forward svc/prometheus-operated 9090:9090
```

### Grafana Dashboards

Create Grafana dashboards for Jetson monitoring:

```bash
# Install Grafana
helm install grafana grafana/grafana

# Access Grafana
kubectl port-forward svc/grafana 3000:80

# Import Jetson dashboard
```

## Step 7: Scaling Operations

### Batch Operations

```bash
# Update all devices with new configuration
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/update_config.yml -l jetsons

# Restart services on all devices
ansible -i ansible/inventory/jetsons.yml jetsons -a "sudo systemctl restart k3s"

# Check disk space on all devices
ansible -i ansible/inventory/jetsons.yml jetsons -a "df -h"
```

### Rolling Updates

```bash
# Update devices one by one
for device in jetson-01 jetson-02 jetson-03; do
    ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/update_apps.yml -l $device
    sleep 60  # Wait between updates
    echo "Updated $device"
done
```

## Best Practices for Multi-Device Deployment

### 1. Unique Identifiers

- Assign unique hostnames to each device
- Use unique hotspot SSIDs
- Configure unique static IPs

### 2. Consistent Configuration

- Use group variables for common settings
- Override only device-specific settings
- Maintain consistent security policies

### 3. Monitoring and Alerting

- Set up centralized monitoring
- Configure alerts for critical issues
- Monitor resource usage across devices

### 4. Backup and Recovery

- Regularly backup configurations
- Test recovery procedures
- Maintain backup of critical data

### 5. Documentation

- Document each device's configuration
- Track hardware revisions
- Record deployment dates

## Troubleshooting Multi-Device Issues

### Issue: Multiple Devices with Same IP

**Symptoms:**
- Devices cannot communicate
- Network conflicts
- SSH connections fail

**Solution:**
- Verify each device has unique IP
- Check DHCP configuration
- Use static IPs for all devices

### Issue: Discovery Fails for Multiple Devices

**Symptoms:**
- Only one device is discovered
- Discovery script times out

**Solution:**
- Run discovery sequentially
- Use static inventory instead of discovery
- Increase discovery timeout

### Issue: Playbook Fails on Some Devices

**Symptoms:**
- Some devices succeed, others fail
- Inconsistent results

**Solution:**
- Run playbook on individual devices
- Check device-specific logs
- Verify hardware compatibility

### Issue: Resource Contention

**Symptoms:**
- Slow performance
- High CPU/memory usage
- Timeouts during operations

**Solution:**
- Limit parallel operations
- Monitor resource usage
- Schedule operations during off-peak hours

## Performance Optimization

### Parallel Execution

```bash
# Use multiple forks for parallel execution
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -l jetsons -f 3
```

### Resource Limits

Configure resource limits in k3s:

```yaml
k3s_config:
  extra_args:
    --kubelet-arg: eviction-hard=memory.available<500Mi,nodefs.available<10%
    --kubelet-arg: eviction-minimum-reclaim=memory.available=1Gi,nodefs.available=5%
```

### Caching

Cache Docker images on admin machine and push to devices:

```bash
# Build and tag images on admin machine
docker build -t my-app:latest .
docker save my-app:latest > my-app.tar

# Copy to Jetson
scp my-app.tar nano-counter@192.168.1.50:/tmp/

# Load on Jetson
ssh nano-counter@192.168.1.50 "docker load -i /tmp/my-app.tar"
```

## Security Considerations

### SSH Key Management

- Use unique SSH keys for each device
- Rotate keys regularly
- Store keys securely

### Network Security

- Configure firewalls appropriately
- Use VLANs for device separation
- Monitor network traffic

### Access Control

- Restrict admin machine access
- Use VPN for remote management
- Implement multi-factor authentication

## Support and Maintenance

### Regular Maintenance Tasks

```bash
# Update all devices
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/update_system.yml -l jetsons

# Clean up unused resources
ansible -i ansible/inventory/jetsons.yml jetsons -a "kubectl delete pods --field-selector=status.phase=Succeeded --all-namespaces"

# Monitor disk space
ansible -i ansible/inventory/jetsons.yml jetsons -a "df -h | grep -v tmpfs"
```

### Upgrade Procedures

1. Test upgrade on staging device
2. Backup all configurations
3. Upgrade devices in batches
4. Monitor for issues
5. Rollback if necessary

## Conclusion

The multi-device deployment capabilities of the Jetson automation framework enable efficient management of multiple Jetson devices. By leveraging Ansible's inventory and variable features, you can maintain consistent configurations across devices while accommodating device-specific requirements.

For additional information, refer to:
- [Troubleshooting Guide](04_troubleshooting.md)
- [Bootstrap Detail](02_bootstrap_detail.md)
- [Reset Procedure](05_reset_procedure.md)
