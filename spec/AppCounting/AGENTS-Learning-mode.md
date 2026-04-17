# AGENTS.md - Règles Globales du Projet

## 1. Aperçu du Projet
Application de comptage de cochons avec détection d'objets en temps réel. La feature "Mode Apprentissage" permet de capturer des images pour préparer un dataset.

## 2. Stack Technique
- **Langage** : Python
- **Inférence** : TensorRT
- **Suivi** : ByteTrack
- **UI** : OpenCV
- **Configuration** : `.env`

## 3. Commandes
- **Exécuter** : `python -m src.main`
- **Tests** : `pytest app/tests/`

## 4. Structure du Projet
```
app/
├── src/
│   ├── main.py          # Point d'entrée
│   ├── settings.py      # Configuration
│   ├── core/            # Logique métier
│   └── ui/              # Interface utilisateur
```

## 5. Architecture
- **Flux** : InferThread → DisplayThread → UI
- **Modules Clés** :
  - `counting.py` : Logique de comptage
  - `tracking.py` : Suivi des objets
  - `rendering.py` : Rendu visuel

## 6. Patterns de Code
- **Nommage** : `snake_case` pour les fichiers, `CamelCase` pour les classes.
- **Logging** : Utilisation de `logging` avec niveaux configurables.

## 7. Fichiers Clés
- `main.py` : Gestion des threads et flux principal.
- `settings.py` : Configuration via `.env`.
- `ui/rendering.py` : Intégration du bouton "Mode Apprentissage".

## 8. Contexte à la Demande
- **PRD** : `PRD_Mode_Apprentissage.md`
- **Configuration** : `.env` pour `DATASET_DIR` et `CAPTURE_INTERVAL`.

## 9. Notes
- **Configuration** : Utiliser `.env` pour les paramètres spécifiques.
- **Performance** : Optimiser l'intervalle de capture pour éviter les ralentissements.
- **Compatibilité** : Vérifier la compatibilité avec les versions de TensorRT et Norfair.
