# Plan: Chaîne de développement autonome avec validation Jetson

## Contexte

Le système de comptage de cochons fonctionne sur un Jetson Orin dans un cluster K3s.
L'application Python (YOLO/TensorRT + OCSORT + comptage) est déployée via Ansible.
Le code de l'app est monté via volume hostPath (pas baked dans l'image Docker).

**Objectif**: Permettre à Pi.dev de développer, valider sur le Jetson, et itérer
autonomement jusqu'à obtention d'un résultat métier correct, puis créer une PR.

## État de l'existant (exploration)

### Application
- `app/src/main.py` — point d'entrée, mode FILE via `--input=FILE --file=...`
- `app/entrypoint.sh` — mode `test` qui lance `./video/test_640.mp4` en FILE
- `app/src/core/counting.py` — logique de comptage, résultat dans `counter_to_right`
- Quand la vidéo se termine en mode FILE → stop_event, fin des threads
- **Pas de sortie structurée** du résultat final (uniquement logs `logger.info`)
- `app/.env` — config de l'application (seuils, offsets, etc.)

### Déploiement
- `ansible/playbooks/app/build_countingapp.yml` — rsync `app/` → Jetson + docker build
- `ansible/playbooks/app/deploy_countingapp.yml` — render templates K8s + kubectl apply
- Code monté via volume (`dev-app` → `/app` sur le Jetson)
- Image Docker = environnement Python uniquement (pas le code app)
- → **Pas besoin de rebuild l'image pour des changements de code** (rsync suffit)

### K3s
- `k3s/templates/countingapp-test.j2` — Job K8s qui lance le mode `test`
  - Déjàexists mais **commenté** dans le playbook de déploiement
  - Nom fixe `countingapp-test`, `ttlSecondsAfterFinished: 30`, `backoffLimit: 0`
- `k3s/templates/build-engine-batch.j2` — Job pour build le moteur TensorRT

### Réseau & accès Jetson
- `.env.local` — Jetson accessible via SSH, IP Ethernet `192.168.50.10`
- `scripts/jetson_discover.sh` — découverte automatique sur le réseau
- Dev machine = WSL (`/mnt/c/Dev/ai/animal-counter`)

### Archon / Pi.dev
- `.archon/workflows/archon-piv-loop.yaml` — PIV loop complet (explore→plan→impl→validate→PR)
- `.archon/workflows/archon-plannotator-piv.yaml` — PIV avec plannotator gate
- `.archon/HOW_TO_RUN_PIV.md` — procédure pour lancer le workflow
- `.archon/config.yaml` — config Pi.dev + plannotator
- **Les workflows existants utilisent `bun run validate`** (patterns JS/TS) — inadapté pour ce projet Python/Jetson
- Git remote: `https://github.com/wloonis/animal-counter.git`, branche `main`

### Vidéos
- `app/video/` contient: `test_640.mp4`, `test_640_2.mp4`, `demo_640_480.mp4`, `demo.mp4`
- `video/` est dans `.gitignore` — les vidéos ne sont PAS commitées
- L'utilisateur mentionne `template-640.mp4` (n'existe pas encore dans le repo)
- `entrypoint.sh` mode test utilise `./video/test_640.mp4`

## Questions ouvertes (en attente de réponse utilisateur)

1. **Vidéo de référence**: `template-640.mp4` — est-ce un renommage d'une vidéo existante
   (laquelle?) ou une nouvelle vidéo? Doit-elle être commitée au repo (retirer `video/`
   du `.gitignore` pour ce fichier) ou gardée uniquement sur le Jetson?

2. **Résultat attendu**: Quelle est la valeur de comptage attendue pour la vidéo de
   référence? Où stocker cette valeur (fichier de config, env var)?

3. **Tolérance**: Le résultat doit-il être exactement égal ou une tolérance est-elle
   acceptable (ex: ±1)?

4. **Déclenchement**: La validation doit-elle être déclenchée par GitHub Actions
   (nécessite Jetson accessible depuis internet) ou par un script local sur la machine
   de dev (Archon workflow qui SSH dans le Jetson)?

5. **Accessibilité Jetson**: Le Jetson est-il toujours accessible à une IP fixe connue,
   ou faut-il le découvrir à chaque fois via `jetson_discover.sh`?

## Approche proposée (préliminaire)

### Vue d'ensemble

```
Pi.dev (Archon)                    Jetson Orin (K3s)
    │                                    │
    ├── 1. Développe sur branche          │
    ├── 2. Push vers GitHub               │
    ├── 3. Déclenche validation ─────────┼──► rsync code → /app
    │                                    ├── K8s Job: run validate mode
    │                                    ├── Écrit result.json
    ├── 4. Récupère result.json ◄────────┤
    ├── 5. Analyse résultat               │
    ├── 6. Si FAIL → corriger → goto 1   │
    └── 7. Si PASS → créer PR            │
```

