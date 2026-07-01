> **⚠️ Plan archivé et obsolète.** Ce document est la version « switch to
> template-validation-23.mp4 » (commits rogue `8c9495e` / `90d48e7`, abandonnée).
> La vidéo de référence réelle est `template-validation-9.mp4` (9 cochons).
> Le travail effectif — fixes de la chaîne + validation métier PASS sur 9 —
> est dans la **PR #1** (`pi/jetson-autonomous-validation`) ; voir sa description
> et les commits. Conservé pour l'historique sous la convention `plans/PR_<slug>.md`.

# Plan: Chaîne de développement autonome avec validation métier sur Jetson

## Summary

L'infrastructure de validation Jetson est **déjà implémentée et commitée** sur `main`
(commit `2204cc7`): mode `validate` dans `entrypoint.sh`, sortie JSON dans `main.py`,
template K8s `countingapp-validate.j2`, script `scripts/validate_on_jetson.sh`, config
`validation/config.json`, workflow Archon `archon-jetson-dev.yaml`. Cette évolution
**change la vidéo de référence** de `template-validation-9.mp4` → `template-validation-23.mp4`
(expected_count = 23 dérivé du nom), corrige un bug de stale `result.json` détecté lors
de la review, et met à jour toutes les références. La vidéo `template-validation-23.mp4`
doit être fournie par l'utilisateur et commitée dans `validation/videos/`.

## In Scope

- Remplacement de toutes les références `template-validation-9.mp4` → `template-validation-23.mp4`
- Ajout de la vidéo `template-validation-23.mp4` dans `validation/videos/` (commitée)
- Ajout de la vidéo dans `app/video/` (source pour rsync vers Jetson — non commitée, `video/` est gitignoré)
- Mise à jour de `validation/config.json` (`reference_video` → `template-validation-23.mp4`)
- Mise à jour de `app/entrypoint.sh` (défaut `VALIDATE_VIDEO` → `template-validation-23.mp4`)
- Mise à jour de `.archon/workflows/archon-jetson-dev.yaml` (commentaires + prompts)
- **Correction bug**: suppression du `result.json` stale avant chaque Job K8s dans `validate_on_jetson.sh`
- Conservation de `template-validation-9.mp4` dans `validation/videos/` (mode full multi-vidéos)

## Out of Scope

- Refactor de l'architecture de validation (l'existant fonctionne, delta minimal)
- GitHub Actions / CI distante (validation déclenchée depuis la machine de dev via SSH)
- Tests unitaires comme critère de validation (le critère = résultat sur la vidéo de référence)
- Rebuild d'image Docker pour des changements de code Python (rsync suffit — code monté via hostPath)
- Auto-correction sur count mismatch (garde-fou anti "metric gaming" — HITL obligatoire)

## Architecture Decisions

### AD1: `expected_count` dérivé du nom du fichier vidéo — inchangé, déjà implémenté
**Rationale**: La convention `template-validation-<N>.mp4` encode la vérité terrain.
`expected_count = parse_int(avant ".mp4", après dernier "-")`. La config ne porte que
`tolerance` (0), `timeout_seconds`, `max_iterations`, `mode`. Un seul source of truth.
**Déjà implémenté** dans `scripts/validate_on_jetson.sh` via `sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p'`.

### AD2: Vidéo dans `validation/videos/` (chemin versionné) — mécanisme existant réutilisé
**Rationale**: `video/` (singulier) est dans `.gitignore` → `validation/videos/` (pluriel)
n'est PAS ignoré. La vidéo `template-validation-23.mp4` est commitée dans
`validation/videos/`. Le script rsync la vidéo vers `APP_PATH/video/` sur le Jetson
(où l'app l'attend en mode FILE via `VALIDATE_VIDEO=./video/template-validation-23.mp4`).
**Aucune modification du `.gitignore` nécessaire** — le mécanisme est déjà prouvé avec
`template-validation-9.mp4` qui est trackée dans git.

### AD3: Script `validate_on_jetson.sh` = single-shot, le workflow gère le bouclage — inchangé
**Rationale**: Séparation des responsabilités. Le script fait une validation complète
(une exécution) et produit un rapport JSON machine-lisible. Le workflow Archon consomme
ce rapport et décide: itérer, pauser (HITL), ou finaliser. Le script est testable
indépendamment.

### AD4: Distinction count_mismatch vs execution_error — inchangé, déjà implémenté
**Rationale**: Le script retourne:
- Exit 0 + `"validation_status": "pass"` → validation réussie
- Exit 0 + `"validation_status": "count_mismatch"` → Job a tourné, count ne matche pas → **business failure** (HITL pause)
- Exit 1 + `"validation_status": "execution_error"` → SSH/kubectl/timeout/crash → **infra failure** (auto-retry limité par `max_iterations`)

