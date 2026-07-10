# PRD: Splash Screen (ultra-minimal, autostart + timer)

## Overview
Afficher `splash.png` en plein écran au début de la session LXDE du Jetson
Nano Orin, pendant que l'application de comptage (`countingapp`) démarre
sous k3s. La fenêtre feh est fermée automatiquement après un délai fixe
(`splash_duration`, défaut : 45 secondes), ce qui est largement suffisant
sur un Jetson mono-node pour que la fenêtre de countingapp se soit déjà
affichée par-dessus.

## Context
Au démarrage du Jetson, l'application de comptage met plusieurs dizaines
de secondes à être opérationnelle (image locale à charger, init du GPU,
TensorRT engine, etc.). L'utilisateur ne doit pas voir un bureau LXDE
vide ou cassé pendant ce temps. Le splash est purement cosmétique :
countingapp finit par s'afficher au-dessus, donc on n'a pas besoin d'un
mécanisme de fermeture "intelligent" — un délai fixe suffit.

Une version précédente de ce PRD (juin 2025) voulait en plus **bloquer
l'accès au bureau** tant que l'app n'est pas prête (fbi sur le framebuffer,
LightDM gtk-greeter, Plymouth, service systemd `splash-guard`, lock 3 min
avec restart de LightDM). Cette approche a été abandonnée : trop complexe,
fragile selon le kernel/LightDM installés, et inutile fonctionnellement.
Voir le diagnostic 2026-06-08 pour le détail des essais.

