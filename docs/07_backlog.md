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

## Ordre recommandé (ROI décroissant)

1. **BL-25** Tests unitaires `counting.py` — P1, M, 🟢 — filet de sécurité pour
   toutes les modifs futures ; élimine la revalidation Jetson systématique.
2. **BL-37** Clés SSH — P1, S, 🟢 — quick win sécurité immédiat.
3. **BL-18** Graceful shutdown — P1, S, 🟢 — arrêt propre K8s sans corruption.
4. **BL-21 + BL-23** Endpoint `/metrics` + `/count` — P1, M, 🟢 — observabilité
   prod ; débloque le monitoring 24/7.
5. **BL-17** GC résiduel — P0, M, 🟡 — clôture la fuite mémoire long-terme
   (après validation sur vidéos à retours).
6. **BL-29** Refactor `main.py` — P1, L, 🟡 — à planifier post-BL-25.

Les quick wins **BL-37 + BL-18 + BL-25** renforcent sécurité + testabilité
sans toucher à la logique de comptage validée (risque 🟢) : point d'entrée
idéal pour la suite.

## Historique des livraisons

| Commit | Items livrés | Résumé |
|---|---|---|
| `8382e0e` | BL-01, BL-02 (+1), BL-03, BL-04, BL-05 (+1), BL-06, BL-07, BL-10¹, BL-14, BL-15 | Fix ID-switch (27/27 pass) |
| `f84d36a` | BL-02 (mirror −1), BL-05 (mirror −1), BL-09, BL-16 | Bidirectionnel + flush + docs |
| `c3f8fdf` | BL-10, BL-11, BL-12, BL-13 | 4 quick wins (GC, deque, defaults, dead code) |

¹ BL-10 esquissé en `8382e0e`, finalisé en `c3f8fdf`.

**État courant** : 30/30 vidéos validées (4/4 prioritaires re-validées après
quick wins, REID-SUPPRESS #35 inchangé). 3 commits locaux, non poussés.