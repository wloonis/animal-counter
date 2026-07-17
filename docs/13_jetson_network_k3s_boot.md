# 13 — Jetson networking & K3s boot (WiFi-only, no RTC, no ethernet cable)

How the Jetson Orin Nano boots a stable single-node K3s cluster **over WiFi
only** (no ethernet cable), with a **stable SSH access IP**, despite having
**no RTC battery** and **no ethernet link**.

This documents the fix for K3s instability at boot + the static WiFi access IP.
It explains **why** each decision was made, because the obvious approaches all
fail on this hardware and the working solution is non-obvious.

---

## TL;DR

| Concern | Solution |
|---------|----------|
| K3s node-ip must be stable + reachable at boot | Put it on a **virtual `dummy0` interface** (always UP, no cable needed), not the physical ethernet (linkdown) and not WiFi (changes between internet/hotspot mode) |
| Jetson has no RTC battery → clock boots to 1970 | `fake-hwclock` restores the clock at boot + `ExecStartPre=/sbin/fake-hwclock load` on k3s re-applies it at the very last moment |
| A late RTC sync resets the clock to 1970 *after* fake-hwclock | `k3s-clock-ready` gate + the `ExecStartPre` re-load cover it |
| WiFi IP drifted (DHCP `.180 → .181`) → unpredictable SSH | Pin the internet WiFi connection to a **static `.180`** |
| First boot has no fake-hwclock data yet | `k3s-clock-ready` waits for the phone (BL-65) time push over the hotspot |

---

## 1. Background — the two problems

### 1.1 K3s was unstable at boot

After a reboot, K3s entered a crash-loop (`activating (auto-restart),
Result: exit-code`) and never became `Ready`. The countingapp pod never ran
reliably across reboots.

### 1.2 The WiFi IP drifted

The Jetson's internet WiFi connection (the home/field router, e.g.
`TP-Link_49F0`) was on **DHCP**, so its IP drifted (e.g.
`192.168.0.180 → 192.168.0.181`). SSH access then required rediscovering the IP
with `scripts/jetson_discover.sh` every time.

These looked related but were **two independent problems** (see §3).

---

## 2. The Jetson's hardware reality

- **Orin Nano 8GB "Super"**, user `nano-counter`.
- **Two network interfaces:**
  - `enP8p1s0` — physical ethernet. Configured static `192.168.50.10/24`, but
    **linkdown** in production (no cable — deployments are WiFi-only).
  - `wlP1p1s0` — WiFi radio. Used in **two mutually-exclusive modes**:
    - **Internet WiFi** (client/infrastructure, e.g. `TP-Link_49F0`) — for
      internet + SSH access. DHCP by default.
    - **HotSpot** (AP mode, `JetsonHotspot`, `192.168.100.1/24`) — for the
      Android phone app (BL-65) to push time + (later) view counts.
  The radio **cannot be client + AP at the same time**, so the Jetson is either
  on internet WiFi **or** in hotspot mode, never both.
- **No coin-cell battery → no RTC.** On every boot the system clock is
  `1970-01-01` until something sets it (the phone via BL-65, or `fake-hwclock`).
- K3s is a **single-node** cluster; `kubectl` is run **on the Jetson**
  (`k3s kubectl`), not from a remote PC.

---

## 3. Investigation & root cause — it was NOT the WiFi IP

The initial hypothesis was "the WiFi IP changed `.180 → .181`, so K3s (which
the install pinned to `.180`) broke." **This was wrong.**

K3s config (`/etc/rancher/k3s/config.yaml`) was:

```yaml
node-ip: 192.168.50.10          # the ETHERNET interface (enP8p1s0)
advertise-address: 192.168.50.10
flannel-iface: enP8p1s0         # the ETHERNET interface
```

So K3s used the **ethernet** IP `.50.10`, **not the WiFi**. The WiFi IP drift
was irrelevant to K3s. The real causes were:

