# Plan: BL-64 — Companion Jetson clock-sync service (`/api/time`)

## Summary
Add a stdlib-only Python HTTP service (`jetson-companion`) running as a root
systemd unit on the Jetson host, exposing `POST /api/time` (applies
`timedatectl set-ntp false` → `set-time` → `set-timezone`) and `GET /api/identify`,
deployed via an Ansible playbook mirroring BL-63's `configure_boot_cleanup.yml`,
plus `docs/11_jetson_companion.md`. This is the Jetson-side foundation for BL-65
(Android phone pushing the clock over the Jetson HotSpot), fixing the wrong-clock
problem on offline boot (no RTC → 1970 / build date).

## In Scope
- New `ansible/playbooks/system/configure_companion.yml` — playbook with the
  inline Python script (→ `/usr/local/bin/jetson-companion`, 0755) and inline
  systemd unit (→ `/etc/systemd/system/jetson-companion.service`), structurally
  mirroring `configure_boot_cleanup.yml` (BL-63).
- Python service (~80 lines, stdlib only: `http.server`, `json`, `subprocess`,
  `datetime`, `os`, `sys`):
  - Binds `0.0.0.0:8090` (configurable via `COMPANION_PORT`, default 8090).
  - `POST /api/time` — JSON `{"time":"<ISO8601>","tz":"Europe/Paris"}`; strict
    input validation (parse ISO8601, check tz, `subprocess.run([...], shell=False)`
    explicit arg lists — no shell injection) → 400 on bad input instead of a
    timedatectl 500; on success runs `timedatectl set-ntp false` →
    `timedatectl set-time "<time>"` → `timedatectl set-timezone "<tz>"` and
    returns 200 + JSON confirmation.
  - `GET /api/identify` → `{"service":"jetson-companion","version":"1"}`.
- systemd unit: `Type=simple`, `User=root`, `Restart=always`,
  `WantedBy=multi-user.target`.
- New `docs/11_jetson_companion.md` — numbered doc convention: service role,
  endpoints, ansible deploy command, curl examples, HotSpot/Android context
  (link to BL-65), NTP handling, and why port 8090 (8080 taken by filebrowser).
- Live deploy during implement: run the playbook against 192.168.0.180, then
  verify the acceptance curls; for `/api/time` POST the dev machine's real
  current time (`date -Iseconds`) so the Jetson keeps the correct clock.
- Run `scripts/validate_on_jetson.sh` (standard) as a regression check
  confirming the companion (port 8090, root) does not interfere with counting.
  `validation/config.json` `mode` stays `"standard"`.

## Out of Scope
- `/api/count` (live counting) → BL-66.
- Android app (clock push) → BL-65.
- Token/auth (omitted in v1).
- Any change to counting code (`app/src/counting.py`, `main.py`,
  tracking/counting, core, params).
- Any change to `validation/config.json` or `scripts/validate_on_jetson.sh`.
- `scripts/validate_on_jetson.sh` only rsyncs `app/` and does NOT deploy the
  companion.

## Architecture Decisions
- **Port 8090 (not 8080)** — filebrowser already holds `*:8080` on the Jetson
  (pid 4118); 8090 verified free. Configurable via `COMPANION_PORT` (default 8090).
- **Host service, not k3s** — running on the host gives direct `timedatectl`
  access without a pod privilege dance; simpler and matches the BL-63 host-side
  pattern. `User=root` in the unit so `timedatectl set-time` succeeds.
- **Stdlib Python only** — no venv/pip/external deps; uses the Jetson's system
  Python. Keeps the service trivially installable and dependency-free.
- **Strict input validation in `/api/time`** — parse the ISO8601 `time` with
  `datetime`, validate `tz` (non-empty string passed to `timedatectl
  set-timezone`), and invoke `timedatectl` via `subprocess.run([...],
  shell=False)` with explicit arg lists (no shell). Return HTTP 400 with a JSON
  error on bad input rather than letting `timedatectl` fail with a 500. This
  prevents shell injection and gives the Android app clean error semantics.