### AD5: Conservation de `template-validation-9.mp4` dans `validation/videos/`
**Rationale**: Garder l'ancienne vidéo permet de valider en mode `full` (multi-vidéos)
et sert de régression. Les deux vidéos coexistent dans `validation/videos/`. Le mode
`standard` ne valide que `template-validation-23.mp4` (config `reference_video`).

### AD6: Correction bug stale `result.json` — NOUVEAU
**Rationale**: Le script actuel ne supprime pas `$FILES_PATH/result.json` avant de lancer
un nouveau Job. En mode `full`, si le Job de la vidéo N crash et n'écrit pas de
`result.json`, le script récupère le `result.json` stale de la vidéo N-1 → faux positif.
**Fix**: ajouter `ssh ... rm -f $FILES_PATH/result.json` avant `kubectl apply` dans
`run_single_validation()`.

### AD7: Workflow prompt — paramétriser la référence vidéo au lieu de hardcoder
**Rationale**: Le workflow `archon-jetson-dev.yaml` hardcode `template-validation-9.mp4`
dans ses commentaires et exemples de prompts. Au lieu de remplacer par
`template-validation-23.mp4` (même problème), le prompt doit dire au Pi agent de lire
`validation/config.json` pour obtenir le nom de la vidéo de référence. Cela rend le
workflow agnostique au changement de vidéo.

## Codebase Context — État de l'existant (déjà implémenté)

| File | Role | Statut | Action requise |
|------|------|--------|----------------|
| `app/src/main.py` | Point d'entrée, threads, `write_result_json()` | ✅ Implémenté | Aucune — `RESULT_JSON_PATH` env var + join threads + JSON écriture déjà fonctionnels |
| `app/entrypoint.sh` | Modes (build-engine, serve, debug, test, validate) | ✅ Implémenté | UPDATE — changer défaut `template-validation-9.mp4` → `template-validation-23.mp4` |
| `k3s/templates/countingapp-validate.j2` | Template K8s Job (args=validate, env RESULT_JSON_PATH + VALIDATE_VIDEO) | ✅ Implémenté | Aucune — template paramétrique via `{{ validate_video }}` |
| `scripts/validate_on_jetson.sh` | Script single-shot (SSH → rsync → Job → poll → result.json → comparaison → rapport) | ✅ Implémenté | UPDATE — fix stale result.json + vérifier parsing `template-validation-23` |
| `validation/config.json` | Config (reference_video, tolerance, timeout, max_iterations, mode) | ✅ Implémenté | UPDATE — `reference_video` → `template-validation-23.mp4` |
| `validation/videos/template-validation-9.mp4` | Vidéo référence actuelle (11MB) | ✅ Committée | CONSERVER — gardée pour mode full |
| `validation/videos/template-validation-23.mp4` | Nouvelle vidéo référence | ❌ N'existe pas | CREATE — fournie par utilisateur, commitée |
| `.archon/workflows/archon-jetson-dev.yaml` | Workflow Archon (clarify → plan → implement → validate → finalize) | ✅ Implémenté | UPDATE — références 9 → 23 + paramétriser prompt |
| `ansible/playbooks/app/deploy_countingapp.yml` | Playbook de déploiement (rend template validate) | ✅ Implémenté | Aucune — task de rendu déjà présente |
| `.gitignore` | Règles git (video/ au singulier ignoré) | ✅ OK | Aucune — validation/videos/ n'est pas ignoré |

### Patterns to Reuse (déjà en place)

**Rsync pattern** (`scripts/validate_on_jetson.sh` ligne ~67):
```bash
rsync -avz --delete --no-owner --no-group --exclude='__pycache__' --exclude='*.pyc' \
  -e "sshpass -p $JETSON_PASSWORD ssh $SSH_OPTS" app/ $JETSON_USER@$JETSON_IP:$APP_PATH/
```

**Expected count derivation** (`scripts/validate_on_jetson.sh` dans `run_single_validation()`):
```bash
EXPECTED_COUNT=$(echo "$VIDEO_FILE" | sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p')
# template-validation-23.mp4 → 23
```

**SSH/discovery pattern** (`scripts/validate_on_jetson.sh` lignes ~38-56):
```bash
# Priority: JETSON_IP (discovery) > JETSON_ETH_IP (.env.local, strip CIDR) > bash scripts/jetson_discover.sh
```

