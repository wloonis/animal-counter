# Product Requirements Document (PRD)

## 1. Executive Summary

This PRD outlines the requirements for industrializing the deployment of containerized applications on Jetson Orin Nano devices running JetPack 6.1 (Ubuntu 22.04). The solution leverages a microservices architecture orchestrated by k3s, with minimal manual intervention on the device. The goal is to enable reproducible, zero-touch deployments and remote management of Jetson devices in the field.

### Core Value Proposition
- **Reproducible Deployments**: Automate the entire setup process from OS configuration to application deployment.
- **Zero-Touch Deployment**: Minimize manual intervention on the Jetson device post-flashing.
- **Remote Management**: Enable MLOps/DevOps practices for managing deployments across multiple devices.
- **GPU Acceleration**: Ensure seamless GPU acceleration for containerized applications.

### MVP Goal Statement
Deliver a fully automated deployment pipeline for Jetson Orin Nano devices, enabling technicians to deploy and manage containerized applications with minimal manual intervention.

---

## 2. Mission

### Product Mission Statement
To provide a scalable, automated, and reproducible deployment solution for containerized applications on Jetson Orin Nano devices, enabling seamless integration into industrial and edge computing environments.

### Core Principles
1. **Automation**: Minimize manual intervention through scripting and configuration management.
2. **Reproducibility**: Ensure consistent deployments across multiple devices.
3. **Scalability**: Support deployment and management of multiple Jetson devices in the field.
4. **Security**: Implement best practices for secure access and configuration.
5. **Observability**: Provide tools for monitoring and troubleshooting deployments.

---

## 3. Target Users

### Primary User Personas
1. **Technicians**: Non-expert Linux/Kubernetes users who prepare Jetson devices for deployment.
2. **DevOps Engineers**: Responsible for managing CI/CD pipelines and remote deployments.
3. **MLOps Engineers**: Focused on deploying and managing machine learning workloads on Jetson devices.

### Technical Comfort Level
- **Technicians**: Basic Linux and network configuration skills.
- **DevOps/MLOps Engineers**: Proficient in Kubernetes, Docker, and CI/CD practices.

### Key User Needs and Pain Points
- **Technicians**: Need a simple, guided process for preparing Jetson devices.
- **DevOps/MLOps Engineers**: Need a reliable, automated pipeline for deploying and updating applications.
- **Common Pain Points**: Manual configuration errors, inconsistent deployments, and lack of remote management capabilities.

---

## 4. MVP Scope

### In Scope (✅)
#### Core Functionality
- ✅ Automated network configuration (hotspot, static IP, Ethernet).
- ✅ Installation and configuration of Docker/Containerd with NVIDIA runtime.
- ✅ Installation and configuration of k3s for container orchestration.
- ✅ Deployment of a test application to validate GPU acceleration.
- ✅ Setup of GitOps (Argo CD or Ansible Pull) for application deployment.

#### Technical
- ✅ Ansible playbooks for automating setup and configuration.
- ✅ Scripts for discovering and connecting to Jetson devices.
- ✅ Validation scripts for GPU and k3s functionality.

#### Integration
- ✅ Integration with GitHub/GitLab for CI/CD.
- ✅ Integration with Docker Hub/GitLab Registry for container images.

#### Deployment
- ✅ Zero-touch deployment process post-JetPack flashing.
- ✅ Documentation for technicians and engineers.

### Out of Scope (❌)
- ❌ Multi-node k3s clusters.
- ❌ Advanced monitoring and observability (Prometheus/Grafana).
- ❌ Automated JetPack flashing process.
- ❌ Advanced security features (e.g., mutual TLS, advanced firewall rules).
- ❌ Support for non-Jetson devices.

---

## 5. User Stories

### Primary User Stories
1. **As a technician**, I want to prepare a Jetson device with minimal manual steps, so that I can deploy it quickly in the field.
   - *Example*: Use a script to discover the Jetson on the network, configure the hotspot, and install k3s.

2. **As a DevOps engineer**, I want to deploy applications to multiple Jetson devices remotely, so that I can manage updates and configurations centrally.
   - *Example*: Use GitOps to push updates to all Jetson devices without manual intervention.

3. **As an MLOps engineer**, I want to ensure GPU acceleration is available in my containerized applications, so that I can run machine learning workloads efficiently.
   - *Example*: Deploy a test pod that validates GPU access and performance.

4. **As a technician**, I want clear documentation and troubleshooting guides, so that I can resolve issues quickly.
   - *Example*: Access a step-by-step guide for resetting a Jetson device.

### Technical User Stories
1. **As a DevOps engineer**, I want to validate that k3s is correctly installed and functional, so that I can deploy applications reliably.
   - *Example*: Run a script to check k3s node status and pod deployment.

