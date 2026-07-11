# Plan: Prevent Disk Saturation in 24/7 (Issue #43, P1)

## Summary

Guarantee `/data/orin/files` never exceeds a configurable video budget regardless of recording scenario, make image rebuilds net-zero on disk (prune dangling images + build cache), and explicitly bound all other disk consumers (kubelet container logs, journald) that could cause saturation in long-running 24/7 operation. Adds a monotonic-schedule systemd timer for weekly build-cache pruning (no wall-clock dependency).

## In Scope

- **Total-size guard** in `cronvideo-dep.j2`: after existing count + per-file-size cleanups, loop `du -sm /videos` and delete oldest `count*` files (by mtime) until usage < `video_budget_gb` (default 40). Deletes ONLY `count*` — never `tocompress-*` or inputs. Logs a warning if `tocompress-*` alone exceeds the budget (guard cannot reduce those).
- **Reduce retention**: `NR>50` → `NR>30` in the count-file cleanup.
- **Docker prune on rebuild**: after `docker buildx build` in `build_countingapp.yml`, add `docker image prune -f && docker builder prune -f`.
- **Configurable budget**: add `video_budget_gb` var (default 40, env-overridable) to `ansible/group_vars/all.yml`; wire into `cronvideo-dep.j2` via Jinja2 (`{{ video_budget_gb | default(40) }}`), same pattern as `TRIM_TAIL={{ delay_last_class | default(180) }}`.
- **Monotonic systemd timer** for weekly `docker builder prune -af`: uses `OnUnitInactiveSec=7d` (not `OnCalendar`) because the Jetson is offline with unreliable wall-clock time.
- **Kubelet container-log bounds**: add explicit `container-log-max-files=5` and `container-log-max-size=10Mi` kubelet-args to the k3s config (currently relying on defaults).
- **Journald bounds**: add a journald config drop-in (`/etc/systemd/journald.conf.d/countingapp.conf`) with `SystemMaxUse=200M` and `Storage=persistent` (currently completely unconfigured = unbounded growth risk).

## Out of Scope

- Validation path (`scripts/validate_on_jetson.sh`, `countingapp-validate.j2`) — no effort per user instruction.
- `tocompress-*` deletion in the guard — inputs are never deleted by the guard.
- App code changes (`app/src/main.py`, `app/entrypoint.sh`, `app/.env`) — no `requirements.txt` change, no image rebuild needed for validation.
- OC-SORT, FPS_OUTPUT=30, H=0 — unchanged per AGENTS.md §7.
- Docker container log rotation (`/etc/docker/daemon.json`) — already bounded at 100m×3=300MB/container, no action needed.

## Architecture Decisions

- **Guard deletes only `count*` oldest-first**: `du -sm /videos` is the budget trigger (measures ALL files in /videos including `tocompress-*`), but the deletion lever is restricted to `count*` compressed outputs. This preserves input clips for re-processing if needed. Edge case: if `tocompress-*` alone exceeds the budget, the guard logs a warning but cannot reduce usage — this is a backpressure signal to the compression loop (which processes `tocompress-*` → `count*` each cycle).
- **Systemd timer uses `OnUnitInactiveSec=7d` (monotonic)**: the Jetson is offline and does not reliably maintain wall-clock date/time. `OnCalendar` would fire at wrong times or never. `OnUnitInactiveSec` measures from the last time the unit was active, independent of system clock. Pattern follows `configure_splash_screen.yml` (service + timer + `systemd` module enable).
- **`video_budget_gb` is an Ansible var, not hardcoded**: follows the `delay_last_class` pattern — `lookup('env', 'VIDEO_BUDGET_GB') | default(40)` in `group_vars/all.yml`, templated directly in the j2. Env-overridable for testing different budgets without editing files.
- **Kubelet container-log args made explicit**: defaults (10Mi×5) are correct but relying on defaults is fragile across kubelet versions. Adding explicit args to the k3s config makes the bound contractual. Note: this change only takes effect on fresh k3s install or manual config edit + k3s restart on an already-deployed Jetson.
- **Journald `SystemMaxUse=200M`**: 200MB is a safe bound for a 116GB disk with 65GB free. Journald will vacuum oldest entries when the limit is hit. `Storage=persistent` ensures logs survive reboots (default varies by distro). Without this, journald can grow to ~10% of filesystem = ~11GB unbounded.
- **New system playbook `configure_disk_guards.yml`**: the journald config and systemd timer are standalone system configs that can be applied to a running Jetson without k3s restart. The kubelet-arg change lives in `install_k3s_with_docker_tasks.yml` (k3s bootstrap config) since kubelet-args are part of the k3s registration config.

## Tasks

- [ ] Task 1: EDIT `ansible/group_vars/all.yml` — add `video_budget_gb` var following the `delay_last_class` pattern: `video_budget_gb: "{{ lookup('env', 'VIDEO_BUDGET_GB') | default(30) }}"`. Place near `delay_last_class` with a comment explaining it's the total-size budget (GB) for /videos, templated into cronvideo-dep.j2.
- [ ] Task 2: EDIT `k3s/templates/cronvideo-dep.j2` — (a) change line 76 `NR>50` → `NR>30` (reduce retention from 50 to 30). (b) After the per-file-size cleanup (`find . -maxdepth 1 -type f -name '*.mp4' -size +2G -delete`) and before `sleep 600`, add a total-size guard block:
  - Template `VIDEO_BUDGET_GB={{ video_budget_gb | default(40) }}` at the top of the loop (same pattern as `TRIM_TAIL`).
  - Loop: `while [ "$(du -sm /videos | awk '{print $1}')" -gt "$((VIDEO_BUDGET_GB * 1024))" ]; do OLDEST=$(ls -t count* 2>/dev/null | tail -1); [ -z "$OLDEST" ] && { echo "WARN: /videos exceeds budget ($VIDEO_BUDGET_GB GB) but no count* files to delete — tocompress-* or other files may be the cause"; break; }; echo "Budget guard: deleting oldest $OLDEST"; rm -f "$OLDEST"; done`
  - This deletes oldest `count*` first (via `ls -t | tail -1` = oldest by mtime) until usage drops below budget or no `count*` remain.
