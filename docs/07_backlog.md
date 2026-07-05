# Backlog d'améliorations

Ce document est la **backlog vivante** du projet *animal-counter*. Il recense
l'ensemble des améliorations identifiées (robustesse, observabilité,
testabilité, architecture, performance, sécurité, documentation), qu'elles
soient déjà livrées ou à venir.

Chaque item possède un identifiant stable (`BL-XX`) pour le suivi dans les
commits, les revues de code et les discussions. L'ordre du tableau récapitulatif
reflète la priorité, pas l'ordre d'implémentation.

## Légende

| Champ | Valeurs |
|---|---|
| **Statut** | ✅ fait · 🔄 partiel · ⬜ à faire · ❌ abandonné |
| **Priorité** | P0 (bloquant production) · P1 (important) · P2 (nice-to-have) |
| **Effort** | S (&lt; 1h) · M (≈ ½ journée) · L (&gt; 1j) |
| **Risque** | 🟢 faible (pas de logique de comptage) · 🟡 moyen (toucher au comptage) · 🔴 élevé |

## Tableau récapitulatif

| ID | Titre | Catégorie | Priorité | Effort | Risque | Statut |
|---|---|---|---|---|---|---|
| BL-01 | Tuning OC-SORT | Robustesse | P0 | M | 🟡 | ✅ fait |
| BL-02 | Garde ID-switch recovery bidirectionnelle | Robustesse | P0 | L | 🔴 | ✅ fait |
| BL-03 | GUARD_MAX_AGE (découplé du lost buffer) | Robustesse | P0 | S | 🟡 | ✅ fait |
| BL-04 | Cleanup `lost_tracks` au retour d'ID | Robustesse | P0 | S | 🟡 | ✅ fait |
| BL-05 | REID-SUPPRESS (sens +1 et −1) | Robustesse | P0 | M | 🔴 | ✅ fait |
| BL-06 | Garde resurrection (Pattern B filet) | Robustesse | P1 | S | 🟡 | ✅ fait |
| BL-07 | Garde miroir (mode log) | Robustesse | P2 | S | 🟢 | ✅ fait |
| BL-08 | Hystérésis ligne de comptage | Robustesse | P2 | S | 🔴 | ❌ abandonné (régression #18) |
| BL-09 | Fix flush `result.json` | Robustesse | P0 | S | 🟡 | ✅ fait |
| BL-10 | GC `first_seen`/`last_seen`/`trails` | Robustesse | P0 | S | 🟢 | ✅ fait |
| BL-11 | `trails` en `deque(maxlen=60)` | Performance | P2 | S | 🟢 | ✅ fait |
| BL-12 | Defaults `settings.py` alignés | Architecture | P1 | S | 🟢 | ✅ fait |
| BL-13 | Suppression `process_for_tracking` | Architecture | P1 | S | 🟢 | ✅ fait |
| BL-14 | `.env.example` + `.gitignore` | Sécurité | P1 | S | 🟢 | ✅ fait |
| BL-15 | Renommage vidéos + manifeste | Documentation | P1 | S | 🟢 | ✅ fait |
| BL-16 | `docs/06_counting_pipeline.md` | Documentation | P1 | M | 🟢 | ✅ fait |
| BL-17 | GC résiduel `detections`/`area_in`/`area_out` | Robustesse | P0 | M | 🟡 | ⬜ à faire |
| BL-18 | Graceful shutdown (SIGTERM) | Robustesse | P1 | S | 🟢 | ⬜ à faire |
| BL-19 | Surveillance mémoire (alerte RSS) | Robustesse | P1 | S | 🟢 | ⬜ à faire |
| BL-20 | Reconnexion caméra auto | Robustesse | P1 | M | 🟡 | ⬜ à faire |
| BL-21 | Endpoint `/metrics` Prometheus | Observabilité | P1 | M | 🟢 | ⬜ à faire |
| BL-22 | Logging JSON structuré | Observabilité | P1 | S | 🟢 | ⬜ à faire |
| BL-23 | Counter exposé via API (`/count`) | Observabilité | P1 | S | 🟢 | ⬜ à faire |
| BL-24 | Dashboard temps réel | Observabilité | P2 | L | 🟢 | ⬜ à faire |
| BL-25 | Tests unitaires `counting.py` | Testabilité | P1 | M | 🟢 | ⬜ à faire |
| BL-26 | Mode de validation local | Testabilité | P1 | M | 🟢 | ⬜ à faire |
| BL-27 | CI (lint + compile + tests) | Testabilité | P1 | S | 🟢 | ⬜ à faire |
| BL-28 | Fixtures de tracks (rejeu d'IDs) | Testabilité | P2 | M | 🟢 | ⬜ à faire |
| BL-29 | Refactor `main.py` (658 lignes) | Architecture | P1 | L | 🟡 | ⬜ à faire |
| BL-30 | Aligner tous les defaults (paths) | Architecture | P2 | S | 🟢 | ⬜ à faire |
| BL-31 | Centraliser la config (source unique) | Architecture | P2 | M | 🟢 | ⬜ à faire |
| BL-32 | Type hints + docstrings `counting.py` | Architecture | P2 | M | 🟢 | ⬜ à faire |
| BL-33 | Préfetch GPU (decode + preprocess) | Performance | P2 | M | 🟡 | ⬜ à faire |
| BL-34 | Vectorisation numpy `counting.py` | Performance | P2 | S | 🟢 | ⬜ à faire |
| BL-35 | Mode headless (sans `cv2.imshow`) | Performance | P2 | S | 🟢 | ⬜ à faire |
| BL-36 | Profiling (py-spy) | Performance | P2 | S | 🟢 | ⬜ à faire |
| BL-37 | Clés SSH (remplacer `sshpass`) | Sécurité | P1 | S | 🟢 | ⬜ à faire |
| BL-38 | Secrets via vault / K8s Secret | Sécurité | P2 | M | 🟢 | ⬜ à faire |
| BL-39 | Diagramme de flux des gardes | Documentation | P2 | S | 🟢 | ⬜ à faire |
| BL-40 | README runbook | Documentation | P2 | M | 🟢 | ⬜ à faire |
| BL-41 | Matrice de validation (vidéo → fix) | Documentation | P2 | S | 🟢 | ⬜ à faire |
| BL-42 | Persistance du compteur (snapshot + reload) | Robustesse | P0 | M | 🟡 | ⬜ à faire |
| BL-43 | `stop()` finalise `video_writer` (release) | Robustesse | P0 | S | 🟡 | ⬜ à faire |
| BL-44 | MP4 fragmented (résistance coupure secteur) | Robustesse | P1 | M | 🟡 | ⬜ à faire |
| BL-45 | `livenessProbe` HTTP `/health` | Robustesse | P1 | S | 🟢 | ⬜ à faire |
| BL-46 | `terminationGracePeriodSeconds` 0→30 s | Robustesse | P0 | S | 🟢 | ⬜ à faire |
| BL-47 | Réduire `privileged` + retirer `docker.sock` | Sécurité | P2 | M | 🟡 | ⬜ à faire |
| BL-48 | Filebrowser creds `admin/admin` → mdp fort | Sécurité | P2 | S | 🟢 | ⬜ à faire |
| BL-49 | Pinner `ffmpeg:latest` | Ops | P2 | S | 🟢 | ⬜ à faire |
| BL-50 | Accès externe countingapp (externalIP/ingress) | Ops | P2 | S | 🟢 | ⬜ à faire |
| BL-51 | Cleanup vidéo restreint aux `.mp4` | Robustesse | P2 | S | 🟢 | ✅ fait |

## 1. Robustesse / Production (24/7)

### ✅ BL-01 — Tuning OC-SORT
Paramètres OC-SORT calibrés sur les vidéos de référence :
`lost_track_buffer=20`, `high_conf_det_threshold=0.6`,
`minimum_iou_threshold=0.3`, `minimum_consecutive_frames=5` (était 3),
`delta_t=3`, `direction_consistency_weight=0.25`. Tous configurables via
`settings.py` + `app/.env`. *Commit `8382e0e`.*

### ✅ BL-02 — Garde ID-switch recovery bidirectionnelle
Détecte les tracks perdus d'un côté de la ligne ; quand un nouvel ID apparaît
de l'autre côté, les fusionne et déclenche le crossing (+1 ou −1 selon la
direction). `want_side = "in" if element[0] <= x else "out"` unifie les deux
sens. *Commits `8382e0e` (+1) + `f84d36a` (mirror −1).*

### ✅ BL-03 — GUARD_MAX_AGE
`COUNTING_GUARD_MAX_AGE=15` découplé de `COUNTING_LOST_BUFFER_FRAMES=60` :
les longues occlusions (#35) et l'évitement de fusion périmée (#30)
coexistent. *Commit `8382e0e`.*

### ✅ BL-04 — Cleanup `lost_tracks` au retour d'ID
Quand un ID réapparaît, on consomme son entrée `lost_tracks` → empêche le
ré-usage fantôme "lost in". Fix #11. *Commit `8382e0e`.*

### ✅ BL-05 — REID-SUPPRESS (sens +1 et −1)
Supprime le faux +1 (resp. −1) quand un ID connu réapparaît après une absence
courte alors qu'un **autre** ID est apparu pendant l'absence et a traversé
récemment. Signature = historique de crossings, pas le saut de position seul.
Fix #35 (+1). Mirror −1 ajouté en `f84d36a` (inactif sur les 4 vidéos de test).
*Commits `8382e0e` + `f84d36a`.*

### ✅ BL-06 — Garde resurrection (Pattern B filet)
Détecte un saut > 150 px + age > 5 frames. Jamais déclenché sur cas réels,
mais inoffensif. *Commit `8382e0e`.*

### ✅ BL-07 — Garde miroir (mode log)
3 modes (off/log/enforce). 0 candidat détecté → laissé en `log` (inerte).
*Commit `8382e0e`.*

### ❌ BL-08 — Hystérésis ligne de comptage
Testée à H=25 → **régression #18** (a avalé un crossed RIGHT légitime →
sur-compte). Désactivée (H=0). *Abandonné.*

### ✅ BL-09 — Fix flush `result.json`
`result.json` était écrit trop tôt : `infer_thread.join(timeout=300)` +
`display_thread.join(timeout=300)` expiraient sur les vidéos longues →
dernier crossing perdu (fix #32). Nouveau séquencement en mode validate :
`infer_thread.join()` (sans timeout) → `frame_queue.join()` (drain) →
`stop_event.set()` → `display_thread.join(60)` → `write_result_json()`.
Mode caméra inchangé. *Commit `f84d36a`.*

### ✅ BL-10 — GC `first_seen`/`last_seen`/`trails`
Purge périodique (toutes les 30 frames) des dicts auxiliaires pour les IDs
absents > `lost_buffer_frames`. Sûr : ces structures ne sont consultées que
par des gardes à fenêtre courte (≤ 15 frames). `detections`/`area_in_list`/
`area_out_list` **non** purgés (BL-17). *Commit `c3f8fdf`.*

### ⬜ BL-17 — GC résiduel `detections`/`area_in_list`/`area_out_list`
**Priorité P0 · Effort M · Risque 🟡.** Suite de BL-10 : ces structures
grandissent encore (1 entrée par ID disparu, jamais purgées). Croissance lente
mais sur semaines/mois en 24/7 ça devient significatif.

**Difficulté** : purger trop tôt risque d'avaler un retour légitime (cochon qui
revient après longue absence → `crossed RIGHT`/`-1` perdu).

**Piste** : seuil de purge **très élevé** (ex. 1800 frames = 60s d'absence, où
un retour est improbable) + ne purger que les IDs **ni visibles ni dans
`lost_tracks`**. À valider sur les vidéos avec retours (#18, #30, #24) avant
activation.

### ⬜ BL-18 — Graceful shutdown (SIGTERM)
**Priorité P1 · Effort S · Risque 🟢.** Handler SIGTERM → `stop_event.set()` +
`join()` des threads → flush `result.json`. Évite la corruption du résultat
et les zombies lors d'un arrêt K8s (rolling update, scale-down).

### ⬜ BL-19 — Surveillance mémoire (alerte RSS)
**Priorité P1 · Effort S · Risque 🟢.** Log + métrique si RSS > seuil. Détecte
une fuite résiduelle (BL-17) avant OOM. À coupler à BL-21 (`/metrics`).

### ⬜ BL-20 — Reconnexion caméra auto
**Priorité P1 · Effort M · Risque 🟡.** Sur perte de flux / timeout, retry
backoff + reset tracker + persistance du compteur. Aujourd'hui un plantage
caméra ferait perdre le compte cumulé.

## 2. Observabilité / Exploitabilité

### ⬜ BL-21 — Endpoint `/metrics` Prometheus
**Priorité P1 · Effort M · Risque 🟢.** Exposer : `count_total`, `count_net`,
`fps`, `latence_inférence_ms`, `nb_tracks_actifs`, `rss_bytes`,
`frames_processed`. Permet à l'orchestrateur K8s / Grafana de suivre le
comptage en direct et facilite le debug prod.

### ⬜ BL-22 — Logging JSON structuré
**Priorité P1 · Effort S · Risque 🟢.** Remplacer les chaînes
`INFO:[TRACK] ID=1.0 crossed LEFT // Count 1` par du JSON
(`{"event":"crossed","tid":1,"direction":"left","count":1,"frame":...}`).
Ingestion ELK/Loki facilitée, requêtes filtrables.

### ⬜ BL-23 — Counter exposé via API (`/count`)
**Priorité P1 · Effort S · Risque 🟢.** `GET /count` →
`{"count":42,"frames_processed":18143,"uptime_s":...}`. Lecture simple pour
un dashboard ou un orchestrateur. À combiner avec BL-21.

### ⬜ BL-24 — Dashboard temps réel
**Priorité P2 · Effort L · Risque 🟢.** Page web simple (ou Grafana) qui
consomme `/metrics` + `/count` : compteur live, FPS, courbe de comptage, flux
caméra. Dépend de BL-21/BL-23.

## 3. Qualité / Testabilité

### ⬜ BL-25 — Tests unitaires `counting.py` ⭐
**Priorité P1 · Effort M · Risque 🟢.** Rejouer les séquences d'IDs des cas
`#35` (REID-SUPPRESS), `#30` (GUARD_MAX_AGE), `#11` (cleanup lost_tracks) en
unitaire, sans vidéo ni Jetson. Détecte les régressions de logique de comptage
**en secondes** au lieu de ~15 min/vidéo sur Jetson. **Haut ROI** : filet de
sécurité pour toutes les futures modifs de `counting.py`.

**Approche** : mocker `Counting.count()` en injectant une liste
`(track_id, x, y, class_id)` par frame, vérifier le `counter_to_right` final.
Capturer les séquences depuis les logs `counting_events` des vidéos validées.

### ⬜ BL-26 — Mode de validation local
**Priorité P1 · Effort M · Risque 🟢.** Lancer l'inférence sur la machine de
dev (GPU si présent) et écrire `result.json`, en sautant le K8s/SCP du Jetson.
Accélère le cycle dev → test. Réutiliser `validate_on_jetson.sh` en mode
`--local`.

### ⬜ BL-27 — CI (lint + compile + tests)
**Priorité P1 · Effort S · Risque 🟢.** Pre-commit : `ruff` (lint/format),
`py_compile` sur tout `app/src/`, `pytest` sur BL-25. Évite les commits
cassés (syntaxe, imports) et les régressions de comptage.

### ⬜ BL-28 — Fixtures de tracks (rejeu d'IDs)
**Priorité P2 · Effort M · Risque 🟢.** Sérialiser les séquences d'IDs des
vidéos validées en fixtures JSON rejouables par les tests (BL-25). Permet de
tester des scénarios synthétiques (ID-switch, longue occlusion, retour).

## 4. Architecture / Dette technique

### ✅ BL-12 — Defaults `settings.py` alignés
`OFFSET 0→10`, `PIG_CONFIDENCE 0.7→0.6`, `DRAW_TRACKING True→False`,
`LOG_LEVEL DEBUG→INFO`, `CAPTURE_INTERVAL 5→1`. `.env` reste prioritaire sur
le Jetson. *Commit `c3f8fdf`.*

### ✅ BL-13 — Suppression `process_for_tracking`
143 lignes de code mort (jamais appelé). *Commit `c3f8fdf`.*

### ⬜ BL-29 — Refactor `main.py` (658 lignes)
**Priorité P1 · Effort L · Risque 🟡.** Séparer en `infer_thread.py`,
`display_thread.py`, `validate.py`, `cli.py`. Chaque module devient testable
et lisible. Gros chantier, à planifier quand la logique de comptage est
stabilisée (post-BL-25).

### ⬜ BL-30 — Aligner tous les defaults (paths)
**Priorité P2 · Effort S · Risque 🟢.** Suite de BL-12 : `DATASET_DIR`,
`OUTPUT_VIDEO_PATH` dépendent de l'env (local vs Jetson). Décider d'un
default unique ou d'une détection auto.

### ⬜ BL-31 — Centraliser la config (source unique)
**Priorité P2 · Effort M · Risque 🟢.** Aujourd'hui les valeurs validées
existent dans `.env`, `.env.example`, `settings.py` (defaults). Un seul source
of truth (ex. `config.py` + `.env` injecté) éviterait la dérive.

### ⬜ BL-32 — Type hints + docstrings `counting.py`
**Priorité P2 · Effort M · Risque 🟢.** `counting.py` est dense (~470 lignes,
plusieurs gardes entrelacées). Type hints + docstrings par garde faciliterait
la revue et l'onboarding. À faire après BL-25 (tests verrouillent le
comportement).

## 5. Performance

### ✅ BL-11 — `trails` en `deque(maxlen=60)`
O(1) append + auto-rotation au lieu de O(n) `pop(0)`. *Commit `c3f8fdf`.*

### ⬜ BL-33 — Préfetch GPU (decode + preprocess)
**Priorité P2 · Effort M · Risque 🟡.** Décoder/préprocesser la frame N+1
pendant l'inférence de la frame N. Gain si la decode CPU est un goulot sur le
Jetson. À confirmer par BL-36 (profiling) d'abord.

### ⬜ BL-34 — Vectorisation numpy `counting.py`
**Priorité P2 · Effort S · Risque 🟢.** Les boucles sur `tracking_boxes` sont
Python pur. Marginal : l'inférence YOLO domine. À faire uniquement si BL-36
montre `counting.py` au profil.

### ⬜ BL-35 — Mode headless (sans `cv2.imshow`)
**Priorité P2 · Effort S · Risque 🟢.** Évite la dépendance X / l'erreur
display sur le Jetson headless. Garde `cv2.imshow` derrière un flag
`DISPLAY_PREVIEW` (default False).

### ⬜ BL-36 — Profiling (py-spy)
**Priorité P2 · Effort S · Risque 🟢.** Profiler un run sur Jetson pour
identifier les vrais bottlenecks (decode ? inférence ? counting ? rendering ?)
avant d'investir dans BL-33/BL-34.

## 6. Sécurité / Ops

### ✅ BL-14 — `.env.example` + `.gitignore`
`.env` gitignoré, `.env.example` versionné (defaults documentés). *Commit
`8382e0e`.*

### ⬜ BL-37 — Clés SSH (remplacer `sshpass`) ⭐
**Priorité P1 · Effort S · Risque 🟢.** `validate_on_jetson.sh` utilise
`sshpass` avec `JETSON_PASSWORD` en clair dans `.env.local`. Passer à une clé
SSH dédiée (dépôt une fois sur le Jetson) supprime le mot de passe et
simplifie l'auth. **Quick win immédiat.**

### ⬜ BL-38 — Secrets via vault / K8s Secret
**Priorité P2 · Effort M · Risque 🟢.** Mdp en var d'env = fuite potentielle.
Migrer vers K8s Secret (ou vault) pour la prod. Dépend du contexte déploiement.

## 7. Documentation

### ✅ BL-15 — Renommage vidéos + manifeste
Convention `validation-<seq>-#<count>.mp4`. *Commit `8382e0e`.*

### ✅ BL-16 — `docs/06_counting_pipeline.md`
Pipeline complet : architecture, ligne de comptage, tuning OC-SORT, toutes
les gardes, flush, table de paramètres, validation (30/30 pass), limitations.
*Commit `f84d36a`.*

### ⬜ BL-39 — Diagramme de flux des gardes
**Priorité P2 · Effort S · Risque 🟢.** Schéma ASCII / mermaid de l'enchaînement
des gardes (ID-switch recovery → GUARD_MAX_AGE → REID-SUPPRESS → resurrection
→ mirror) dans `docs/06`. Rend le pipeline visuel.

### ⬜ BL-40 — README runbook
**Priorité P2 · Effort M · Risque 🟢.** Démarrage caméra / validation / debug,
pas-à-pas, avec les commandes exactes et les pièges connus. Actuellement
éparpillé dans `01_quickstart.md` + `06_counting_pipeline.md` + scripts.

### ⬜ BL-41 — Matrice de validation (vidéo → fix)
**Priorité P2 · Effort S · Risque 🟢.** Table qui relie chaque vidéo de test
au(x) fix(es) qui la résout (ex. `#35` → BL-05 REID-SUPPRESS, `#30` → BL-03
GUARD_MAX_AGE, `#11` → BL-04 cleanup, `#32` → BL-09 flush). Aide au debug et
au choix des vidéos de régression.

## 8. Déploiement K3S en production

> **Recadrage important (2026-07-05).** Les **vrais manifests de prod** sont les
> templates Jinja2 dans `k3s/templates/`, déployés via Ansible
> (`ansible/playbooks/app/deploy_countingapp.yml`). Les fichiers
> `examples/deploy/k3s_conf/*` sont **legacy et ne sont pas appliqués en prod** —
> une première analyse s'était basée dessus à tort.
>
> **Constats de l'analyse précédente INVALIDÉS par le recadrage** (ne pas
> re-créer comme items) :
> - ❌ « Pas de `resources` limits sur countingapp » → **faux**, `countingapp-dep.j2`
>   a déjà `requests 2Gi / limits 4Gi` (+ `nvidia.com/gpu: 1`, cpu 500m/2).
> - ❌ « Env du manifest inertes (`INPUT`/`FILE`/`DRAWTRACKING`) » → **faux**, le
>   vrai template ne passe que `DISPLAY` ; les noms erronés n'existaient que dans
>   le manifest legacy `examples/deploy/k3s_conf/countingapp-rs.yaml`.
> - ❌ « Ingress cassé (port 30501 vs 31501, `apiVersion` manquant) » → l'ingress
>   legacy `examples/deploy/` n'est **pas déployé en prod**. Reformulé en BL-50
>   (ajouter un accès externe, optionnel).
> - ❌ « `video-compress-fast` non versionné » → **faux**, il est dans
>   `k3s/templates/cronvideo-dep.j2`.
> - ❌ « `filebrowser:latest` non pinné » → **faux**, image
>   `ghcr.io/gtsteffaniak/filebrowser:stable` (pinné). Seul `ffmpeg:latest` reste
>   non pinné (BL-49).
> - ❌ « `hostPath /app` code source live » → **volontaire** (choix utilisateur,
>   permet le rsync + restart à chaud pour itérations). Ne pas corriger.
>
> **État constaté sur le Jetson (Orin Nano 8 Gi, « Super » 25 W) :** RAM 7,4 Gi,
> dispo 5,5 Gi. Le pod `countingapp` est un **DaemonSet** `countingapp-dep.j2`,
> pausable via `nodeSelector: validate-paused=true` (mécanisme de pause pendant
> les validations — voulu). `filebrowser` (78 Mi) + `video-compress-fast` (411 Mi)
> tournent en continu. RESTARTS=50 sur 40 jours ≈ coupure secteur quotidienne.

