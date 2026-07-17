# Plan: BL-64 — Jetson Companion Clock-Sync Service

## Summary
A stdlib-only Python HTTP service (`jetson-companion`) running on the Jetson **host** (not k3s) on port **8090** that receives time/timezone from an Android phone (BL-65) over the HotSpot and applies it via `timedatectl`, fixing the Jetson's lack of RTC at offline boot. Deployed by an Ansible playbook modeled on BL-63's `configure_boot_cleanup.yml` structure, plus a numbered doc `docs/11_jetson_companion.md`.

## In Scope
- NEW `ansible/playbooks/system/configure_companion.yml` — playbook + inline Python script (`/usr/local/bin/jetson-companion`, 0755) + inline systemd unit (`/etc/systemd/system/jetson-companion.service`).
- NEW `docs/11_jetson_companion.md` — role, endpoints, deploy command, curl examples, HotSpot/Android (BL-65) context, NTP handling, why port 8090 (8080 taken by filebrowser).
- Python stdlib HTTP server (http.server, json, subprocess, datetime, os, sys) — NO external deps, NO venv/pip.
- `POST /api/time` — body `{"time":"<ISO8601>","tz":"Europe/Paris"}` → `timedatectl set-ntp false` → `timedatectl set-time "<time>"` → `timedatectl set-timezone "<tz>"` → 200 + JSON confirmation.
- `GET /api/identify` — `{"service":"jetson-companion","version":"1"}`.
- Port configurable via `COMPANION_PORT` env (default 8090), bind 0.0.0.0.
- Strict input validation on `POST /api/time`: ISO8601 parse + tz check + `subprocess.run([...], shell=False)` → 400 JSON error on bad input.
- Journald logging via stdout (logs every set-time / identify / error).

## Out of Scope
- `/api/count` (live counting) → BL-66.
- Android app (push time) → BL-65.
- Token/auth (omitted in v1).
- Any change to counting code (`app/src/counting.py`, `main.py` tracking/counting, core, params).
- Changes to `validation/config.json` (stays `mode: "standard"`) or `scripts/validate_on_jetson.sh`.