1. **`enP8p1s0` is linkdown** (no cable). K3s tried to bind/advertise
   `192.168.50.10` on an interface with no carrier → the API server could not
   start → crash-loop. Forcing the interface admin-UP did **not** help: it
   stayed `NO-CARRIER, state DOWN`, and K3s still refused to bind.
2. **The clock was `1970`** at boot (no RTC). Even once the interface problem
   was bypassed, K3s would not come up with a 1970 clock.

Confirmed empirically:
- Putting `.50.10` on a `dummy0` interface (always UP, carrier present) +
  `flannel-iface: dummy0` + setting the clock to 2026 → **K3s `active`, node
  `Ready`, countingapp `Running`**.
- Reverting either (no dummy0, or clock 1970) → K3s crash-loops.

The WiFi IP drift was a **separate, real** annoyance (SSH access), fixed
independently in §6.

---

## 4. Why a `dummy0` interface (and not the obvious alternatives)

K3s needs a **stable** node-ip that is:
- **reachable at boot** (so the API server can bind), and
- **the same regardless of WiFi mode** (the Jetson switches between internet
  WiFi and hotspot).

The candidates:

| Candidate | Why it fails |
|-----------|--------------|
| Physical ethernet `enP8p1s0` (`.50.10`) | **Linkdown without a cable** → no carrier → K3s can't bind. This was the original (broken) design. |
| WiFi interface `wlP1p1s0` | IP **changes between modes** (internet WiFi `.0.x` vs hotspot `.100.1`). Pinning K3s to one mode breaks it in the other. |
| Forcing `enP8p1s0` UP without a cable | Stays `NO-CARRIER, state DOWN`; K3s still refuses to bind the IP. |