### ⬜ BL-42 — Persistance du compteur (snapshot + reload) ⭐⭐
**Priorité P0 · Effort M · Risque 🟡.** `shared_state.counter_to_right` est
**strictement en mémoire**, jamais écrit sur disque. `stop()` ne le sauvegarde
pas. Au redémarrage du pod (crash, OOM, mise à jour K3S, **coupure secteur
quotidienne**), le compteur **retombe à 0** → l'utilisateur perd le cumul depuis le
matin. `restartPolicy: Always` relance l'app automatiquement → l'écran revient,
compteur à 0, **sans que l'utilisateur ne le remarque forcément** → relevé de fin
 de journée faux. C'est **le risque prod #1**.

**Fix** : snapshot périodique (ex. toutes les 30 s ou tous les 10 cochons) dans
`/files/count_snapshot.json` (volume déjà monté) ; au démarrage, **recharger le
snapshot du jour** si présent. Comportement « 0 au matin » à préserver via un
reset manuel (bouton/flag) ou un reset auto à minuit. **À discuter avec
l'utilisateur** : reset matin volontaire vs reload après crash.

### ⬜ BL-43 — `stop()` finalise `video_writer` (release)
**Priorité P0 · Effort S · Risque 🟡.** `stop()` (appelée par le handler SIGTERM)
**ne release pas `video_writer`** (le `release()` est dans la boucle
`DisplayThread`, `main.py:274`, pas dans `stop()`). Sur SIGTERM K3S → mp4 non
finalisé (moov atom manquant) → **vidéo illisible**. Fix code : dans `stop()`,
`if self.video_writer: self.video_writer.release()` avant le `join`. Complète
BL-46 (manifest) et BL-18 (umbrella).

