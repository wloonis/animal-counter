# Pipeline de comptage des cochons

Ce document décrit l'ensemble du traitement de comptage et les techniques
mises en œuvre pour obtenir un compte fiable, ainsi que les paramètres et
les compromis validés sur 30 vidéos de référence.

## 1. Vue d'ensemble

Le système compte des cochons traversant une ligne verticale, dans le sens
**droite → gauche** (la caméra est fixe, 30 fps). Chaque cochon qui traverse
la ligne de la droite vers la gauche compte pour **+1** ; un retour
gauche → droite compte pour **−1** (le compteur net reflète le nombre réel
de cochons passés).

Le défi principal est l'**ID-switch** : OC-SORT perd parfois la trace d'un
cochon près de la ligne (occlusion par un autre cochon) et lui attribue un
nouvel ID de l'autre côté. Selon le moment et le côté où l'ID switch se
produit, cela peut **sous-compter** (le cochon traversé n'est jamais vu
traverser) ou **surcompter** (le cochon est compté deux fois, une fois sous
chaque ID). La logique de comptage détecte et corrige ces cas par une
succession de **gardes** complémentaires, sans changer de tracker (OC-SORT
est conservé).

## 2. Architecture du pipeline

Deux threads coopèrent via une `frame_queue` (taille max 3, backpressure) :

```
InferThread (capture + détection)
  ├── lit la frame (caméra /dev/video0 ou fichier vidéo)
  ├── détection YOLO (TensorRT) → bounding boxes + scores + classes
  ├── post_process (NMS, filtrage conf) → boxes_pp
  └── frame_queue.put([image, boxes_pp, ...])

DisplayThread (tracking + comptage + rendu)
  ├── frame_queue.get()
  ├── reconstruit les détections (xyxy, confidence, class_id)
  ├── OC-SORT .update(detections) → boxes/IDs/classes suivies
  ├── filtre tracker_id == -1 (pas de track associée)
  ├── Counting.count(image, boxes, trackids, classids, ...)
  └── rendu / écriture vidéo
```

- **Détection** : YOLO (TensorRT), seuil de confiance `PIG_CONFIDENCE_THRESHOLD`
  (0.6), seuil renforcé sur les premières frames
  `PIG_CONFIDENCE_THRESHOLD_START_VIDEO` (0.8). NMS YOLO `IOU_THRESHOLD` (0.45),
  `CONF_THRESH` (0.5).
- **Tracking** : `OCSORTTracker` (lib `trackers`), voir §4.
- **Comptage** : `Counting.count()`, voir §3 et §5.

## 3. La ligne de comptage et le comptage de base

### Position de la ligne

```
x = img_width / 2 + img_width * OFFSET_PERCENT_COUNTING_LINE / 100
```

Avec `OFFSET_PERCENT_COUNTING_LINE = 10` et `img_width = 640`, la ligne est à
`x = 384`. Les régions sont :

- **côté "in" (droite)** : `cx > x`  → `area_in_list`
- **côté "out" (gauche)** : `cx ≤ x` → `area_out_list`

(`cx` = abscisse du centroïde de la bbox.)

### Comptage de base (crossed LEFT / RIGHT)

Pour chaque ID déjà connu, on compare la position courante à la précédente :

- **crossed LEFT** (`cx ≤ x_low` et ID était dans `area_in_list`) →
  `counter += 1`, ID passe dans `area_out_list`.
- **crossed RIGHT** (`cx ≥ x_high` et ID était dans `area_out_list`) →
  `counter -= 1`, ID passe dans `area_in_list`.

`x_low = x − H` et `x_high = x + H` avec `H = COUNTING_HYSTERESIS_PX`
(hystérésis, voir §5.7).

### Pourquoi c'est insuffisant

Si un cochon traverse la ligne mais qu'OC-SORT perd son ID juste avant et lui
en attribue un nouveau juste après, **aucun des deux IDs ne traverse
visiblement la ligne** : l'ancien ID disparaît côté "in", le nouvel ID apparaît
côté "out". Le comptage de base ne voit aucun `crossed LEFT` → **sous-comptage
de 1**. C'est ce que corrige la garde **ID-switch recovery** (§5.1).

