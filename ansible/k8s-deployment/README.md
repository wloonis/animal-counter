# Kubernetes Deployment with Ansible kubernetes.core Collection

This directory contains the Ansible playbook and configuration for deploying the countingapp using the official Kubernetes Ansible collection.

## Prerequisites

- Ansible 2.10 or higher
- Python 3.6 or higher
- kubectl configured with access to your Kubernetes cluster
- kubernetes.core Ansible collection

## Installation

### 1. Install the Kubernetes collection

```bash
# Install using requirements file
ansible-galaxy install -r requirements.yml

# Or install directly
ansible-galaxy collection install kubernetes.core
```

### 2. Configure Kubernetes access

Ensure your `~/.kube/config` file is properly configured, or set the `K8S_AUTH_KUBECONFIG` environment variable.

## Usage

### Deploy the application

```bash
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml
```

### Run specific tags

```bash
# Deploy only namespace
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml --tags namespace

# Deploy only the application
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml --tags deployment

# Deploy service
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml --tags service

# Deploy cleanup cronjob
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml --tags cleanup

# Configure logs
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml --tags logs
```

## Configuration Files

The Kubernetes resources are defined in YAML files in the `app/k3s/` directory:

- `namespace.yaml` - Kubernetes namespace definition
- `deployment.yaml` - Application deployment configuration
- `service.yaml` - Service configuration
- `cronjob.yaml` - Video file cleanup cronjob

## Variables

Configure deployment using environment variables:

```bash
export APP_NAMESPACE=countingapp-prod
export APP_NAME=countingapp
export APP_VERSION=1.0.0
export APP_PORT=31501
export APP_PATH=/path/to/app
export FILES_PATH=/path/to/files
```

## Benefits of This Approach

1. **Native Kubernetes Integration**: Uses Ansible modules specifically designed for Kubernetes
2. **Idempotent Operations**: Automatic handling of resource state
3. **Better Error Handling**: Robust error reporting and recovery
4. **Consistent Interface**: All Kubernetes operations use the same module
5. **Advanced Features**: Access to Kubernetes API features through Ansible

## Troubleshooting

### Collection installation issues

If you have locale issues:
```bash
LC_ALL=C ansible-galaxy collection install kubernetes.core
```

### Kubernetes connection issues

Ensure your kubeconfig is properly set:
```bash
export K8S_AUTH_KUBECONFIG=~/.kube/config
```

### Debugging

Add `-vvv` for verbose output:
```bash
ansible-playbook -i inventory/jetsons.yml playbooks/app/deploy_countingapp_k8s.yml -vvv
```