### ⬜ BL-44 — MP4 fragmented (résistance coupure secteur)
**Priorité P1 · Effort M · Risque 🟡.** La coupure secteur (arrêt quotidien) coupe
net l'écriture du mp4 → moov atom manquant → vidéo corrompue. `cv2.VideoWriter`
n'écrit pas le moov en début/fragments. Mitigation : mp4 **fragmented /
faststart** (moov en début de fichier, ou fragments réguliers) → vidéo
récupérable même coupée. Soit un muxer fragmented natif, soit un remux ffmpeg
périodique, soit `ffmpeg -movflags +faststart` post-processing par
`video-compress-fast`. À évaluer vs `cv2.VideoWriter`.

### ⬜ BL-45 — `livenessProbe` HTTP `/health`
**Priorité P1 · Effort S · Risque 🟢.** `countingapp-dep.j2` n'a **aucune probe**.
Si l'app **freeze** (caméra bloquée, deadlock thread, fuite sévère) sans crasher,
K3S ne redémarre pas → écran figé, comptage mort, utilisateur non alerté. Fix :
`livenessProbe` HTTP `GET /health` qui répond 200 si l'inférence tourne
(FPS > 0 / `counter` mis à jour récemment). Nécessite BL-23 (endpoint `/count`)
ou un endpoint `/health` minimal.