## Architecture Decisions
- **Host service, not k3s** — the service must call `timedatectl set-time`, which requires host root + systemd; running on the host (not in a k3s pod) is the simplest path to host clock control. Same rationale as BL-63's host-side boot cleanup.
- **Port 8090, not 8080** — 8080 is already bound by `filebrowser` on the Jetson (pid 4118, `*:8080`); 8090 is free. Documented in the doc + the spec.
- **`Type=simple` long-running unit (adapted from BL-63's oneshot)** — a persistent HTTP server needs `Type=simple` + `Restart=on-failure`, `After=network-online.target` + `Wants=network-online.target`, `User=root`. The **playbook structure** (inline `copy: content: |`, vars, systemd module daemon_reload/enabled/started, `hosts: all`, `become: true`, header comment + "Usage:" block) stays identical to BL-63 — only the unit type adapts to a long-running daemon.
- **stdlib-only Python** — no Flask/FastAPI/uvicorn; the Jetson's host Python runs the service directly. Zero install footprint, matches the "no venv/pip" constraint.
- **`User=root` in the unit** — `timedatectl set-time` requires root; same approach as BL-63.
- **NTP disabled before set-time** — `timedatectl set-ntp false` must run before `set-time`, otherwise systemd-timesyncd can reject the write or immediately overwrite it.
- **`subprocess.run([...], shell=False)`** — argument-list form, never `shell=True`, to avoid injection from the JSON body. Each timedatectl call is a separate `subprocess.run` with checked return codes; any failure → 500 with the stderr captured.
- **Strict input validation** — parse `time` with `datetime.datetime.fromisoformat()` (reject unparseable → 400); validate `tz` is a known timezone by checking `/usr/share/zoneinfo/<tz>` existence or running `timedatectl list-timezones` cache (reject → 400). Never pass raw body strings to a shell.
- **Deploy during implement** — run the playbook live on the Jetson (192.168.0.180) and verify the acceptance curls. For `POST /api/time`, send the dev machine's real current time (`date -Iseconds`) so the Jetson keeps a correct clock, not a bogus 2025 test value that would mis-date subsequent videos/logs.
- **Standard validation as regression** — run `scripts/validate_on_jetson.sh` (reference video only, no `--full`) per AGENTS.md infra convention, confirming the root service on port 8090 does not disturb counting. `validation/config.json` `mode` stays `standard`.

## Tasks
- [ ] Task 1: CREATE `ansible/playbooks/system/configure_companion.yml` — Ansible playbook modeled exactly on `ansible/playbooks/system/configure_boot_cleanup.yml` structure: header comment block + "Usage:" block, `hosts: all` / `become: true` / `gather_facts: yes`, `vars:` with `companion_script: /usr/local/bin/jetson-companion`, `companion_service: jetson-companion.service`, `companion_port: 8090`. Three tasks: (1) `copy` the inline Python script to `{{ companion_script }}` mode 0755 owner/group root; (2) `copy` the inline systemd unit to `/etc/systemd/system/{{ companion_service }}` mode 0644; (3) `systemd` module with `daemon_reload: yes`, `enabled: yes`, `state: started` (and a handler/task to restart the service when the script/unit changes so the running instance picks up the new code).
- [ ] Task 2: WRITE inline Python script (inside the playbook's first `copy: content: |`) — `~80 lines`, stdlib only (`http.server`, `json`, `subprocess`, `datetime`, `os`, `sys`): `BaseHTTPRequestHandler` subclass with `do_GET` (route `/api/identify` → `{"service":"jetson-companion","version":"1"}` 200; 404 otherwise) and `do_POST` (route `/api/time` → parse JSON body → validate `time` via `datetime.fromisoformat` → validate `tz` via zoneinfo/list-timezones → run `subprocess.run(["timedatectl","set-ntp","false"], check=True)`, `subprocess.run(["timedatectl","set-time",time_str], check=True)`, `subprocess.run(["timedatectl","set-timezone",tz], check=True)` → 200 + `{"status":"ok","time":...,"tz":...}`; 400 on bad JSON/parse/tz; 500 on timedatectl failure with captured stderr). `ThreadingHTTPServer` on `0.0.0.0` and `int(os.environ.get("COMPANION_PORT","8090"))`. Log every request + result to stdout (journald). `if __name__ == "__main__"` entrypoint.
- [ ] Task 3: WRITE inline systemd unit (inside the playbook's second `copy: content: |`) — `[Unit]` Description=Jetson companion clock-sync service (BL-64), `After=network-online.target`, `Wants=network-online.target`. `[Service]` `Type=simple`, `User=root`, `ExecStart={{ companion_script }}`, `Restart=on-failure`, `RestartSec=3`, `Environment=COMPANION_PORT={{ companion_port }}`. `[Install]` `WantedBy=multi-user.target`.
- [ ] Task 4: CREATE `docs/11_jetson_companion.md` — numbered-doc style matching `docs/01`–`docs/10`. Sections: (a) role — offline clock sync via Android phone (BL-65) connecting to the Jetson HotSpot; (b) the Jetson-has-no-RTC problem (1970/build date at offline boot, mis-dated `tocompress-counting-*.mp4` and logs); (c) endpoints table — `GET /api/identify` and `POST /api/time` with request/response JSON; (d) deploy command — `set -a; source .env.local; set +a; ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/configure_companion.yml`; (e) curl examples for both endpoints (identify + set time with `date -Iseconds`); (f) NTP note — `set-ntp false` before `set-time` so timesyncd doesn't reject/overwrite; (g) why port 8090 — 8080 taken by filebrowser, 8090 free, configurable via `COMPANION_PORT`; (h) link to BL-65 (Android push) and BL-66 (/api/count, future). Cross-link from README's table of contents row (add `docs/11` entry).
- [ ] Task 5: RUN playbook live on Jetson — `set -a; source .env.local; set +a; ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/configure_companion.yml` against 192.168.0.180; confirm idempotent (re-run is clean / changed=0 on second run after handler restart logic is correct).
- [ ] Task 6: VERIFY acceptance curls live — `curl http://192.168.0.180:8090/api/identify` → `{"service":"jetson-companion","version":"1"}`; `curl -X POST http://192.168.0.180:8090/api/time -H 'Content-Type: application/json' -d "{\"time\":\"$(date -Iseconds)\",\"tz\":\"Europe/Paris\"}"` → 200 confirmation; then `ssh ... timedatectl` on the Jetson reflects the new time; `systemctl is-enabled jetson-companion` → enabled; negative test — POST with bad ISO → 400.
- [ ] Task 7: RUN standard validation regression — `scripts/validate_on_jetson.sh` (reference video, standard mode, no `--full`); confirm counting result unchanged vs baseline (the host service on 8090 must not disturb the k3s countingapp). `validation/config.json` stays `mode: "standard"`.
- [ ] Task 8: VERIFY no external Python deps — confirm the inline script imports only `http.server`, `json`, `subprocess`, `datetime`, `os`, `sys` (grep the playbook content for `import`/`from`); no `pip`/`venv` references; `python3 -m py_compile` the script (extracted locally) passes.

## Validation
- `curl http://192.168.0.180:8090/api/identify` → `{"service":"jetson-companion","version":"1"}`.
- `curl -X POST http://192.168.0.180:8090/api/time -H 'Content-Type: application/json' -d "{\"time\":\"$(date -Iseconds)\",\"tz\":\"Europe/Paris\"}"` → 200 JSON; `timedatectl` on the Jetson reflects the change.
- `ssh ... 'systemctl is-enabled jetson-companion'` → `enabled`; `systemctl is-active jetson-companion` → `active`.
- Playbook is idempotent: second `ansible-playbook` run reports the script/unit tasks unchanged (changed=0 except the restart handler).
- Bad-input test: `curl -X POST .../api/time -d '{"time":"not-a-date","tz":"Europe/Paris"}'` → 400 JSON error; `curl -X POST .../api/time -d '{"time":"2025-07-15T14:30:00","tz":"Mars/Olympus"}'` → 400.
- `scripts/validate_on_jetson.sh` standard run → counting PASS (regression, unchanged from baseline).
- `python3 -m py_compile` on the inline script → no errors; imports limited to stdlib.

## Risks
- **timedatectl set-time fails under timesyncd** — mitigate by always running `set-ntp false` first and checking the return code; on failure return 500 with stderr so the Android app can surface the error.
- **Port 8090 collision discovered later** — low risk (verified free); if it occurs, `COMPANION_PORT` env var in the unit lets us change it without editing the script.
- **Playbook not idempotent (restart loop)** — mitigate by using a handler or `notify` on the copy tasks so the service restarts only when content changes, and by testing the second run reports changed=0 for the copy tasks.
- **Injection via JSON body** — mitigate with `subprocess.run([...], shell=False)` argument-list form and strict ISO8601/timezone validation; never `shell=True`, never string-interpolate the body into a shell command.
- **Root service security** — service is open (no auth in v1) on the HotSpot LAN only; documented as v1 limitation. Acceptable because the HotSpot is a closed offline network and auth is explicitly out of scope (future BL).
- **Validation regression false-fail** — if the live `set-time` shifts the clock during a counting validation, video timestamps could confuse the run; mitigate by running validation after the clock is correctly set (not mid-set), and the standard reference-video run is robust to wall-clock.