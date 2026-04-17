## FEATURE:
Industrialiser le déploiement d’applications conteneurisées sur un Jetson Orin Nano sous JetPack 6.1 (Ubuntu 22.04), avec une architecture de micro‑services orchestrés par k3s et un minimum d’actions manuelles sur le device.

Objectifs fonctionnels :
- Disposer d’un cluster k3s sur le Jetson Orin Nano pour exécuter un service permettant de tester l’accélération GPU (via Docker/Containerd et runtime NVIDIA).
- Permettre la gestion à distance (MLOps / DevOps) des déploiements applicatifs (CI/CD vers k3s).

Objectifs d’industrialisation / “zero‑touch” :
- Supposer uniquement :
  - Flash JetPack 6.1 sur la carte SD depuis un PC.
  - Démarrage initial et configuration minimale (utilisateur, mot de passe, langue). Le nom de utilisateur sera nano-counter et le nom de la machine sera aussi nanocounter-desktop. Il sera connecté au wifi de ma box  
- Automatiser à distance :
  - La configuration réseau initiale pour créer un hotspot de connexion sur le orin (Wi‑Fi, IP fixe sur Ethernet, hotspot).
  - L’installation de la stack de base (Docker ou Containerd + runtime NVIDIA, k3s).
  - Le bootstrap de l’outillage d’auto‑gestion (Ansible/Pull, GitOps type Argo CD ou équivalent).
- Limiter les actions physiques sur le Jetson à :
  - Flash de l’image JetPack.
  - Branchement alimentation / Ethernet si nécessaire.

Use‑cases principaux :
- Déployer en série plusieurs Jetson Orin Nano sur le terrain avec un process reproductible.
- Permettre à un technicien non expert Linux/Kubernetes de préparer un Jetson en quelques étapes guidées.
- Gérer les mises à jour applicatives (micro‑services) sans intervention sur site (GitOps, playbooks Ansible, etc.).


## EXAMPLES
Le fichier ./examples/jetson_first_connect.sh contient un exemple de connexion pour la première fois sur le Orin en ssh.
Le répertoire ./examples/jetson_ssh_init contient un script exemple pour mettre le jetson Orin en Hotspot dessus et faire du ssh.

## DOCUMENTATION:
### Hypothèses techniques de base
- Plateforme cible :
  - Jetson Orin Nano Developer Kit avec JetPack 6.1
- Orchestration des conteneurs :
  - k3s (Kubernetes léger) déployé directement sur le Jetson.
- Stockage de configuration :
  - Un dépôt Git central (GitHub) contenant :
    - Playbooks/roles Ansible.
    - Manifests Helm/kustomize pour k3s.
    - Éventuellement /la configuration Argo CD ou équivalent GitOps.

### Flux global cible “from scratch”
1. Préparation physique et OS
   - Flasher JetPack 6.1 sur la carte SD depuis un PC (Balena Etcher, image officielle NVIDIA).
   - Boot du Jetson, configuration initiale (user, mot de passe, paramètres régionaux, wifi connecté à ma box locale).

2. Première connexion réseau
   - Connexion du Jetson à un Wi‑Fi existant pour obtenir un accès Internet (via interface graphique ou CLI ponctuelle).
   - Découverte du Jetson par son IP sur le réseau local (mDNS / DNS local) pour établir une première connexion SSH. S'inspirer de l'exemple
   
3. Configuration réseau automatisée (via Ansible)
   - Mettre en variables d'environnement les informations de connexion au Jetson. S'inpirer de l'exemple jetson_first_connect.sh pour récupérer l'IP du Jetson ainsi que l'utilisateur et mot de passe. 
   - Playbook Ansible exécuté depuis une machine d’admin, ciblant le Jetson via SSH :
     - Installation de `community.general` pour `nmcli`.
     - Installation la clé SSH.
     - Configuration de l’interface Wi‑Fi comme hotspot :
       - SSID dédié (ex: `JetsonCounter`).
       - Mot de passe WPA2.
       - Attribution d’un plan d’adressage dédié (ex: 192.168.50.1/24).
       - Activation du DHCP pour les clients (dnsmasq ou NetworkManager).
     - Création d’une connexion Ethernet statique (par exemple `enp1s0-static`) :
       - IP fixe, masque, gateway, DNS, activation automatique.
   - Après exécution :
     - Possibilité de se connecter au Jetson par ssh, en se connectant sur le hotspot du Jetson.

4. Installation de la stack container + k3s (automatisée)
   - Toujours via Ansible (depuis l’admin, une fois la connectivité SSH fiable) :
     - Installation des dépendances NVIDIA pour le support GPU dans les conteneurs (runtime NVIDIA fourni avec JetPack, configuration nvidia-container-toolkit si besoin).
     - Installation de Docker ou Containerd (si non déjà présent) et configuration pour autoriser l’accès GPU.
     - Installation de k3s avec les options compatibles Jetson (cgroup driver, flannel ou autre CNI suivant les retours de compatibilité JetPack 6.x).
   - Vérifications automatisées :
     - k3s node `Ready`.
     - Pod test utilisant le GPU (device query) pour valider l’accès GPU depuis un pod.

