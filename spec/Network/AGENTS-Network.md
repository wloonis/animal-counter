# AGENTS.md

This file provides guidance to AGENTS when working with code in this repository.

---

## Project Overview

This project focuses on industrializing the deployment of containerized applications on Jetson Orin Nano devices running JetPack 6.1 (Ubuntu 22.04). The solution leverages a microservices architecture orchestrated by k3s, with minimal manual intervention on the device. The goal is to enable reproducible, zero-touch deployments and remote management of Jetson devices in the field.

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **JetPack 6.1** | NVIDIA's Linux distribution for Jetson Orin Nano |
| **Ubuntu 22.04** | Base OS for Jetson devices |
| **k3s** | Lightweight Kubernetes distribution for container orchestration |
| **Docker/Containerd** | Container runtime with NVIDIA GPU support |
| **NVIDIA Runtime** | GPU acceleration for containers |
| **Ansible** | Configuration management and automation |
| **Argo CD** | GitOps continuous delivery tool |
| **Prometheus/Grafana** | Monitoring and visualization |
| **GitHub/GitLab** | Repository management and CI/CD |
| **Docker Hub/GitLab Registry** | Container image storage |

---

## Commands

```bash
# Development
# No specific development commands for this project

# Build
# No specific build commands for this project

# Test
# No specific test commands for this project

# Lint
# No specific lint commands for this project
```

---

## Project Structure

```
repo-infra/
├── ansible/
│   ├── bootstrap_jetson.yml
│   ├── network_setup.yml
│   ├── install_k3s.yml
│   └── deploy_gitops.yml
├── k3s/
│   ├── manifests/
│   └── helm/
└── docs/
    └── deployment_guide.md

repo-apps/
├── Dockerfile
├── helm/
│   └── Chart.yaml
├── k8s/
│   ├── deployment.yaml
│   └── service.yaml
└── .github/
    └── workflows/
        └── ci.yml
```

---

## Architecture

The architecture follows a layered approach:

1. **Physical Layer**: Jetson Orin Nano devices with JetPack 6.1
2. **Network Layer**: Hotspot and static IP configuration for remote access
3. **Orchestration Layer**: k3s for container management
4. **Application Layer**: Containerized applications deployed via GitOps
5. **Management Layer**: Ansible for infrastructure automation and Argo CD for application deployment

---

## Code Patterns

### Naming Conventions
- **Files**: Use descriptive names in lowercase with hyphens (e.g., `network_setup.yml`)
- **Variables**: Use uppercase with underscores for constants (e.g., `HOTSPOT_NAME`)
- **Playbooks**: Use descriptive names ending with `.yml` (e.g., `bootstrap_jetson.yml`)

### File Organization
- **Ansible Playbooks**: Organized by function (bootstrap, network, k3s, GitOps)
- **Kubernetes Manifests**: Organized by type (deployments, services, ingress)
- **Documentation**: Markdown files in the `docs` directory

### Error Handling
- **Ansible**: Use `failed_when` and `ignore_errors` directives where appropriate
- **Shell Scripts**: Check exit codes and handle errors gracefully
- **k3s**: Use health checks and liveness probes for pods

---

## Testing

- **Ansible Playbooks**: Test on a staging Jetson device before production
- **k3s**: Validate GPU acceleration with a test pod running `nvidia-smi`
- **Network Configuration**: Verify hotspot and static IP setup with `nmcli` and `ip` commands

---

## Validation

```bash
# Validate Ansible playbooks
ansible-playbook --check bootstrap_jetson.yml

# Validate k3s installation
kubectl get nodes

# Validate GPU acceleration
kubectl run test-gpu --image=nvidia/cuda:11.0-base --command -- sleep infinity
kubectl exec test-gpu -- nvidia-smi
```

---

## Key Files

| File | Purpose |
|------|---------|
| `examples/jetson_first_connect.sh` | Script to find and connect to Jetson via SSH |
| `examples/jetson_ssh_init/init_ssh.sh` | Script to configure hotspot and static IP on Jetson |
| `INITIAL-Network.md` | Initial network configuration requirements |
| `INITIAL-MicroServices.md` | Initial microservices architecture requirements |
| `PRD.md` | Product Requirements Document |

---

## On-Demand Context

| Topic | File |
|-------|------|
| **Network Configuration** | `INITIAL-Network.md` |
| **Microservices Architecture** | `INITIAL-MicroServices.md` |
| **Product Requirements** | `PRD.md` |
| **Example Scripts** | `examples/` |

---

## Notes

- **Zero-Touch Deployment**: After flashing JetPack 6.1, all configuration should be automated via Ansible and GitOps
- **Security**: Use SSH key-based authentication and WPA2 encryption for the hotspot
- **Compatibility**: Validate k3s and CNI compatibility with JetPack 6.1
- **Resources**: Monitor CPU, memory, and GPU usage to avoid saturation
