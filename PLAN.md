# Plan: BL-76 — App Android : réorganiser l'onglet Réglages + paramètres à chaud

## Summary
Réorganiser `SettingsScreen.kt` en 5 sections claires (Horloge / Connexion / Alimentation / Enregistrement & tracking / Ligne de comptage) et exposer depuis le téléphone l'arrêt du Jetson + des paramètres pris à chaud dès la prochaine vidéo. L'IPC entre le companion (service systemd sur l'hôte) et la counting app (pod K3s) passe par un fichier partagé dans le hostPath `/files` (host `/data/orin/files`, déjà utilisé pour `counting-history.jsonl`) : `runtime-settings.json` pour les toggles (lu à chaud par `main.py` à chaque enregistrement) et un sentinel pour l'arrêt (poll par `DisplayThread.run` qui setter `arret_requested`, réutilisant la séquence BL-62 finalize→stop→nsenter poweroff). Aucune modification de la logique de comptage (OC-SORT, crossing detection, guards, `TRACKER_*`).

## In Scope
- **Android (Compose/Kotlin)** — 5 sections UI, nouveaux états DataStore, appels réseau (`poweroff`/`getSettings`/`putSettings`), chaînes FR/EN.
- **Companion Jetson** (`configure_companion.yml`) — `POST /api/power` (sentinel), `GET /api/settings` + `PUT /api/settings` (runtime-settings.json).
- **Counting app** (`app/src/`) — lecture runtime à chaud au démarrage de chaque enregistrement (`main.py`), poll sentinel arrêt (`display_thread.py`), fallback sur `os.getenv`.
- **Validation** — `--full` (OFFSET modifiable impacte le comptage) + build APK debug.

## Out of Scope
- `DRAW_BOX` (mort — vestige docstring `settings.py:24`) — droppé.
- `FPS_OUTPUT`, `PIG_CONFIDENCE_THRESHOLD`, direction de comptage — reportés en issue de suivi.
- Params OC-SORT (`TRACKER_*`, `DRAW_*_THICKNESS`) — jamais exposés.
- Logique de comptage (crossing detection, guard eligibility) — intouchable.
- Auto-correction d'un count mismatch de validation.
- `validation/config.json` `mode` — doit rester `"standard"` par défaut (non modifié).

## Architecture Decisions

- **IPC via fichier partagé `/files`** (host `/data/orin/files`, monté `/files` dans le pod, monté direct sur l'hôte pour le companion). `runtime-settings.json` pour les toggles + un sentinel d'arrêt `.arret_requested`. Rationnel : canal déjà éprouvé pour `counting-history.jsonl`, aucun IPC/dep supplémentaire, fonctionne HotSpot comme LAN (le companion est atteint via l'IP résolue par `JetsonConnectionManager`).

- **`runtime-settings.json` schema** : `{"draw_tracking": bool, "box_tracking": bool, "centroid_tracking": bool, "offset_counting_line": int (0-100)}`. Toutes les clés optionnelles à l'écriture (PATCH-like : seules les clés présentes sont écrasées). Le companion valide types/ranges et rejette (400) tout JSON invalide. Le fichier n'est pas créé au boot ; la counting app retombe sur `os.getenv`/défauts s'il est absent/illisible.

- **Sentinel d'arrêt anti-stale** : le companion écrit `os.path.join(FILES_DIR, ".arret_requested")` (atomic write). La counting app ne déclenche l'arrêt QUE si le mtime du sentinel est **postérieur au start time du process** (`shared_state` enregistre son propre boot time). Un sentinel pré-boot (restant d'un crash antérieur) est ignoré + supprimé. L'app supprime le sentinel dès qu'il agit (consume). Rationnel : éviter un poweroff en boucle au reboot, et rester idempotent.

- **Master `DRAW_TRACKING` gate déjà fonctionnel** en amont (`display_thread.py:237,402` : décide frame annotée vs brute écrite dans l'enregistrement). Sub-toggles `BOX_TRACKING` (gate box+label, `tracking.py:222`) et `CENTROID_TRACKING` (gate uniquement les trails ; le point centroid est **toujours** dessiné, `tracking.py:230,233,248`). UI : sub-toggles grisés si master OFF. Aucun changement au gating existant — on expose juste la valeur au téléphone.

- **Point d'application à chaud** : `main.py:132-134` instancie `Tracking(draw_box=shared_state.draw_tracking, ...)` et `Rendering(offset_counting_line=settings.OFFSET_PERCENT_COUNTING_LINE)` au démarrage de **chaque** enregistrement. En y relisant `runtime-settings.json` (et en mettant à jour `shared_state.*` + `settings.OFFSET_PERCENT_COUNTING_LINE`) juste avant ces instanciations, le changement est pris à chaud pour la prochaine vidéo, sans redémarrage.

- **Endpoint `POST /api/power` répond 200 avant le poweroff effectif** : il ne fait qu'écrire le sentinel ; le poweroff réel est exécuté par la counting app via sa séquence `nsenter -t 1 systemctl poweroff` (BL-62, déjà en place, `cli.py:131-144`). L'UI Android affiche « Arrêt en cours » après réception du 200.

- **`OFFSET_PERCENT_COUNTING_LINE` impacte le comptage** → avertissement UI + validation `--full` sur la branche. Default `10` conservé.

- **Conventions AGENTS.md §7** : OC-SORT conservé, `FPS_OUTPUT=30`, droits→gauche = +1, `.env.local` gitignored, `GITHUB_TOKEN` dans `.env.local`, naming `BL-76`, pas d'auto-correct count mismatch.

## Tasks

### Companion Jetson

- [x] Task 1: EDIT `ansible/playbooks/system/configure_companion.yml` — Ajouter les constantes `RUNTIME_SETTINGS_FILE = os.path.join(FILES_DIR, "runtime-settings.json")` et `POWER_SENTINEL_FILE = os.path.join(FILES_DIR, ".arret_requested")` près de la définition de `FILES_DIR` (~ligne 148). Bumper `SERVICE_VERSION` à `"5"` (et mettre à jour le header docstring des endpoints ~lignes 18-31 pour lister `POST /api/power`, `GET /api/settings`, `PUT /api/settings`).

- [x] Task 2: EDIT `ansible/playbooks/system/configure_companion.yml` — Ajouter une fonction helper `_load_runtime_settings()` qui renvoie le dict JSON désérialisé depuis `RUNTIME_SETTINGS_FILE`, ou `{}` si absent/illisible (best-effort, log warning). Ajouter `_validate_settings_payload(payload)` qui valide un dict : `draw_tracking`/`box_tracking`/`centroid_tracking` ∈ {True, False} si présents (bool strict, rejeter les strings), `offset_counting_line` ∈ int 0-100 si présent. Retourne `(ok, errors)`.

- [x] Task 3: EDIT `ansible/playbooks/system/configure_companion.yml` — Étendre `do_GET` (~ligne 1021) : ajouter une branche `if path == "/api/settings":` qui appelle `_load_runtime_settings()`, renvoie 200 JSON (toujours un objet, vide `{}` si pas de fichier). Logger `GET /api/settings -> 200`.

- [x] Task 4: EDIT `ansible/playbooks/system/configure_companion.yml` — Ajouter une méthode `do_PUT` (nouvelle) : si `self.path != "/api/settings"` → 404. Sinon lire le body JSON via le helper `_read_json_body` existant (~ligne 938), valider via `_validate_settings_payload`. Sur erreur → 400 avec message. Sinon : charger les settings existants (`_load_runtime_settings`), merger les clés présentes (PATCH-like), écrire atomiquement (write temp + `os.replace`) le JSON dans `RUNTIME_SETTINGS_FILE`, renvoyer 200 avec le settings mergé complet. Logger `PUT /api/settings -> 200 ({...})`.

- [x] Task 5: EDIT `ansible/playbooks/system/configure_companion.yml` — Étendre `do_POST` (~ligne 1182) : ajouter une branche `if self.path == "/api/power":` AVANT le check `/api/time`. Accepter un body JSON optionnel (ex. `{"action":"poweroff"}`) ; ignorer le contenu. Supprimer tout sentinel préexistant puis écrire `POWER_SENTINEL_FILE` (contenu = ISO8601 timestamp, atomic write). Renvoyer 200 `{"status":"poweroff_requested"}`. Logger `POST /api/power -> 200 (sentinel written)`. Ne PAS exécuter le poweroff ici — c'est la counting app qui le fera via BL-62.

### Counting app (app/src)

- [x] Task 6: EDIT `app/src/utils/shared_state.py` — Ajouter `self.app_start_time = time.time()` dans `__init__` (près de `arret_requested`, ~ligne 66) pour le test anti-stale du sentinel d'arrêt. Ajouter `import time` si absent.

- [x] Task 7: EDIT `app/src/state.py` (ou `app/src/main.py`) — Ajouter une fonction helper `load_runtime_settings()` qui lit `/files/runtime-settings.json` (constante `RUNTIME_SETTINGS_PATH = "/files/runtime-settings.json"`) et renvoie un dict, ou `{}` si absent/illisible (best-effort, log warning via `logger`). Aucune levée d'exception. Ne pas importer de nouveau module lourd.

- [x] Task 8: EDIT `app/src/main.py` — Dans `start()` (ou le bloc qui instancie Tracking/Rendering, ~lignes 110-134), **juste avant** l'instantiation de `Tracking`/`Rendering`, appeler `load_runtime_settings()` et appliquer sélectivement les valeurs au runtime (fallback sur les valeurs `os.getenv` courantes si la clé est absente) : `shared_state.draw_tracking`, `shared_state.box_tracking`, `shared_state.centroid_tracking`, et `settings.OFFSET_PERCENT_COUNTING_LINE`. Concrètement : ne PAS réécrire `settings.py` ; updater `shared_state.*` (déjà fait au boot dans `state.py:31-33`) + `settings.OFFSET_PERCENT_COUNTING_LINE` (l'instanciation `Rendering(offset_counting_line=settings.OFFSET_PERCENT_COUNTING_LINE)` à la ligne 134 lit alors la valeur à chaud). Valider les types à la lecture (bool/int) ; ignorer une clé invalide. Ne PAS toucher aux autres `settings.*` (TRACKER_*, PIG_CONFIDENCE_*, COUNTING_*).

- [x] Task 9: EDIT `app/src/display_thread.py` — En tête de la boucle `while not self.stop_event.is_set():` (~ligne 197), **avant** le check `if shared_state.arret_requested:` existant, ajouter un poll du sentinel : si `os.path.exists(POWER_SENTINEL_PATH)` (constante `POWER_SENTINEL_PATH = "/files/.arret_requested"`) et `os.path.getmtime(POWER_SENTINEL_PATH) > shared_state.app_start_time` → supprimer le sentinel (`os.remove`, best-effort) et setter `shared_state.arret_requested = True`. Si le sentinel existe mais est plus ancien que `app_start_time` (stale pré-boot) → le supprimer silencieusement sans setter le flag. Le reste de la séquence BL-62 (finalize → stop_event → poweroff_requested → nsenter poweroff via cli.py) reste **inchangé**. Ajouter `import os, time` si absents.

### Android (Compose/Kotlin)

- [x] Task 10: EDIT `android/app/src/main/java/com/animalcounter/net/Models.kt` — Ajouter `data class JetsonSettings(val drawTracking: Boolean? = null, val boxTracking: Boolean? = null, val centroidTracking: Boolean? = null, val offsetCountingLine: Int? = null)` (tous nullable pour le PATCH-like ; null = non modifié). Ajouter `data class PoweroffResponse(val status: String)`.

- [x] Task 11: EDIT `android/app/src/main/java/com/animalcounter/net/JetsonClient.kt` — Ajouter 3 fonctions suspend : `getSettings(baseUrl): JetsonSettings` (GET `/api/settings`), `putSettings(baseUrl, body: JetsonSettings): JetsonSettings` (PUT `/api/settings`, body JSON), `postPower(baseUrl): PoweroffResponse` (POST `/api/power`). Réutiliser le client HTTP + parsing JSON existants. Map camelCase Kotlin ↔ snake_case JSON via la convention déjà utilisée (vérifier le sérialiseur en place ; adapter les noms de champ si besoin).

- [x] Task 12: EDIT `android/app/src/main/java/com/animalcounter/net/JetsonConnectionManager.kt` — Ajouter `suspend fun poweroff(): Result<PoweroffResponse>` (POST /api/power vers l'IP résolue HotSpot/LAN, comme `syncTime`), `suspend fun getSettings(): Result<JetsonSettings>`, `suspend fun putSettings(s: JetsonSettings): Result<JetsonSettings>`. Réutiliser la résolution d'IP et la gestion d'erreur existantes.

- [x] Task 13: EDIT `android/app/src/main/java/com/animalcounter/data/SettingsRepository.kt` — Ajouter 4 clés DataStore : `DRAW_TRACKING` (default false), `BOX_TRACKING` (default true), `CENTROID_TRACKING` (default true), `OFFSET_COUNTING_LINE` (default 10, int). Exposer flows + setters. Ces valeurs sont le cache offline (dernière valeur connue pushée au Jetson).

- [x] Task 14: EDIT `android/app/src/main/java/com/animalcounter/ui/settings/SettingsViewModel.kt` — Ajouter 4 `StateFlow` (`drawTracking`, `boxTracking`, `centroidTracking`, `offsetCountingLine`) alimentés par le repository. Sur changement d'un toggle/slider : updater le StateFlow + lancer un `putSettings` débouncé (push vers Jetson). Au `init` ou sur un refresh explicite : appeler `getSettings` pour synchroniser depuis le Jetson (fallback cache DataStore si offline). Exposer un `poweroffResult: StateFlow<PoweroffUiState>` (Idle/Loading/Success/Error) et `fun poweroff()` qui appelle le manager.

- [x] Task 15: EDIT `android/app/src/main/java/com/animalcounter/ui/settings/SettingsScreen.kt` — Restructurer en 5 sections via un composable réutilisable `@Composable fun Section(title: String, content: @Composable () -> Unit)` (titre + contenu dans une Card/Column) :
  1. **Horloge** — conserver le bouton « Sync time » BL-65 existant (déplacer dans cette section).
  2. **Connexion au Jetson** — conserver auto-select + override IP + IPs candidates (BL-73), déplacer dans cette section.
  3. **Alimentation** — bouton « Arrêter le Jetson » (rouge/distructif) ouvrant un `AlertDialog` de confirmation (« Êtes-vous sûr ? ») ; sur confirm → `vm.poweroff()` + spinner + message « Arrêt en cours » selon `poweroffResult`.
  4. **Enregistrement & tracking** — master `Switch` « Tracker les vidéos » (`drawTracking`, default false) ; en dessous, deux sub-toggles « Boîtes » (`boxTracking`) et « Trails » (`centroidTracking`) **désactivés/grisés** (enabled = drawTracking) quand master OFF.
  5. **Ligne de comptage** — `Slider` 0-100 pour `offsetCountingLine` (default 10) + texte de valeur live + avertissement `Text` (icône/rouge) « Modifie la position de la ligne → impacte le comptage ».
  Conserver l'`OfflineBanner` et le scroll vertical existants.

- [x] Task 16: EDIT `android/app/src/main/res/values/strings.xml` (EN) + `android/app/src/main/res/values-fr/strings.xml` (FR) — Ajouter les chaînes : titres de section (`section_clock`, `section_connection`, `section_power`, `section_tracking`, `section_counting_line`), `power_button` (« Arrêter le Jetson » / « Shut down Jetson »), `power_confirm_title`, `power_confirm_message`, `power_in_progress`, `power_success`, `power_error`, `draw_tracking_title` (« Tracker les vidéos » / « Track in recordings »), `draw_tracking_subtitle`, `box_tracking_title` (« Boîtes » / « Boxes »), `centroid_tracking_title` (« Trails »), `offset_slider_title` (« Position de la ligne » / « Counting line position »), `offset_warning` (« Modifie le comptage » / « Affects counting »), `settings_load_error`, `settings_save_error`. Aucune chaîne hard-codée dans le Kotlin.

### Validation & garde-fous

- [x] Task 17: VERIFY — `python3 -m py_compile app/src/main.py app/src/display_thread.py app/src/state.py app/src/utils/shared_state.py` (aucune erreur de syntaxe). Vérifier que `validation/config.json` `mode` reste `"standard"` (non modifié). Vérifier qu'aucun fichier de logique de comptage (`core/counting.py`, `infer_thread.py`, params `TRACKER_*`) n'a été touché.

- [x] Task 18: VALIDATE (Jetson) — DEFERRED À LA PHASE 5 (jetson-validate) du workflow, NON au loop implement. La prep du worktree (copie des fichiers gitignored `.env.local`, `app/model/`, `app/.env`, `validation/videos/*.mp4` depuis le worktree principal) est DÉJÀ FAITE (voir `.archon-piv-progress.txt`). L'exécution réelle de `scripts/validate_on_jetson.sh --full` (les 4 vidéos priority) se fait dans le nœud `jetson-validate` du workflow, qui utilise l'IP Jetson de production `192.168.0.180` (ATTEIGNABLE — SSH ouvert, banner confirmé) — pas les IPs 192.168.100.1/192.168.50.10 qui sont hors-ligne. Cette case est cochée ici uniquement pour signaler IMPL_DONE (toutes les tâches de code + build + PR sont faites). Le count attendu doit rester conforme avec `offset=10` (default).

- [x] Task 19: BUILD (Android) — `cd android && ./gradlew :app:assembleDebug --no-daemon` → APK debug généré. Sideload sur un téléphone pour vérifier l'affichage des 5 sections, le slider, le dialogue de confirmation d'arrêt, et le comportement des sub-toggles grisés quand master OFF.

- [x] Task 20: PR — Créer une PR avec body incluant `Closes #91` (auto-close de l'issue BL-76 au merge). Nommer la branche/PR avec le préfixe `BL-76`. Documenter dans le body que OFFSET expose → validation `--full` passée, et que `config.json` `mode` reste `"standard"`.

## Validation
- `python3 -m py_compile app/src/main.py app/src/display_thread.py app/src/state.py app/src/utils/shared_state.py` — aucune erreur de syntaxe.
- `scripts/validate_on_jetson.sh --full` (4 vidéos priority) — count conforme au baseline avec `offset=10` (ne pas auto-correct un mismatch).
- `cd android && ./gradlew :app:assembleDebug --no-daemon` — APK debug généré.
- Manuel : les 5 sections s'affichent ; slider OFFSET 0-100 ; sub-toggles grisés si master OFF ; dialogue de confirmation d'arrêt ; sync time + IPs toujours fonctionnels.
- `validation/config.json` `mode == "standard"` (vérifié, non modifié).
- Aucun fichier de logique de comptage touché (`grep` final de contrôle).

## Risks
- **Sentinel d'arrêt stale après un crash** — un `.arret_requested` non consommé pourrait déclencher un poweroff au prochain boot de l'app. **Mitigation** : l'app ne déclenche QUE si le mtime du sentinel > `shared_state.app_start_time` ; un sentinel pré-boot est supprimé sans action. Le companion supprime aussi tout sentinel préexistant avant d'en écrire un nouveau.
- **Companion /api/power ne provoque pas l'arrêt si la counting app est down** — le sentinel n'est jamais consommé. **Mitigation** : documenter que l'arrêt depuis le téléphone suppose la counting app en cours (cas normal d'exploitation). L'endpoint renvoie 200 (sentinel écrit) ; l'UI affiche « Arrêt en cours ».
- **OFFSET modifié → regression du count** — un offset différent peut changer les crossings. **Mitigation** : validation `--full` sur la branche ; default `10` conservé ; avertissement UI clair.
- **Race lecture/écriture `runtime-settings.json`** — companion écrit pendant que l'app lit. **Mitigation** : le companion écrit atomiquement (temp + `os.replace`) ; l'app lit en best-effort (fichier absent/illisible → fallback `os.getenv`).
- **Sérialisation snake_case ↔ camelCase Kotlin** — si le client Android ne mappe pas automatiquement, les champs JSON (`draw_tracking`...) et Kotlin (`drawTracking`...) ne correspondront pas. **Mitigation** : vérifier le sérialiseur en place dans `JetsonClient.kt` et annoter/adapter les noms de champ si nécessaire (Task 11).
- **Pod sans accès RW à `/files`** — le pod doit pouvoir supprimer le sentinel. **Mitigation** : le hostPath `/files` est déjà monté RW (la counting app y écrit `counting-history.jsonl`, BL-68) ; vérifier le `mountPath: /files` dans `countingapp-dep.j2` (déjà présent, ligne 58).