5. Mise en place de GitOps / orchestration applicative
   - Choix 1 : Ansible comme orchestrateur principal
     - Playbooks pour :
       - Déployer/mettre à jour les manifests Kubernetes (via `kubernetes.core`).
       - Gérer la configuration applicative (ConfigMap, Secret).
     - Possibilité de mettre en place Ansible Pull sur le Jetson pour qu’il se mette à jour tout seul en périodique depuis un dépôt Git.

   - Choix 2 : GitOps avec Argo CD (ou équivalent léger)
     - Argo CD déployé dans k3s (en tant que controleur GitOps).
     - Un repo Git “environnement Jetson” définissant :
       - Ingress/Service config pour l’exposition via le réseau local / hotspot.
     - Flux :
       - Commit sur Git → Argo CD sync → déploiement automatique sur le Jetson.

   - Dans les deux cas :
     - L’admin ne fait plus que :
       - Gérer les repos Git.
       - Éventuellement lancer des playbooks Ansible pour les opérations de base (OS, réseau, k3s upgrade).

## Artefacts à produire (alignés avec le flux global cible)
### 📦 Repository “infra” (bootstrap + provisioning Jetson)
#### 0. Variables d'environnements
Elles sont définies dans le fichier .env.local et devront être copiées dans le .env.example et explotées dans les scripts ou dans les playbooks
#### 1. Scripts de bootstrap (pré-Ansible)
Correspond aux étapes 2 et début 3 du flux.
* `install_ansible.sh`
  Installation d’Ansible (WSL2 / Linux admin)
* `jetson_discover.sh`
  * Scan réseau (mDNS / nmap / arp). S'inspirer du script example jetson_first_connect.sh pour récupérer l'IP du jetson ainsi que les données de connexions/
  * Détection IP du Jetson
  * Export automatique :

```bash
export JETSON_IP=...
export JETSON_USER=nano-counter
```
* `jetson_first_access.sh`

  * Wrapper autour de l’exemple existant
  * Test SSH (authentification par mot de passe)
  * Préparation de l’inventaire Ansible dynamique

---
#### 2. Inventaire & variables Ansible (industrialisation)
Permet la gestion multi-Jetson et le déploiement en série.

* `inventory/jetsons.yml`

```yaml
all:
  hosts:
    jetson-01:
      ansible_host: "{{ lookup('env', 'JETSON_IP') }}"
      ansible_user: nano-counter
```

* `group_vars/all.yml`

```yaml
jetson_hostname: nanocounter-desktop

wifi_hotspot:
  ssid: JetsonCounter
  password: "ChangeMe123"
  ip: 192.168.50.1/24

ethernet_static:
  interface: enp1s0
  ip: 192.168.1.50/24
  gateway: 192.168.1.1
```

---
#### 3. Playbooks Ansible (structurés par phase du flux)
##### 🔐 `network_ssh.yml`

Étape 3 : sécurisation de l’accès

* Installation des paquets de base
* Configuration SSH :

  * Ajout de clé publique
  * Désactivation du login par mot de passe (optionnel)
* Configuration du hostname
* Hardening minimal

---
##### 🌐 `network_setup.yml`
Étape 3 : configuration réseau automatisée

* Configuration hotspot WiFi (`nmcli`)
* DHCP via NetworkManager
* IP statique Ethernet
* Activation automatique au boot

---
##### ⚙️ `install_container_runtime.yml`
Étape 4 : prérequis container

* Vérification du runtime NVIDIA (JetPack)
* Installation / configuration :

  * containerd ou docker
  * nvidia-container-toolkit
* Test GPU (ex: `docker run` ou équivalent Jetson)

---
##### ☸️ `install_k3s.yml`
Étape 4 : orchestration Kubernetes

* Installation de k3s (version figée)
* Paramétrage spécifique Jetson :

  * cgroups
  * désactivation Traefik si nécessaire
* Vérifications :

  * node `Ready`
  * accès `kubectl`

---
##### 🧪 `validate_gpu_k8s.yml`
Étape 4 : validation GPU dans Kubernetes

* Déploiement d’un pod test GPU
* Vérification des logs (device query)
* Nettoyage

---
##### 🔁 `deploy_gitops.yml`
Étape 5 : déploiement GitOps

* Installation Argo CD **ou**
* Mise en place Ansible Pull :

  * cron job
  * dépôt Git cible
* Bootstrap initial des applications

---
#### 4. Orchestrateur global
Point d’entrée unique pour un déploiement “zero-touch”.

* `bootstrap_jetson.yml`

```yaml
- import_playbook: network_ssh.yml
- import_playbook: network_setup.yml
- import_playbook: install_container_runtime.yml
- import_playbook: install_k3s.yml
- import_playbook: validate_gpu_k8s.yml
- import_playbook: deploy_gitops.yml
```

---
#### 5. Rôles Ansible (recommandé pour industrialisation)
```text
roles/
  common/
  network/
  ssh/
  container_runtime/
  k3s/
  gpu_test/
  gitops/
```

Permet :