### Composants à créer/modifier

#### 1. Mode `validate` dans `entrypoint.sh`
- Nouveau mode qui lance l'app en FILE sur la vidéo de référence
- Capture le résultat final et écrit un JSON structuré
- Arguments: chemin vidéo, chemin output JSON

#### 2. Sortie structurée dans `main.py`
- À la fin du traitement (mode FILE, vidéo terminée), écrire un fichier JSON:
  ```json
  {
    "count": <int>,
    "video_file": "<name>",
    "timestamp": "<ISO>",
    "duration_seconds": <float>,
    "status": "completed" | "error",
    "error": null | "<message>"
  }
  ```
- Écriture dans le volume monté (`/files/` ou chemin configurable)

#### 3. Template K8s Job de validation: `k3s/templates/countingapp-validate.j2`
- Basé sur `countingapp-test.j2` mais:
  - Args: `["validate"]`
  - `generateName` pour éviter les conflits de nom
  - Écrit le résultat dans le volume `/files/`
  - Pas de `ttlSecondsAfterFinished` (on garde les logs)

#### 4. Script de validation: `scripts/validate_on_jetson.sh`
- Charge `.env.local`
- Rsync le code de la branche vers le Jetson
- Supprime l'ancien Job de validation s'il existe
- Crée et lance le nouveau Job via `kubectl`
- Attend la complétion (avec timeout)
- Récupère le fichier de résultats via SSH
- Récupère les logs du Job
- Compare le résultat avec la valeur attendue
- Écrit un rapport JSON structuré pour Pi.dev
- Retourne 0 (pass) ou 1 (fail)

#### 5. Config de validation: `validation/config.json`
```json
{
  "reference_video": "template-640.mp4",
  "expected_count": <à définir>,
  "tolerance": 0
}
```

#### 6. Nouveau workflow Archon: `.archon/workflows/archon-jetson-dev.yaml`
- Basé sur `archon-piv-loop.yaml` adapté pour Python/Jetson:
  - **Explore** — conversation avec l'utilisateur
  - **Plan** — plannotator gate (comme existant)
  - **Implement** — task-by-task avec commits (adapté Python, pas `bun`)
  - **Jetson Validate** — exécute `scripts/validate_on_jetson.sh`
    - Si FAIL: feed le rapport d'erreur à Pi.dev, retour à Implement
    - Si PASS: continue
  - **Finalize** — push + create PR
- Loop automatique jusqu'à validation ou max retries

### Réutilisation de l'existant
- `ansible/playbooks/app/build_countingapp.yml` — logique de rsync (à réutiliser/extraire)
- `k3s/templates/countingapp-test.j2` — base pour le template de validation
- `scripts/jetson_discover.sh` — découverte du Jetson
- `.env.local` — variables de connexion
- `archon-piv-loop.yaml` — structure du workflow PIV

## Risques identifiés

1. **Durée de validation**: Le traitement de la vidéo + rsync peut prendre plusieurs minutes.
   Le workflow doit avoir des timeouts généreux.
2. **Conflits de Job K8s**: Les Jobs sont immuables — nécessite delete + recreate.
3. **Modèle TensorRT**: Le fichier `.engine` doit exister sur le Jetson. Si le code change
   la logique d'inférence, le moteur peut nécessiter un rebuild.
4. **État du Jetson**: Si l'app principale tourne en mode CAMERA, le Job de validation
   peut entrer en conflit pour les ressources GPU.
5. **Vidéos non commitées**: `video/` est dans `.gitignore`. La vidéo de référence doit
   être disponible sur le Jetson indépendamment du repo.

## Steps (à détailler après réponses aux questions)

- [ ] Définir la vidéo de référence et le résultat attendu
- [ ] Ajouter le mode `validate` à `entrypoint.sh`
- [ ] Ajouter l'écriture du résultat JSON dans `main.py`
- [ ] Créer le template K8s `countingapp-validate.j2`
- [ ] Créer le script `scripts/validate_on_jetson.sh`
- [ ] Créer `validation/config.json`
- [ ] Créer le workflow Archon `archon-jetson-dev.yaml`
- [ ] Tester la validation end-to-end manuellement
- [ ] Tester le workflow complet avec Pi.dev

## Verification

1. Lancer `scripts/validate_on_jetson.sh` manuellement → doit produire un rapport JSON
2. Le rapport doit contenir le count attendu et le statut pass/fail
3. Lancer le workflow Archon avec une tâche simple → Pi.dev doit pouvoir:
   - Implémenter, valider sur le Jetson, lire le rapport, itérer si nécessaire
4. Vérifier que les logs K8s sont récupérables après la validation