**K8s Job template rendering** (`scripts/validate_on_jetson.sh` dans `run_single_validation()`):
```bash
sed -e "s|{{ app_namespace }}|$APP_NAMESPACE|g" ... k3s/templates/countingapp-validate.j2 > /tmp/countingapp-validate.yaml
```

## Tasks

### Task 1: UPDATE `validation/config.json` — changer la vidéo de référence
**Action**: UPDATE `validation/config.json`
**Details**: Changer `reference_video` de `template-validation-9.mp4` à `template-validation-23.mp4`.
Garder `tolerance: 0`, `timeout_seconds: 300`, `max_iterations: 5`, `mode: "standard"`.
```json
{
  "reference_video": "template-validation-23.mp4",
  "tolerance": 0,
  "timeout_seconds": 300,
  "max_iterations": 5,
  "mode": "standard"
}
```
**Validate**: `jq . validation/config.json` → `reference_video` = `template-validation-23.mp4`.

### Task 2: CREATE `validation/videos/template-validation-23.mp4` — committer la vidéo
**Action**: CREATE (fichier binaire fourni par l'utilisateur)
**Details**: L'utilisateur fournit le fichier vidéo `template-validation-23.mp4` (vérité
terrain: 23 cochons). Le fichier est placé dans `validation/videos/` et commité.
Vérifier que le fichier n'est pas gitignoré: `git check-ignore validation/videos/template-validation-23.mp4`
ne doit rien retourner. Le fichier `template-validation-9.mp4` est CONSERVÉ dans le même
répertoire (mode full multi-vidéos).
**Prérequis**: L'utilisateur doit fournir le fichier vidéo. Si le fichier n'est pas
disponible, cette task est bloquée.
**Validate**: `ls -la validation/videos/template-validation-23.mp4` && `git status validation/videos/template-validation-23.mp4` (untracked → à committer).

### Task 3: CREATE `app/video/template-validation-23.mp4` — copie locale pour rsync
**Action**: CREATE (copie depuis `validation/videos/`)
**Details**: Copier `validation/videos/template-validation-23.mp4` vers
`app/video/template-validation-23.mp4`. Ce fichier n'est PAS commité (`video/` est dans
`.gitignore`). Il sert de source pour le rsync de l'app vers le Jetson (le script rsync
`app/` → Jetson, et l'entrypoint attend la vidéo dans `./video/`). Alternative: le
script `validate_on_jetson.sh` rsync déjà explicitement chaque vidéo de
`validation/videos/` vers `$APP_PATH/video/` sur le Jetson (ligne `$SCP_CMD`), donc
cette copie locale est optionnelle mais utile pour test local (`docker run ... validate`).
```bash
cp validation/videos/template-validation-23.mp4 app/video/template-validation-23.mp4
```
**Validate**: `ls -la app/video/template-validation-23.mp4` (présent, non tracké par git).

### Task 4: UPDATE `app/entrypoint.sh` — changer le défaut de la vidéo de validation
**Action**: UPDATE `app/entrypoint.sh`
**Details**: Dans le case `validate)`, changer le défaut de `VALIDATE_VIDEO`:
```bash
  validate)
    VIDEO="${VALIDATE_VIDEO:-./video/template-validation-23.mp4}"
    echo "Running validation mode on: $VIDEO"
    exec python3 src/main.py \
      --input=FILE \
      --file="$VIDEO" \
      --drawtracking=True
    ;;
```
Le Job K8s injecte `VALIDATE_VIDEO` via le template (`{{ validate_video }}`), donc le
défaut n'est utilisé que pour test local sans env var.
**Validate**: `bash -n app/entrypoint.sh` (syntaxe OK) && `grep template-validation-23 app/entrypoint.sh` (présent).

### Task 5: UPDATE `scripts/validate_on_jetson.sh` — fix stale result.json
**Action**: UPDATE `scripts/validate_on_jetson.sh`
**Details**: Dans la fonction `run_single_validation()`, AVANT `kubectl apply`, ajouter
la suppression du `result.json` stale:
```bash
  # Delete stale result.json before launching new job (prevents false positive
  # if the new job crashes and doesn't write a new result.json)
  $SSH_CMD "rm -f $FILES_PATH/result.json" 2>/dev/null || true
```
Insérer après la ligne `$SSH_CMD "kubectl delete job countingapp-validate ..."` et avant
`$SSH_CMD "kubectl apply -f /dev/stdin"`.
**Rationale**: En mode `full`, si le Job de la vidéo N crash, le script ne doit pas
récupérer le `result.json` de la vidéo N-1. Sans ce fix, `result_json_missing` n'est
jamais détecté si une vidéo précédente a réussi.
**Validate**: `bash -n scripts/validate_on_jetson.sh` (syntaxe OK) && `grep "rm -f.*result.json" scripts/validate_on_jetson.sh` (présent).

