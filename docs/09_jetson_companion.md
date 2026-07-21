# 09 — Jetson companion clock-sync service (BL-64)

A stdlib-only Python HTTP service (`jetson-companion`) running on the Jetson
**host** (not k3s) on port **8090** that receives the current time + timezone
from an Android phone
([BL-65](https://github.com/wloonis/animal-counter/issues)) over the WiFi
HotSpot and applies it via `timedatectl`, fixing the Jetson's lack of a
real-time clock (RTC) at offline boot.

This implements [GitHub issue BL-64](https://github.com/wloonis/animal-counter/issues).

## Why it exists — the Jetson has no RTC

The production Jetson has **no coin-cell battery**, so it has no real-time
clock. On every offline boot (no internet, no NTP) its system clock is stuck
at the **build date** (or `1970-01-01`). Everything that stamps a wall-clock
time is then wrong until the clock is manually set:

- the `tocompress-counting-*.mp4` video clips get mis-dated filenames and
  metadata,
- the journald logs are stamped with the bogus date,
- any file/output written during the session inherits the wrong timestamp.

When the Jetson is in **WiFi HotSpot mode**, the Android phone (BL-65) is the
only source of wall-clock time: it connects to the HotSpot and POSTs the
current time + timezone to this small HTTP service on the Jetson host, which
applies it via `timedatectl`. There is no internet, no NTP server, and no other
clock reference available — the phone is the clock.

## Endpoints

The service is a plain `http.server`-based daemon (Python stdlib only — no
Flask, no FastAPI, no `pip`, no `venv`). It binds `0.0.0.0:8090` and exposes
two JSON endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/identify` | Service discovery — returns the service name + version |
| `POST` | `/api/time` | Set the Jetson clock + timezone from the phone's time |

### `GET /api/identify`

**Response** `200`:
```json
{"service":"jetson-companion","version":"1"}
```

Any other path returns `404`:
```json
{"error":"not found"}
```

### `POST /api/time`

**Request body:**
```json
{"time":"2025-07-15T14:30:00","tz":"Europe/Paris"}
```

- `time` — an ISO8601 timestamp (parsed with `datetime.fromisoformat`;
  unparseable values are rejected with `400`).
- `tz` — an IANA timezone name (validated against `timedatectl
  list-timezones`; unknown zones are rejected with `400`).

**On success** `200`:
```json
{"status":"ok","time":"2025-07-15T14:30:00","tz":"Europe/Paris"}
```

**On bad input** `400` (malformed JSON, unparseable time, unknown timezone):
```json
{"error":"invalid ISO8601 time: 'not-a-date'"}
```

**On `timedatectl` failure** `500` (captured stderr included):
```json
{"error":"'timedatectl set-time 2025-07-15T14:30:00' failed: <stderr>"}
```

Input is strictly validated and `timedatectl` is always invoked via
`subprocess.run([...], shell=False)` (argument-list form, never
`shell=True`), so the JSON body is **never** interpolated into a shell
command — no injection surface.

## NTP note

The service always runs `timedatectl set-ntp false` **before** `set-time`.
This is required: if `systemd-timesyncd` (NTP) is still active, it can reject
the manual `set-time` write or immediately overwrite it with its own
(nonsense, offline) value. Disabling NTP first ensures the manual time sticks.

If you ever want to re-enable NTP (e.g. the Jetson later gets internet), run
it manually on the host:

```bash
sudo timedatectl set-ntp true
```

## Why port 8090

Port **8080** is already bound by `filebrowser` on the Jetson (the
file-management web UI), so the companion service cannot use it. **8090** is
free. The port is configurable via the `COMPANION_PORT` environment variable
in the systemd unit — change it in the playbook's `companion_port` var (or
the unit's `Environment=` line) and redeploy if 8090 is ever taken.

## Deploy

The service is deployed by the Ansible playbook
`ansible/playbooks/system/configure_companion.yml`, which installs the
script (`/usr/local/bin/jetson-companion`, mode `0755`) and the systemd unit
(`/etc/systemd/system/jetson-companion.service`), then enables + starts it. A
`notify` handler restarts the service whenever the script or unit content
changes, so the running instance picks up new code and the second playbook
run is idempotent (`changed=0` on the copy tasks).

The playbook runs on `hosts: all` with `become: true` (root, because
`timedatectl set-time` requires root). It is safe to re-run — the second run
reports `changed=0` for the copy tasks (the handler only fires on content
change).

### Offline, over the Jetson hotspot (preferred)

The companion is **stdlib-only Python** (http.server, json, subprocess,
datetime — no apt/pip/docker-pull), so it is the only system playbook that can
be deployed with **no internet** — exactly the situation once the Jetson is in
WiFi HotSpot mode (isolated LAN, no uplink). Use the standalone wrapper, which
mirrors `scripts/load_image.sh`'s offline pattern: it derives the target IP
from `JETSON_HOTSPOT_IP` (CIDR stripped) and pauses for a manual checkpoint
(the script cannot switch the Jetson to hotspot itself).

```bash
./scripts/install_companion_standalone.sh
```

Prereq (manual): switch the Jetson to **HotSpot mode** and connect this PC to
that hotspot. Required `.env.local` vars: `JETSON_HOTSPOT_IP` (e.g.
`192.168.100.1/24`), `JETSON_PASSWORD`, `JETSON_USER`. The wrapper sources
`.env.local`, exports `JETSON_IP` (CIDR stripped) for the env-based inventory,
checks SSH reachability, then runs the playbook.

### Raw ansible (if `JETSON_IP` is already exported)

If you just ran `prepare_jetson.sh` on the WiFi-internet network (which exports
`JETSON_IP` via `jetson_discover.sh`), you can run the playbook directly:

```bash
set -a; source .env.local; set +a
ansible-playbook -i ansible/inventory/jetsons.yml \
                 ansible/playbooks/system/configure_companion.yml
```

## curl examples

Assuming the Jetson is reachable at `192.168.0.180` (its IP on the HotSpot or
the local WiFi):

**Identify the service:**
```bash
curl http://192.168.0.180:8090/api/identify
# {"service":"jetson-companion","version":"1"}
```

**Set the clock from the PC's current time** (use `date -Iseconds` so the
Jetson gets the real current time, not a bogus test value):
```bash
curl -X POST http://192.168.0.180:8090/api/time \
  -H 'Content-Type: application/json' \
  -d "{\"time\":\"$(date -Iseconds)\",\"tz\":\"Europe/Paris\"}"
# {"status":"ok","time":"2025-07-15T14:30:00+02:00","tz":"Europe/Paris"}
```

**Negative test — bad ISO8601 (expect 400):**
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://192.168.0.180:8090/api/time \
  -H 'Content-Type: application/json' \
  -d '{"time":"not-a-date","tz":"Europe/Paris"}'
# 400
```

**Negative test — unknown timezone (expect 400):**
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://192.168.0.180:8090/api/time \
  -H 'Content-Type: application/json' \
  -d '{"time":"2025-07-15T14:30:00","tz":"Mars/Olympus"}'
# 400
```

After a successful `POST /api/time`, verify on the Jetson that the clock
reflects the change:

```bash
ssh nano-counter@192.168.0.180 'timedatectl'
```

And confirm the service is enabled + active:

```bash
ssh nano-counter@192.168.0.180 'systemctl is-enabled jetson-companion'
# enabled
ssh nano-counter@192.168.0.180 'systemctl is-active jetson-companion'
# active
```

## Security note (v1)

The service is open (no auth/token) in v1. It is reachable only on the
HotSpot LAN — a closed offline network where the only peer is the Android
phone. Auth is explicitly out of scope for v1 and will be added in a future
backlog item.

## Related

- **BL-65** — the Android app that connects to the Jetson HotSpot and pushes
  the current time to `/api/time` (the phone is the clock source).
- **BL-66** — `/api/count`, the future live-counting endpoint on the same
  companion service (not yet implemented; `GET /api/identify` and
  `POST /api/time` are the v1 surface).