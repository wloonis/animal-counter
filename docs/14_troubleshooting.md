# 14 — Troubleshooting

## Overview

This guide provides solutions to common issues encountered during Jetson automation framework deployment and operation.

## Common Issues and Solutions

### SSH Connection Problems

#### Issue: Cannot connect to Jetson via SSH

**Symptoms:**
- Connection timed out
- Connection refused
- Authentication failed

**Solutions:**
1. Verify Jetson is powered on and connected to network
2. Check network cable or WiFi connection
3. Verify SSH is enabled on Jetson:
   ```bash
   sudo systemctl status ssh
   ```
4. Check firewall settings:
   ```bash
   sudo ufw status
   sudo iptables -L
   ```
5. Verify correct IP address and credentials
6. Test with ping:
   ```bash
   ping <jetson-ip>
   ```

#### Issue: SSH key authentication fails

**Symptoms:**
- Permission denied (publickey)
- Key not accepted

**Solutions:**
1. Verify SSH key exists on admin machine:
   ```bash
   ls ~/.ssh/id_rsa.pub
   ```
2. Check authorized_keys file on Jetson:
   ```bash
   cat ~/.ssh/authorized_keys
   ```
3. Verify file permissions:
   ```bash
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   ```
4. Re-add SSH key:
   ```bash
   ssh-copy-id nano-counter@<jetson-ip>
   ```

### Network Configuration Issues

#### Issue: Hotspot not working

**Symptoms:**
- Hotspot not visible
- Cannot connect to hotspot
- Hotspot disconnects immediately

**Solutions:**
1. Verify WiFi interface name:
   ```bash
   nmcli device status
   ```
2. Check NetworkManager logs:
   ```bash
   journalctl -u NetworkManager -f
   ```
3. Verify hotspot configuration:
   ```bash
   nmcli con show <hotspot-name>
   ```
4. Restart NetworkManager:
   ```bash
   sudo systemctl restart NetworkManager
   ```
5. Recreate hotspot connection:
   ```bash
   sudo nmcli con delete <hotspot-name>
   # Then re-run network_setup.yml playbook
   ```

#### Issue: Ethernet not getting IP

**Symptoms:**
- No network connectivity via Ethernet
- IP address not assigned

**Solutions:**
1. Verify cable connection
2. Check interface status:
   ```bash
   ip link show
   nmcli device status
   ```
3. Test with DHCP first:
   ```bash
   sudo nmcli con mod <interface> ipv4.method auto
   sudo nmcli con up <interface>
   ```
4. Verify static IP configuration:
   ```bash
   nmcli con show <interface>
   ```
5. Check for IP conflicts
6. Test with different IP address

#### Issue: No internet access

**Symptoms:**
- Can ping Jetson but not external hosts
- No internet from Jetson

**Solutions:**
1. Verify gateway and DNS settings:
   ```bash
   nmcli con show <interface>
   ```
2. Test connectivity:
   ```bash
   ping 8.8.8.8
   ping google.com
   ```
3. Check routing table:
   ```bash
   ip route
   ```
4. Verify firewall rules:
   ```bash
   sudo iptables -L
   ```
5. Test with different DNS:
   ```bash
   echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
   ```

### Container Runtime Issues

#### Issue: Containerd installation fails

**Symptoms:**
- Package not found
- Dependency errors
- Installation hangs

**Solutions:**
1. Update package lists:
   ```bash
   sudo apt update
   ```
2. Clean apt cache:
   ```bash
   sudo apt clean
   sudo apt autoremove
   ```
3. Verify repository configuration:
   ```bash
   cat /etc/apt/sources.list.d/docker.list
   ```
4. Try manual installation:
   ```bash
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt update
   sudo apt install containerd.io
   ```

#### Issue: NVIDIA runtime not working

**Symptoms:**
- GPU not detected in containers
- NVIDIA runtime errors

**Solutions:**
1. Verify NVIDIA drivers:
   ```bash
   nvidia-smi
   ```
2. Check NVIDIA Container Toolkit installation:
   ```bash
   dpkg -l | grep nvidia-container
   ```
3. Verify containerd configuration:
   ```bash
   cat /etc/containerd/config.toml | grep nvidia
   ```