2. **As a technician**, I want to ensure the Jetson device is securely configured, so that I can prevent unauthorized access.
   - *Example*: Disable password-based SSH login and enable key-based authentication.

---

## 6. Core Architecture & Patterns

### High-Level Architecture
The architecture follows a layered approach:
1. **Physical Layer**: Jetson Orin Nano devices with JetPack 6.1.
2. **Network Layer**: Hotspot and static IP configuration for remote access.
3. **Orchestration Layer**: k3s for container management.
4. **Application Layer**: Containerized applications deployed via GitOps.
5. **Management Layer**: Ansible for infrastructure automation and Argo CD for application deployment.

### Directory Structure
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

### Key Design Patterns
- **Infrastructure as Code (IaC)**: Use Ansible playbooks to define and manage infrastructure.
- **GitOps**: Use Argo CD or Ansible Pull to manage application deployments.
- **Immutable Infrastructure**: Treat Jetson devices as immutable, with automated setup and configuration.

---

## 7. Tools/Features

### Ansible Playbooks
- **network_ssh.yml**: Secure SSH access and configure hostname.
- **network_setup.yml**: Configure hotspot, DHCP, and static IP.
- **install_container_runtime.yml**: Install and configure Docker/Containerd with NVIDIA runtime.
- **install_k3s.yml**: Install and configure k3s.
- **validate_gpu_k8s.yml**: Validate GPU acceleration in Kubernetes.
- **deploy_gitops.yml**: Deploy GitOps tools (Argo CD or Ansible Pull).

### Scripts
- **jetson_discover.sh**: Discover Jetson devices on the network.
- **jetson_first_access.sh**: Establish initial SSH connection.
- **prepare_jetson.sh**: One-shot script for technicians to prepare a Jetson device.

---

## 8. Technology Stack

### Backend Technologies
- **Ansible**: Configuration management and automation.
- **k3s**: Lightweight Kubernetes distribution.
- **Docker/Containerd**: Container runtime with NVIDIA GPU support.
- **NVIDIA Runtime**: GPU acceleration for containers.

### Frontend Technologies
- **Markdown**: Documentation for technicians and engineers.

### Dependencies and Libraries
- **Ansible Modules**: `community.general` for `nmcli`, `kubernetes.core` for Kubernetes operations.
- **Network Tools**: `nmap`, `arp`, `mDNS` for device discovery.

### Third-Party Integrations
- **GitHub/GitLab**: Repository management and CI/CD.
- **Docker Hub/GitLab Registry**: Container image storage.
- **Argo CD**: GitOps continuous delivery tool.

---

## 9. Security & Configuration

### Authentication/Authorization
- **SSH**: Key-based authentication, disable password-based login.
- **Hotspot**: WPA2 encryption with a robust password.
- **k3s**: Secure access to the Kubernetes API.

### Configuration Management
- **Environment Variables**: Store sensitive data (e.g., passwords, API keys) in `.env` files.
- **Ansible Variables**: Use `group_vars` and `host_vars` for configuration.

### Security Scope
- **In Scope**: SSH hardening, hotspot security, and basic firewall rules.
- **Out of Scope**: Advanced security features (e.g., mutual TLS, advanced firewall rules).

### Deployment Considerations
- **Firewall**: Use UFW or nftables to restrict access to necessary ports (SSH, HTTP/HTTPS).
- **Network Isolation**: Use hotspot for local access and static IP for remote management.

---

## 10. API Specification

### Kubernetes API
- **Endpoints**: Standard Kubernetes API endpoints for managing pods, services, and deployments.
- **Authentication**: Use `kubectl` with k3s configuration.
- **Example Payloads**:
  ```yaml
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: gpu-test
  spec:
    replicas: 1
    template:
      spec:
        containers:
          - name: gpu-test
            image: nvidia/cuda:11.0-base
            command: ["sleep", "infinity"]
  ```

---

## 11. Success Criteria

### MVP Success Definition
- ✅ Jetson devices can be prepared and deployed with minimal manual intervention.
- ✅ Applications can be deployed and updated remotely using GitOps.
- ✅ GPU acceleration is validated and functional in containerized applications.
- ✅ Technicians can follow documentation to prepare and troubleshoot Jetson devices.

### Functional Requirements
- ✅ Automated network configuration (hotspot, static IP, Ethernet).
- ✅ Automated installation of Docker/Containerd with NVIDIA runtime.
- ✅ Automated installation of k3s.
- ✅ Automated deployment of test applications to validate GPU acceleration.
- ✅ Automated setup of GitOps for application deployment.