Une version intermédiaire (même date, ~11h) ajoutait un wrapper
`splash.sh` qui pollishait k3s et faisait un healthcheck HTTP pour
fermer feh. Cette version a été abandonnée à son tour : la combinaison
`Exec=env VAR=x VAR=y ... script` dans le `.desktop` ne se déclenchait
pas correctement depuis LXDE (probablement à cause du passage de
variables d'environnement à travers openbox/lxpolkit), et l'app
countingapp ne définit aucune readinessProbe k8s ni endpoint HTTP
exposé, donc le critère HTTP n'était de toute façon pas atteignable.

## Goal
L'image `splash.png` doit s'afficher en plein écran au login LXDE, et
disparaître d'elle-même après un délai fixe court. Aucun mécanisme de
synchronisation avec k3s ou avec l'application elle-même.

## Tasks

- [x] Task 1: Installer `feh` via `apt`
- [x] Task 2: Copier `splash.png` du poste de contrôle vers `/opt/splash-screen/`
- [x] Task 3: Créer `~/.config/autostart/splash.desktop` qui lance
  `feh --fullscreen --hide-pointer` au login LXDE
- [x] Task 4: Installer un service + timer systemd
  (`countingapp-splash-killer.{service,timer}`) qui exécute
  `pkill feh` `splash_duration` secondes après le boot

## Files to Change

- [x] `ansible/playbooks/system/configure_splash_screen.yml` (new file)
- [x] `scripts/install_splash_screen_standalone.sh` (invoque le playbook)

## Acceptance Criteria

- [x] Au login LXDE, `splash.png` s'affiche en plein écran plein cadre,
  curseur masqué, sans bordure ni menu.
- [x] Au plus tard `splash_duration` secondes (défaut : 45s) après le boot,
  le processus feh est tué par le timer systemd. À ce moment-là, la fenêtre
  countingapp est déjà visible par-dessus, donc l'utilisateur ne voit
  pas le splash disparaître "à nu".
- [x] Idempotent : relancer le playbook ne casse rien et n'affiche pas de
  diff sur un système déjà configuré.
- [x] Aucune modification de LightDM, Plymouth, fbi, ni de service
  utilisateur — tout passe par l'autostart LXDE et un timer système simple.

## Security & Fail-Safe Rules

Aucune règle fail-safe particulière. Si k3s ou countingapp ne démarrent
jamais, le splash reste à l'écran jusqu'à expiration du timer (45s), puis
disparaît. L'utilisateur voit alors un bureau LXDE normal avec, au
pire, une fenêtre d'erreur de countingapp. C'est le comportement attendu
et acceptable.

## Technical Details

### Trigger : LXDE autostart

LXDE lit `~/.config/autostart/*.desktop` au démarrage de la session (et
uniquement à ce moment-là). Comme `install_lxde.yml` active l'autologin
LightDM, l'utilisateur est toujours logué automatiquement, donc le
`.desktop` est toujours exécuté après le boot.

Le `.desktop` est volontairement trivial : un seul `Exec=/usr/bin/feh ...`
sans wrapper, sans variables d'environnement, sans logique conditionnelle.
C'est la configuration la plus simple possible et c'est exactement celle
qui s'est avérée fonctionner en pratique.

### Cleanup : systemd timer

Le fichier `~/.config/autostart/splash.desktop` lance feh en avant-plan
(au sens LXDE — feh est la seule "application" du démarrage, donc
l'utilisateur voit son image). Au bout de `splash_duration` secondes,
le timer système `countingapp-splash-killer.timer` déclenche le service
`countingapp-splash-killer.service` qui exécute :

```bash
/usr/bin/pkill -f 'feh.*splash-screen/splash.png' || true
/usr/bin/pkill -u <target_user> -x feh || true
```

Le premier `pkill` cible feh par sa command line (la chaîne
`splash-screen/splash.png` est dans les arguments). Le second est un
fallback qui tue n'importe quel feh appartenant à l'utilisateur cible,
au cas où la première commande n'aurait pas matché (par ex. si feh a été
relancé manuellement par l'utilisateur avec un autre image).

Les `|| true` garantissent que le service systemd est marqué comme
"success" même si feh n'existe plus, ce qui est important pour qu'un
redémarrage du timer fonctionne correctement.

### Pourquoi un timer système et pas un timer utilisateur

Un timer systemd **utilisateur** (dans `~/.config/systemd/user/`)
nécessite que `loginctl enable-linger <user>` soit activé pour pouvoir
démarrer avant que l'utilisateur ne se logue. C'est une source fréquente
d'erreurs (le service se lance après le login, donc le timer a déjà
expiré et n'a jamais eu lieu d'exister). Un timer **système** est
démarré par PID 1 dès le boot, indépendamment du login, ce qui est plus
fiable.

### Fichiers créés sur le Jetson

- `/opt/splash-screen/splash.png` — l'image, copiée depuis le contrôleur
- `~/.config/autostart/splash.desktop` — l'entrée d'autostart, mode 0644
- `/etc/systemd/system/countingapp-splash-killer.service` — le oneshot
- `/etc/systemd/system/countingapp-splash-killer.timer` — le timer

### Paquets installés via apt

- `feh` — viewer d'image fullscreen X11

### Variables Ansible

| Variable                | Défaut                  | Notes                                       |
|-------------------------|-------------------------|---------------------------------------------|
| `splash_duration`       | `45`                    | Secondes avant que feh soit tué             |
| `app_namespace`         | `countingapp-dev` (env) | Lu depuis `APP_NAMESPACE` (info seulement)  |
| `app_name`              | `countingapp` (env)     | Lu depuis `APP_NAME` (info seulement)       |
| `target_user`           | `ansible_user`          | Propriétaire de l'autostart `.desktop`, et user ciblé par le `pkill -u` du killer |
| `local_app_path`        | `./app` (env)           | Lu depuis `LOCAL_APP_PATH`                  |

### Diagnostic

Le playbook `diagnose_splash_screen.yml` reste utile pour vérifier l'état
du système après installation. **Attention** : il a été écrit pour
l'ancienne version (fbi, LightDM, systemd splash-guard). Ses tâches
concernant ces composants renverront des erreurs, mais les autres (présence
de l'image, du `.desktop`, version de feh, status k3s) restent valides.
Aucune de ses tâches n'écrit sur le Jetson : c'est un playbook read-only.

### Commandes utiles côté Jetson

```bash
# Vérifier que le .desktop est bien là
cat ~/.config/autostart/splash.desktop

# Vérifier que feh est bien installé
which feh && feh --version

# Vérifier que le timer est armé
systemctl status countingapp-splash-killer.timer
systemctl list-timers countingapp-splash-killer.timer

# Forcer un kill immédiat de feh
sudo systemctl start countingapp-splash-killer.service

# Désactiver complètement le splash (par exemple pour debug countingapp)
sudo systemctl disable --now countingapp-splash-killer.timer
rm ~/.config/autostart/splash.desktop
```