4. Reconfigure NVIDIA runtime:
   ```bash
   sudo nvidia-ctk runtime configure --runtime=containerd
   sudo systemctl restart containerd
   ```
5. Test with simple container:
   ```bash
   sudo ctr run --rm --gpus=all docker.io/library/nvidia/cuda:11.0-base sh nvidia-smi
   ```

#### Issue: GPU not detected

**Symptoms:**
- nvidia-smi shows no devices
- GPU not available in containers

**Solutions:**
1. Check physical connections
2. Verify JetPack installation
3. Check kernel modules:
   ```bash
   lsmod | grep nvidia
   ```
4. Reinstall NVIDIA drivers:
   ```bash
   sudo apt install --reinstall nvidia-driver-525
   ```
5. Reboot Jetson
6. Check BIOS/UEFI settings (if applicable)

### k3s Installation Issues

#### Issue: k3s installation fails

**Symptoms:**
- Download fails
- Installation script errors
- Service not starting

**Solutions:**
1. Verify internet connectivity
2. Check disk space:
   ```bash
   df -h
   ```
3. Try different k3s version:
   ```bash
   export INSTALL_K3S_VERSION=v1.27.3+k3s1
   ```
4. Manual installation:
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```
5. Check logs:
   ```bash
   journalctl -u k3s -f
   ```

#### Issue: k3s node not ready

**Symptoms:**
- Node status shows NotReady
- kubectl get nodes shows NotReady

**Solutions:**
1. Check k3s logs:
   ```bash
   journalctl -u k3s -f
   ```
2. Verify container runtime:
   ```bash
   ctr version
   ```
3. Check resource availability:
   ```bash
   free -h
   df -h
   ```
4. Restart k3s:
   ```bash
   sudo systemctl restart k3s
   ```
5. Check for errors:
   ```bash
   kubectl describe nodes
   ```

#### Issue: kubectl not working

**Symptoms:**
- kubectl commands fail
- Connection refused
- Authentication errors

**Solutions:**
1. Verify kubeconfig:
   ```bash
   cat ~/.kube/config
   ```
2. Check kubectl version:
   ```bash
   kubectl version --client
   ```
3. Test connection:
   ```bash
   kubectl cluster-info
   ```
4. Verify k3s is running:
   ```bash
   sudo systemctl status k3s
   ```
5. Reconfigure kubectl:
   ```bash
   sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
   sudo chown $USER ~/.kube/config
   ```

### GPU Validation Issues

#### Issue: GPU test pod fails

**Symptoms:**
- Pod stuck in Pending or CrashLoopBackOff
- Pod fails to start

**Solutions:**
1. Check pod status:
   ```bash
   kubectl get pods -n gpu-test
   ```
2. View pod logs:
   ```bash
   kubectl logs -n gpu-test pod/gpu-test
   ```
3. Check pod events:
   ```bash
   kubectl describe pod -n gpu-test pod/gpu-test
   ```
4. Verify NVIDIA device plugin:
   ```bash
   kubectl get pods -n kube-system | grep nvidia
   ```
5. Test with different image:
   ```bash
   kubectl run test-gpu --image=nvidia/cuda:11.0-base --command -- sleep infinity
   kubectl exec test-gpu -- nvidia-smi
   ```

#### Issue: No GPU detected in pod

**Symptoms:**
- Pod runs but no GPU detected
- nvidia-smi shows no devices in pod

**Solutions:**
1. Verify NVIDIA runtime configuration:
   ```bash
   nvidia-ctk runtime list
   ```
2. Check containerd configuration:
   ```bash
   cat /etc/containerd/config.toml
   ```
3. Test GPU access on host:
   ```bash
   nvidia-smi
   ```
4. Verify k3s configuration:
   ```bash
   cat /etc/rancher/k3s/config.yaml
   ```
5. Check for resource limits:
   ```bash
   kubectl describe pod -n gpu-test pod/gpu-test
   ```

### Deployment Issues

> This project has **no GitOps/Argo CD layer** — the app is deployed by
> `scripts/prepare_jetson.sh` → `ansible/playbooks/app/deploy_app.yml` →
> `deploy_countingapp.yml`, which renders `k3s/templates/*.j2` and applies them
> with `kubectl apply`. There is nothing to "sync".

#### Issue: app deployment fails

**Symptoms:**
- `deploy_countingapp.yml` errors during template rendering or `kubectl apply`
- The `countingapp` pod is missing or in `CrashLoopBackOff`

**Solutions:**
1. Re-run the one-shot deploy wrapper from your workstation:
   ```bash
   bash scripts/prepare_jetson.sh
   ```
2. Apply the templates directly to converge:
   ```bash
   ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/app/deploy_countingapp.yml
   ```
3. Check the pod status and logs:
   ```bash
   kubectl get pods -n countingapp-dev
   kubectl logs -n countingapp-dev -l app=countingapp
   ```
4. If `app/requirements.txt` changed, rebuild the image first (the deploy
   only rsyncs code):
   ```bash
   cd ansible/playbooks/app
   ansible-playbook -i ../../inventory/jetsons.yml deploy_app.yml --tags build
   ```
5. For a quick app restart without a full redeploy:
   ```bash
   kubectl scale daemonset countingapp -n countingapp-dev --replicas=0
   kubectl scale daemonset countingapp -n countingapp-dev --replicas=1
   ```

### Bootstrap Process Issues

#### Issue: Bootstrap hangs

**Symptoms:**
- Playbook hangs at certain task
- No progress for extended period
- Timeout errors

**Solutions:**
1. Increase timeout:
   ```bash
   ansible-playbook --timeout=3600 playbook.yml
   ```
2. Run with verbose logging:
   ```bash
   ansible-playbook -vvv playbook.yml
   ```
3. Check Jetson resources:
   ```bash
   free -h
   df -h
   top
   ```
4. Run individual playbooks:
   ```bash
   ansible-playbook ansible/playbooks/network_ssh.yml
   ```
5. Check network connectivity:
   ```bash
   ping <jetson-ip>
   ```

#### Issue: Bootstrap fails on specific task

**Symptoms:**
- Playbook fails at specific task
- Error message displayed

**Solutions:**
1. Read error message carefully
2. Check task requirements
3. Verify prerequisites
4. Run task individually:
   ```bash
   ansible-playbook playbook.yml --start-at-task="<task-name>"
   ```
5. Check logs on Jetson:
   ```bash
   journalctl -u <service-name>
   ```

### Performance Issues

#### Issue: Slow performance

**Symptoms:**
- Playbook execution is slow
- High CPU usage
- Memory pressure

**Solutions:**
1. Monitor resources:
   ```bash
   htop
   free -h
   df -h
   ```
2. Limit concurrent operations:
   ```bash
   ansible-playbook -f 2 playbook.yml
   ```
3. Schedule during off-peak hours
4. Upgrade Jetson hardware if possible
5. Optimize playbooks:
   - Use tags to run only necessary tasks
   - Cache frequently used data
   - Reduce unnecessary tasks

#### Issue: High memory usage

**Symptoms:**
- Memory pressure warnings
- OOM killer activating
- Swapping

**Solutions:**
1. Check memory usage:
   ```bash
   free -h
   ```
2. Identify memory-hungry processes:
   ```bash
   top
   ```
3. Limit k3s resources:
   ```bash
   --kubelet-arg: eviction-hard=memory.available<500Mi
   ```
4. Clean up unused resources:
   ```bash
   kubectl delete pods --field-selector=status.phase=Succeeded --all-namespaces
   ```
5. Add swap space:
   ```bash
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   ```

### Discovery Script Issues

#### Issue: Discovery script fails

**Symptoms:**
- No devices found
- Script times out
- Wrong IP detected

**Solutions:**
1. Verify nmap is installed:
   ```bash
   sudo apt install nmap
   ```
2. Check network connectivity:
   ```bash
   ping 192.168.1.1
   ```
3. Specify network manually:
   ```bash
   ./scripts/jetson_discover.sh 192.168.1.0/24
   ```
4. Test with arp-scan:
   ```bash
   sudo apt install arp-scan
   sudo arp-scan --localnet
   ```
5. Use static inventory instead

#### Issue: Wrong device detected

**Symptoms:**
- Script detects wrong device
- Multiple devices with SSH open

**Solutions:**
1. Filter by hostname:
   ```bash
   nmap -p 22 --open -n 192.168.1.0/24 | grep jetson
   ```
2. Use MAC address filtering
3. Manually specify IP address
4. Disable SSH on other devices temporarily

## Logging and Debugging

### Ansible Logging

Enable verbose logging:
```bash
ansible-playbook -vvv playbook.yml
```

Enable connection debugging:
```bash
ansible-playbook -vvv -c paramiko playbook.yml
```

### Jetson Logs

Check system logs:
```bash
journalctl -u ssh
journalctl -u NetworkManager
journalctl -u k3s
journalctl -u containerd
```

View all logs:
```bash
journalctl -f
```

### Kubernetes Logs

Check k3s logs:
```bash
kubectl get pods --all-namespaces
kubectl logs <pod-name> -n <namespace>
```

Check k3s service logs:
```bash
journalctl -u k3s -f
```

### Network Debugging

Check network interfaces:
```bash
ip addr show
nmcli device status
```

Check routing:
```bash
ip route
route -n
```

Check DNS:
```bash
cat /etc/resolv.conf
nslookup google.com
```

### Container Debugging

Check containerd logs:
```bash
journalctl -u containerd -f
```

Check container runtime:
```bash
ctr version
ctr images list
```

Test container runtime:
```bash
sudo ctr run --rm docker.io/library/alpine:latest sh echo "Hello World"
```

## Recovery Procedures

### Reset Network Configuration

```bash
# Remove all NetworkManager connections
nmcli con show | awk '{print $1}' | grep -v NAME | xargs -I {} nmcli con del {}

# Restart NetworkManager
sudo systemctl restart NetworkManager

# Reconfigure network
ansible-playbook ansible/playbooks/network_setup.yml
```

### Reset k3s Installation

```bash
# Stop k3s service
sudo systemctl stop k3s

# Remove k3s
sudo /usr/local/bin/k3s-uninstall.sh

# Remove k3s data
sudo rm -rf /var/lib/rancher/k3s

# Reinstall k3s
ansible-playbook ansible/playbooks/install_k3s.yml
```

### Reset Container Runtime

```bash
# Stop containerd
sudo systemctl stop containerd

# Remove containerd
sudo apt remove --purge containerd.io

# Remove configuration
sudo rm -rf /etc/containerd
sudo rm -rf /var/lib/containerd

# Reinstall containerd
ansible-playbook ansible/playbooks/install_container_runtime.yml
```

### Factory Reset Jetson

```bash
# WARNING: This will erase all data

# Power off Jetson
sudo shutdown -h now

# Remove microSD card
# Flash new JetPack image
# Reinsert microSD card
# Power on Jetson

# Re-run bootstrap
./scripts/prepare_jetson.sh
```

## Prevention and Best Practices

### Regular Maintenance

1. **Monitor resources**: Set up monitoring to track CPU, memory, and disk usage
2. **Update regularly**: Keep software up to date
3. **Backup configurations**: Regularly backup important configurations
4. **Test changes**: Test changes on staging device before production

### Error Handling

1. **Use tags**: Run playbooks with specific tags to isolate issues
2. **Check mode**: Run playbooks in check mode first:
   ```bash
   ansible-playbook --check playbook.yml
   ```
3. **Dry run**: Use --diff to see changes:
   ```bash
   ansible-playbook --diff playbook.yml
   ```

### Documentation

1. **Document changes**: Keep records of all changes made
2. **Track issues**: Maintain issue logs for recurring problems
3. **Update documentation**: Keep documentation up to date with changes

## Support Resources

- [Jetson Forums](https://forums.developer.nvidia.com/c/jetson)
- [k3s Documentation](https://docs.k3s.io/)
- [Ansible Documentation](https://docs.ansible.com/)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

For additional information, refer to:
- [Quick Start Guide](01_quickstart.md)
- [Jetson Setup](02_setup.md)
- [Deployment](03_deployment.md)
- [Configuration](04_configuration.md)
- [Reset Procedure](14_reset.md)