- [ ] Task 3: EDIT `ansible/playbooks/app/build_countingapp.yml` — after the `docker buildx build` command (line 35), add `docker image prune -f && docker builder prune -f` to the same shell block. This removes dangling old images (~20GB) and build cache (~8.6GB) accumulated by each rebuild, making rebuilds net-zero on disk.
- [ ] Task 4: EDIT `ansible/playbooks/system/install_k3s_with_docker_tasks.yml` — in the kubelet-arg list (around line 181), add two explicit args: `"container-log-max-files=5"` and `"container-log-max-size=10Mi"`. These match the kubelet defaults but make the bound explicit and non-reliant on default behavior across versions. Add a comment noting these bound `/var/log/containers` and `/var/log/pods` growth.
- [ ] Task 5: CREATE `ansible/playbooks/system/configure_disk_guards.yml` — new playbook with two tasks:
  - **Journald bound**: create `/etc/systemd/journald.conf.d/` directory + copy a drop-in file `countingapp.conf` with content `[Journal]\nStorage=persistent\nSystemMaxUse=200M\n` then restart `systemd-journald` service. Tag: `journald`.
  - **Docker builder prune timer**: create a systemd service `docker-builder-prune.service` (oneshot, `ExecStart=/usr/bin/docker builder prune -af`) + timer `docker-builder-prune.timer` with `OnUnitInactiveSec=7d` and `Persistent=false` (monotonic, no wall-clock dependency), then enable+start the timer. Follow the pattern from `configure_splash_screen.yml` (copy service file, copy timer file, `systemd` module enable+start with `daemon_reload: yes`). Tag: `prune-timer`.
  - Add a doc comment at the top explaining: these guards bound non-video disk consumers that could cause saturation in 24/7 operation. Journald was completely unconfigured; kubelet container-log defaults are made explicit in install_k3s_with_docker_tasks.yml.
- [ ] Task 6: VERIFY all Jinja2 templates render correctly — run `ansible-playbook --syntax-check` or equivalent dry-run on the deploy playbook to confirm `video_budget_gb` templating resolves without error. Confirm the guard block shell syntax is valid (no Jinja2/whitespace issues in the inline script).

## Validation

- **Template rendering**: `cd ansible/playbooks/app && ansible-playbook -i ../../inventory/jetsons.yml deploy_app.yml --tags cleanup --syntax-check` — confirms `cronvideo-dep.j2` renders with the new `video_budget_gb` var and guard block without Jinja2 errors.
- **New playbook syntax**: `ansible-playbook ansible/playbooks/system/configure_disk_guards.yml --syntax-check` — confirms the new playbook is valid YAML/Ansible.
- **K3s config syntax**: verify the kubelet-arg additions produce valid YAML in the k3s config template (no indentation/structure issues).
- **On-Jetson deploy** (manual, post-approval): apply the cronvideo template change via `ansible-playbook deploy_app.yml --tags deploy` (renders + applies `cronvideo-dep.yaml`); apply disk guards via the new system playbook. Then verify:
  - `du -sh /data/orin/files` stays within budget during recording.
  - `journalctl --disk-usage` reports ≤200MB after journald config applied.
  - `systemctl list-timers docker-builder-prune.timer` shows the timer active with `OnUnitInactiveSec=7d`.
  - After a `docker buildx build`, `docker system df` shows no dangling images / minimal build cache.
- **No count regression**: this change touches only k3s templates + ansible (no app/requirements.txt change), so no image rebuild is needed and counting logic is unaffected. The cronvideo pod only does compression/cleanup — it does not touch the counting pipeline.

## Risks

- **Guard cannot reduce `tocompress-*` backlog**: if raw input clips accumulate faster than the 10-min compression cycle can process them, `tocompress-*` alone could exceed the budget and the guard (which only deletes `count*`) cannot help. Mitigation: the guard logs a clear warning when this happens; the compression loop processes `tocompress-*` → `count*` each cycle so the backlog is self-clearing under normal load. The warning surfaces the condition for manual intervention if sustained.
- **Kubelet-arg change only effective on fresh k3s install**: modifying `install_k3s_with_docker_tasks.yml` changes the bootstrap config. On an already-deployed Jetson, the kubelet-args require manually editing `/etc/rancher/k3s/config.yaml` + `systemctl restart k3s`. Mitigation: document this in the playbook comments; the values match existing defaults so no behavioral change on already-deployed systems until next reinstall.
- **`docker builder prune -af` during active build**: the systemd timer fires 7d after the prune unit was last inactive, so it won't fire during an active build. However, if a build is in progress when the timer fires, `prune -af` could remove cache layers in use. Mitigation: `docker builder prune -af` only removes unused cache (not layers referenced by running builds); `OnUnitInactiveSec` further reduces collision likelihood.
- **Journald `SystemMaxUse=200M` too aggressive**: if verbose logging is needed for debugging, 200MB may vacuum useful entries. Mitigation: value is configurable (hardcoded in the drop-in for now, could be parameterized later); 200MB is generous for stdout logging at INFO level on a single-node system.