- **Playbook mirrors BL-63** — inline `copy: content: |` blocks for both the
  script and the unit, `hosts: all`, `become: true`, `gather_facts: yes`, vars
  for paths/port, systemd `daemon_reload`/`enabled`/`started`, BL-63-style
  header comment + `Usage:` block. Adapted to a long-running `Type=simple`
  service (BL-63's is `oneshot`).
- **Live deploy + verification during implement** — not deferred to post-merge.
  POST the real dev-machine clock (`date -Iseconds`) so the Jetson ends up with
  a correct time rather than a bogus test value.
- **Standard validation as regression** — per AGENTS.md infra convention;
  confirms the root service on 8090 does not disturb the counting pipeline.

## Tasks
- [ ] Task 1: CREATE `ansible/playbooks/system/configure_companion.yml` — the
  playbook. Mirror BL-63's `configure_boot_cleanup.yml` structure exactly:
  header comment + `Usage:` block; `hosts: all`, `become: true`,
  `gather_facts: yes`; `vars` with `companion_script: /usr/local/bin/jetson-companion`,
  `companion_service: jetson-companion.service`, `companion_port: 8090`. Three
  tasks: (a) `copy` inline the Python script to `{{ companion_script }}`,
  owner/group root, mode `0755`; (b) `copy` inline the systemd unit to
  `/etc/systemd/system/{{ companion_service }}`, owner/group root, mode `0644`;
  (c) systemd module `daemon_reload: yes`, `enabled: yes`, `state: started`.
- [ ] Task 2: WRITE the inline Python service (~80 lines, stdlib only) inside
  the playbook's script `copy` block. `http.server.BaseHTTPRequestHandler` with
  two routes: `POST /api/time` (parse JSON, validate `time` via
  `datetime.fromisoformat`, validate non-empty `tz`, run
  `subprocess.run(["timedatectl","set-ntp","false"], check=True)`, then
  `set-time`, then `set-timezone` via `subprocess.run([...], shell=False)`;
  return 200 + `{"ok":true,"time":...,"tz":...}` on success, 400 + JSON error
  on bad input / `timedatectl` failure) and `GET /api/identify` (return
  `{"service":"jetson-companion","version":"1"}`). Port from
  `os.environ.get("COMPANION_PORT", "8090")`; bind `0.0.0.0`. Log to stdout for
  journald.
- [ ] Task 3: WRITE the inline systemd unit inside the playbook's unit `copy`
  block: `[Unit]` Description + `After=network-online.target` +
  `Wants=network-online.target`; `[Service]` `Type=simple`,
  `ExecStart={{ companion_script }}`, `User=root`, `Restart=always`,
  `RestartSec=3`; `[Install]` `WantedBy=multi-user.target`.
- [ ] Task 4: CREATE `docs/11_jetson_companion.md` following the numbered doc
  convention (`# 11 — Jetson Companion Clock-Sync Service`). Cover: role of the
  service (offline clock sync via Android phone, BL-65 link), the two endpoints
  with curl examples, the ansible deploy command
  (`set -a; source .env.local; set +a; ansible-playbook -i
  ansible/inventory/jetsons.yml ansible/playbooks/system/configure_companion.yml`),
  NTP handling (`set-ntp false` before `set-time`), why port 8090 (8080 taken by
  filebrowser), and a link to issue #64.
- [ ] Task 5: (Optional) UPDATE `README.md` table of contents to list
  `docs/11_jetson_companion.md` (and `docs/10_offline_image_transfer.md` if
  still missing) so the docs index stays current.
- [ ] Task 6: DEPLOY live — `set -a; source .env.local; set +a;
  ansible-playbook -i ansible/inventory/jetsons.yml
  ansible/playbooks/system/configure_companion.yml` against 192.168.0.180.
- [ ] Task 7: VERIFY acceptance — `curl http://192.168.0.180:8090/api/identify`
  → `{"service":"jetson-companion","version":"1"}`; `curl -X POST
  http://192.168.0.180:8090/api/time -H 'Content-Type: application/json' -d
  "{\"time\":\"$(date -Iseconds)\",\"tz\":\"Europe/Paris\"}"` and confirm
  `timedatectl` reflects the change; `ssh ... systemctl is-enabled
  jetson-companion` → enabled.
- [ ] Task 8: VERIFY stdlib-only — `python3 -m py_compile` on the extracted
  script and grep for forbidden imports (no third-party packages; only
  `http.server`, `json`, `subprocess`, `datetime`, `os`, `sys`).
- [ ] Task 9: RUN `scripts/validate_on_jetson.sh` (standard) as a regression
  check confirming the companion does not interfere with counting; confirm
  `validation/config.json` `mode` is still `"standard"`.

## Validation
- `curl http://192.168.0.180:8090/api/identify` →
  `{"service":"jetson-companion","version":"1"}`.
- `curl -X POST http://192.168.0.180:8090/api/time -H 'Content-Type: application/json' -d
  "{\"time\":\"$(date -Iseconds)\",\"tz\":\"Europe/Paris\"}"` → 200 + JSON
  confirmation; `timedatectl` on the Jetson reflects the new time/timezone.
- `ssh nano-counter@192.168.0.180 'systemctl is-enabled jetson-companion'` →
  `enabled`; `systemctl is-active jetson-companion` → `active`.
- Playbook idempotent: re-running it reports no unexpected changes.
- `python3 -m py_compile` on the script passes; no third-party imports.
- `scripts/validate_on_jetson.sh` (standard) passes — counting unaffected.
- `docs/11_jetson_companion.md` exists and documents the service/endpoints.

## Risks
- **`timedatectl set-time` fails without root** — mitigated by `User=root` in
  the systemd unit (same approach as BL-63).
- **Port 8090 already in use by something else on this Jetson** — verified free
  during clarify; the implementer should re-confirm with `ss -ltnp | grep 8090`
  before deploying.
- **NTP re-enables and overwrites the pushed time** — mitigated by running
  `timedatectl set-ntp false` before `set-time` on every POST; note in docs that
  NTP stays off until manually re-enabled.
- **Bad input → shell injection via `timedatectl`** — mitigated by strict
  ISO8601/tz validation and `subprocess.run([...], shell=False)` (no shell).
- **Pushing the wrong time missets the Jetson clock** — implement POSTs the real
  dev-machine clock (`date -Iseconds`), not a hardcoded test value.
- **README docs TOC goes stale** — optional Task 5 updates it; low risk if
  skipped since the requirement is only that `docs/11_*.md` exists.