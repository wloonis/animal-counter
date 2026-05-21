# Animal Counter Application - Deployment Guide

This document provides comprehensive instructions for deploying the Animal Counter Application using Ansible for infrastructure provisioning and K3s for container orchestration.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation via Ansible](#installation-via-ansible)
4. [K3s Deployment](#k3s-deployment)
5. [Configuration](#configuration)
6. [Running the Application](#running-the-application)
7. [Testing](#testing)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The Animal Counter Application is a containerized service designed to track and count animal sightings in wildlife monitoring systems. The application is designed to run on Kubernetes (K3s) and can be easily deployed using Ansible automation.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        K3s Cluster                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   Deployment │  │    Service   │  │   ConfigMap/Secret   │  │
│  │ (animal-     │──│  (animal-    │  │   (env vars, configs)│  │
│  │  counter)    │  │   counter)   │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│         │                  │                    │               │
│  ┌──────┴──────────────────┴────────────────────┴───────────┐   │
│  │  Persistent Storage (FileBrowser PVC)                     │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────┐  ┌───────────────────────────────────┐    │
│  │  CronJob         │  │  LoadBalancer/NodePort           │    │
│  │  (data-export)   │  │  (external access)                │    │
│  └──────────────────┘  └───────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   Ansible        │
                    │   (provisioning) │
                    └──────────────────┘
```

### Key Features

- **RESTful API**: HTTP endpoints for animal counting operations
- **Database Integration**: Persistent storage for animal data
- **Cron Jobs**: Scheduled data export and cleanup tasks
- **File Browser**: Web-based file management interface
- **Health Monitoring**: Built-in health checks and metrics

---

## Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **Master Node** | 2 CPU cores, 2GB RAM, 20GB SSD | 4 CPU cores, 8GB RAM, 50GB SSD |
| **Worker Nodes** | 2 CPU cores, 4GB RAM, 40GB SSD | 4 CPU cores, 16GB RAM, 100GB SSD |
| **Total Cluster** | 3 nodes | 5+ nodes |
| **Network** | 1 Gbps | 10 Gbps |

### Software Requirements

#### Control Machine (Ansible Controller)

```bash
# Operating System
- Ubuntu 20.04 LTS or later
- Debian 11 or later
- RHEL 8+ or CentOS Stream 8+

# Required Software
- Ansible >= 2.12
- Python >= 3.8
- SSH client
- kubectl >= 1.24 (for manual cluster management)
```

#### K3s Nodes

```bash
# Operating System
- Ubuntu 20.04 LTS / 22.04 LTS
- Debian 11/12
- Rocky Linux 8/9
- RHEL 8/9

# Minimum Requirements per Node
- 2 CPU cores
- 2GB RAM (4GB recommended)
- 20GB free disk space
- Root/sudo access
- SSH access
```

#### Runtime Dependencies

```bash
# For Docker/Containerd
- Docker >= 20.10 or
- Containerd >= 1.6

# For K3s (included in install)
- K3s >= v1.27
- Helm >= 3.12 (optional)
```

### Network Requirements

| Port | Protocol | Service | Direction |
|------|----------|---------|-----------|
| 22   | TCP      | SSH     | Inbound    |
| 6443 | TCP      | K3s API | Inbound    |
| 80   | HTTP     | App     | Inbound    |
| 443  | HTTPS    | App     | Inbound    |
| 10250| TCP      | Kubelet | Inbound    |
| 30000-32767 | TCP | NodePort | Inbound |

### Firewall Configuration

```bash
# On all nodes - UFW example
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 6443/tcp  # K3s API
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

---

## Installation via Ansible

### Ansible Project Structure

```
animal-counter-deploy/
├── ansible.cfg
├── inventory/
│   └── hosts.ini
├── playbooks/
│   ├── preflight.yml
│   ├── install-k3s.yml
│   └── deploy-app.yml
├── roles/
│   ├── k3s/
│   │   ├── tasks/
│   │   │   └── main.yml
│   │   └── templates/
│   │       └── config.yaml.j2
│   ├── docker/
│   │   └── tasks/
│   │       └── main.yml
│   └── app/
│       ├── tasks/
│       │   └── main.yml
│       └── templates/
│           └── deployment.yaml.j2
└── vars/
    └── main.yml
```

### Step 1: Prepare the Control Machine

```bash
# Install Ansible on Ubuntu/Debian
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository --yes ppa:ansible/ansible
sudo apt update
sudo apt install -y ansible

# Install Ansible on RHEL/CentOS
sudo yum install -y epel-release
sudo yum install -y ansible

# Verify installation
ansible --version
# Expected output: ansible 2.12+ with Python 3.8+
```

### Step 2: Configure Inventory

Create the inventory file at `inventory/hosts.ini`:

```ini
# inventory/hosts.ini

[all:vars]
ansible_user=ubuntu
ansible_ssh_private_key_file=~/.ssh/id_rsa
ansible_python_interpreter=/usr/bin/python3

[k3s_master]
k3s-node-01 ansible_host=192.168.1.10 node_ip=192.168.1.10
k3s-node-02 ansible_host=192.168.1.11 node_ip=192.168.1.11
k3s-node-03 ansible_host=192.168.1.12 node_ip=192.168.1.12

[k3s_agent]
k3s-node-04 ansible_host=192.168.1.13 node_ip=192.168.1.13
k3s-node-05 ansible_host=192.168.1.14 node_ip=192.168.1.14

[k3s_cluster:children]
k3s_master
k3s_agent

[all:vars]
# K3s configuration
k3s_version=v1.27.12+k3s1
k3s_install_dir=/usr/local/bin
k3s_data_dir=/var/lib/rancher/k3s

# Application configuration
app_namespace=animal-counter
app_name=animal-counter
app_version=latest
```

### Step 3: Create Ansible Configuration

Create `ansible.cfg`:

```ini
# ansible.cfg
[defaults]
inventory = inventory/hosts.ini
host_key_checking = False
retry_files_enabled = False
gathering = fact
interative_timeout = 60
stdout_callback = yaml

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False
```

### Step 4: Create Variables File

Create `vars/main.yml`:

```yaml
# vars/main.yml

---
# K3s Configuration
k3s_version: v1.27.12+k3s1
k3s_server_url: "https://192.168.1.10:6443"
k3s_token_file: "/etc/rancher/k3s/k3s.yaml"
k3s_cluster_init: true

# Application Variables
app_namespace: animal-counter
app_name: animal-counter
app_image: animalcounter/app:latest
app_port: 8080
app_replicas: 3

# Database Configuration
db_type: postgresql
db_host: postgres-service.animal-counter.svc.cluster.local
db_port: 5432
db_name: animal_counter
db_user: animalcounter
db_password: "changeme"  # Use Ansible Vault for production

# Storage Configuration
storage_enabled: true
storage_capacity: 10Gi
storage_class: local-path

# Ingress Configuration
ingress_enabled: true
ingress_host: animal-counter.local
ingress_tls_enabled: false

# Cron Job Configuration
cronjob_enabled: true
cronjob_schedule: "0 2 * * *"  # Daily at 2 AM
cronjob_retention_days: 30
```

### Step 5: Create Playbooks

#### Preflight Check Playbook

```yaml
# playbooks/preflight.yml
---
- name: Preflight Checks
  hosts: k3s_cluster
  gather_facts: true
  become: true
  vars:
    preflight_errors: []

  tasks:
    - name: Check if Python is installed
      ansible.builtin.command: python3 --version
      register: python_check
      changed_when: false
      failed_when: python_check.rc != 0

    - name: Check available memory
      ansible.builtin.shell: |
        free -m | awk 'NR==2{printf "%.0f", $7}'
      register: mem_check
      changed_when: false
      failed_when: mem_check.stdout | int < 1536

    - name: Check available disk space
      ansible.builtin.shell: |
        df -BG / | tail -1 | awk '{print $4}' | sed 's/G//'
      register: disk_check
      changed_when: false
      failed_when: disk_check.stdout | int < 20

    - name: Check internet connectivity
      ansible.builtin.uri:
        url: https://rancher.io
        timeout: 5
      register: connectivity_check
      ignore_errors: true

    - name: Display preflight results
      ansible.builtin.debug:
        msg: |
          Python: Installed
          Available Memory: {{ mem_check.stdout }}MB
          Available Disk: {{ disk_check.stdout }}GB
          Internet: {{ 'Connected' if connectivity_check is defined and connectivity_check is success else 'Not Connected' }}
```

#### Install K3s Playbook

```yaml
# playbooks/install-k3s.yml
---
- name: Install and Configure K3s
  hosts: k3s_master,k3s_agent
  gather_facts: true
  become: true
  vars:
    k3s_token: "your-secure-token-here"  # Generate with: openssl rand -hex 32

  tasks:
    - name: Update system packages
      ansible.builtin.apt:
        update_cache: yes
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

    - name: Disable swap
      ansible.builtin.shell: |
        swapoff -a
        sed -i '/swap/d' /etc/fstab
      changed_when: false

    - name: Load required kernel modules
      ansible.builtin.modprobe:
        name: "{{ item }}"
        state: present
      loop:
        - br_netfilter
        - overlay

    - name: Set kernel parameters
      ansible.builtin.sysctl:
        name: "{{ item.name }}"
        value: "{{ item.value }}"
        state: present
        reload: yes
      loop:
        - { name: 'net.bridge.bridge-nf-call-iptables', value: '1' }
        - { name: 'net.bridge.bridge-nf-call-ip6tables', value: '1' }
        - { name: 'net.ipv4.ip_forward', value: '1' }

    - name: Install K3s on master node
      ansible.builtin.shell: |
        curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION={{ k3s_version }} \
          K3S_NODE_NAME={{ inventory_hostname }} \
          K3S_KUBE_CONFIG_MODE=644 \
          sh -
      args:
        creates: /etc/rancher/k3s/k3s.yaml
      when: inventory_hostname in groups['k3s_master']

    - name: Install K3s on agent nodes
      ansible.builtin.shell: |
        curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION={{ k3s_version }} \
          K3S_NODE_NAME={{ inventory_hostname }} \
          K3S_URL={{ k3s_server_url }} \
          K3S_AGENT_TOKEN={{ k3s_token }} \
          sh -
      args:
        creates: /var/lib/rancher/k3s/agent/etc/k3s-agent-certs
      when: inventory_hostname in groups['k3s_agent']

    - name: Wait for K3s to be ready
      ansible.builtin.shell: |
        kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml get nodes
      register: k3s_check
      retries: 30
      delay: 10
      until: k3s_check.rc == 0
      changed_when: false

    - name: Configure K3s kubectl alias
      ansible.builtin.copy:
        dest: /etc/profile.d/k3s.sh
        content: |
          alias k3s='kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml'
        mode: '0644'
```

#### Deploy Application Playbook

```yaml
# playbooks/deploy-app.yml
---
- name: Deploy Animal Counter Application
  hosts: k3s_master
  gather_facts: false
  become: true
  vars:
    kubeconfig: /etc/rancher/k3s/k3s.yaml

  tasks:
    - name: Create application namespace
      community.kubernetes.k8s:
        name: "{{ app_namespace }}"
        api_version: v1
        kind: Namespace
        state: present
        kubeconfig: "{{ kubeconfig }}"

    - name: Create Docker registry secret
      community.kubernetes.k8s:
        name: docker-registry-secret
        namespace: "{{ app_namespace }}"
        api_version: v1
        kind: Secret
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          type: kubernetes.io/dockerconfigjson
          data:
            .dockerconfigjson: "{{ docker_config_json }}"

    - name: Create ConfigMap
      community.kubernetes.k8s:
        name: animal-counter-config
        namespace: "{{ app_namespace }}"
        api_version: v1
        kind: ConfigMap
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          data:
            APP_ENV: "{{ app_env | default('production') }}"
            LOG_LEVEL: "{{ log_level | default('info') }}"
            DB_TYPE: "{{ db_type }}"
            DB_HOST: "{{ db_host }}"
            DB_PORT: "{{ db_port }}"
            DB_NAME: "{{ db_name }}"
            STORAGE_PATH: "/data"
          metadata:
            name: animal-counter-config

    - name: Create Secret
      community.kubernetes.k8s:
        name: animal-counter-secret
        namespace: "{{ app_namespace }}"
        api_version: v1
        kind: Secret
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          stringData:
            DB_USER: "{{ db_user }}"
            DB_PASSWORD: "{{ db_password }}"
            JWT_SECRET: "{{ jwt_secret }}"
          metadata:
            name: animal-counter-secret

    - name: Create Storage PersistentVolumeClaim
      community.kubernetes.k8s:
        name: animal-counter-storage
        namespace: "{{ app_namespace }}"
        api_version: v1
        kind: PersistentVolumeClaim
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          spec:
            accessModes:
              - ReadWriteOnce
            resources:
              requests:
                storage: "{{ storage_capacity }}"
            storageClassName: "{{ storage_class }}"

    - name: Create Deployment
      community.kubernetes.k8s:
        name: animal-counter
        namespace: "{{ app_namespace }}"
        api_version: apps/v1
        kind: Deployment
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          spec:
            replicas: "{{ app_replicas }}"
            selector:
              matchLabels:
                app: animal-counter
            template:
              metadata:
                labels:
                  app: animal-counter
              spec:
                containers:
                  - name: animal-counter
                    image: "{{ app_image }}"
                    imagePullPolicy: Always
                    ports:
                      - containerPort: {{ app_port }}
                        name: http
                    envFrom:
                      - configMapRef:
                          name: animal-counter-config
                      - secretRef:
                          name: animal-counter-secret
                    volumeMounts:
                      - name: app-storage
                        mountPath: /data
                    livenessProbe:
                      httpGet:
                        path: /health
                        port: http
                      initialDelaySeconds: 30
                      periodSeconds: 10
                    readinessProbe:
                      httpGet:
                        path: /ready
                        port: http
                      initialDelaySeconds: 5
                      periodSeconds: 5
                    resources:
                      requests:
                        memory: "256Mi"
                        cpu: "250m"
                      limits:
                        memory: "512Mi"
                        cpu: "500m"
                volumes:
                  - name: app-storage
                    persistentVolumeClaim:
                      claimName: animal-counter-storage

    - name: Create Service
      community.kubernetes.k8s:
        name: animal-counter-service
        namespace: "{{ app_namespace }}"
        api_version: v1
        kind: Service
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          spec:
            type: ClusterIP
            selector:
              app: animal-counter
            ports:
              - port: 80
                targetPort: http
                protocol: TCP
                name: http

    - name: Create Ingress (Optional)
      community.kubernetes.k8s:
        name: animal-counter-ingress
        namespace: "{{ app_namespace }}"
        api_version: networking.k8s.io/v1
        kind: Ingress
        state: present
        kubeconfig: "{{ kubeconfig }}"
        definition:
          spec:
            rules:
              - host: "{{ ingress_host }}"
                http:
                  paths:
                    - path: /
                      pathType: Prefix
                      backend:
                        service:
                          name: animal-counter-service
                          port:
                            number: 80
```

### Step 6: Run Ansible Deployment

```bash
# Navigate to the Ansible directory
cd /path/to/animal-counter-deploy

# Test connectivity to all hosts
ansible all -m ping

# Run preflight checks
ansible-playbook playbooks/preflight.yml

# Install K3s cluster
ansible-playbook playbooks/install-k3s.yml

# Deploy the application
ansible-playbook playbooks/deploy-app.yml

# Verify deployment
ansible all -m shell -a "kubectl --kubeconfig=/etc/rancher/k3s/k3s.yaml get pods -n animal-counter"
```

---

## K3s Deployment

### Manual YAML Manifests

If you prefer to deploy without Ansible, you can use the following YAML manifests directly with kubectl.

#### Namespace

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: animal-counter
  labels:
    name: animal-counter
    environment: production
```

#### ConfigMap

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: animal-counter-config
  namespace: animal-counter
data:
  APP_ENV: "production"
  LOG_LEVEL: "info"
  DB_TYPE: "postgresql"
  DB_HOST: "postgres-service.animal-counter.svc.cluster.local"
  DB_PORT: "5432"
  DB_NAME: "animal_counter"
  DB_MAX_CONNECTIONS: "20"
  STORAGE_PATH: "/data"
  API_RATE_LIMIT: "100"
  API_TIMEOUT: "30"
```

#### Secret

```yaml
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: animal-counter-secret
  namespace: animal-counter
type: Opaque
stringData:
  DB_USER: "animalcounter"
  DB_PASSWORD: "changeme"
  JWT_SECRET: "your-secret-key-change-in-production"
  ENCRYPTION_KEY: "your-encryption-key"
```

#### PersistentVolumeClaim for FileBrowser

```yaml
# pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: animal-counter-storage
  namespace: animal-counter
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: local-path
```

#### Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: animal-counter
  namespace: animal-counter
  labels:
    app: animal-counter
    version: v1
spec:
  replicas: 3
  selector:
    matchLabels:
      app: animal-counter
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: animal-counter
        version: v1
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: animal-counter
                topologyKey: kubernetes.io/hostname
      containers:
        - name: animal-counter
          image: animalcounter/app:latest
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          envFrom:
            - configMapRef:
                name: animal-counter-config
            - secretRef:
                name: animal-counter-secret
          volumeMounts:
            - name: data
              mountPath: /data
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: animal-counter-storage
      restartPolicy: Always
```

#### Service

```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: animal-counter-service
  namespace: animal-counter
  labels:
    app: animal-counter
spec:
  type: ClusterIP
  selector:
    app: animal-counter
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
  sessionAffinity: None
```

#### FileBrowser Deployment

```yaml
# filebrowser-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: filebrowser
  namespace: animal-counter
spec:
  replicas: 1
  selector:
    matchLabels:
      app: filebrowser
  template:
    metadata:
      labels:
        app: filebrowser
    spec:
      containers:
        - name: filebrowser
          image: filebrowser/filebrowser:latest
          ports:
            - containerPort: 8080
              name: http
          env:
            - name: WEB_PORT
              value: "8080"
            - name: ROOT
              value: "/srv"
          volumeMounts:
            - name: storage
              mountPath: /srv
              readOnly: false
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "200m"
      volumes:
        - name: storage
          persistentVolumeClaim:
            claimName: animal-counter-storage
```

#### FileBrowser Service

```yaml
# filebrowser-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: filebrowser-service
  namespace: animal-counter
spec:
  type: NodePort
  selector:
    app: filebrowser
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 30080
      protocol: TCP
      name: http
```

#### CronJob for Data Export

```yaml
# cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: animal-counter-export
  namespace: animal-counter
spec:
  schedule: "0 2 * * *"
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
            app: animal-counter
            job: export
        spec:
          restartPolicy: OnFailure
          containers:
            - name: export
              image: animalcounter/app:latest
              command:
                - /bin/sh
                - -c
                - |
                  echo "Starting data export..."
                  /app/export.sh --retention-days 30
                  echo "Export completed successfully"
              envFrom:
                - configMapRef:
                    name: animal-counter-config
                - secretRef:
                    name: animal-counter-secret
              volumeMounts:
                - name: data
                  mountPath: /data
          volumes:
            - name: data
              persistentVolumeClaim:
                claimName: animal-counter-storage
```

### Applying All Manifests

```bash
# Apply all manifests in order
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secret.yaml
kubectl apply -f pvc.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f filebrowser-deployment.yaml
kubectl apply -f filebrowser-service.yaml
kubectl apply -f cronjob.yaml

# Or apply all at once
kubectl apply -f .

# Check deployment status
kubectl get all -n animal-counter
```

---

## Configuration

### Environment Variables

The application accepts the following environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_ENV` | No | `production` | Application environment (development, staging, production) |
| `LOG_LEVEL` | No | `info` | Logging verbosity (debug, info, warn, error) |
| `APP_HOST` | No | `0.0.0.0` | Host to bind to |
| `APP_PORT` | No | `8080` | Port to listen on |
| `DB_TYPE` | Yes | - | Database type (postgresql, mysql, sqlite) |
| `DB_HOST` | Yes | - | Database host address |
| `DB_PORT` | No | `5432` | Database port |
| `DB_NAME` | Yes | - | Database name |
| `DB_USER` | Yes | - | Database username |
| `DB_PASSWORD` | Yes | - | Database password |
| `DB_MAX_CONNECTIONS` | No | `20` | Maximum database connections |
| `DB_SSL_MODE` | No | `disable` | SSL mode for database connection |
| `JWT_SECRET` | Yes | - | Secret key for JWT token generation |
| `JWT_EXPIRY` | No | `24h` | JWT token expiry time |
| `ENCRYPTION_KEY` | No | - | Key for data encryption |
| `STORAGE_PATH` | No | `/data` | Path for file storage |
| `API_RATE_LIMIT` | No | `100` | API requests per minute |
| `API_TIMEOUT` | No | `30` | API request timeout in seconds |
| `CORS_ALLOWED_ORIGINS` | No | `*` | Allowed CORS origins |
| `METRICS_ENABLED` | No | `true` | Enable Prometheus metrics |
| `METRICS_PORT` | No | `9090` | Metrics port |

### Configuration via ConfigMap

Create a comprehensive ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: animal-counter-config
  namespace: animal-counter
data:
  APP_ENV: "production"
  LOG_LEVEL: "info"
  APP_HOST: "0.0.0.0"
  APP_PORT: "8080"
  DB_TYPE: "postgresql"
  DB_HOST: "postgres-service.animal-counter.svc.cluster.local"
  DB_PORT: "5432"
  DB_NAME: "animal_counter"
  DB_MAX_CONNECTIONS: "20"
  DB_SSL_MODE: "disable"
  STORAGE_PATH: "/data"
  API_RATE_LIMIT: "100"
  API_TIMEOUT: "30"
  CORS_ALLOWED_ORIGINS: "*"
  METRICS_ENABLED: "true"
  METRICS_PORT: "9090"
```

### Configuration via Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: animal-counter-secret
  namespace: animal-counter
type: Opaque
stringData:
  DB_USER: "animalcounter"
  DB_PASSWORD: "changeme"
  JWT_SECRET: "your-secret-key-change-in-production"
  JWT_EXPIRY: "24h"
  ENCRYPTION_KEY: "encryption-key-32-chars-minimum"
```

### K3s Configuration Options

#### Using local-path Storage

```bash
# Install local-path storage
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml

# Set as default storage class
kubectl patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```

#### Using Metallb for LoadBalancer

```yaml
# metallb-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  namespace: metallb-system
  name: config
data:
  config: |
    address-pools:
      - name: default
        protocol: layer2
        addresses:
          - 192.168.1.100-192.168.1.200
```

---

## Running the Application

### Running Locally with Docker

```bash
# Pull the image
docker pull animalcounter/app:latest

# Run with environment variables
docker run -d \
  --name animal-counter \
  -p 8080:8080 \
  -e APP_ENV=production \
  -e LOG_LEVEL=debug \
  -e DB_TYPE=postgresql \
  -e DB_HOST=localhost \
  -e DB_PORT=5432 \
  -e DB_NAME=animal_counter \
  -e DB_USER=animalcounter \
  -e DB_PASSWORD=changeme \
  -e JWT_SECRET=your-secret-key \
  -v animal-counter-data:/data \
  animalcounter/app:latest

# Check logs
docker logs -f animal-counter

# Stop the container
docker stop animal-counter

# Remove the container
docker rm animal-counter
```

### Running via Helm

```yaml
# helm-values.yaml
replicaCount: 3

image:
  repository: animalcounter/app
  tag: latest
  pullPolicy: Always

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: animal-counter.local
      paths:
        - path: /
          pathType: Prefix

persistence:
  enabled: true
  size: 10Gi
  storageClass: local-path

config:
  APP_ENV: production
  LOG_LEVEL: info
  DB_TYPE: postgresql
  DB_HOST: postgres-service.animal-counter.svc.cluster.local
  DB_PORT: 5432
  DB_NAME: animal_counter
  API_RATE_LIMIT: "100"

secret:
  DB_USER: animalcounter
  DB_PASSWORD: changeme
  JWT_SECRET: your-secret-key

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 250m
    memory: 256Mi
```

```bash
# Add Helm repository
helm repo add animal-counter https://your-repo.github.io/charts
helm repo update

# Install the chart
helm install animal-counter animal-counter/animal-counter \
  -f helm-values.yaml \
  -n animal-counter \
  --create-namespace

# Upgrade
helm upgrade animal-counter animal-counter/animal-counter \
  -f helm-values.yaml

# Uninstall
helm uninstall animal-counter
```

### Command Line Arguments

```bash
# Run with command line arguments
./animal-counter \
  --host 0.0.0.0 \
  --port 8080 \
  --config /etc/animal-counter/config.yaml \
  --log-level debug \
  --migrate

# Available flags
--host string          Host to bind to (default "0.0.0.0")
--port int            Port to listen on (default 8080)
--config string       Path to configuration file
--log-level string    Log level: debug, info, warn, error (default "info")
--migrate             Run database migrations on startup
--seed                Seed database with sample data
--version             Show version information
--help                Show help information
```

---

## Testing

### Unit Tests

```bash
# Run unit tests
docker run --rm animalcounter/app:latest test --verbose

# With coverage
docker run --rm animalcounter/app:latest test --coverage
```

### Integration Tests

```bash
# Run integration tests against a test database
docker run --rm \
  -e DB_TYPE=postgresql \
  -e DB_HOST=test-db \
  -e DB_NAME=test_animal_counter \
  -e DB_USER=test \
  -e DB_PASSWORD=test \
  animalcounter/app:latest test --integration
```

### End-to-End Tests

Create a test script:

```bash
#!/bin/bash
# e2e-test.sh

set -e

BASE_URL="${BASE_URL:-http://localhost:8080}"

echo "Running end-to-end tests..."

# Test 1: Health Check
echo "Test 1: Health Check"
curl -f "${BASE_URL}/health" || exit 1

# Test 2: Readiness Check
echo "Test 2: Readiness Check"
curl -f "${BASE_URL}/ready" || exit 1

# Test 3: Create Animal Sighting
echo "Test 3: Create Animal Sighting"
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/sightings" \
  -H "Content-Type: application/json" \
  -d '{
    "species": "deer",
    "count": 5,
    "location": "zone-a",
    "timestamp": "2024-01-15T10:30:00Z"
  }')
echo "Response: $RESPONSE"

# Test 4: Get All Sightings
echo "Test 4: Get All Sightings"
curl -f "${BASE_URL}/api/v1/sightings" || exit 1

# Test 5: Get Statistics
echo "Test 5: Get Statistics"
curl -f "${BASE_URL}/api/v1/statistics" || exit 1

# Test 6: File Browser Access
echo "Test 6: File Browser Access"
curl -f "http://localhost:30080/" || exit 1

echo "All tests passed!"
```

### Load Testing

```yaml
# k6-load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 10,
  duration: '1m',
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const baseUrl = 'http://animal-counter-service.animal-counter.svc.cluster.local';
  
  // Health check
  check(http.get(`${baseUrl}/health`), {
    'health check status 200': (r) => r.status === 200,
  });

  // Create sighting
  const payload = JSON.stringify({
    species: 'deer',
    count: Math.floor(Math.random() * 10) + 1,
    location: `zone-${Math.floor(Math.random() * 5)}`,
  });
  
  check(http.post(`${baseUrl}/api/v1/sightings`, payload, {
    headers: { 'Content-Type': 'application/json' },
  }), {
    'create sighting status 201': (r) => r.status === 201,
  });

  // Get sightings
  check(http.get(`${baseUrl}/api/v1/sightings`), {
    'get sightings status 200': (r) => r.status === 200,
  });

  sleep(1);
}
```

```bash
# Run load test
k6 run k6-load-test.js
```

### K3s Specific Tests

```bash
# Test pod scheduling
kubectl run test-pod --image=busybox --restart=Never -- sleep 3600
kubectl get pod test-pod -n animal-counter

# Test storage
kubectl exec -it animal-counter-0 -n animal-counter -- ls -la /data

# Test logs
kubectl logs -l app=animal-counter -n animal-counter --tail=100

# Test service connectivity
kubectl run curl --image=curlimages/curl --restart=Never --rm -it -- curl animal-counter-service.animal-counter.svc.cluster.local/health

# Test from inside cluster
kubectl run test-client --image=busybox --restart=Never -- \
  sh -c "nslookup animal-counter-service.animal-counter.svc.cluster.local"
```

---

## Troubleshooting

### Common Issues

#### Pod Issues

**Problem**: Pod is stuck in Pending state

```bash
# Check pod status
kubectl get pod animal-counter-0 -n animal-counter -o wide
kubectl describe pod animal-counter-0 -n animal-counter

# Check if PVC is bound
kubectl get pvc -n animal-counter

# Check node resources
kubectl describe nodes | grep -A 5 "Allocated resources"
kubectl top nodes
```

**Solution**:
```bash
# If PVC not bound, check storage class
kubectl get storageclass
kubectl describe pvc animal-counter-storage -n animal_counter

# If node resources insufficient, add more nodes or scale down replicas
kubectl scale deployment animal-counter --replicas=2 -n animal-counter
```

**Problem**: Pod is in CrashLoopBackOff

```bash
# Check logs
kubectl logs animal-counter-0 -n animal-counter --previous

# Check events
kubectl get events -n animal-counter --sort-by='.lastTimestamp'

# Describe pod for more details
kubectl describe pod animal-counter-0 -n animal-counter
```

**Solution**:
```bash
# Common causes: missing environment variables, database connection issues
# Fix ConfigMap or Secret
kubectl apply -f configmap.yaml
kubectl apply -f secret.yaml

# Restart deployment
kubectl rollout restart deployment/animal-counter -n animal-counter
kubectl rollout status deployment/animal-counter -n animal-counter
```

#### Service Issues

**Problem**: Service not accessible

```bash
# Check service endpoints
kubectl get endpoints animal-counter-service -n animal-counter

# Check if pods are ready
kubectl get pods -n animal-counter -l app=animal-counter

# Test service from another pod
kubectl run test --image=busybox --restart=Never --rm -it -- \
  wget -qO- http://animal-counter-service.animal-counter.svc.cluster.local/health
```

**Solution**:
```bash
# If no endpoints, check pod selector match
kubectl get svc animal-counter-service -n animal-counter -o yaml

# If selector is correct but no endpoints, check pod readiness
kubectl describe pod -l app=animal-counter -n animal-counter
```

#### Database Connection Issues

```bash
# Test database connectivity
kubectl run db-test --image=postgres:15 --restart=Never --rm -it -- \
  sh -c "apt-get update && apt-get install -y postgresql-client && \
  psql -h postgres-service.animal-counter.svc.cluster.local -U animalcounter -d animal_counter"

# Check database logs
kubectl logs -l app=animal-counter -n animal-counter | grep -i database

# Test from application pod
kubectl exec -it animal-counter-0 -n animal-counter -- \
  sh -c "nc -zv postgres-service.animal-counter.svc.cluster.local 5432"
```

#### Storage Issues

```bash
# Check PVC status
kubectl get pvc -n animal-counter

# Check PV
kubectl get pv

# Check if local-path-provisioner is running
kubectl get pods -n kube-system | grep local-path

# Check persistent volume claims events
kubectl describe pvc animal-counter-storage -n animal-counter

# If stuck in Pending, check storage class exists
kubectl get storageclass
```

#### CronJob Issues

```bash
# Check CronJob status
kubectl get cronjob animal-counter-export -n animal-counter

# Check last job status
kubectl get jobs -n animal-counter

# Manually trigger job
kubectl create job --from=cronjob/animal-counter-export manual-export -n animal-counter

# Check manual job logs
kubectl logs job/manual-export -n animal-counter
```

### Debugging Commands

```bash
# Get all resources in namespace
kubectl get all -n animal-counter

# Get events sorted by time
kubectl get events -n animal-counter --sort-by='.lastTimestamp'

# Watch pod status
kubectl get pods -n animal-counter -w

# Get resource usage
kubectl top pods -n animal-counter

# Get all labels
kubectl get pods --show-labels -n animal-counter

# Get pod YAML
kubectl get pod animal-counter-0 -n animal-counter -o yaml

# Edit resource live
kubectl edit deployment animal-counter -n animal-counter

# Port forward for debugging
kubectl port-forward -n animal-counter svc/animal-counter-service 8080:80
```

### Logs and Monitoring

```bash
# View application logs
kubectl logs -f -l app=animal-counter -n animal-counter --tail=1000

# View previous container logs (after restart)
kubectl logs -p -l app=animal-counter -n animal-counter

# Get logs for specific pod
kubectl logs animal-counter-0 -n animal-counter

# Check node logs
journalctl -u k3s -n 100

# Check container runtime
sudo crictl logs $(sudo crictl ps -q | head -1)
```

### Network Troubleshooting

```bash
# Check DNS resolution
kubectl run dns-test --image=busybox:1.36 --restart=Never --rm -it -- \
  nslookup animal-counter-service.animal-counter.svc.cluster.local

# Check network policies
kubectl get networkpolicies -n animal-counter

# Test pod-to-pod connectivity
kubectl run network-test --image=busybox:1.36 --restart=Never --rm -it -- \
  wget -qO- http://animal-counter-service.animal-counter.svc.cluster.local/health

# Check ingress
kubectl describe ingress animal-counter-ingress -n animal-counter

# Test external connectivity
kubectl run connectivity-test --image=curlimages/curl --restart=Never --rm -it -- \
  curl -v https://rancher.io
```

### Performance Issues

```bash
# Check resource limits
kubectl get limits -n animal-counter

# Check OOM events
kubectl get events -n animal-counter | grep OOMKilled

# Check pod resource usage
kubectl top pods -n animal-counter

# Describe node resources
kubectl describe nodes | grep -A 10 "Allocated resources"

# Check for throttling
kubectl logs -l app=animal-counter -n animal-counter | grep -i throttle
```

### Backup and Recovery

```bash
# Backup database
kubectl exec -it animal-counter-0 -n animal-counter -- \
  /app/backup.sh --output /data/backups/backup-$(date +%Y%m%d).sql

# Restore database
kubectl exec -it animal-counter-0 -n animal-counter -- \
  /app/restore.sh --input /data/backups/backup-20240115.sql

# Scale down for maintenance
kubectl scale deployment animal-counter --replicas=0 -n animal-counter

# Scale up after maintenance
kubectl scale deployment animal-counter --replicas=3 -n animal-counter

# Rolling restart
kubectl rollout restart deployment/animal-counter -n animal-counter
```

### Emergency Procedures

```bash
# Emergency: Force delete stuck pod
kubectl delete pod animal-counter-0 -n animal-counter --grace-period=0 --force

# Emergency: Restart K3s agent
sudo systemctl restart k3s-agent

# Emergency: View certificate issues
kubectl get csr
kubectl certificate approve <csr-name>

# Emergency: Reset cluster
sudo k3s-uninstall.sh
# Then reinstall with Ansible
ansible-playbook playbooks/install-k3s.yml
```

---

## Additional Resources

- K3s Documentation: https://docs.k3s.io/
- Ansible Documentation: https://docs.ansible.com/
- Kubernetes Documentation: https://kubernetes.io/docs/
- Animal Counter Application GitHub: https://github.com/your-repo/animal-counter

---

*Document Version: 1.0.0*  
*Last Updated: 2024*