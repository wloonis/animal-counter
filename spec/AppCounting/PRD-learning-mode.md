# PRD: Mode Apprentissage

## 1. Executive Summary
La feature "Mode Apprentissage" ajoute une fonctionnalité à l'application existante de comptage de cochons. Elle permet de basculer entre un mode de comptage standard et un mode d'apprentissage où des images sont capturées pour constituer un dataset. Cette feature vise à préparer un ensemble d'images pour l'entraînement futur de modèles, tout en s'intégrant harmonieusement avec l'interface existante.

## 2. Mission
- Faciliter la préparation de datasets pour l'entraînement de modèles.
- Maintenir la cohérence avec l'interface utilisateur actuelle (boutons et images simulées).
- Assurer une intégration transparente avec les fonctionnalités existantes.

## 3. Target Users
- Utilisateurs finaux de l'application de comptage de cochons.
- Équipes techniques préparant des datasets pour l'entraînement de modèles.

## 4. MVP Scope
### In Scope
✅ Bouton On/Off pour activer/désactiver le mode Apprentissage (intégré à l'interface existante).
✅ Capture d'images toutes les X secondes en mode Apprentissage.
✅ Stockage des images dans une arborescence `dataset`.
✅ Nommage des images avec horodatage.
✅ Configuration du répertoire du dataset via le fichier `.env`.

### Out of Scope
❌ Entraînement automatique du modèle.
❌ Annotation automatique des images.

## 5. User Stories
- En tant qu'utilisateur, je veux activer le mode Apprentissage via un bouton en haut à droite de l'écran pour capturer des images et préparer un dataset.
- En tant qu'utilisateur, je veux configurer le répertoire de stockage des images dans le fichier `.env`.
- En tant qu'utilisateur, je veux que les images soient nommées avec un horodatage pour une organisation claire.

## 6. Core Architecture & Patterns
- Intégration avec l'interface UI existante (boutons et images simulées).
- Utilisation de l'architecture actuelle pour la capture d'images.
- Stockage des images dans un répertoire configurable via `.env`.

## 7. Tools/Features
- Bouton On/Off en haut à droite de l'écran (style cohérent avec les boutons existants).
- Paramètre `DATASET_DIR` dans `.env` pour le répertoire de stockage.
- Paramètre `CAPTURE_INTERVAL` dans `.env` pour l'intervalle de capture.

## 8. Technology Stack
- Langage : Python (si applicable).
- Bibliothèques : OpenCV pour la capture d'images (si applicable).

## 9. Security & Configuration
- Configuration via le fichier `.env` (`./app/.env`).
- Pas de données sensibles capturées.

## 10. API Specification
Non applicable pour cette feature.

## 11. Success Criteria
- Le mode Apprentissage peut être activé/désactivé via l'UI existante.
- Les images sont capturées et stockées correctement dans le répertoire configuré.
- Les images sont nommées avec un horodatage.

## 12. Implementation Phases
### Phase 1: Intégration UI
- Ajout du bouton On/Off (style cohérent avec l'interface existante).
- Configuration des paramètres dans `.env`.

### Phase 2: Capture d'images
- Implémentation de la capture d'images.
- Stockage dans le répertoire configuré.

### Phase 3: Tests et Validation
- Tests unitaires et d'intégration.
- Validation utilisateur.

## 13. Future Considerations
- Ajout de fonctionnalités d'annotation.
- Intégration avec des outils d'entraînement de modèles.

## 14. Risks & Mitigations
- **Risque** : Performance impactée par la capture d'images.
  **Mitigation** : Optimiser l'intervalle de capture.

## 15. Appendix
- Répertoire de base : `./app`
- Fichier de configuration : `./app/.env`