# Plan: BL-79 — Separate config from content: second hostPath /conf

## Summary

Add a second hostPath `/data/orin/conf` (mounted `/conf` in the countingapp pod) to separate config/control (`runtime-settings.json`, `.arret_requested`) from data (`counting-history.jsonl`, videos, dataset) which stays in `/files`. This clarifies the companion⇄countingapp IPC contract and prepares the ground for isolated config/control.

## In Scope

- **A. K3s manifests** — add a `conf` volume (hostPath `/data/orin/conf`, type `Directory`) + volumeMount `/conf` in `countingapp-dep.j2` AND `countingapp-test.j2` (NOT `countingapp-validate.j2` — it only reads/writes `result.json` in `/files`).
- **B. Ansible** — new var `conf_path` (default `/data/orin/conf`) by symmetry with `files_path` in `group_vars/all.yml` and `deploy_countingapp.yml`; create the directory `/data/orin/conf` (owner/perms consistent with `/data/orin/files`); one-shot idempotent migration of `runtime-settings.json` + `.arret_requested` from `/data/orin/files` to `/data/orin/conf` if present.
- **C. Python code** — `app/src/state.py` `RUNTIME_SETTINGS_PATH` → `/conf/runtime-settings.json`; `app/src/display_thread.py` `POWER_SENTINEL_PATH` → `/conf/.arret_requested`. `settings.py` and `history.py` UNCHANGED (stay on `/files`).
- **D. IPC contract** — update `docs/IPC_CONTRACT.md` to describe the `/files` (data) vs `/conf` (config/control) split. Companion coordination (sister repo) is out of scope for this BL, but this repo's contract must already describe the target split.
- **E. Docs** — update `docs/04_configuration.md` + `ansible/README.md`.

## Out of Scope

- BL-78 (multi-species, `model-classes.json`)
- Companion code (sister repo `wloonis/animal-counter-companion`) — separate BL
- Docker rebuild (paths are Python constants, live rsync mount `/app`)
- Modification of `countingapp-validate.j2`, `filebrowser-dep.j2`, `cronvideo-dep.j2` (do not interact with runtime-settings.json / .arret_requested)

## Architecture Decisions

- **No read fallback on the old `/files` path** — clean move + restart. `runtime-settings.json` is rewritten by the companion on the first interaction (POST/PUT), so a brief absence is not a problem. A fallback would create confusion about the source of truth.
- **`conf_path` by symmetry with `files_path`** — same Ansible pattern (`lookup('env', 'CONF_PATH') | default('/data/orin/conf')`), overridable via env.
- **Idempotent migration in the playbook** — use `ansible.builtin.command` with `creates:` or a `stat` test to only move the file if it exists at the old location AND does not exist at the new location. Idempotent: re-run = no-op.
- **No Docker rebuild** — paths are Python constants in `state.py`/`display_thread.py`. The `/app` mount (live rsync) picks up the change on pod restart. Deployment = re-render manifests + kubectl apply + create /data/orin/conf + restart pod.

## Tasks