### ⬜ BL-46 — `terminationGracePeriodSeconds` 0→30 s
**Priorité P0 · Effort S · Risque 🟢.** `countingapp-dep.j2` a
`terminationGracePeriodSeconds: 0` → K3S envoie SIGTERM et **tue immédiatement**.
`stop()` n'a donc **même pas le temps** d'appeler `video_writer.release()` →
vidéo en cours corrompue à **chaque arrêt de pod**. Fix manifest : passer à
`30` (laisse le temps à BL-43 de finaliser). À appliquer dans
`k3s/templates/countingapp-dep.j2`.

### ⬜ BL-47 — Réduire `privileged` + retirer `docker.sock`
**Priorité P2 · Effort M · Risque 🟡.** `countingapp-dep.j2` tourne en
`securityContext: privileged: true` **et** monte `/var/run/docker.sock` → le pod
a accès au Docker du host (peut lancer/tuer n'importe quel container du node).
Surface d'attaque large. Réduction : passer en headless (BL-35 supprime X11/
`DISPLAY`), `devices` pour `/dev/video0` au lieu de `privileged`, **supprimer
le mount `docker.sock`** (vérifier pourquoi il était là). Sur Jetson dédié c'est
acceptable mais à durcir.

### ⬜ BL-48 — Filebrowser creds `admin/admin` → mdp fort
**Priorité P2 · Effort S · Risque 🟢.** `filebrowser-sct.j2` + defaults Ansible
(`group_vars/all.yml` : `admin_username=admin`, `admin_password=admin`) →
credentials faibles par défaut. N'importe qui sur le réseau local peut accéder
en admin au filebrowser (supprimer les vidéos). Fix : mdp fort via
`FILEBROWSER_ADMIN_PASSWORD` en env (pas en clair dans le repo), et ne pas
default sur `admin`. Secret déjà en place (`filebrowser-sct.j2`) — juste un
 défaut faible à durcir.

