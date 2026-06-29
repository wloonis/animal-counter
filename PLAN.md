# Plan: Chaîne de développement autonome avec validation métier sur Jetson

## Summary

Créer une chaîne de développement autonome où Pi.dev code sur une branche Git,
valide le résultat métier sur le Jetson Orin via une vidéo de référence
(`template-validation-9.mp4`, résultat attendu = 9 dérivé du nom de fichier),
itère jusqu'à validation, puis crée une PR draft. La boucle d'itération distingue
les **count mismatches métier** (PAUSE HITL — pas d'auto-correction) des
**erreurs d'exécution/infra** (auto-reprise limitée par `max_iterations`).

## In Scope

- Mode `validate` dans `entrypoint.sh` (lance la vidéo de référence en FILE)
- Sortie JSON structurée du résultat dans `main.py` (count, video, timestamp, etc.)
- Template K8s Job `countingapp-validate.j2` (basé sur `countingapp-test.j2`)
- Script single-shot `scripts/validate_on_jetson.sh` (SSH → rsync → Job → poll → result.json → comparaison → rapport)
- Config `validation/config.json` (tolerance, timeout, max_iterations — PAS de expected_count)
- Vidéo de référence `validation/videos/template-validation-9.mp4` commitée (copiée depuis `app/video/`)
- Workflow Archon `archon-jetson-dev.yaml` (clarify → plan → implement → validate-feedback loop → finalize)
- HITL gate sur count mismatch métier ; auto-reprise sur erreur infra
- Deux modes de validation : `standard` (un fichier) et `full` (tous les mp4 du répertoire `validation/videos/`)
- Arrêt automatique de countingapp-dep/countingapp-test avant validation (libération GPU)

## Out of Scope

- GitHub Actions / CI distante (la validation est déclenchée depuis la machine de dev via SSH)
- Tests unitaires comme critère de validation (le critère = résultat sur la vidéo de référence)
- Rebuild d'image Docker pour des changements de code Python (rsync suffit — le code est monté via hostPath)
- Auto-correction sur count mismatch (garde-fou anti "metric gaming")

## Architecture Decisions

### AD1: `expected_count` dérivé du nom du fichier vidéo, pas en config
**Rationale**: La convention de nommage `template-validation-<N>.mp4` encode la vérité terrain. `expected_count = parse_int(avant ".mp4")`. La config ne porte que `tolerance` (0), `timeout_seconds`, `max_iterations`. Un seul source of truth (le nom du fichier), pas de risque de désynchronisation config vs vidéo.

### AD2: Vidéo dans `validation/videos/` (chemin versionné), copiée depuis `app/video/`
**Rationale**: `video/` est dans `.gitignore` (match any `video/` dir). Placer la vidéo dans `validation/videos/` (note le `s` pluriel) évite de toucher au `.gitignore` et sépare clairement les assets de validation du code applicatif. Le fichier source `app/video/template-validation-9.mp4` (11MB, fourni par l'utilisateur) est copié vers `validation/videos/template-validation-9.mp4` et commité. Le script de validation rsync la vidéo vers `APP_PATH/video/` sur le Jetson (où l'app l'attend en mode FILE).

### AD2b: Deux modes de validation — `standard` (un fichier) et `full` (tous les mp4 du répertoire)
**Rationale**: En mode **standard**, la validation ne porte que sur `template-validation-9.mp4` (config `reference_video`). En mode **full**, le script scanne `validation/videos/` pour tous les fichiers `*.mp4`, dérive `expected_count` de chaque nom, exécute le Job K8s pour chaque vidéo, et agrège les résultats dans un rapport JSON multi-vidéos. Le mode est configurable dans `validation/config.json` (`mode: "standard"` ou `"full"`) ou via l'argument CLI `--full`. Le workflow Archon utilise le mode standard par défaut.

### AD3: Script `validate_on_jetson.sh` = single-shot, le workflow gère le bouclage
**Rationale**: Séparation des responsabilités. Le script fait une validation complète (une exécution) et produit un rapport JSON machine-lisible. Le workflow Archon consomme ce rapport et décide de la suite (itérer, pauser, finaliser). Le script est testable indépendamment du workflow.

### AD4: Distinction count_mismatch vs execution_error par exit code + rapport JSON
**Rationale**: Le script retourne :
- Exit 0 + `"validation_status": "pass"` → validation réussie
- Exit 0 + `"validation_status": "count_mismatch"` → le Job a tourné, le count ne matche pas → **business failure** (HITL)
- Exit 1 + `"validation_status": "execution_error"` → SSH/kubectl/timeout/crash → **infra failure** (auto-retry)

Cette distinction permet au workflow d'appliquer la bonne stratégie sans ambiguïté.

### AD5: Sortie JSON via `RESULT_JSON_PATH` env var, pas hardcodé
**Rationale**: L'env var `RESULT_JSON_PATH` (défaut `/files/result.json`) est injectée par le Job K8s. L'app écrit le JSON à cet emplacement via `os.getenv()`. Aucune modification du `.env` applicatif nécessaire. L'app reste utilisable en mode CAMERA sans écriture JSON (var vide = pas de sortie).

### AD6: Thread joins explicites dans `main.py` — SEULEMENT en mode validate (RESULT_JSON_PATH set)
**Rationale**: Actuellement `main.py` lance les threads via `.start()` sans `.join()`. Le process reste vivant (threads non-daemon) mais il n'y a pas de point d'attente explicite. Pour écrire le JSON résultat après la fin du traitement, on ajoute `.join(timeout=300)` après `start()`, **uniquement si `RESULT_JSON_PATH` est défini**. En mode `serve` normal (countingapp-dep, CAMERA), `RESULT_JSON_PATH` n'est pas set → aucun join, aucun JSON → **comportement inchangé**, l'app continue à compter en permanence sans interruption.

### AD7: Template K8s avec nom fixe `countingapp-validate`, delete avant apply, arrêt des services existants
**Rationale**: Les Jobs K8s sont immuables. `kubectl apply` échoue si le Job existe déjà. Le script fait `kubectl delete job countingapp-validate --ignore-not-found` avant `kubectl apply`. Le nom fixe simplifie le polling. `ttlSecondsAfterFinished: 86400` (24h) préserve les logs. **Avant de lancer le Job de validation**, le script vérifie que `countingapp-dep` (DaemonSet) et `countingapp-test` (Job) ne consomment pas le GPU : si des pods `countingapp` tournent, le script les arrête (scale down du DaemonSet) et les relance après validation. Cela évite les conflits de ressources GPU sur le Jetson.

### AD8: Workflow Archon dédié `archon-jetson-dev.yaml`, pas modification des workflows existants
**Rationale**: Les workflows existants (`archon-piv-loop.yaml`, `archon-plannotator-piv.yaml`) utilisent `bun run validate` / `bun run type-check` (patterns JS/TS). Ce projet est Python/Jetson. Un nouveau workflow dédié évite de casser l'existant et permet d'intégrer la logique de validation Jetson + HITL spécifique.

### AD9: Validation syntaxique Python (`py_compile`) dans la phase implement, validation métier dans la phase validate
**Rationale**: La phase implement fait du `python3 -m py_compile` après chaque tâche (pas de `bun run type-check`). La vraie validation (critère métier) se fait dans la phase validate via le script Jetson. Le workflow ne mélange pas les deux.

## Codebase Context

### Key Files

| File | Role | Action |
|------|------|--------|
| `app/src/main.py` | Point d'entrée, lance les threads | UPDATE — ajouter join + écriture JSON |
| `app/entrypoint.sh` | Modes (build-engine, serve, debug, test) | UPDATE — ajouter mode `validate` |
| `app/src/utils/shared_state.py` | État partagé (counter_to_right, threads, stop_event) | READ — source du count |
| `k3s/templates/countingapp-test.j2` | Template K8s Job existant (mode test) | READ — base pour le nouveau template |
| `ansible/playbooks/app/build_countingapp.yml` | rsync app/ → Jetson + docker build | READ — pattern rsync à réutiliser |
| `scripts/jetson_discover.sh` | Découverte IP Jetson sur le réseau | READ — appelé par le script de validation |
| `.env.local` | Variables de connexion Jetson + app | READ — source des vars SSH/K8s |
| `.archon/workflows/archon-plannotator-piv.yaml` | Workflow PIV avec plannotator gate | READ — base pour le nouveau workflow |
| `.gitignore` | Règles gitignore (video/ est ignoré) | READ — pas de changement nécessaire |

### Patterns to Reuse

**Rsync pattern** (from `ansible/playbooks/app/build_countingapp.yml`):
```bash
rsync -avz --delete --no-owner --no-group --exclude='__pycache__' --exclude='*.pyc' \
  -e "sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" \
  app/ $JETSON_USER@$JETSON_IP:$APP_PATH/
```

**K8s Job template** (from `k3s/templates/countingapp-test.j2`):
- Même structure de volumes (dev-app → /app, filebrowser → /files, docker-sock)
- Même image/resources (GPU nvidia requis)
- Différences: args `["validate"]`, pas de `ttlSecondsAfterFinished`, env var `RESULT_JSON_PATH`

**SSH/discovery pattern** (from `scripts/jetson_discover.sh` + `scripts/prepare_jetson.sh` + `scripts/jetson_first_access.sh`):
```bash
# 1. Load env vars
if [ -f ".env.local" ]; then set -a; source .env.local; set +a; fi
# 2. Load discovered JETSON_IP if available
if [ -f /tmp/jetson_env.sh ]; then set -a; source /tmp/jetson_env.sh; set +a; fi
# 3. Discover if needed (jetson_discover.sh writes JETSON_IP to /tmp/jetson_env.sh)
if [ -z "${JETSON_IP:-}" ]; then
  JETSON_IP="${JETSON_ETH_IP%%/*}"  # strip CIDR from .env.local
  if [ -z "$JETSON_IP" ]; then bash scripts/jetson_discover.sh; source /tmp/jetson_env.sh; fi
fi
# 4. SSH command
sshpass -p "$JETSON_PASSWORD" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$JETSON_USER@$JETSON_IP" "..."
```

**Entrypoint mode pattern** (from `app/entrypoint.sh`):
```bash
  test)
    echo "Running test mode..."
    exec python3 src/main.py \
      --input=FILE \
      --file=./video/test_640.mp4 \
      --drawtracking=True
    ;;
```

## Tasks

### Task 1: CREATE `validation/config.json`
**Action**: CREATE
**Details**: Fichier de config de validation. Contient uniquement:
```json
{
  "reference_video": "template-validation-9.mp4",
  "tolerance": 0,
  "timeout_seconds": 300,
  "max_iterations": 5,
  "mode": "standard"
}
```
`expected_count` n'est PAS stocké ici — il est dérivé du nom du fichier vidéo (parser l'entier avant `.mp4`, après le dernier `-`). `max_iterations` limite les auto-reprises sur erreur d'exécution/infra. `mode` peut être `"standard"` (valide uniquement `reference_video`) ou `"full"` (valide tous les `*.mp4` dans `validation/videos/`).
**Validate**: `cat validation/config.json && jq . validation/config.json`

### Task 2: CREATE `validation/videos/` + copier la vidéo de référence
**Action**: CREATE
**Details**: Créer `validation/videos/` et copier `app/video/template-validation-9.mp4` vers `validation/videos/template-validation-9.mp4`. Le fichier source existe (11MB, fourni par l'utilisateur dans `app/video/`). Le répertoire `validation/videos/` n'est PAS dans `.gitignore` (seul `video/` au singulier l'est — `videos` au pluriel ne matche pas). Ajouter un `.gitkeep` dans le répertoire pour s'assurer qu'il est créé même si la vidéo n'est pas encore copiée. La vidéo de 11MB est commitable sans Git LFS.
```bash
mkdir -p validation/videos
cp app/video/template-validation-9.mp4 validation/videos/template-validation-9.mp4
touch validation/videos/.gitkeep
```
**Validate**: `git status validation/` — doit montrer le répertoire comme non-ignoré. `git check-ignore validation/videos/template-validation-9.mp4` — ne doit rien retourner (non-ignoré). `ls -la validation/videos/template-validation-9.mp4` — fichier présent.

### Task 3: UPDATE `app/src/main.py` — ajout écriture JSON résultat
**Action**: UPDATE
**Details**:
1. Ajouter un import `json` en haut du fichier (déjà importé? non — ajouter).
2. Ajouter une fonction `write_result_json(result_path, video_path, shared_state, start_time, error=None)`:
   ```python
   def write_result_json(result_path, video_path, shared_state, start_time, error=None):
       """Write structured result JSON after processing completes."""
       end_time = time.time()
       result = {
           "count": int(shared_state.counter_to_right),
           "video_file": os.path.basename(video_path),
           "timestamp": datetime.datetime.now().isoformat(),
           "duration_seconds": round(end_time - start_time, 2),
           "frames_processed": shared_state.infer_thread.frame_counter if shared_state.infer_thread else 0,
           "status": "error" if error else "completed",
           "error": str(error) if error else None
       }
       os.makedirs(os.path.dirname(result_path), exist_ok=True)
       with open(result_path, 'w') as f:
           json.dump(result, f, indent=2)
       logger.info(f"Result JSON written to {result_path}: {json.dumps(result)}")
   ```
3. Dans le bloc `if __name__ == "__main__":`, après `start(input_source, video)`:
   - Enregistrer `start_time = time.time()` AVANT l'appel à `start()`.
   - **UNIQUEMENT si `RESULT_JSON_PATH` est défini** (mode validate), join des threads + écriture JSON:
     ```python
     result_json_path = os.getenv("RESULT_JSON_PATH", "")
     if result_json_path:
         # Mode validate: attendre la fin du traitement puis écrire le JSON
         if shared_state.infer_thread and shared_state.infer_thread.is_alive():
             shared_state.infer_thread.join(timeout=300)
         if shared_state.display_thread and shared_state.display_thread.is_alive():
             shared_state.display_thread.join(timeout=300)
         write_result_json(result_json_path, video, shared_state, start_time)
     ```
   - **Si `RESULT_JSON_PATH` n'est PAS défini** (mode serve/CAMERA normal): **AUCUN join, AUCUN JSON**. Le comportement est identique à l'existant — le process reste vivant via les threads non-daemon, l'app compte en continu sans interruption.
   - Le `except Exception as e:` existant doit aussi écrire le JSON d'erreur si `RESULT_JSON_PATH` est défini.
**Pattern**: Suivre le style existant de `main.py` (logger.info pour le logging, datetime pour timestamps).
**Validate**: `python3 -m py_compile app/src/main.py` — doit passer sans erreur.

### Task 4: UPDATE `app/entrypoint.sh` — ajout mode `validate`
**Action**: UPDATE
**Details**: Ajouter un nouveau case avant `*)`:
```bash
  validate)
    VIDEO="${VALIDATE_VIDEO:-./video/template-validation-9.mp4}"
    echo "Running validation mode on: $VIDEO"
    exec python3 src/main.py \
      --input=FILE \
      --file="$VIDEO" \
      --drawtracking=True
    ;;
```
Le mode `validate` utilise la variable d'env `VALIDATE_VIDEO` si présente, sinon le fichier par défaut `template-validation-9.mp4`. Le script de validation rsync la vidéo vers `APP_PATH/video/` sur le Jetson et set `VALIDATE_VIDEO` dans le Job K8s. En mode `full`, le script set `VALIDATE_VIDEO` à chaque vidéo du répertoire. L'env var `RESULT_JSON_PATH` est settée par le Job K8s, pas par l'entrypoint.
**Pattern**: Suivre exactement le pattern du mode `test` existant.
**Validate**: `bash -n app/entrypoint.sh` — syntaxe OK. `docker run --rm countingapp:local validate 2>&1 | head -5` (sur Jetson, vérifie que le mode est reconnu).

### Task 5: CREATE `k3s/templates/countingapp-validate.j2`
**Action**: CREATE
**Details**: Template K8s Job basé sur `countingapp-test.j2` avec les différences suivantes:
- `metadata.name: countingapp-validate` (nom fixe — le script fait delete avant apply)
- `args: ["validate"]`
- `ttlSecondsAfterFinished: 86400` (24h) pour préserver les logs et faciliter le diagnostic
- `backoffLimit: 0` (pas de retry K8s — le script gère les retries)
- Ajouter les env vars au container:
  ```yaml
  env:
  - name: RESULT_JSON_PATH
    value: /files/result.json
  - name: VALIDATE_VIDEO
    value: "{{ validate_video }}"
  ```
  `VALIDATE_VIDEO` permet au script de validation de spécifier la vidéo à traiter (mode standard = `./video/template-validation-9.mp4`, mode full = itération sur chaque vidéo). Le template Jinja2 `{{ validate_video }}` est rendu par le script via sed.
- Mêmes volumes que `countingapp-test.j2` (dev-app → /app, filebrowser → /files, docker-sock)
- Mêmes resources (GPU nvidia)
**Pattern**: Copier `k3s/templates/countingapp-test.j2` et modifier.
**Validate**: `sed -e 's|{{ app_namespace }}|countingapp-dev|g' -e 's|{{ app_name }}|countingapp|g' -e 's|{{ app_version }}|local|g' -e 's|{{ app_path }}|/data/orin/git/animal-counting/app|g' -e 's|{{ files_path }}|/data/orin/files|g' k3s/templates/countingapp-validate.j2 | kubectl apply --dry-run=client -f -` — doit passer la validation YAML/K8s.

### Task 6: CREATE `scripts/validate_on_jetson.sh`
**Action**: CREATE
**Details**: Script single-shot de validation. Étapes:

```bash
#!/bin/bash
set -euo pipefail

# ─── 0. Load config + env ─────────────────────────────────────────
if [ -f ".env.local" ]; then
  set -a
  source .env.local
  set +a
fi

# Load discovered JETSON_IP if available from previous discovery
if [ -f /tmp/jetson_env.sh ]; then
  set -a
  source /tmp/jetson_env.sh
  set +a
fi

CONFIG_FILE="validation/config.json"
TOLERANCE=$(jq -r '.tolerance' "$CONFIG_FILE")
TIMEOUT_SEC=$(jq -r '.timeout_seconds' "$CONFIG_FILE")
MAX_ITERATIONS=$(jq -r '.max_iterations' "$CONFIG_FILE")
MODE=$(jq -r '.mode' "$CONFIG_FILE")
# Allow CLI override: --full flag
if [ "${1:-}" = "--full" ]; then
  MODE="full"
fi

REPORT_FILE="validation-report.json"
VALIDATION_START=$(date +%s)

# ─── 1. Discover Jetson IP (reuse existing scripts pattern) ────────
# Priority: JETSON_IP (from /tmp/jetson_env.sh) > JETSON_ETH_IP (.env.local) > discovery
if [ -z "${JETSON_IP:-}" ]; then
  # Strip CIDR suffix from JETSON_ETH_IP if present
  JETSON_IP="${JETSON_ETH_IP%%/*}"
fi

if [ -z "${JETSON_IP:-}" ]; then
  echo "JETSON_IP not set, running jetson_discover.sh..."
  bash scripts/jetson_discover.sh
  set -a
  source /tmp/jetson_env.sh
  set +a
fi

if [ -z "${JETSON_IP:-}" ]; then
  echo "{\"validation_status\": \"execution_error\", \"error_type\": \"jetson_not_found\"}"
  echo "ERROR: Could not determine Jetson IP"
  exit 1
fi

echo "🎯 Jetson IP: $JETSON_IP"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH_CMD="sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS $JETSON_USER@$JETSON_IP"
SCP_CMD="sshpass -p $JETSON_PASSWORD scp $SSH_OPTS"
RSYNC_CMD="sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS"

# ─── 2. Build video list ────────────────────────────────────────────
if [ "$MODE" = "full" ]; then
  # Full mode: all *.mp4 files in validation/videos/
  VIDEO_LIST=$(ls validation/videos/*.mp4 2>/dev/null || true)
  if [ -z "$VIDEO_LIST" ]; then
    echo "{\"validation_status\": \"execution_error\", \"error_type\": \"no_videos_found\"}"
    echo "ERROR: No mp4 files found in validation/videos/"
    exit 1
  fi
else
  # Standard mode: single reference video from config
  VIDEO_FILE=$(jq -r '.reference_video' "$CONFIG_FILE")
  VIDEO_PATH="validation/videos/$VIDEO_FILE"
  if [ ! -f "$VIDEO_PATH" ]; then
    echo "{\"validation_status\": \"execution_error\", \"error_type\": \"video_not_found\", \"video_file\": \"$VIDEO_FILE\", \"message\": \"Reference video not found at $VIDEO_PATH. Place it before running validation.\"}"
    echo "ERROR: Reference video not found at $VIDEO_PATH"
    exit 1
  fi
  VIDEO_LIST="$VIDEO_PATH"
fi

# ─── 3. Rsync code to Jetson (same pattern as build_countingapp.yml) ─
rsync -avz --delete --no-owner --no-group \
  --exclude='__pycache__' --exclude='*.pyc' \
  -e "sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS" \
  app/ \
  $JETSON_USER@$JETSON_IP:$APP_PATH/

# ─── 4. Stop existing countingapp services (free GPU) ──────────────
DEP_WAS_RUNNING=false
DEP_PODS=$($SSH_CMD "kubectl get pods -l app=$APP_NAME -n $APP_NAMESPACE -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo ''" 2>/dev/null)
if [ -n "$DEP_PODS" ]; then
  echo "⏸️  Stopping countingapp-dep (DaemonSet) to free GPU resources..."
  DEP_WAS_RUNNING=true
  $SSH_CMD "kubectl scale daemonset $APP_NAME -n $APP_NAMESPACE --replicas=0 2>/dev/null || \
    kubectl patch daemonset $APP_NAME -n $APP_NAMESPACE -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"validate-paused\":\"true\"}}}}}'" 2>/dev/null || true
  $SSH_CMD "kubectl wait --for=delete pod -l app=$APP_NAME -n $APP_NAMESPACE --timeout=30s" 2>/dev/null || true
fi

# Also clean up any leftover test job
$SSH_CMD "kubectl delete job countingapp-test -n $APP_NAMESPACE --ignore-not-found 2>/dev/null || true"

# ─── 5. Define single-validation function ───────────────────────────
run_single_validation() {
  local VIDEO_PATH="$1"
  local VIDEO_FILE=$(basename "$VIDEO_PATH")
  local VIDEO_START=$(date +%s)

  # Derive expected_count from filename (integer before .mp4, after last dash)
  local EXPECTED_COUNT=$(echo "$VIDEO_FILE" | sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p')
  if [ -z "$EXPECTED_COUNT" ]; then
    echo "WARNING: Cannot derive expected_count from filename: $VIDEO_FILE — skipping"
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"cannot_derive_expected_count\"}"
    return 1
  fi

  echo "\n─── Validating: $VIDEO_FILE (expected: $EXPECTED_COUNT) ───"

  # Rsync this video to Jetson
  $SSH_CMD "mkdir -p $APP_PATH/video"
  $SCP_CMD "$VIDEO_PATH" "$JETSON_USER@$JETSON_IP:$APP_PATH/video/$VIDEO_FILE"

  # Render K8s Job template with this video
  sed -e "s|{{ app_namespace }}|$APP_NAMESPACE|g" \
      -e "s|{{ app_name }}|$APP_NAME|g" \
      -e "s|{{ app_version }}|$APP_VERSION|g" \
      -e "s|{{ app_path }}|$APP_PATH|g" \
      -e "s|{{ files_path }}|$FILES_PATH|g" \
      -e "s|{{ validate_video }}|./video/$VIDEO_FILE|g" \
      k3s/templates/countingapp-validate.j2 > /tmp/countingapp-validate.yaml

  # Delete old job + apply new one
  $SSH_CMD "kubectl delete job countingapp-validate -n $APP_NAMESPACE --ignore-not-found 2>/dev/null || true"
  $SSH_CMD "kubectl apply -f /dev/stdin" < /tmp/countingapp-validate.yaml

  # Poll for job completion
  echo "Waiting for validation job to complete (timeout: ${TIMEOUT_SEC}s)..."
  local JOB_STATUS=""
  while true; do
    local ELAPSED=$(( $(date +%s) - VIDEO_START ))
    if [ $ELAPSED -gt $TIMEOUT_SEC ]; then
      JOB_STATUS="timeout"
      break
    fi
    local COND=$($SSH_CMD "kubectl get job countingapp-validate -n $APP_NAMESPACE -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo ''" 2>/dev/null)
    case "$COND" in
      Complete) JOB_STATUS="complete"; break ;;
      Failed)   JOB_STATUS="failed"; break ;;
      *) echo "  Job status: ${COND:-pending} (${ELAPSED}s)..."; sleep 5 ;;
    esac
  done

  # Fetch result.json
  local RESULT_FILE="/tmp/result-$VIDEO_FILE.json"
  $SCP_CMD "$JETSON_USER@$JETSON_IP:$FILES_PATH/result.json" "$RESULT_FILE" 2>/dev/null || {
    local JOB_LOGS=$($SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1 | tail -50" 2>/dev/null || echo "Could not fetch logs")
    echo "{\"video_file\": \"$VIDEO_FILE\", \"validation_status\": \"execution_error\", \"error_type\": \"result_json_missing\", \"expected_count\": $EXPECTED_COUNT, \"job_status\": \"$JOB_STATUS\", \"logs\": $(echo "$JOB_LOGS" | jq -Rs .)}"
    return 1
  }

  # Compare count
  local ACTUAL_COUNT=$(jq -r '.count' "$RESULT_FILE")
  local DIFF=$(( ACTUAL_COUNT - EXPECTED_COUNT ))
  local ABS_DIFF=$(( DIFF < 0 ? -DIFF : DIFF ))
  local VSTATUS
  if [ "$ABS_DIFF" -le "$TOLERANCE" ]; then
    VSTATUS="pass"
  else
    VSTATUS="count_mismatch"
  fi

  local JOB_LOGS=$($SSH_CMD "kubectl logs job/countingapp-validate -n $APP_NAMESPACE 2>&1 | tail -100" 2>/dev/null || echo "Could not fetch logs")
  local VDURATION=$(( $(date +%s) - VIDEO_START ))

  # Output single-video result as JSON (to be collected by caller)
  jq -n \
    --arg status "$VSTATUS" \
    --argjson expected "$EXPECTED_COUNT" \
    --argjson actual "$ACTUAL_COUNT" \
    --argjson tolerance "$TOLERANCE" \
    --arg video "$VIDEO_FILE" \
    --arg job_status "$JOB_STATUS" \
    --argjson duration "$VDURATION" \
    --arg timestamp "$(date -Iseconds)" \
    --arg result_json "$(cat "$RESULT_FILE")" \
    --arg logs "$JOB_LOGS" \
    '{
      video_file: $video,
      validation_status: $status,
      expected_count: $expected,
      actual_count: $actual,
      tolerance: $tolerance,
      diff: ($actual - $expected),
      job_status: $job_status,
      duration_seconds: $duration,
      timestamp: $timestamp,
      result: ($result_json | fromjson),
      logs: $logs
    }'
}

# ─── 6. Run validation(s) ──────────────────────────────────────────
RESULTS_FILE="/tmp/validation-results.jsonl"
> "$RESULTS_FILE"

for VIDEO_PATH in $VIDEO_LIST; do
  run_single_validation "$VIDEO_PATH" >> "$RESULTS_FILE" 2>/dev/null || true
done

# ─── 7. Restart countingapp-dep if it was stopped ──────────────────
if [ "$DEP_WAS_RUNNING" = "true" ]; then
  echo "\n▶️  Restarting countingapp-dep (DaemonSet)..."
  $SSH_CMD "kubectl scale daemonset $APP_NAME -n $APP_NAMESPACE --replicas=1 2>/dev/null || \
    kubectl patch daemonset $APP_NAME -n $APP_NAMESPACE --type=json -p='[{\"op\":\"remove\",\"path\":\"/spec/template/spec/nodeSelector/validate-paused\"}]'" 2>/dev/null || true
fi

# ─── 8. Aggregate results into final report ────────────────────────
TOTAL_DURATION=$(( $(date +%s) - VALIDATION_START ))
VIDEO_COUNT=$(wc -l < "$RESULTS_FILE" | tr -d ' ')
PASS_COUNT=$(jq -r 'select(.validation_status == "pass")' "$RESULTS_FILE" | wc -l | tr -d ' ')
MISMATCH_COUNT=$(jq -r 'select(.validation_status == "count_mismatch")' "$RESULTS_FILE" | wc -l | tr -d ' ')
ERROR_COUNT=$(jq -r 'select(.validation_status == "execution_error")' "$RESULTS_FILE" | wc -l | tr -d ' ')

# Determine overall status
if [ "$ERROR_COUNT" -gt 0 ] && [ "$MISMATCH_COUNT" -eq 0 ] && [ "$PASS_COUNT" -eq 0 ]; then
  OVERALL_STATUS="execution_error"
  EXIT_CODE=1
elif [ "$MISMATCH_COUNT" -gt 0 ]; then
  OVERALL_STATUS="count_mismatch"
  EXIT_CODE=0  # script succeeded, business validation failed
elif [ "$PASS_COUNT" -eq "$VIDEO_COUNT" ]; then
  OVERALL_STATUS="pass"
  EXIT_CODE=0
else
  OVERALL_STATUS="execution_error"
  EXIT_CODE=1
fi

# Build final report
jq -n \
  --arg status "$OVERALL_STATUS" \
  --argjson video_count "$VIDEO_COUNT" \
  --argjson pass_count "$PASS_COUNT" \
  --argjson mismatch_count "$MISMATCH_COUNT" \
  --argjson error_count "$ERROR_COUNT" \
  --argjson duration "$TOTAL_DURATION" \
  --arg timestamp "$(date -Iseconds)" \
  --arg mode "$MODE" \
  --slurpfile results "$RESULTS_FILE" \
  '{
    validation_status: $status,
    mode: $mode,
    total_videos: $video_count,
    pass_count: $pass_count,
    mismatch_count: $mismatch_count,
    error_count: $error_count,
    duration_seconds: $duration,
    timestamp: $timestamp,
    results: $results
  }' > "$REPORT_FILE"

echo "\n=== Validation Report ==="
cat "$REPORT_FILE"
echo "\n========================="
echo "Overall: $OVERALL_STATUS ($PASS_COUNT pass, $MISMATCH_COUNT mismatch, $ERROR_COUNT error / $VIDEO_COUNT total)"
exit $EXIT_CODE
```

**Key design points**:
- **Mode standard**: valide `reference_video` du config. **Mode full**: valide tous les `*.mp4` dans `validation/videos/` (activé via `mode: "full"` dans config ou flag `--full`).
- **Arrêt des services existants**: avant la validation, le script stoppe `countingapp-dep` (DaemonSet) et supprime `countingapp-test` (Job) pour libérer le GPU. Après validation, `countingapp-dep` est relancé s'il tournait.
- **Découverte Jetson**: réutilise le pattern de `scripts/jetson_discover.sh` → `/tmp/jetson_env.sh` → `JETSON_IP`. Priority: `JETSON_IP` (discovery) > `JETSON_ETH_IP` (.env.local, strip CIDR) > `bash scripts/jetson_discover.sh`.
- Exit 0 pour `pass` ET `count_mismatch` (le script a réussi à s'exécuter; la distinction est dans le JSON)
- Exit 1 pour `execution_error` (infra failure)
- Le rapport JSON est écrit dans `validation-report.json` à la racine du repo (workspace)
- Les logs K8s sont récupérés et inclus dans le rapport pour le diagnostic
- `EXPECTED_COUNT` est parsé depuis le nom du fichier via `sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p'`
- En mode full, le rapport contient un tableau `results` avec une entrée par vidéo

**Pattern**: SSH/discovery depuis `scripts/jetson_discover.sh` + `scripts/prepare_jetson.sh` (source .env.local, source /tmp/jetson_env.sh, sshpass). Rsync depuis `ansible/playbooks/app/build_countingapp.yml`. Template rendering via `sed`.
**Validate**: `bash -n scripts/validate_on_jetson.sh` — syntaxe OK. `chmod +x scripts/validate_on_jetson.sh`. Sur le Jetson (avec vidéo présente): `bash scripts/validate_on_jetson.sh` — doit produire `validation-report.json`. Mode full: `bash scripts/validate_on_jetson.sh --full`.

### Task 7: CREATE `.archon/workflows/archon-jetson-dev.yaml`
**Action**: CREATE
**Details**: Workflow Archon dédié pour le développement avec validation Jetson. Basé sur `archon-plannotator-piv.yaml` avec les phases:

1. **CLARIFY** (loop, interactive) — converge rapidement vers "ready" (les décisions utilisateur sont déjà tranchées)
2. **PLANNOTATOR-PLAN** — Pi session écrit PLAN.md et soumet via plannotator
3. **VERIFY-PLAN** (bash) — sanity check PLAN.md
4. **IMPLEMENT** (loop, fresh_context) — task-by-task, validation = `python3 -m py_compile`
5. **JETSON-VALIDATE** (loop, interactive) — exécute `scripts/validate_on_jetson.sh`, parse le rapport, gère les 3 cas:
   - `pass` → signal `VALIDATED` → finalize
   - `count_mismatch` → **HITL pause** (gate_message présente le mismatch), l'utilisateur guide la correction, implémente le fix, re-valide
   - `execution_error` → auto-diagnostic + fix, re-valide (limite `max_iterations` du config)
6. **FINALIZE** — push + PR draft

Le prompt du node `jetson-validate` doit explicitement:
- Lire `validation/config.json` pour `max_iterations`
- Tracker le compteur d'erreurs d'exécution séparément
- Sur count_mismatch: NE PAS auto-corriger, PAUSER et attendre l'input utilisateur
- Sur execution_error: diagnostiquer (SSH down? Job manquant? Crash app? Timeout?), corriger, re-essayer
- Si `execution_error_count >= max_iterations`: escalader en HITL

```yaml
name: archon-jetson-dev
description: |
  Use when: User wants autonomous development with Jetson-based business validation.
  Triggers: "jetson dev", "validate on jetson", "autonomous dev pipeline".
  NOT for: Standard PIV without Jetson validation (use archon-plannotator-piv).

  Phases:
  1. CLARIFY: Converge on intent (user decisions already resolved → fast).
  2. PLAN: Pi writes PLAN.md → plannotator review UI.
  3. IMPLEMENT: Task-by-task with py_compile validation.
  4. JETSON-VALIDATE: Run validate_on_jetson.sh → parse report →
     - pass → finalize
     - count_mismatch → HITL pause (no auto-fix)
     - execution_error → auto-retry (limited by max_iterations)
  5. FINALIZE: Push + create draft PR.

provider: pi
model: ollama/glm-5.2
interactive: true

nodes:
  - id: clarify
    loop:
      prompt: |
        # Jetson Dev — Clarify Phase
        ... (fast converge — user decisions already resolved)
      until: READY_FOR_PLAN
      max_iterations: 4
      interactive: true

  - id: plannotator-plan
    depends_on: [clarify]
    ... (same as archon-plannotator-piv.yaml plannotator-plan node)

  - id: verify-plan
    depends_on: [plannotator-plan]
    bash: |
      # Verify PLAN.md exists and has tasks
      ... (same as existing verify-plan)

  - id: implement
    depends_on: [verify-plan]
    idle_timeout: 600000
    model: large
    loop:
      prompt: |
        # Jetson Dev — Implementation Agent
        Read PLAN.md, implement ONE task, validate with:
        python3 -m py_compile <changed_files>
        Commit. Do NOT run Jetson validation (that's the next phase).
      until: IMPL_DONE
      max_iterations: 20
      fresh_context: true

  - id: jetson-validate
    depends_on: [implement]
    idle_timeout: 600000
    loop:
      prompt: |
        # Jetson Dev — Validation Feedback Loop
        
        ## Step 1: Run validation
        ```bash
        bash scripts/validate_on_jetson.sh 2>&1
        ```
        
        ## Step 2: Read the report
        Read `validation-report.json` (or the script output).
        Also read `validation/config.json` for max_iterations.
        
        ## Step 3: Handle result based on validation_status
        
        ### "pass" → SUCCESS
        Signal: VALIDATED. Done.
        
        ### "count_mismatch" → HITL PAUSE (BUSINESS FAILURE)
        DO NOT auto-correct. This is a business validation failure.
        Present the mismatch clearly:
        - Expected: N
        - Actual: M
        - Diff: D
        - Video: template-validation-9.mp4
        
        PAUSE and wait for user guidance. The user will tell you what to
        investigate or fix. Implement their fix, commit, then re-run
        validation (next loop iteration).
        
        DO NOT signal VALIDATED. Do NOT auto-fix. Wait for human input.
        
        ### "execution_error" → AUTO-RETRY (INFRA FAILURE)
        Diagnose the error from the report:
        - SSH connection failed → check .env.local, retry discovery
        - Job missing/not applied → re-render template, re-apply
        - App crash → read logs from report, fix the code, re-run
        - Timeout → check if Jetson is busy, increase timeout if needed
        
        Track execution_error_count. Read max_iterations from config.
        If execution_error_count >= max_iterations:
          ESCALATE to HITL — present the errors and ask for guidance.
        Else:
          Fix the issue, commit, re-run validation (next loop iteration).
        
        DO NOT signal VALIDATED on execution_error.
      until: VALIDATED
      max_iterations: 15
      interactive: true
      gate_message: |
        Jetson validation returned a count mismatch (business failure).
        Review the result and provide guidance on what to fix,
        or say "approve" to finalize despite the mismatch.

  - id: finalize
    depends_on: [jetson-validate]
    context: fresh
    prompt: |
      # Jetson Dev — Finalize
      Validation passed. Push changes and create a draft PR.
      (Same pattern as archon-piv-loop finalize node, adapted for Python)
```

**Pattern**: Basé sur `archon-plannotator-piv.yaml` (structure clarify → plan → implement → validate) avec ajout du node `jetson-validate` et adaptation Python (pas de `bun run`).
**Validate**: `cat .archon/workflows/archon-jetson-dev.yaml | python3 -c "import sys,yaml; yaml.safe_load(sys.stdin)"` — YAML valide (si PyYAML installé). Sinon: vérifier visuellement la structure.

### Task 8: UPDATE `ansible/playbooks/app/deploy_countingapp.yml` — ajouter rendu du template validate
**Action**: UPDATE
**Details**: Ajouter une task de rendu du template validate (après le rendu du template test existant):
```yaml
- name: Render counting app validate
  template:
    src: "../../../k3s/templates/countingapp-validate.j2"
    dest: "{{ app_path }}/../k3s/countingapp-validate.yaml"
  become: yes
```
Ne PAS appliquer le job automatiquement (le script de validation gère l'apply). Cette task rend juste le template disponible sur le Jetson pour référence. La task de déploiement du test job reste commentée.
**Pattern**: Suivre le pattern du rendu `countingapp-test` existant.
**Validate**: `ansible-playbook ansible/playbooks/app/deploy_countingapp.yml --tags always --check` (si environnement disponible).

## Validation

### End-to-end validation procedure

1. **Vérifier la structure des fichiers créés**:
   ```bash
   ls validation/config.json validation/videos/ scripts/validate_on_jetson.sh \
       k3s/templates/countingapp-validate.j2 .archon/workflows/archon-jetson-dev.yaml
   ```

2. **Vérifier la syntaxe Python**:
   ```bash
   python3 -m py_compile app/src/main.py
   ```

3. **Vérifier la syntaxe shell**:
   ```bash
   bash -n app/entrypoint.sh
   bash -n scripts/validate_on_jetson.sh
   ```

4. **Vérifier que la vidéo n'est pas gitignorée**:
   ```bash
   git check-ignore validation/videos/template-validation-9.mp4
   # Ne doit rien retourner (le fichier n'est pas ignoré)
   ```
   Note: `validation/videos/` n'est pas dans `.gitignore` (seul `video/` au singulier l'est).

5. **Vérifier le parsing du expected_count**:
   ```bash
   echo "template-validation-9.mp4" | sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p'
   # Doit afficher: 9
   ```

6. **Vérifier le rendu du template K8s**:
   ```bash
   source .env.local
   sed -e "s|{{ app_namespace }}|$APP_NAMESPACE|g" \
       -e "s|{{ app_name }}|$APP_NAME|g" \
       -e "s|{{ app_version }}|$APP_VERSION|g" \
       -e "s|{{ app_path }}|$APP_PATH|g" \
       -e "s|{{ files_path }}|$FILES_PATH|g" \
       k3s/templates/countingapp-validate.j2 | head -30
   ```

7. **Validation complète sur Jetson** (nécessite le Jetson accessible + vidéo présente):
   ```bash
   # Mode standard (un seul fichier)
   bash scripts/validate_on_jetson.sh
   # Doit produire validation-report.json avec validation_status
   
   # Mode full (tous les mp4 du répertoire)
   bash scripts/validate_on_jetson.sh --full
   # Le rapport contient un tableau results avec une entrée par vidéo
   ```

8. **Vérifier le rapport JSON**:
   ```bash
   jq . validation-report.json
   # Mode standard: doit contenir validation_status, results[0].expected_count, results[0].actual_count, results[0].diff, results[0].logs
   # Mode full: doit contenir validation_status, total_videos, pass_count, mismatch_count, error_count, results[]
   ```

9. **Vérifier l'arrêt/relance de countingapp-dep**:
   ```bash
   # Avant validation: countingapp-dep doit être arrêté par le script
   # Après validation: countingapp-dep doit être relancé si il tournait
   # Vérifier sur le Jetson:
   ssh $JETSON_USER@$JETSON_IP "kubectl get pods -l app=$APP_NAME -n $APP_NAMESPACE"
   ```

10. **Workflow Archon** (test manuel):
   ```bash
   # Lancer le workflow avec une tâche simple
   ~/archon-run-piv.sh "archon-jetson-dev: add a comment to main.py"
   # Vérifier que le workflow atteint la phase jetson-validate
   ```

## Challenges & Suggestions

### Challenge 1: Duplication du rsync vs réutilisation d'Ansible
Le script `validate_on_jetson.sh` duplique la logique de rsync de `ansible/playbooks/app/build_countingapp.yml`. **Suggestion**: acceptable car le script est conçu pour être standalone (pas de dépendance Ansible sur la machine de dev). Le pattern rsync est simple (3 lignes). Si la logique devient plus complexe, extraire un script `scripts/rsync_to_jetson.sh` partagé.

### Challenge 2: `jetson_discover.sh` — corrigé par l'utilisateur
Le fichier `scripts/jetson_discover.sh` a été corrigé (les marqueurs de conflit de merge ont été supprimés par l'utilisateur). Le script fonctionne maintenant correctement et est réutilisé par `validate_on_jetson.sh` pour la découverte du Jetson. **Pattern de découverte réutilisé**: `jetson_discover.sh` exporte `JETSON_IP` dans `/tmp/jetson_env.sh`, qui est ensuite sourcé par `validate_on_jetson.sh`. Priority: `JETSON_IP` (discovery) > `JETSON_ETH_IP` (.env.local) > `bash scripts/jetson_discover.sh`.

### Challenge 3: Rendu de template via `sed` vs Jinja2
Le script rend le template K8s via `sed` (substitution de `{{ var }}`). C'est fragile si un template contient des `{{` dans du contenu YAML. **Suggestion**: acceptable car les templates existants (`countingapp-test.j2`, `countingapp-dep.j2`) utilisent le même pattern et le rendu est fait via Ansible en production. Le `sed` du script n'est qu'un fallback pour le mode standalone. Si Jinja2 CLI (`jinja2` package Python) est disponible, l'utiliser : `python3 -c "import jinja2; ..."`. Mais `sed` est plus universel.

### Challenge 4: `max_iterations` dans le workflow vs dans le config
Le config `validation/config.json` porte `max_iterations` mais le workflow Archon a aussi un `max_iterations` sur son loop. **Suggestion**: le `max_iterations` du config est pour les **erreurs d'exécution** (auto-reprise infra), lu par le Pi agent au runtime. Le `max_iterations` du workflow YAML est la limite hard du loop Archon (sécurité). Les deux sont indépendants : le Pi agent lit le config et décide d'escalader en HITL avant que le loop Archon n'atteigne sa propre limite.

### Challenge 5: La vidéo de référence existe dans `app/video/`
Le fichier `app/video/template-validation-9.mp4` (11MB) existe dans le repo local. Il doit être copié vers `validation/videos/` et commité (Task 2). La copie est une opération manuelle simple (`cp app/video/template-validation-9.mp4 validation/videos/`). En mode full, d'autres vidéos `template-validation-*.mp4` peuvent être ajoutées au même répertoire. **Note**: `app/video/` est dans `.gitignore`, donc la vidéo source n'est pas commitée — seule la copie dans `validation/videos/` l'est.

### Challenge 6: Prévention du "metric gaming"
Le risque de metric gaming (Pi.dev modifie le comptage pour matcher le résultat attendu sans réellement corriger le problème) est un risque réel. **Mitigations déjà en place**: HITL gate sur count mismatch (l'utilisateur contrôle). **Suggestion supplémentaire**: le rapport JSON inclut les logs K8s complets, permettant à l'utilisateur d'auditer ce que l'app a réellement fait. De plus, le script de validation est commité au repo et ne peut pas être modifié par Pi.dev sans review (il est sur la même branche, mais l'utilisateur review le diff avant la PR).

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Vidéo de référence**: `template-validation-9.mp4` existe dans `app/video/` (11MB) et doit être copiée vers `validation/videos/` | LOW | Copie simple via `cp` (Task 2). 11MB commitable sans Git LFS. |
| **Durée de validation longue**: rsync + traitement vidéo + poll peut prendre plusieurs minutes | MED | `timeout_seconds: 300` (5 min) dans config, configurable. Le script affiche la progression pendant le poll. |
| **Conflit de ressources GPU**: si l'app principale tourne en mode CAMERA, le Job de validation peut entrer en conflit | MED | Le Job a `backoffLimit: 0` et le script gère les retries. Si le GPU est occupé, le Job échouera rapidement (OOM ou CUDA error) → `execution_error` → auto-retry. Documenter qu'il faut arrêter l'app principale avant validation. |
| **Engine TensorRT manquant**: si `my_model.engine` n'existe pas sur le Jetson, l'app crash au démarrage | MED | Le script récupère les logs K8s et les inclut dans le rapport → `execution_error` avec diagnostic. L'utilisateur peut alors lancer le build-engine Job. |
| **Job K8s immuable**: `kubectl apply` échoue si le Job existe déjà | LOW | Le script fait `kubectl delete job countingapp-validate --ignore-not-found` avant `kubectl apply`. |
| **Git LFS nécessaire pour vidéo**: si la vidéo est volumineuse (>100MB), Git standard ne suffit pas | LOW | Évaluer la taille. Si >100MB, configurer Git LFS. Pour l'instant, assumer que la vidéo est <100MB. |
| **Metric gaming**: Pi.dev pourrait "tricher" en modifiant le comptage pour matcher le résultat attendu | HIGH | HITL gate sur count mismatch — l'utilisateur contrôle les changements. Le script ne fait pas d'auto-correction sur count mismatch. Les logs K8s sont conservés pour audit. |
| **Workflow Archon non testé**: le nouveau workflow `archon-jetson-dev.yaml` n'a jamais été exécuté | MED | Tester d'abord le script standalone (`validate_on_jetson.sh`), puis le workflow avec une tâche triviale. Le workflow est basé sur le pattern existant de `archon-plannotator-piv.yaml`. |
| **`jetson_discover.sh` cassé**: ~~le script contient des marqueurs de conflit Git~~ | ✅ RESOLU | Corrigé par l'utilisateur. Le script fonctionne et est réutilisé par `validate_on_jetson.sh`. |
| **`main.py` join timeout**: les threads pourraient ne pas terminer dans les 300s | LOW | Le timeout de join est à 300s. Si dépassé, le process se termine quand même (les threads deviennent zombies). Le JSON résultat peut avoir un count incomplet → `execution_error` côté script. |