- [x] Task 1: EDIT `k3s/templates/countingapp-dep.j2` — add a `conf` volumeMount (mountPath `/conf`) after the existing `filebrowser` volumeMount, and add the `conf` volume (hostPath `{{ conf_path }}`, type `Directory`) after the `filebrowser` volume in the `volumes:` section.
- [x] Task 2: EDIT `k3s/templates/countingapp-test.j2` — add a `conf` volumeMount (mountPath `/conf`) after the existing `filebrowser` volumeMount, and add the `conf` volume (hostPath `{{ conf_path }}`, type `Directory`) after the `filebrowser` volume in the `volumes:` section.
- [x] Task 3: EDIT `ansible/group_vars/all.yml` — add `conf_path: "{{ lookup('env', 'CONF_PATH') | default('/data/orin/conf') }}"` in the `app_config:` block, right after `files_path`.
- [x] Task 4: EDIT `ansible/playbooks/app/deploy_countingapp.yml` — add `conf_path: "{{ lookup('env', 'CONF_PATH') | default('/data/orin/conf', true) }}"` in the `set_fact` block (line ~13, after `files_path`). Add a "Create conf directory on Jetson" task (file: state=directory, mode=0775, owner/group=ansible_user, become=yes) by symmetry with "Create files directory". Add 2 idempotent migration tasks: move `runtime-settings.json` and `.arret_requested` from `{{ files_path }}` to `{{ conf_path }}` if present at the old location and absent at the new (stat + command mv with `creates:`).
- [x] Task 5: EDIT `app/src/state.py` — change `RUNTIME_SETTINGS_PATH = "/files/runtime-settings.json"` → `"/conf/runtime-settings.json"` (line ~67). Update the BL-76 comment to reflect the /conf (config) vs /files (data) split.
- [x] Task 6: EDIT `app/src/display_thread.py` — change `POWER_SENTINEL_PATH = "/files/.arret_requested"` → `"/conf/.arret_requested"` (line ~54). Update the BL-76 comment to reflect the /conf (control) vs /files (data) split.
- [x] Task 7: EDIT `docs/IPC_CONTRACT.md` — update the "Shared path" section to describe the two hostPaths: `/files` (data: counting-history.jsonl, mp4 clips, dataset) and `/conf` (config/control: runtime-settings.json, .arret_requested). Move sections 2 (runtime-settings.json) and 3 (.arret_requested) under `/conf`. Add a note that companion coordination (sister repo) is a separate BL but the target contract is already described here.
- [x] Task 8: EDIT `docs/04_configuration.md` — add a section or note on the `/files` (data) vs `/conf` (config/control) split: explain that `runtime-settings.json` and `.arret_requested` are now in `/conf` (hostPath `/data/orin/conf`), and that `/files` keeps the data (counting-history.jsonl, videos, dataset).
- [x] Task 9: EDIT `ansible/README.md` — add `CONF_PATH` in the `.env.local` section (by symmetry with `FILES_PATH`) and mention the `/data/orin/conf` hostPath in the deployment docs.

## Reuse

- `ansible/playbooks/app/deploy_countingapp.yml:34-46` — "Create files/dataset directory on Jetson" pattern to duplicate for `/data/orin/conf`.
- `ansible/group_vars/all.yml:42` — `files_path` pattern to duplicate for `conf_path`.
- `ansible/playbooks/app/deploy_countingapp.yml:13` — `set_fact` `files_path` pattern to duplicate for `conf_path`.
- `k3s/templates/countingapp-dep.j2:50-53,73-76` — volumeMount + volume `filebrowser` pattern to duplicate for `conf`.
- `k3s/templates/countingapp-test.j2:23-24,33-35` — same.

## Validation

- **Python syntax** : `python3 -m py_compile app/src/state.py app/src/display_thread.py` (the 2 modified files).
- **Jinja syntax** : `ansible-playbook --syntax-check` (or render dry-run) on `deploy_countingapp.yml` to validate the templates.
- **Jetson validation (standard)** : `bash scripts/validate_on_jetson.sh` (standard mode, reference pig-only video) to confirm non-regression of BL-76 hot-reload (runtime-settings in /conf) and BL-71 power sentinel (.arret_requested in /conf). Prerequisite: copy/symlink the gitignored files (`.env.local`, `validation/videos/*.mp4`, `app/model/`, `app/.env`) from the main repo (`git worktree list` → first worktree path) before validating.
- **Manifest check** : confirm that `countingapp-validate.j2`, `filebrowser-dep.j2`, `cronvideo-dep.j2` are NOT modified (diff scope check).

## Risks

- **Companion not yet updated** — the companion (sister repo) still writes to `/data/orin/files/runtime-settings.json` and `/data/orin/files/.arret_requested`. After this BL, countingapp reads from `/conf`. Window of non-functioning hot-reload and power sentinel until the companion is updated (separate BL). Mitigation: clearly document the dependency in IPC_CONTRACT.md; the companion is deployed separately and the migration (file move) + pod restart suffice for countingapp.
- **Migration on existing deployment** — if `/data/orin/conf` does not yet exist at first deployment, the countingapp pod will not be able to mount the volume (type: Directory requires the directory to exist). Mitigation: the Ansible "Create conf directory" task runs BEFORE the `kubectl apply` (task order in the playbook).
- **Migration race condition** — if the pod is still running during migration, it may read/write at the old location. Mitigation: the migration is idempotent and the pod is restarted after `kubectl apply` (the DaemonSet RollingUpdate handles the restart).