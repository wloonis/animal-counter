# Issue #43 (P1) — Disk Saturation Guards: Template Verification

This record documents the off-Jetson syntax/render verification performed as
Task 6 of the approved plan (`PLAN.md`). On-Jetson deploy verification is
documented separately in the plan's **Validation** section and is performed
manually post-approval.

## Scope

Confirm that every Jinja2 template and Ansible playbook touched by the disk
saturation work (issue #43) renders without error, and that the inline shell
guard block in `cronvideo-dep.j2` is syntactically valid bash.

## Results

| # | Check | Command | Result |
|---|-------|---------|--------|
| 1 | Deploy playbook syntax (renders `cronvideo-dep.j2` path) | `ansible-playbook -i ../../inventory/jetsons.yml deploy_app.yml --tags cleanup --syntax-check` | **PASS** |
| 2 | New disk-guards playbook syntax | `ansible-playbook ansible/playbooks/system/configure_disk_guards.yml --syntax-check` | **PASS** |
| 3 | k3s bootstrap playbook syntax (contains kubelet-arg additions) | `ansible-playbook ansible/playbooks/system/prepare_system.yml --syntax-check` | **PASS** |
| 4 | Real Jinja2 render of `cronvideo-dep.j2` via Ansible `template` module (localhost) | localhost playbook w/ `group_vars/all.yml` + `app_namespace`/`files_path` | **PASS** — no Jinja2 errors, no leftover `{{ }}` braces, output parses as YAML |
| 5 | Guard-block shell syntax | `bash -n` on the extracted inline script from the rendered ConfigMap | **PASS** (`BASH SYNTAX OK`) |
| 6 | k3s `config.yaml` content renders to valid YAML with new kubelet-args | Ansible `copy` render + `yaml.safe_load` | **PASS** — `kubelet-arg` list includes `container-log-max-files=5`, `container-log-max-size=10Mi` |

## Rendered guard block (from `cronvideo-dep.j2`)

The total-size guard block renders as valid bash inside the container
`command` array. Key lines after rendering:

```bash
VIDEO_BUDGET_GB={{ video_budget_gb | default(40) }}   # templated from group_vars
...
BUDGET_MB=$((VIDEO_BUDGET_GB * 1024))
while [ "$(du -sm /videos | awk '{print $1}')" -gt "$BUDGET_MB" ]; do
  OLDEST=$(ls -t count* 2>/dev/null | tail -1)
  [ -z "$OLDEST" ] && {
    echo "WARN: /videos exceeds budget (${VIDEO_BUDGET_GB} GB) but no count* files left to delete — tocompress-* or other files may be the cause"
    break
  }
  echo "Budget guard: deleting oldest $OLDEST"
  rm -f "$OLDEST"
done
```

The count-file retention line renders as `ls -t count* 2>/dev/null | awk 'NR>30' | xargs -r rm -f`
(reduced from `NR>50` → `NR>30`).

## Note on env-default semantics

`video_budget_gb` follows the same `lookup('env', ...) | default(N)` pattern as
the existing `delay_last_class` var. As with `delay_last_class`, when the env
var is unset the value renders empty unless `default(N, true)` is used. This is
intentionally consistent with the existing pattern (per the plan: "same pattern
as `TRIM_TAIL`"). On the Jetson the value is supplied via the deployment `.env`,
so the default applies only as a documentation fallback. No change to this
semantics was made; it is out of scope for the verification task.

## Conclusion

All templates and playbooks render without Jinja2 errors. The inline guard
script is valid bash. The k3s config with the new explicit kubelet container-log
bounds is valid YAML. Ready for on-Jetson deploy verification.