**`dummy0`** (a Linux virtual interface, `ip link add dummy0 type dummy`) is:
- **always UP with carrier** (no cable needed), so K3s can bind its IP, and
- **independent of WiFi mode** (it's a separate virtual interface), so the
  node-ip is stable whether the Jetson is on internet WiFi or in hotspot.

This is the standard trick for "K3s node-ip on a host with a changing network"
(laptops, WiFi-only edge boxes). The Jetson keeps its `.50.10` node-ip — it now
just lives on `dummy0` instead of the dead ethernet.

> `JETSON_ETH_IP` (`.50.10`) is reused as the dummy/node IP so `.env.local`
> doesn't change. The name is historical; the value is carried by `dummy0`.

---

## 5. The boot-clock problem (no RTC) and why it needed three layers

The Jetson has no RTC battery, so at boot the clock is `1970-01-01`. K3s cannot
start with a 1970 clock. The fix has **three cooperating layers**, each
covering a gap the others leave:

### 5.1 `fake-hwclock` — restore the clock at boot

`fake-hwclock` saves the current clock to `/etc/fake-hwclock.data` (on shutdown
+ hourly) and restores it at boot. This gives a roughly-correct clock (within
the downtime) — enough for K3s certs (which are valid for a year), even if it's
stale by days. Installed + enabled as a systemd service.

### 5.2 The "late RTC sync resets to 1970" surprise

`fake-hwclock` runs early (`Before=sysinit.target`) and **does** restore the
clock (confirmed: service `active (exited) since 2026-07-17 17:34`). But the
clock ended up `1970` anyway — a **late sync from the dead onboard RTC**
(`/dev/rtc` → `rtc0`, which reads `1970`) runs *after* fake-hwclock and
overwrites it. `hwclock.service` was already masked and `systemd-timesyncd`
disabled, so the culprit is a kernel/udev RTC sync — not worth fighting at the
kernel-cmdline level.

### 5.3 `k3s-clock-ready` — wait for a sane clock before K3s

A oneshot gate (`k3s-clock-ready.service`) that loops: re-runs
`fake-hwclock load` and checks `date +%Y >= 2025`; exits 0 once sane.
`Before=k3s.service` + K3s `After=k3s-clock-ready.service`. This re-applies
fake-hwclock **after** the late RTC reset, and on a **fresh install with no
fake-hwclock data yet** it waits for the phone (BL-65) to push time over the
hotspot before letting K3s start.

### 5.4 `ExecStartPre=/sbin/fake-hwclock load` on K3s — the last-moment guarantee

Even the gate could be beaten by a reset between gate-exit and K3s-start. So
K3s's own override adds:

```ini
[Service]
ExecStartPre=/sbin/fake-hwclock load
```

This reloads the clock **immediately before** K3s's `ExecStart` — the last
possible moment, after any late RTC sync. This is the layer that actually made
the live test pass (clock was 1970 → `ExecStartPre` → 2026 → K3s `active`).

> **Why three layers?** Each alone is insufficient: fake-hwclock gets reset by
> the late RTC sync; the gate's single load can be beaten by a reset after it;
> the `ExecStartPre` alone wouldn't wait for the phone on a first boot with no
> saved data. Together they cover: saved-data boots (instant, via
> `ExecStartPre`), first-boot-no-data (waits for phone, via the gate), and
> late-reset robustness (re-applied by both the gate and `ExecStartPre`).

---

## 6. Static WiFi access IP (`.180`)

Independent of K3s (which uses `dummy0`), the internet WiFi connection was
pinned to a static IP for predictable SSH access.

`configure_static_wifi.yml`:
- Discovers the **active infrastructure** WiFi connection on `wlP1p1s0`
  (excludes the hotspot AP connection by checking
  `802-11-wireless.mode == infrastructure`), so it works for any router SSID
  without hardcoding credentials.
- `nmcli connection modify` → `ipv4.method manual`, `192.168.0.180/24`,
  gateway `192.168.0.1`, DNS `192.168.0.1` + `8.8.8.8`, autoconnect-priority 50.
- `modify` only rewrites the profile — it does **not** drop the active SSH
  session. The static IP applies on the **next activation** (reboot, or when
  the hotspot is cut and the Jetson rejoins the internet WiFi).

> The static `.180` and the hotspot `192.168.100.1` coexist: `.180` is the
> internet-WiFi IP, `.100.1` is the hotspot IP. Which one is active depends on
> which WiFi mode the Jetson is in.

---

## 7. Files

| File | Role |
|------|------|
| `ansible/playbooks/system/install_k3s_with_docker_tasks.yml` | K3s install (WiFi-only): creates `dummy0-net.service`, installs `fake-hwclock`, creates `k3s-clock-ready`, writes k3s `config.yaml` (`flannel-iface: dummy0`) + the k3s override (`After=…` + `ExecStartPre=/sbin/fake-hwclock load`) |
| `ansible/playbooks/system/configure_static_wifi.yml` | Pins the active internet WiFi connection to static `192.168.0.180` |
| `scripts/prepare_jetson.sh` | Runs `configure_static_wifi.yml` as **Step 4.5**, before `hotspot_setup.yml` (the discovery needs the active infrastructure WiFi, which disappears once the Jetson switches to AP mode) |

On the Jetson, the installed units:
- `/etc/systemd/system/dummy0-net.service` — creates `dummy0` + `.50.10` at boot
- `/usr/local/bin/k3s-clock-ready.sh` + `/etc/systemd/system/k3s-clock-ready.service` — the clock gate
- `/etc/systemd/system/k3s.service.d/override.conf` — `After=docker dummy0-net fake-hwclock k3s-clock-ready` + `ExecStartPre=/sbin/fake-hwclock load`
- `/etc/rancher/k3s/config.yaml` — `node-ip`/`advertise-address` `.50.10`, `flannel-iface: dummy0`

---

## 8. How to apply

### Fresh install (next Jetson)

`scripts/prepare_jetson.sh` does everything in order: system prep (installs
K3s with dummy0 + clock layers) → app deploy → **static WiFi `.180`** →
hotspot setup → splash screen. No manual steps.

### Existing Jetson (already done on the current one)

The fix was applied live on the current Jetson. To reproduce on another:
1. Run the k3s install tasks (or re-run `prepare_system.yml`).
2. Run `configure_static_wifi.yml` while the Jetson is on internet WiFi:
   ```bash
   JETSON_IP=192.168.0.181 JETSON_USER=nano-counter \
     ansible-playbook -i ansible/inventory/jetsons.yml \
     ansible/playbooks/system/configure_static_wifi.yml
   ```
3. Reboot. K3s comes up alone.

---

## 9. Verification (after a clean reboot, no intervention)

```bash
# from a PC on the same network (internet WiFi = .180, hotspot = .100.1)
ssh nano-counter@192.168.0.180   # or @192.168.100.1 if still in hotspot
```
On the Jetson:
```bash
date                                       # expect a 2026+ date, NOT 1970
systemctl is-active dummy0-net             # active
ip -o addr show dummy0 | grep inet         # 192.168.50.10/24
systemctl is-active k3s-clock-ready        # active
systemctl is-active k3s                    # active
sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get nodes   # Ready
sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get pods -A | grep counting   # Running
```

Expected after a clean reboot: clock 2026+, `dummy0` `.50.10`, K3s `active`,
node `Ready`, countingapp `Running` — all without any manual action.

---

## 10. Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| K3s `activating` / crash-loop after boot | `date` → is it `1970`? | `ExecStartPre=/sbin/fake-hwclock load` missing from the k3s override, or `/etc/fake-hwclock.data` is empty/stale → `sudo fake-hwclock save` once the clock is sane |
| K3s can't bind `.50.10` | `ip -o addr show dummy0` | `dummy0-net.service` not enabled/started → `sudo systemctl enable --now dummy0-net` |
| K3s `Ready` but countingapp not scheduled | `get pods -A` | GPU/manifest issue, not this fix — see `docs/07_troubleshooting.md` |
| SSH can't find the Jetson | which WiFi mode? | hotspot = `192.168.100.1`; internet = `192.168.0.180` (static). If drifted, `scripts/jetson_discover.sh` |
| `configure_static_wifi.yml` fails "no active infrastructure WiFi" | Jetson is in hotspot mode | cut the hotspot first so TP-Link reconnects, then re-run |

> **Do NOT** revert K3s to the physical ethernet interface (`enP8p1s0`). It is
> linkdown without a cable and K3s will crash-loop. The `dummy0` interface is
> intentional, not a workaround to "fix".

---

## 11. Decision rationale (why this way)

- **dummy0, not WiFi, not ethernet:** WiFi changes IP between internet/hotspot
  modes; ethernet is linkdown without a cable. A virtual interface is the only
  option that is both always-up and mode-independent.
- **fake-hwclock, not NTP:** the Jetson is offline (hotspot has no internet),
  so NTP is unavailable. fake-hwclock is the standard no-RTC fix.
- **Three clock layers:** the late dead-RTC sync (→1970) defeated fake-hwclock
  alone; a single gate load could be beaten by a post-gate reset; the
  `ExecStartPre` is the final guarantee. The gate additionally handles the
  first-boot-no-saved-data case (waits for the phone push).
- **Reusing `JETSON_ETH_IP` for the dummy IP:** avoids touching `.env.local`;
  the value `.50.10` is unchanged, only the carrying interface changes.
- **Static `.180` via `nmcli modify` (not `up`):** `modify` doesn't drop the
  active SSH session; `up` would. The IP applies on the next activation, so the
  install can finish on the DHCP IP and `.180` takes effect later.
- **`configure_static_wifi` before `hotspot_setup`:** it discovers the *active
  infrastructure* WiFi connection, which disappears once the Jetson switches to
  AP mode, so it must run while still on internet WiFi.