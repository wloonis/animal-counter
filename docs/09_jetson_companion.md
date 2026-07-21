# 09 — Jetson companion service & API (BL-64 / BL-68)

A stdlib-only Python HTTP service (`jetson-companion`) running on the Jetson
**host** (not k3s) on port **8090**. It exposes the **companion API** consumed
by the Android app ([BL-65](https://github.com/wloonis/animal-counter/issues))
over the WiFi HotSpot:

- **v1 (BL-64)** — clock-sync: receives the current time + timezone from the
  phone and applies it via `timedatectl`, fixing the Jetson's lack of a
  real-time clock (RTC) at offline boot.
- **v2 (BL-68)** — read-only history/video: serves the persistent
  counting-session history and recorded videos from the hostPath `/files`
  (see [`11_counting_history.md`](11_counting_history.md) for the store
  internals — JSONL schema, compaction, disk guard).

This implements [GitHub issue BL-64](https://github.com/wloonis/animal-counter/issues)
and [BL-68](https://github.com/wloonis/animal-counter/issues).

## Why it exists — the Jetson has no RTC

> **Only needed without a hardware RTC.** This companion clock-sync service is
> a **software workaround** for the Jetson's missing real-time clock. If you've
> installed a **DS3231 RTC module** on the Jetson Nano (the optional hardware
> listed in [`02_setup.md`](02_setup.md) § Hardware), the system clock survives
> power cycles on its own and **this service is unnecessary** — leave it
> uninstalled or disable it. The companion is only useful on Jetsons that boot
> with no RTC battery and no other clock reference.

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
Flask, no FastAPI, no `pip`, no `venv`). It binds `0.0.0.0:8090`. The API is
versioned (`GET /api/identify` returns `"version"`): **v1** (BL-64) is the
clock-sync surface; **v2** (BL-68) adds the read-only history/video surface
backed by the hostPath `/files` JSONL (see
[`11_counting_history.md`](11_counting_history.md)).

### v1 — clock-sync (BL-64)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/identify` | Service discovery — returns the service name + version |
| `POST` | `/api/time` | Set the Jetson clock + timezone from the phone's time |

#### `GET /api/identify`

**Response** `200` (with the BL-68 history endpoints deployed):
```json
{"service":"jetson-companion","version":"2"}
```
Clock-sync-only deployments (pre-BL-68) return `"version":"1"`; the version
bumps to `"2"` once the read-only history endpoints (below) are deployed.

Any other path returns `404`:
```json
{"error":"not found"}
```

#### `POST /api/time`

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

### v2 — read-only history & video (BL-68)

The companion is bumped to **version `"2"`** (`GET /api/identify` returns
`"version":"2"`). These endpoints are **read-only** and never mutate the
JSONL (the pod is the sole writer). The reader uses a lazy `HistoryIndex`:
on the first history request it scans the JSONL once, builds an in-memory
`session_id → {offsets, summary}` map + a list of `startup` lines, caches it,
and invalidates the cache when `os.path.getsize` changes. Partial last lines
are tolerated.

| Method | Path | Query | Purpose |
|--------|------|-------|---------|
| `GET` | `/api/sessions` | `limit=50&offset=0` | Paginated session summaries (A + net count + last event ts), newest first |
| `GET` | `/api/sessions/<id>` | — | Full session detail (A–G): aggregate `session_start` + `heartbeat`s (last = `end_at` if no `session_end`) + `event`s + `session_end` |
| `GET` | `/api/summary` | `days=7` | Daily aggregates (count per day, sessions, guard events) |
| `GET` | `/api/startups` | `limit=50` | Startup history lines |
| `GET` | `/api/videos` | `limit=50&offset=0` | Paginated video summaries (one row per recorded video + running recording as synthetic first row), newest first |
| `GET` | `/api/video/<id>` | — (Range supported) | Range-streamed compressed `counting-<id>-*.mp4` (HTTP 200/206/416); 404 if absent or not yet compressed |

See the [curl examples](#curl-examples) below and
[`11_counting_history.md`](11_counting_history.md) for the JSONL line schema
(A–G) and the store internals.

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
# {"service":"jetson-companion","version":"2"}
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

**v2 — history & video (BL-68):**

**List recent sessions:**
```bash
curl 'http://192.168.0.180:8090/api/sessions?limit=10'
# {"sessions":[...],"limit":10,"offset":0,"total":N}
```

**Paginate (next page):**
```bash
curl 'http://192.168.0.180:8090/api/sessions?limit=10&offset=10'
```

**Get full detail for one session:**
```bash
curl http://192.168.0.180:8090/api/sessions/<session_id>
# {"session_id":"...","start_at":"...","end_at":"...","counters":{...},"events":[...],...}
```

**Daily summary (last 7 days):**
```bash
curl 'http://192.168.0.180:8090/api/summary?days=7'
# {"days":7,"daily":[{"date":"2025-07-15","count":9,"sessions":1,"guard_events":0},...]}
```

**List recent videos (running recording is the synthetic first row):**
```bash
curl 'http://192.168.0.180:8090/api/videos?limit=10'
# {"videos":[{"video_id":"counting-20250608-100000","filename":"counting-20250608-100000-#9.mp4","duration":120,"count_delta":9,"session_id":"...","ts":"...","status":"ready"},...],"limit":10,"offset":0,"total":N}
```

**Range-stream a video (resumable/partial download):**
```bash
curl -H 'Range: bytes=0-1023' \
  http://192.168.0.180:8090/api/video/counting-20250608-100000 -o /tmp/head.mp4
# HTTP 206, Content-Range: bytes 0-1023/<size>
curl http://192.168.0.180:8090/api/video/counting-20250608-100000 -o file.mp4
# HTTP 200, full file (playable on Android)
```

**Startup history:**
```bash
curl 'http://192.168.0.180:8090/api/startups?limit=50'
# {"startups":[{"boot_at":"...","image_tag":"...","git_commit":"...","mode":"serve",...}]}
```

**Negative test — unknown session (expect 404):**
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  http://192.168.0.180:8090/api/sessions/does-not-exist
# 404
```

## Security note

The service is open (no auth/token). It is reachable only on the HotSpot LAN —
a closed offline network where the only peer is the Android phone. Auth is
explicitly out of scope for v1/v2 and will be added in a future backlog item.

## Related

- **BL-65** — the Android app that connects to the Jetson HotSpot and pushes
  the current time to `/api/time` (the phone is the clock source), and reads
  the v2 history/video endpoints.
- **BL-68/71** — the read-only history/video endpoints (v2) served here; the
  backing JSONL store is documented in
  [`11_counting_history.md`](11_counting_history.md).
- **BL-66** — `/api/count`, the future live-counting endpoint on the same
  companion service (not yet implemented).