* Réutilisation
* Maintenance simplifiée
* Déploiement multi-devices

---
#### 6. Documentation
* `docs/`

  * `01_quickstart.md` → guide technicien (simplifié)
  * `02_bootstrap_detail.md` → flux détaillé
  * `03_multi_jetson.md` → déploiement en série
  * `04_troubleshooting.md`
  * `05_reset_procedure.md`

---
#### 7. Script utilisateur “one-shot”
Simplifie l’expérience terrain.

* `prepare_jetson.sh`

Fonctions :

1. Découverte IP
2. Export variables
3. Lancement Ansible

Exemple :

```bash
git clone <repo-infra>
cd infra
./prepare_jetson.sh
```

Objectif : atteindre un déploiement quasi “zero-touch”.

---
### 📦 Repository “apps” (GitOps / workloads)
#### 1. Structure des applications

```text
apps/
  gpu-test/
  ingress/
  core-services/
```

---
#### 2. Packaging Kubernetes

* Helm charts :

  * Service GPU test
  * Ingress
  * APIs

OU

* Kustomize :

  * `dev/`
  * `prod/`
  * `edge/jetson`

---
#### 3. Configuration GitOps (Argo CD)

```text
argocd/
  applications.yaml
  projects.yaml
```

Flux :
Git → Argo CD → k3s → Jetson

---
#### 4. CI/CD

* `.github/workflows/build.yml`

  * Build image Docker
  * Push vers registry

* `.github/workflows/deploy.yml`

  * Mise à jour des manifests
  * Synchronisation Argo CD

---


## OTHER CONSIDERATIONS:
### Choix de l’outil d’automatisation
- Ansible :
  - Avantages :
    - Mature, très adapté à la configuration OS/réseau (modules `nmcli`, `user`, `apt`, etc.).[web:3][web:6][web:9]
    - Facile à exécuter depuis un laptop d’admin.
    - Idéal pour la phase bootstrap (réseau, dépendances, k3s).
  - Limites :
    - Moins “déclaratif” sur la partie applicative continue que GitOps pur, nécessite des exécutions manuelles ou Ansible Pull.

- Argo CD (ou GitOps similaire) :
  - Avantages :
    - Automatisation continue du déploiement applicatif à partir de Git.
    - Forte traçabilité des versions déployées.
  - Limites :
    - Ajoute de la complexité (un contrôleur complet dans k3s).
    - Nécessite une configuration initiale (qu’on fera probablement via Ansible).

- Stratégie recommandée :
  - Phase 1 : Ansible pour tout le bootstrap (réseau, k3s, prérequis GPU).
  - Phase 2 : GitOps (Argo CD ou équivalent) uniquement pour les workloads Kubernetes applicatifs.
  - Option : garder des playbooks Ansible pour les opérations d’OS (upgrade JetPack, maintenance système).

### Compatibilité JetPack 6.x / k3s
- JetPack 6.1 apporte Jetson Linux R36 et Ubuntu 22.04, ce qui peut impacter la compatibilité de certains runtimes ou CNI k3s.
- Action :
  - Valider une configuration k3s minimale “référence” pour Orin Nano + JetPack 6.2.2 :
    - Version de k3s.
    - CNI (flannel, calico ou autre).
    - Paramètres de runtime container (cgroup driver, modules kernel).
    - Vigilance sur les ressources pour empêcher les saturations mémoires, logs, inodes.

### Sécurité et accès
- Usage de clés SSH (interdiction des mots de passe sur SSH en prod).
- Rotation des mots de passe de l’utilisateur local Jetson.
- Configuration d’un firewall de base (UFW ou nftables) :
  - Ouverture uniquement des ports nécessaires :
    - SSH.
    - HTTP/HTTPS pour l’interface web.
    - Ports internes k3s si besoin de multi‑nœuds à terme.
- Sécurisation du hotspot :
  - WPA2 avec mot de passe robuste.
  - Possibilité de restreindre les IPs autorisées via firewall.

### Observabilité et maintenance
- Mettre en place :
  - Logs applicatifs consolidés (stdout/err → stack type Loki/Promtail ou centralisation plus simple).
  - Monitoring basique (Prometheus/Grafana léger, ou métriques exportées vers une instance centrale).
- Prévoir :
  - Gestion des ressources pour ne pas saturer le Jetson (log, mémoire, Inodes).
  - Procédure de “reset” du Jetson :
    - Reflash JetPack (procédure documentée).
    - Rebootstrap automatisé via Ansible / GitOps.

### Roadmap indicative
- Étape 1 : POC local
  - Un Jetson Orin Nano, configuration JetPack 6.1.
  - Playbook Ansible minimal pour IP statique + hotspot.
  - Installation manuelle puis automatisée de k3s.
- Étape 2 : Industrialisation
  - Structuration des repos infra + apps.
  - GitOps en place (Argo CD ou équivalent).
  - Documentation pas‑à‑pas pour un technicien terrain.
- Étape 3 : Durcissement et observabilité
  - Sécurité réseau, logs centralisés, monitoring.
  - Stratégies de sauvegarde et de mise à jour à grande échelle.
