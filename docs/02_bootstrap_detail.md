# Jetson Bootstrap Process - Detailed Documentation

## Overview

This document provides detailed information about the Jetson bootstrap process, including each step, configuration options, and troubleshooting tips.

## Bootstrap Process Flow

The bootstrap process consists of several phases executed in sequence:

```
1. SSH Configuration
2. Network Setup
3. Container Runtime Installation
4. k3s Installation
5. GPU Validation
6. GitOps Deployment
```

## Phase 1: SSH Configuration

### Purpose
Configure secure SSH access to the Jetson device.

### Tasks Performed
- Install base packages (sudo, openssh-server, curl, wget, vim, tmux, net-tools, dnsmasq)
- Set hostname to `nanocounter-desktop`
- Configure SSH daemon:
  - Disable root login
  - Enable password authentication
  - Enable public key authentication
- Create SSH directory for user
- Add authorized keys from admin machine
- Enable and start SSH service

### Configuration Options

```yaml
ssh_config:
  user: "nano-counter"  # Default SSH user
  password: "your-password"  # SSH password (optional)
  port: 22  # SSH port
```

### Troubleshooting

**Issue: SSH connection fails**
- Verify SSH is enabled on Jetson
- Check firewall settings
- Ensure correct credentials
- Verify network connectivity

**Issue: Public key authentication fails**
- Ensure `~/.ssh/id_rsa.pub` exists on admin machine
- Verify key is properly copied to Jetson
- Check file permissions on authorized_keys

## Phase 2: Network Setup

### Purpose
Configure network interfaces including WiFi hotspot and Ethernet.

### Tasks Performed
- Install NetworkManager
- Enable WiFi radio
- Create WiFi hotspot connection
- Configure hotspot as access point with WPA2 encryption
- Set hotspot autoconnect priority
- Create Ethernet connection
- Configure Ethernet with static IP
- Configure firewall rules
- Enable IP forwarding

### Configuration Options

```yaml
wifi_hotspot:
  ssid: "JetsonCounter"  # Hotspot SSID
  password: "ChangeMe123"  # Hotspot password
  ip: "192.168.50.1/24"  # Hotspot IP address
  interface: "wlP1p1s0"  # WiFi interface

ethernet_static:
  interface: "enP8p1s0"  # Ethernet interface
  ip: "192.168.1.50/24"  # Static IP
  gateway: "192.168.1.1"  # Gateway
  dns: "8.8.8.8"  # DNS server
```

### Troubleshooting

**Issue: Hotspot not working**
- Verify WiFi interface name
- Check NetworkManager logs: `journalctl -u NetworkManager`
- Ensure no other WiFi connections are active
- Verify hotspot password is correct

**Issue: Ethernet not getting IP**
- Check cable connection
- Verify interface name
- Test with different IP configuration
- Check for IP conflicts

**Issue: No internet access**
- Verify gateway and DNS settings
- Check firewall rules
- Test connectivity: `ping 8.8.8.8`

## Phase 3: Container Runtime Installation

### Purpose
Install and configure container runtime with NVIDIA GPU support.

### Tasks Performed
- Install prerequisites (apt-transport-https, ca-certificates, curl, gnupg, lsb-release)
- Add Docker GPG key and repository
- Install containerd
- Configure containerd
- Install NVIDIA Container Toolkit
- Configure NVIDIA runtime
- Test GPU access with nvidia-smi

### Configuration Options

```yaml
container_runtime:
  type: containerd  # Container runtime type
  nvidia_runtime: true  # Enable NVIDIA GPU support
```

### Troubleshooting

**Issue: Containerd installation fails**
- Check internet connectivity
- Verify repository configuration
- Clean apt cache: `sudo apt clean`
- Try manual installation

**Issue: NVIDIA runtime not working**
- Verify NVIDIA drivers are installed
- Check `nvidia-smi` output
- Verify containerd configuration
- Reboot Jetson

**Issue: GPU not detected**
- Check physical GPU connection
- Verify JetPack installation
- Test with `nvidia-smi`
- Check kernel modules

## Phase 4: k3s Installation

### Purpose
Install and configure k3s Kubernetes cluster.

### Tasks Performed
- Install prerequisites (curl, wget)
- Download k3s installation script
- Install k3s with specific configuration:
  - Disable Traefik
  - Set flannel interface
  - Disable cloud controller
  - Disable local storage
  - Disable metrics server
- Wait for k3s to be ready
- Verify k3s node status
- Install kubectl
- Configure kubectl

### Configuration Options

```yaml
k3s_config:
  version: "v1.28.4+k3s1"  # k3s version
  cgroup_driver: "cgroupfs"  # Cgroup driver
  disable_traefik: true  # Disable Traefik
  flannel_iface: "enP8p1s0"  # Flannel interface
```

