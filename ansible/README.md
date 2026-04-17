# Ansible Playbooks pour Jetson Nano Orin

Ce dossier contient les playbooks Ansible pour configurer et déployer l'application de comptage de cochons sur les Jetson Nano Orin.

## Structure Globale

```
.
├── ansible/               # Playbooks et configuration Ansible
│   ├── group_vars/        # Variables globales
│   ├── inventory/         # Inventaire des hôtes
│   ├── playbooks/         # Playbooks principaux
│   └── README.md          # Documentation (ce fichier)
│
├── scripts/               # Scripts d'automatisation
│   ├── prepare_jetson.sh  # Script principal de préparation
│   ├── jetson_discover.sh  # Découverte automatique des Jetson
│   ├── jetson_first_access.sh # Test de connexion SSH
│   └── install_ansible.sh  # Installation d'Ansible
│
└── .env.local             # Fichier de variables d'environnement (à créer)
```

## Préparation du Jetson Nano Orin

### 1. Téléchargement des outils nécessaires

Avant de commencer, préparez votre Jetson Nano Orin avec les éléments suivants :

- **JetPack 6.1 Rev.1** pour SD Card
  - Téléchargez depuis le site NVIDIA : [JetPack 6.1 Rev.1](https://developer.nvidia.com/embedded/jetpack)
  - Cette version permet de passer le Orin Nano en mode "Super Orin Nano"

- **SD Card Formatter**
  - Téléchargez depuis : [SD Card Formatter](https://www.sdcard.org/downloads/formatter/)
  - Carte SD minimum 64 Go requise

- **BalenaEtcher**
  - Téléchargez depuis : [BalenaEtcher](https://www.balena.io/etcher/)
  - Outil pour flasher l'image sur la carte SD

### 2. Préparation de la carte SD

1. **Formater la carte SD** :
   - Utilisez SD Card Formatter
   - Formatage rapide (pas besoin de donner un nom de libellé)
   - Assurez-vous que la carte est bien de 64 Go minimum

2. **Flasher l'image JetPack** :
   - Dézippez l'ISO du JetPack 6.1 Rev.1
   - Utilisez BalenaEtcher pour transférer l'image sur la carte SD
   - Désactivez la vérification après installation (non nécessaire)

3. **Installer la carte SD** :
   - Réinsérez la carte SD dans le Jetson Nano Orin
   - Branchez les périphériques : clavier, écran, souris, caméra

### 3. Première configuration du Jetson

1. **Démarrage initial** :
   - Allumez le Jetson Nano Orin
   - Suivez l'assistant de configuration

2. **Création de l'utilisateur** :
   - Nom d'utilisateur : `nano-counter`
   - Nom du Jetson : `nanocounter-desktop`

3. **Configuration réseau** :
   - Configurez le WiFi pour vous connecter à Internet
   - Sélectionnez votre box WiFi

4. **Paramètres système** :
   - Langue : Anglais (par défaut)
   - Timezone : France
   - Refusez l'installation de Chromium
   - Laissez les autres options par défaut

5. **Finalisation** :
   - Attendez la fin de l'installation
   - Le système redémarrera automatiquement

## Prérequis Logiciels

- Ansible 2.9+
- Python 3.6+
- `sshpass` pour l'authentification par mot de passe
- Accès réseau aux devices Jetson
- **Clés SSH** : Paire de clés publique/privée générée sur votre machine de contrôle

## Configuration SSH

### Génération des clés SSH (sur votre ordinateur local)

Avant d'exécuter les playbooks, générez une paire de clés SSH si vous ne l'avez pas déjà :

```bash
# Générer une paire de clés SSH (à exécuter sur votre ordinateur local)
ssh-keygen -t ed25519 -C "jetson-deploy"

# Ou pour une clé RSA (si ed25519 n'est pas supporté)
ssh-keygen -t rsa -b 4096 -C "jetson-deploy"
```

> ⚠️ **Important** : Ne pas mettre de phrase secrète (passphrase) pour permettre l'automatisation.

### Configuration de la clé publique

La clé publique (`~/.ssh/id_ed25519.pub` ou `~/.ssh/id_rsa.pub`) sera automatiquement installée sur le Jetson par Ansible lors de l'exécution du playbook `network_ssh.yml`.

Si vous souhaitez installer manuellement la clé publique sur le Jetson :

```bash
# Copier manuellement la clé publique sur le Jetson
ssh-copy-id -i ~/.ssh/id_ed25519.pub nano-counter@$JETSON_IP

# Ou pour une clé RSA
ssh-copy-id -i ~/.ssh/id_rsa.pub nano-counter@$JETSON_IP
```

## Configuration Initial

### 1. Préparer le Jetson Nano Orin

Avant d'exécuter les scripts Ansible, assurez-vous que votre Jetson Nano Orin est correctement préparé selon les instructions de la section [Préparation du Jetson Nano Orin](#préparation-du-jetson-nano-orin).

### 2. Installer les dépendances sur votre ordinateur local

> ⚠️ **Important** : Ces étapes doivent être exécutées sur votre **machine de contrôle** (votre ordinateur local), pas sur le Jetson.

```bash
# Installer Ansible (si nécessaire) - À exécuter sur votre ordinateur local
bash scripts/install_ansible.sh

# Installer sshpass (pour l'authentification par mot de passe) - À exécuter sur votre ordinateur local
sudo apt install sshpass
```

### 2. Créer le fichier .env.local

Créez un fichier `.env.local` à la racine du projet :

```bash
# Jetson Connection
JETSON_USER=nano-counter
JETSON_PASSWORD=votre_mot_de_passe

# Réseau pour la découverte automatique
WIFI_NETWORK=192.168.1.0/24

# Hotspot WiFi
JETSON_HOTSPOT_SSID=JetsonCounter
JETSON_HOTSPOT_PASSWORD=ChangeMe123
JETSON_HOTSPOT_IP=192.168.50.1/24
JETSON_HOTSPOT_INTERFACE=wlP1p1s0

# Ethernet
JETSON_ETH_INTERFACE=enP8p1s0
JETSON_ETH_IP=192.168.1.50/24
JETSON_ETH_GATEWAY=192.168.1.1

# Application countingapp
APP_NAMESPACE=countingapp-dev
APP_NAME=countingapp
APP_VERSION=local
APP_PORT=31501
APP_PATH=/media/nano-counter/data/orin/git/animal-counting/app
FILES_PATH=/media/nano-counter/data/orin/files
MAX_LOG_FILES=50
LOG_MAX_SIZE=100M
IMAGE_NAME=countingapp
IMAGE_TAG=local
VIDEO_DEVICE=/dev/video0
```

## Utilisation des Scripts

### Script Principal : prepare_jetson.sh

Ce script automatise tout le processus en 3 étapes :

1. **Découverte du Jetson** - Scanne le réseau pour trouver le device
2. **Test de connexion SSH** - Vérifie l'accès SSH
3. **Exécution Ansible** - Lance le playbook de bootstrap

**Exécution complète** :
```bash
cd /chemin/vers/animal-counter
bash scripts/prepare_jetson.sh
```

### Découverte Manuelle : jetson_discover.sh

Scanne le réseau pour trouver les Jetson accessibles :

```bash
bash scripts/jetson_discover.sh
```

Ce script :
- Scanne le réseau défini par `WIFI_NETWORK`
- Teste la connexion SSH avec les identifiants fournis
- Exporte `JETSON_IP` dans `/tmp/jetson_env.sh`

### Test de Connexion : jetson_first_access.sh

Teste la connexion SSH à un Jetson spécifique :

```bash
# Après avoir défini JETSON_IP
export JETSON_IP=192.168.1.50
bash scripts/jetson_first_access.sh
```

## Playbooks Ansible

### bootstrap_jetson.yml (Playbook Principal)

Exécute toutes les étapes de configuration dans l'ordre :

1. **Configuration SSH** (`network_ssh.yml`)
   - Sécurise la configuration SSH
   - Configure l'authentification par clé
   - Désactive l'authentification par mot de passe

2. **Configuration Réseau** (`network_setup.yml`)
   - Configure le hotspot WiFi
   - Configure l'interface Ethernet
   - Active le routage entre interfaces

3. **Installation LXDE** (`install_lxde.yml`)
   - Installe LXDE avec LightDM
   - Configure le gestionnaire d'affichage léger
   - Désactive GDM si présent

4. **Optimisation Système** (intégré)
   - Désactive les services inutiles
   - Désactive snapd complètement
   - Active le mode Super Orin (MAXN)
   - Active les fréquences maximales CPU/GPU

5. **Runtime Conteneurs** (`install_container_runtime.yml`)
   - Installe Docker
   - Configure NVIDIA Container Toolkit
   - Configure les permissions utilisateur

5. **Installation k3s** (`install_k3s.yml`)
   - Installe k3s avec support GPU
   - Configure le réseau pour k3s
   - Désactive Traefik (inclus dans k3s)

**Tags disponibles** :
- `ssh` - Configuration SSH uniquement
- `network` - Configuration réseau uniquement
- `lxde` - Installation LXDE uniquement
- `optimize` - Optimisation système uniquement
- `container` - Installation runtime conteneurs uniquement
- `k3s` - Installation k3s uniquement
- `info` - Messages d'information

### Exécution Directe avec Ansible

**Exécution complète** :
```bash
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml
```

**Optimisation système uniquement** :
```bash
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags optimize
```

**Vérification de syntaxe** :
```bash
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --syntax-check
```

## Optimisation Système

Le playbook inclut une étape d'optimisation qui :

1. **Installe LXDE avec LightDM** :
   - `lxde-core` - Environnement de bureau léger
   - `lxterminal` - Terminal léger
   - `lxappearance` - Outil de personnalisation
   - `lightdm` - Gestionnaire d'affichage léger
   - `lightdm-gtk-greeter` - Écran de connexion graphique

2. **Désactive les services inutiles** :
   - `bluetooth` - Service Bluetooth
   - `avahi-daemon` - Découverte de services réseau
   - `ModemManager` - Gestion des modems
   - `packagekit` - Mises à jour automatiques
   - `kerneloops` - Surveillance des erreurs noyau

> ℹ️ **Note** : GDM est remplacé par LightDM qui est plus léger et mieux adapté aux Jetson.

3. **Désactive snapd** :
   - Désactive le service snapd
   - Désactive le socket snapd

4. **Active le mode Super Orin** :
   - `sudo nvpmodel -m 2` - Passe en mode MAXN (Super Orin)
   - `sudo jetson_clocks` - Active les fréquences maximales CPU/GPU

> ⚠️ **Important** : Ces commandes activent les performances maximales du Jetson Nano Orin, ce qui peut augmenter la consommation électrique et la température. Assurez-vous d'avoir un refroidissement adéquat.

## Workflow Complet

### Première Installation

```bash
# 1. Installer les dépendances
bash scripts/install_ansible.sh
sudo apt install sshpass

# 2. Configurer l'environnement
cp .env.example .env.local
nano .env.local  # Modifier avec vos valeurs

# 3. Exécuter le processus complet
bash scripts/prepare_jetson.sh
```

### Mise à Jour/Reconfiguration

```bash
# Pour réexécuter seulement l'optimisation système
export JETSON_IP=192.168.1.50
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --tags optimize
```

## Variables Importantes

### Dans `group_vars/all.yml`

- `wifi_hotspot` : Configuration du hotspot WiFi
- `ethernet_static` : Configuration Ethernet
- `ssh_config` : Configuration SSH
- `k3s_config` : Configuration k3s (version, interface, etc.)
- `install_nvidia_docker` : Chemins des scripts d'installation

### Dans `.env.local`

- `JETSON_USER` : Utilisateur SSH (défaut: nano-counter)
- `JETSON_PASSWORD` : Mot de passe SSH
- `WIFI_NETWORK` : Réseau pour la découverte (ex: 192.168.1.0/24)
- `JETSON_HOTSPOT_SSID` : Nom du hotspot WiFi
- `JETSON_HOTSPOT_PASSWORD` : Mot de passe du hotspot

## Dépannage

### Erreur de Découverte

```bash
# Vérifier que le Jetson est sur le même réseau
ping 192.168.1.50

# Vérifier que SSH est accessible
nmap -p 22 192.168.1.50

# Vérifier les identifiants
ssh nano-counter@192.168.1.50
```

### Échec de Connexion SSH

- Vérifiez que SSH est activé sur le Jetson
- Vérifiez le mot de passe dans `.env.local`
- Installez `sshpass` si vous utilisez l'authentification par mot de passe
- Pour l'authentification par clé, configurez votre clé publique sur le Jetson

### Échec d'Ansible

```bash
# Vérifier la syntaxe
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --syntax-check

# Exécuter en mode check (dry-run)
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml --check

# Exécuter avec plus de verbosité
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/bootstrap_jetson.yml -vvv
```

## Bonnes Pratiques

1. **Testez d'abord en mode check** :
   ```bash
   ansible-playbook -i inventory/jetsons.yml playbooks/bootstrap_jetson.yml --check
   ```

2. **Utilisez les tags** pour exécuter seulement les parties nécessaires

3. **Sauvegardez la configuration** avant d'exécuter les playbooks

4. **Vérifiez les logs** après chaque exécution

5. **Testez sur un seul device** avant de déployer sur plusieurs

6. **Utilisez les scripts** pour automatiser le processus complet

## Architecture Cible

Après exécution complète, le Jetson aura :
- ✅ Environnement LXDE minimal installé
- ✅ Services inutiles désactivés
- ✅ Docker avec support NVIDIA GPU
- ✅ Cluster k3s opérationnel
- ✅ Hotspot WiFi configuré
- ✅ Interface Ethernet avec IP statique
- ✅ SSH sécurisé
- ✅ Application de comptage de cochons prête au déploiement

## Commandes Utiles

```bash
# Vérifier l'état des services après optimisation
ssh nano-counter@$JETSON_IP "systemctl status bluetooth avahi-daemon snapd"

# Vérifier l'installation de Docker
ssh nano-counter@$JETSON_IP "docker --version"

# Vérifier l'état de k3s
ssh nano-counter@$JETSON_IP "sudo k3s kubectl get nodes"

# Accéder à l'application
# Après déploiement, l'application sera accessible via le hotspot WiFi

## Support

Pour les problèmes persistants :
1. Vérifiez les logs Ansible
2. Consultez la documentation NVIDIA pour les Jetson
3. Vérifiez la connectivité réseau
4. Assurez-vous que les variables d'environnement sont correctement définies