### Quality Indicators
- **Reliability**: 95% success rate for automated deployments.
- **Usability**: Technicians can prepare a Jetson device in under 30 minutes.
- **Maintainability**: Clear documentation and troubleshooting guides.

### User Experience Goals
- **Technicians**: Simple, guided process for preparing Jetson devices.
- **DevOps/MLOps Engineers**: Reliable, automated pipeline for deploying and updating applications.

---

## 12. Implementation Phases

### Phase 1: POC Local
**Goal**: Validate the automated deployment process on a single Jetson device.

**Deliverables**:
- ✅ Ansible playbooks for network configuration, container runtime, and k3s installation.
- ✅ Scripts for discovering and connecting to Jetson devices.
- ✅ Validation scripts for GPU and k3s functionality.
- ✅ Documentation for technicians and engineers.

**Validation Criteria**:
- Jetson device is prepared and deployed successfully.
- GPU acceleration is validated and functional.
- Documentation is clear and usable.

**Timeline**: 2-4 weeks.

### Phase 2: Industrialization
**Goal**: Structuring the repositories and setting up GitOps.

**Deliverables**:
- ✅ Structured repositories for infrastructure and applications.
- ✅ GitOps setup (Argo CD or Ansible Pull).
- ✅ Documentation for multi-device deployment.

**Validation Criteria**:
- Multiple Jetson devices can be prepared and deployed successfully.
- Applications can be deployed and updated remotely using GitOps.
- Documentation is clear and usable for multi-device deployment.

**Timeline**: 4-6 weeks.

### Phase 3: Durcissement et Observabilité
**Goal**: Enhance security and observability.

**Deliverables**:
- ✅ Advanced security features (e.g., mutual TLS, advanced firewall rules).
- ✅ Monitoring and observability tools (Prometheus/Grafana).
- ✅ Backup and recovery procedures.

**Validation Criteria**:
- Security features are implemented and tested.
- Monitoring and observability tools are functional.
- Backup and recovery procedures are tested.

**Timeline**: 6-8 weeks.

---

## 13. Future Considerations

### Post-MVP Enhancements
- **Multi-Node k3s Clusters**: Support for deploying and managing multi-node k3s clusters.
- **Advanced Monitoring**: Integration with centralized monitoring and logging platforms.
- **Automated JetPack Flashing**: Automate the JetPack flashing process for even less manual intervention.

### Integration Opportunities
- **CI/CD Pipelines**: Integration with advanced CI/CD pipelines for automated testing and deployment.
- **Container Registries**: Support for additional container registries (e.g., AWS ECR, Google Container Registry).
- **Cloud Platforms**: Integration with cloud platforms for hybrid deployments.

### Advanced Features
- **Dynamic Scaling**: Support for dynamically scaling applications based on demand.
- **Advanced Security**: Support for advanced security features (e.g., mutual TLS, advanced firewall rules).
- **Edge AI**: Support for advanced edge AI workloads (e.g., federated learning, model serving).

---

## 14. Risks & Mitigations

| Risk | Mitigation Strategy |
|------|-------------------|
| **Incompatibility with JetPack 6.1**: Some tools or configurations may not be compatible with JetPack 6.1. | Validate compatibility early and adjust configurations as needed. |
| **Network Configuration Issues**: Issues with hotspot or static IP configuration may prevent remote access. | Test network configurations thoroughly and provide clear troubleshooting guides. |
| **GPU Acceleration Issues**: Issues with NVIDIA runtime or GPU acceleration may prevent applications from running efficiently. | Validate GPU acceleration early and provide clear troubleshooting guides. |
| **Security Vulnerabilities**: Security vulnerabilities may be introduced during the deployment process. | Follow security best practices and provide clear documentation for securing Jetson devices. |
| **Dependency Issues**: Issues with dependencies (e.g., Ansible modules, Docker images) may prevent deployments from succeeding. | Use versioned dependencies and provide clear documentation for resolving dependency issues. |

---

## 15. Appendix

### Related Documents
- **INITIAL-Network.md**: Initial network configuration requirements.
- **INITIAL-MicroServices.md**: Initial microservices architecture requirements.
- **AGENTS.md**: Project guidelines and conventions.

### Key Dependencies
- **JetPack 6.1**: NVIDIA's Linux distribution for Jetson Orin Nano.
- **k3s**: Lightweight Kubernetes distribution.
- **Docker/Containerd**: Container runtime with NVIDIA GPU support.
- **Ansible**: Configuration management and automation.
- **Argo CD**: GitOps continuous delivery tool.

### Repository/Project Structure
- **repo-infra**: Contains Ansible playbooks, scripts, and documentation for infrastructure automation.
- **repo-apps**: Contains Dockerfiles, Helm charts, and Kubernetes manifests for applications.