### Troubleshooting

**Issue: k3s installation fails**
- Check internet connectivity
- Verify disk space
- Check for conflicting services
- Try different k3s version

**Issue: k3s node not ready**
- Check k3s logs: `journalctl -u k3s`
- Verify container runtime is working
- Check resource availability
- Wait longer for initialization

**Issue: kubectl not working**
- Verify kubeconfig is copied correctly
- Check kubectl version
- Test connection: `kubectl cluster-info`

## Phase 5: GPU Validation

### Purpose
Validate GPU access within Kubernetes pods.

### Tasks Performed
- Create GPU test namespace
- Create GPU test pod manifest
- Apply GPU test pod
- Wait for pod to complete
- Get pod logs
- Verify GPU access
- Clean up resources

### Test Details

The test pod uses `nvidia/cuda:11.0-base` image and runs:
```bash
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
```

### Troubleshooting

**Issue: GPU test pod fails**
- Check pod logs: `kubectl logs -n gpu-test pod/gpu-test`
- Verify NVIDIA device plugin is installed
- Check resource limits
- Test with different CUDA version

**Issue: No GPU detected in pod**
- Verify NVIDIA runtime configuration
- Check containerd configuration
- Test GPU access on host
- Verify k3s configuration

## Phase 6: GitOps Deployment

### Purpose
Deploy GitOps tooling for continuous delivery.

### Tasks Performed
- Install Helm
- Add Argo CD Helm repository
- Install Argo CD
- Wait for Argo CD to be ready
- Get Argo CD admin password
- Create GitOps configuration
- Apply Argo CD application

### Configuration Options

```yaml
gitops:
  type: "argocd"  # GitOps type (argocd or ansible)
  repo_url: "https://github.com/your-org/jetson-apps.git"  # Git repository
  repo_path: "k3s"  # Path to Kubernetes manifests
```

### Troubleshooting

**Issue: Argo CD installation fails**
- Check Helm version
- Verify internet connectivity
- Check disk space
- Try manual installation

**Issue: Argo CD not accessible**
- Verify service is running: `kubectl get pods -n argocd`
- Check NodePort: `kubectl get svc -n argocd`
- Verify firewall rules
- Test connectivity

**Issue: Application sync fails**
- Check Argo CD logs
- Verify repository URL
- Check authentication
- Test Git access

## Running Individual Phases

You can run individual phases by using tags:

```bash
# Run only SSH configuration
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags "ssh"

# Run only network setup
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags "network"

# Run only container runtime installation
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags "container"

# Run only k3s installation
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags "k3s"

# Run only GPU validation
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags "gpu"

# Run only GitOps deployment
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags "gitops"
```

## Logging and Debugging

### Ansible Logging

Enable verbose logging:
```bash
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -vvv
```

### Jetson Logs

Check system logs:
```bash
journalctl -u ssh
journalctl -u NetworkManager
journalctl -u k3s
journalctl -u containerd
```

### Kubernetes Logs

Check k3s logs:
```bash
kubectl get pods --all-namespaces
kubectl logs <pod-name> -n <namespace>
```

## Performance Considerations

- Bootstrap process may take 10-30 minutes
- Jetson Orin Nano has limited resources
- Monitor CPU, memory, and disk usage
- Consider running bootstrap during off-peak hours
- Large package downloads can be slow

## Security Considerations

- Change default passwords after bootstrap
- Rotate SSH keys regularly
- Disable password authentication after initial setup
- Configure firewall rules appropriately
- Monitor for unauthorized access
- Keep software up to date

## Customization

### Custom Playbooks

You can create custom playbooks and include them in the bootstrap process:

1. Create a new playbook in `ansible/playbooks/`
2. Add it to `bootstrap_jetson.yml`:
   ```yaml
   - import_playbook: custom_playbook.yml
   ```
3. Run the bootstrap process

### Custom Configuration

Override default configuration in `ansible/group_vars/all.yml`:

```yaml
# Override hotspot configuration
wifi_hotspot:
  ssid: "MyCustomHotspot"
  password: "StrongPassword123"

# Override k3s configuration
k3s_config:
  version: "v1.27.3+k3s1"
  cgroup_driver: "systemd"
```

## Best Practices

1. **Backup Configuration**: Always backup configuration files before making changes
2. **Test Changes**: Test changes on a staging Jetson before production
3. **Monitor Resources**: Keep an eye on resource usage during bootstrap
4. **Document Changes**: Document any customizations for future reference
5. **Regular Updates**: Keep the framework updated with the latest versions
6. **Security First**: Always prioritize security in your configurations

## Support

For issues and questions, refer to:
- [Troubleshooting Guide](04_troubleshooting.md)
- [Multi-Device Deployment](03_multi_jetson.md)
- [Reset Procedure](05_reset_procedure.md)