### Task 6: UPDATE `.archon/workflows/archon-jetson-dev.yaml` — références vidéo + paramétrisation
**Action**: UPDATE `.archon/workflows/archon-jetson-dev.yaml`
**Details**: Trois changements:
1. **Commentaire d'en-tête** (ligne ~14): remplacer `template-validation-9.mp4 (expected_count = 9, derived from filename)` par `the reference video from validation/config.json (expected_count derived from filename)`.
2. **Exemple de rapport JSON** (ligne ~394): remplacer `"video_file": "template-validation-9.mp4"` par `"video_file": "<reference_video from config>"` et `"expected_count": 9` par `"expected_count": <derived from filename>`.
3. **Prompt count_mismatch** (ligne ~562): remplacer `Video: template-validation-9.mp4` par `Video: {video_file from report}` — le Pi agent lit le nom depuis le rapport, pas en dur.
4. **Prompt finalize** (référence à `template-validation-9.mp4` et `Expected: 9`): remplacer par lecture dynamique depuis `validation-report.json`.
**Rationale**: Le workflow ne doit pas hardcoder le nom de la vidéo. Le Pi agent lit
`validation/config.json` et `validation-report.json` au runtime.
**Validate**: `grep -n "template-validation-9" .archon/workflows/archon-jetson-dev.yaml` → ne doit retourner aucune ligne (toutes les références supprimées).

### Task 7: UPDATE `PLAN.md` — ce fichier (auto-descriptif)
**Action**: UPDATE `PLAN.md` (ce fichier)
**Details**: Le PLAN.md lui-même est mis à jour pour refléter `template-validation-23.mp4`.
Cette task est le plan lui-même — elle est complétée lorsque le plan est approuvé.
**Validate**: Le plan est approuvé par l'utilisateur via plannotator.

## Validation

### Vérifications syntaxiques (sur machine de dev)

1. **Python**:
   ```bash
   python3 -m py_compile app/src/main.py
   ```
2. **Shell**:
   ```bash
   bash -n app/entrypoint.sh
   bash -n scripts/validate_on_jetson.sh
   ```