### ⬜ BL-49 — Pinner `ffmpeg:latest`
**Priorité P2 · Effort S · Risque 🟢.** `cronvideo-dep.j2` utilise
`lscr.io/linuxserver/ffmpeg:latest` (non reproductible — une mise à jour de
l'image peut casser la compression). Fix : pinner un tag/digest précis
(ex. `:7.x` ou `@sha256:...`).

### ⬜ BL-50 — Accès externe countingapp (externalIP/ingress)
**Priorité P2 · Effort S · Risque 🟢.** `countingapp-svc.j2` est `ClusterIP`
**sans externalIP** → accessible uniquement à l'intérieur du cluster
(`10.43.222.223:31501`). Pour un dashboard/future API exposés, ajouter soit un
`externalIPs` (IP du Jetson), soit un Ingress Traefik (k3s default). Optionnel —
dépend du besoin d'accès externe (aujourd'hui l'utilisateur lit le compteur sur
l'écran X11 local du Jetson, pas via le réseau).

### ✅ BL-51 — Cleanup vidéo restreint aux `.mp4`
**Priorité P2 · Effort S · Risque 🟢.** `cronvideo-dep.j2` faisait
`find . -type f -size +2G -delete` → supprimait **tout fichier >2 Go** (y compris
un dataset/modèle éventuel dans `/videos`). Restreint à
`find . -maxdepth 1 -type f -name '*.mp4' -size +2G -delete` (ne cible que les
mp4 trop gros). Le `ls -t count* | awk 'NR>50'` est conservé (déjà ciblé `count*`).
*Commit à venir.*

## Ordre recommandé (ROI décroissant)

**Palier prod (protège l'usage quotidien matin→soir + coupure secteur) :**

1. **BL-42** Persistance du compteur — P0, M, 🟡 — **risque prod #1** : un
   redémarrage (crash/OMM/coupure) remet le compteur à 0 ; snapshot + reload.
2. **BL-43 + BL-46** Finaliser la vidéo (`stop().release()` +
   `terminationGracePeriodSeconds` 0→30 s) — P0, S, 🟡/🟢 — termine le mp4 à
   l'arrêt du pod ; sans ça, **chaque arrêt = vidéo corrompue**.
3. **BL-25** Tests unitaires `counting.py` — P1, M, 🟢 — filet de sécurité pour
   toutes les modifs futures ; élimine la revalidation Jetson systématique.
4. **BL-37** Clés SSH — P1, S, 🟢 — quick win sécurité immédiat.
5. **BL-18** Graceful shutdown (umbrella) — P1, S, 🟢 — englobe BL-43/BL-46.
6. **BL-21 + BL-23** Endpoint `/metrics` + `/count` — P1, M, 🟢 — observabilité
   prod ; débloque le monitoring 24/7 + BL-45 (`livenessProbe`).
7. **BL-44** MP4 fragmented — P1, M, 🟡 — résistance vidéo à la coupure secteur.
8. **BL-17** GC résiduel — P0, M, 🟡 — clôture la fuite mémoire long-terme.
9. **BL-29** Refactor `main.py` — P1, L, 🟡 — à planifier post-BL-25.

Les **BL-42 + BL-43 + BL-46** sont le minimum pour fiabiliser le workflow
quotidien (compteur persistant + vidéos non corrompues). Les quick wins
**BL-37 + BL-25** renforcent ensuite sécurité + testabilité sans toucher à la
logique de comptage validée (risque 🟢).

## Historique des livraisons

| Commit | Items livrés | Résumé |
|---|---|---|
| `8382e0e` | BL-01, BL-02 (+1), BL-03, BL-04, BL-05 (+1), BL-06, BL-07, BL-10¹, BL-14, BL-15 | Fix ID-switch (27/27 pass) |
| `f84d36a` | BL-02 (mirror −1), BL-05 (mirror −1), BL-09, BL-16 | Bidirectionnel + flush + docs |
| `c3f8fdf` | BL-10, BL-11, BL-12, BL-13 | 4 quick wins (GC, deque, defaults, dead code) |
| `119501b` | — (backlog initiale BL-01..BL-41) | docs: backlog vivante |
| _(à venir)_ | BL-51 | cronvideo-dep.j2 : cleanup vidéo restreint aux `.mp4` |

¹ BL-10 esquissé en `8382e0e`, finalisé en `c3f8fdf`.

**État courant** : 30/30 vidéos validées (4/4 prioritaires re-validées après
quick wins, REID-SUPPRESS #35 inchangé). Backlog à jour (BL-01..BL-51, dont
16 faits, 1 abandonné BL-08, 34 à faire). Recadrage des manifests de
prod (`k3s/templates/` via Ansible, et non `examples/deploy/` legacy). Commits
locaux, non poussés.