À l'inverse, si un ID est perdu côté "in" puis **réattribué** (OC-SORT rattache
une détection gauche à l'ancien ID), cet ID réapparaît côté "out" et déclenche
un `crossed LEFT` alors qu'un **autre ID** a déjà traversé pour le même
cochon pendant l'absence → **sur-comptage de 1**. C'est ce que corrige
**REID-SUPPRESS** (§5.4).

## 4. Tracker OC-SORT (tuning anti-ID-switch)

OC-SORT (`OCSORTTracker`) est configuré via `settings.py` :

| Paramètre | Valeur | Rôle |
|---|---|---|
| `TRACKER_LOST_TRACK_BUFFER` | 20 | frames de survie d'une track perdue (~0.67s @30fps). Compromis : plus grand = survit aux occlusions longues mais peut se ré-associer à une mauvaise détection (sur-comptage) ; plus petit = sous-compte. |
| `TRACKER_HIGH_CONF_THRESHOLD` | 0.6 | seuil de confiance des détections **avant** association. 0.5 laissait passer des détections bruitées (0.5–0.6) qui créaient des tracks fantômes. 0.6 ne garde que les cochons confiants ; la 2e chance d'OC-SORT rescue les occlus. |
| `TRACKER_MIN_IOU_THRESHOLD` | 0.3 | IoU min d'association détection/track. Trop bas = ré-bindings erronés. |
| `TRACKER_MIN_CONSECUTIVE_FRAMES` | 5 | nb de frames consécutives avant qu'une track obtienne un `tracker_id` stable. Filtre les tracks éphémères (humain qui traverse, bruit) qui auraient un ID et pourraient traverser la ligne (faux ±1). 3 était trop permissif. |
| `TRACKER_DIRECTION_CONSISTENCY_WEIGHT` | 0.25 | poids du terme de cohérence de direction (OCM). |
| `TRACKER_DELTA_T` | 3 | fenêtre temporelle d'estimation de vitesse/direction (OCM). |
| `TRACKER_FRAME_RATE` | 30.0 | utilisé pour scaler le lost buffer en valeur temporelle. |

Les IDs avec `tracker_id == -1` (pas de track associée par OC-SORT) sont
filtrés avant le comptage.

## 5. Techniques de comptage avancées (gardes anti-ID-switch)

Toutes ces gardes vivent dans `Counting.count()`. Elles sont **cumulatives et
complémentaires** : chacune cible une signature précise d'ID-switch.

### 5.1 ID-switch recovery guard (fusion bidirectionnelle)

**Cible** : sous-comptage quand un cochon traverse mais est perdu juste avant la
ligne et réapparaît avec un nouvel ID de l'autre côté. Gère les **deux sens** :

- **droite → gauche (+1)** : cochon perdu côté "in" (droite), nouvel ID côté
  "out" (gauche) → fusion avec une lost "in" → **+1** (crossed LEFT).
- **gauche → droite (−1)** : cochon déjà traversé (+1) qui **revient**, perdu
  côté "out" (gauche), nouvel ID côté "in" (droite) → fusion avec une lost
  "out" → **−1** (crossed RIGHT). Sans cette branche, le retour serait
  sous-compté (le −1 perdu).

**Mécanisme** :
1. À chaque frame, on détecte les IDs **nouvellement perdus**
   (`prev_visible_ids − current_ids`). Pour chacun, on enregistre sa dernière
   position et son côté dans `lost_tracks[tid] = {cx, cy, side, frame}`.
   L'enregistrement se fait **une seule fois** (à la transition visible→absent),
   pas à chaque frame d'absence → logs lisibles et âge correct.
2. Quand un **nouvel ID** apparaît **déjà côté gauche** (`cx ≤ x`), on cherche
   dans `lost_tracks` une track perdue côté **"in"** (droite), récente
   (âge ≤ `COUNTING_GUARD_MAX_AGE`), proche de la ligne
   (bande `COUNTING_REASSOC_LINE_BAND`) et spatialement proche
   (dx ≤ `COUNTING_REASSOC_MAX_DIST_X`, dy ≤ `COUNTING_REASSOC_MAX_DIST_Y`).