3. **YAML**:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-jetson-dev.yaml'))"
   ```
4. **JSON**:
   ```bash
   jq . validation/config.json
   ```

### Vérifications de cohérence

5. **Parsing du expected_count depuis le nom**:
   ```bash
   echo "template-validation-23.mp4" | sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p'
   # Doit afficher: 23
   ```
6. **Vidéo non gitignorée**:
   ```bash
   git check-ignore validation/videos/template-validation-23.mp4
   # Ne doit rien retourner (exit 1 = non ignoré)
   ```
7. **Aucune référence résiduelle à template-validation-9 dans les fichiers modifiés**:
   ```bash
   grep -rn "template-validation-9" validation/config.json app/entrypoint.sh .archon/workflows/archon-jetson-dev.yaml
   # Ne doit retourner aucune ligne (sauf si template-validation-9.mp4 est conservé
   # dans validation/videos/ — c'est OK, c'est un fichier, pas une référence code)
   ```

### Validation end-to-end sur Jetson (nécessite Jetson accessible + vidéo présente)

8. **Validation standard** (mode standard = `template-validation-23.mp4` uniquement):
   ```bash
   bash scripts/validate_on_jetson.sh 2>&1
   ```
   Doit produire `validation-report.json` avec:
   - `validation_status`: `"pass"` | `"count_mismatch"` | `"execution_error"`
   - `results[0].video_file`: `"template-validation-23.mp4"`
   - `results[0].expected_count`: `23`
   - `results[0].actual_count`: `<count from app>`
   - `results[0].diff`: `actual - 23`

9. **Vérifier le rapport JSON**:
   ```bash
   jq . validation-report.json
   ```

10. **Vérifier l'arrêt/relance de countingapp-dep** (le script gère le GPU):
    ```bash
    # Pendant validation: countingapp-dep doit être arrêté
    # Après validation: countingapp-dep doit être relancé
    ```

### Validation workflow Archon

11. **Lancer le workflow avec une tâche triviale**:
    ```bash
    # Via archon-run-piv.sh ou procédure .archon/HOW_TO_RUN_PIV.md
    # Vérifier que le workflow atteint la phase jetson-validate
    # Vérifier que le rapport est lu correctement par le Pi agent
    ```

## Challenges & Suggestions (review de l'existant)

### C1: Bug stale `result.json` — CORRIGÉ (Task 5)
Le script ne supprimait pas `$FILES_PATH/result.json` avant de lancer un nouveau Job.
En mode `full`, si le Job N crash, le script récupère le `result.json` de la vidéo N-1
→ faux positif. **Fix**: `rm -f $FILES_PATH/result.json` avant `kubectl apply`.

### C2: Rendu de template via `sed` — acceptable mais fragile
Le script rend `countingapp-validate.j2` via `sed` (substitution de `{{ var }}`).
Fragile si un template contient `{{` dans du contenu YAML. **Suggestion**: acceptable
car les templates existants sont simples. Alternative: `python3 -c "import jinja2; ..."`
mais `sed` est plus universel et ne nécessite pas Jinja2 CLI.

### C3: Vidéos binaires dans git — 11MB acceptable, surveiller
`template-validation-9.mp4` = 11MB, commitée sans Git LFS. Si d'autres vidéos s'ajoutent
(mode full), le repo grossit. **Suggestion**: pour l'instant acceptable (<50MB total).
Si >100MB, configurer Git LFS avec `.gitattributes` pour `validation/videos/*.mp4`.

### C4: `app/video/demo.mp4` est trackée malgré `video/` dans `.gitignore`
`demo.mp4` a été force-addée (`git add -f`). C'est inconsistent avec le reste de `video/`
qui est ignoré. **Suggestion**: retirer `demo.mp4` du tracking (`git rm --cached
app/video/demo.mp4`) pour cohérence, ou documenter l'exception. Non bloquant pour ce plan.

### C5: Workflow prompt hardcode le nom de la vidéo — CORRIGÉ (Task 6)
Le workflow `archon-jetson-dev.yaml` hardcode `template-validation-9.mp4` dans ses
commentaires et exemples. **Fix**: le prompt du Pi agent doit lire le nom depuis
`validation/config.json` et `validation-report.json` au runtime, pas en dur.

### C6: `max_iterations` — double niveau de limite
`validation/config.json` porte `max_iterations: 5` (pour les erreurs d'exécution, lu
par le Pi agent au runtime). Le workflow YAML a `max_iterations: 15` sur son loop (limite
hard Archon). **Suggestion**: acceptable — le Pi agent escalade en HITL après 5 erreurs
d'exécution, avant que le loop Archon n'atteigne 15. Les deux sont indépendants et
complémentaires.

### C7: Prévention du "metric gaming" — déjà mitigée
Le risque de metric gaming (Pi.dev modifie le comptage pour matcher le résultat attendu
sans corriger le vrai problème) est mitigé par: (1) HITL gate sur count mismatch,
(2) logs K8s inclus dans le rapport pour audit, (3) le script de validation est sur la
même branche — l'utilisateur review le diff avant la PR. **Suggestion supplémentaire**:
le rapport pourrait inclure un hash du code exécuté (`git rev-parse HEAD` au moment du
rsync) pour permettre l'audit de la version exacte validée.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Vidéo `template-validation-23.mp4` non fournie** | HIGH | Task 2 est bloquée jusqu'à ce que l'utilisateur fournisse le fichier. Le reste du plan (Tasks 1, 4-7) peut être implémenté indépendamment. |
| **Durée de validation longue** (rsync + traitement vidéo + poll) | MED | `timeout_seconds: 300` (5 min) dans config, configurable. Le script affiche la progression pendant le poll. |
| **Conflit de ressources GPU** si l'app principale tourne | MED | Le script stoppe `countingapp-dep` (DaemonSet) avant validation et le relance après. |
| **Engine TensorRT manquant** sur le Jetson | MED | Le script récupère les logs K8s → `execution_error` avec diagnostic. L'utilisateur peut lancer le build-engine Job. |
| **Job K8s immuable** — `kubectl apply` échoue si le Job existe | LOW | Le script fait `kubectl delete job countingapp-validate --ignore-not-found` avant apply. |
| **Metric gaming** — Pi.dev modifie le comptage pour matcher | HIGH | HITL gate sur count mismatch (pas d'auto-correction). Logs K8s conservés pour audit. |
| **Bug stale result.json** en mode full | MED | **CORRIGÉ** (Task 5): `rm -f $FILES_PATH/result.json` avant chaque Job. |
| **Parsing du nom** — `template-validation-23.mp4` doit matcher `*-N.mp4` | LOW | Testé: `echo "template-validation-23.mp4" \| sed -n 's/.*-\([0-9]\+\)\.mp4/\1/p'` → `23`. |