3. Si trouvée → **fusion** : selon le côté d'apparition, `counter += 1`
   (crossed LEFT, lost "in") ou `counter -= 1` (crossed RIGHT, lost "out").
   L'ID est marqué du côté de destination (`area_out_list` pour +1,
   `area_in_list` pour −1), la lost track est consommée. Le crossing est
   enregistré dans `recent_crossings` (pour REID-SUPPRESS, §5.4, dans les deux
   sens).

> Le nouvel ID est placé dans la liste du côté de destination (et non la source)
> pour éviter qu'un crossing parasite suivant ne double le compte.

### 5.2 Découplage GUARD_MAX_AGE vs LOST_BUFFER_FRAMES

Deux âges distincts coexistent :

- **`COUNTING_LOST_BUFFER_FRAMES` (60)** : expiration **globale** des
  `lost_tracks` (nettoyage mémoire). **Long** (~2s) pour que la garde puisse
  fusionner un "in" perdu avec un nouvel ID gauche même après une occlusion
  longue à la ligne (critique pour les vidéos à forte occlusion).
- **`COUNTING_GUARD_MAX_AGE` (15)** : âge d'**éligibilité** d'une lost "in"
  pour la fusion. **Court** (~0.5s) pour ne pas fusionner avec une lost "in"
  **stale** appartenant à un **autre** cochon (ou à un cochon déjà traversé
  sous un autre ID) → faux +1 (cas #30/#11).

Ce découplage permet à deux exigences contradictoires de coexister : occlusions
longues (besoin d'un buffer long) et refus des fusions stale (besoin d'un âge
court).

### 5.3 Cleanup de `lost_tracks` au retour d'un ID (fix #11)

**Cible** : sur-comptage quand un "in" perdu **persiste** dans `lost_tracks`
et est réutilisé plus tard par la garde pour fusionner avec un **autre** nouvel
ID gauche (le cochon d'origine ayant pu déjà traverser sous son propre ID).

**Mécanisme** : quand un ID **réapparaît** (branche `if track_id in
self.detections`), on **consomme** son entrée dans `lost_tracks`
(`del self.lost_tracks[track_id]`). Ainsi, un "in" perdu ne peut pas être
réutilisé par la garde pour un nouvel ID différent — la "ghost lost in" est
éliminée dès que l'ID réapparaît.

### 5.4 REID-SUPPRESS (fix #35)

**Cible** : sur-comptage quand un ID connu (côté "in", pas encore compté)
**réapparaît côté gauche** après une absence, alors qu'un **autre ID** — qui
est **apparu pendant cette absence** — a déjà traversé (`crossed LEFT` récent).
Cet autre ID est presque certainement un **re-ID du même cochon** (déjà
compté) → le +1 de l'ID réappar serait un double-comptage.

**Mécanisme** :
- On tient `recent_crossings = [{frame, tid, direction}]` (nettoyé chaque
  frame, keep âge ≤ `COUNTING_REID_WINDOW` = 15).
- On tient `first_seen[tid]` (frame de 1re apparition) et `last_seen[tid]`
  (frame de dernière apparition).
- Quand un ID côté "in" réapparaît côté gauche (`cx ≤ x_low`) avec un âge
  d'absence ≥ `COUNTING_REID_MIN_AGE` (3), on cherche dans `recent_crossings`
  un `crossed LEFT` par un **autre** `tid` dont `first_seen[other] >
  last_seen[current]` (l'autre ID est **apparu pendant l'absence** du
  courant).
- Si trouvé → **suppression du +1** : l'ID passe côté "out", lost_tracks
  nettoyée, **aucun changement de compteur**.

**Miroir (faux −1)** : la même logique s'applique au sens inverse. Un ID côté
"out" (gauche, déjà compté +1) qui réapparaît côté droite après une absence,
alors qu'un autre ID apparu pendant l'absence a récemment `crossed RIGHT`, est
un re-ID du même cochon qui revient (l'autre ID a déjà fait le −1) → le −1 de
l'ID réappar est **supprimé** (sinon double −1).

**Insight clé** : la signature d'un double-comptage par re-ID **n'est pas** le
saut de position ni l'âge d'absence seuls (qui peuvent être faibles), mais le
fait qu'**un autre ID apparu pendant l'absence a traversé récemment**. Une
traversée occluse légitime n'a **aucun autre ID apparaissant** pendant
l'absence → elle se déclenche normalement.

### 5.5 Resurrection guard (Pattern B — filet)

**Cible** : re-ID par **saut de position** important (OC-SORT rattache une
détection gauche à un vieil ID droit, le saut droite→gauche déclencherait un
faux `crossed LEFT`).

**Mécanisme** : si un ID connu réapparaît avec un saut horizontal
`> COUNTING_RESURRECTION_MIN_JUMP` (150 px) ET une absence
`> COUNTING_RESURRECTION_THRESHOLD` (5 frames) → on **reset** sa zone par la
position courante, **sans changer le compteur**, et on nettoie sa lost track.

> Filet de sécurité : sur les cas réels observés, les sauts étaient < 150 px
> (le vrai fix pour #35 est REID-SUPPRESS). Ce garde n'a jamais déclenché sur
> la validation mais reste inoffensif pour les gros sauts de re-ID.

### 5.6 Mirror guard (mode `log` — inerte)

**Cible** : miroir de l'ID-switch — un cochon traverse (+1), est perdu côté
"out" (gauche), obtient un nouvel ID côté "in" (droite) qui va traverser
encore (+1 = sur-comptage).

**Mécanisme** : 3 modes (`COUNTING_MIRROR_GUARD`) :
- `off` : désactivé.
- `log` (défaut) : détecte et logge les candidats sans changer le compte.
- `enforce` : supprime le prochain `crossed LEFT` du nouvel ID.

> Resté en `log` : **0 candidat** détecté sur le set de validation → inerte.
> Laisse en place pour observation, sans impact sur le compte.

### 5.7 Hysteresis (désactivée, H = 0)

Une **dead-band** de `H = COUNTING_HYSTERESIS_PX` pixels autour de la ligne :
une traversée n'est comptée qu'une fois le centroïde passé à `x ± H`, pour
absorber le jitter de bbox pile sur la ligne.

> **H = 0** : testé à H = 25, l'hystérésis a **avalé un `crossed RIGHT`
> légitime** (cochon allant gauche→droite mais restant dans la dead-band),
> laissant son `crossed LEFT` ultérieur non compensé → sur-comptage
> (démontré sur #18). Donc désactivée.

## 6. Sérialisation du résultat (mode validation)

En mode validation (`RESULT_JSON_PATH` set), le `main` doit écrire le
`result.json` **après** que tous les cochons aient été comptés. Un bug de
flush écrivait le résultat trop tôt (joins avec `timeout=300` trop courts pour
les vidéos longues → le `DisplayThread` n'avait pas vidé sa dernière frame →
le dernier cochon était perdu).

**Correctif** (`main.py`, mode validate uniquement) :
```python
# 1) Attendre la fin de l'InferThread (lecture complète de la vidéo)
shared_state.infer_thread.join()          # pas de timeout court
# 2) Attendre que le DisplayThread traite TOUTES les frames en queue
shared_state.frame_queue.join()           # block jusqu'à task_done() de chaque frame
# 3) Arrêter le DisplayThread (sinon boucle infinie sur get(timeout=1))
shared_state.stop_event.set()
shared_state.display_thread.join(timeout=60)
# 4) Sérialiser
write_result_json(...)
```

> Ce bloc est dans `if result_json_path:` → **ne s'applique pas au mode
> caméra** (qui compte en continu et ne sérialise pas de `result.json` de fin).

## 7. Paramètres de comptage (récap)

| Paramètre | Valeur | Rôle / justification |
|---|---|---|
| `OFFSET_PERCENT_COUNTING_LINE` | 10 | position de la ligne (x ≈ 384 sur 640 px) |
| `COUNTING_LOST_BUFFER_FRAMES` | 60 | expiration globale des lost_tracks (long, pour occlusions) |
| `COUNTING_GUARD_MAX_AGE` | 15 | âge d'éligibilité d'une lost "in" pour la fusion (court) |
| `COUNTING_REASSOC_LINE_BAND` | 200 | bande horizontale de la ligne pour la fusion (px) |
| `COUNTING_REASSOC_MAX_DIST_X` | 120 | dx max fusion (px) |
| `COUNTING_REASSOC_MAX_DIST_Y` | 80 | dy max fusion (px) |
| `COUNTING_REID_WINDOW` | 15 | âge max d'un crossing pour être "récent" (REID-SUPPRESS) |
| `COUNTING_REID_MIN_AGE` | 3 | absence min (frames) pour qu'un ID soit suspect |
| `COUNTING_RESURRECTION_MIN_JUMP` | 150 | saut horizontal min (px) pour resurrection |
| `COUNTING_RESURRECTION_THRESHOLD` | 5 | absence min (frames) pour resurrection |
| `COUNTING_HYSTERESIS_PX` | 0 | dead-band ligne (désactivée, avalait un crossed RIGHT légitime) |
| `COUNTING_MIRROR_GUARD` | `log` | garde miroir, détecte seulement (0 candidat sur la validation) |

Tous configurables via `settings.py` + `app/.env` (voir `app/.env.example`).

## 8. Validation

- **30 vidéos validées** (convention de nommage
  `validation-<seq>-#<count>.mp4`, `<count>` = compte confirmé).
- Résultat : **30/30 pass** (l'app donne le compte attendu pour chaque
  vidéo).
- Comptes confirmés par vision pour les vidéos dont le nom d'origine était
  trompeur : `#11`→12, `#27`→12, `#24`→42, `#51`→51 (le compteur était juste
  dès le départ ; le ground truth d'origine était faux).
- Défauts historiques résolus :
  - `#35` (re-ID resurrection) → **REID-SUPPRESS**.
  - `#30` (fusion avec lost "in" stale) → **GUARD_MAX_AGE**.
  - `#11` (ghost lost "in" réutilisé) → **cleanup lost_tracks au retour**.
  - `#32` (dernier cochon perdu) → **correctif de flush du result.json**.
- Script de validation : `scripts/validate_on_jetson.sh` (modes `standard`
  sur la vidéo de référence, et `--full` sur toutes les vidéos du manifest
  `validation/expected_counts.json`).

## 9. Limites & considérations

### 9.1 Paramètres tunés sur vidéo — à valider sur caméra réelle

Les valeurs ci-dessus ont été **tunées empiriquement sur les vidéos**. La
logique tracking/comptage transfère au mode caméra (FPS = 30 et caméra fixe
confirmés), mais ces paramètres **dépendent de l'installation** et doivent
être vérifiés/ajustés sur site :

- `OFFSET_PERCENT_COUNTING_LINE` : position de la ligne vs installation.
- `TOP_IGNORE` / `BOTTOM_IGNORE` : régions à ignorer (cadre caméra).
- `PIG_CONFIDENCE_THRESHOLD` : luminosité / distance / conditions de détection.

### 9.2 Mode caméra longue durée (24/7) — fuite mémoire potentielle

`self.first_seen` (dict `{track_id: frame}` utilisé par REID-SUPPRESS)
accumule **une entrée par ID unique** et **n'est jamais nettoyé**. En
validation vidéo (courte), négligeable. En caméra continue (heures/jours),
OC-SORT génère des milliers d'IDs → `first_seen` grandit indéfiniment →
fuite mémoire lente.

`recent_crossings` est nettoyé (keep ≤ `reid_window`) — OK.
`last_seen` grandit aussi (une entrée par ID) mais reste borné en pratique par
le nombre d'IDs actifs récents.

**Pour un déploiement 24/7** : purger `first_seen` (ex. retirer les IDs plus
vieux que `lost_buffer_frames` + marge, ou absents des détections courantes).
C'est un correctif de robustesse, sans impact sur le compte (les vidéos
validées resteraient identiques).

### 9.3 Bidirectionnalité, hystérésis & mirror guard

Les gardes **ID-switch recovery** (§5.1) et **REID-SUPPRESS** (§5.4) gèrent
maintenant les **deux sens** (droite→gauche +1 et gauche→droite −1), y
compris le cas rare d'un cochon qui revient avec un nouvel ID et retraverse
dans l'autre sens. Le retour avec **ID-switch à la ligne** est récupéré par la
branche −1 de la garde (fusion lost "out" + nouvel ID droit).

L'hystérésis est désactivée (H = 0) car elle avale un `crossed RIGHT`
légitime. Le mirror guard est en `log` (inerte, 0 candidat). Ces deux leviers
restent disponibles si de nouveaux patterns apparaissent, **à valider**
avant réactivation (H = 25 a régressé #18).