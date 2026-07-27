# 13 — DS3231 RTC (HW-084) install + on-demand, durable time sync (BL-74)

The Jetson Orin Nano has **no coin-cell battery and no working onboard RTC**,
so on every power cut the system clock falls back to the build date (or
`1970-01-01`). The existing clock stack ([`docs/12_jetson_network_k3s_boot.md`])
covers this with `fake-hwclock` (rough, restored-at-boot clock) and the
[companion service](https://github.com/wloonis/animal-counter-companion) (phone pushes exact time
over the hotspot; see [`IPC_CONTRACT.md`](IPC_CONTRACT.md)). But both need either a previous good shutdown
(`fake-hwclock` saves the clock on shutdown, so it is wrong after a long
power cut) or a phone present (companion). A **hardware RTC** is the only
source that survives a power cut *without* a phone and sets the clock
*before* userspace starts counting.

This document covers the **DS3231 HW-084** module — wiring, the boot service
that detects it at runtime, the fallback chain that keeps `fake-hwclock` as a
tertiary, the **NTP one-shot that initializes the DS3231 at install time**, and
the Android **"Synchroniser l'heure"** button that replaces the old automatic
keep-alive time-push loop **and now persists the correction into the DS3231**
(so a manual sync survives reboots).

---

## TL;DR

| Concern | Solution |
|---------|----------|
| No RTC battery → clock resets on every power cut | Add a **DS3231 HW-084** module on the 40-pin header (I2C bus 7, addr `0x68`) |
| RTC must not break a Jetson with the module removed | `rtc-ds3231.service` does **runtime I2C detection** at boot — absent = clean no-op, present = register + `hwclock --hctosys` |
| The DS3231 does NOT ACK `i2cdetect` quick-write probes (shows `--`) | The detect script probes with a **real `i2cget` register read** (reg `0x00`), and falls back to the sysfs device node once the driver is bound |
| The Jetson has two onboard Tegra RTCs (`rtc0`, `rtc1`, both stuck at 1970); the DS3231 binds as `/dev/rtc2`, **not** `/dev/rtc1` | Every script finds the DS3231 **dynamically by driver name** (`ds1307` in `/sys/class/rtc/*/device/name`) → `/dev/rtcN`. Nothing hardcodes `/dev/rtc1` |
| An uninitialized DS3231 (battery out, OSF flag) reads year 2000 — `hctosys` from it would reset the system clock to 2000 | `rtc-ds3231-init.sh` only does `hctosys` if the RTC **year ≥ 2024** (year-sanity gate); otherwise it leaves the system clock alone (fake-hwclock/companion take over) |
| The DS3231 ships unset; it must start accurate | `init-ds3231-from-ntp.sh` does a **one-shot NTP sync → `hwclock --systohc`** into the DS3231 at install time (best-effort; offline → skip, the Android button initializes it later) |
| Production is offline — the NTP daemon is useless there | NTP daemon (`systemd-timesyncd`) is **disabled** in production. The DS3231 is the boot source; the Android button is the corrector |
| A manual Android sync used to set only the system clock (lost on reboot) | The companion `POST /api/time` now also runs `hwclock --systohc --rtc=/dev/rtcN` → the correction **persists into the DS3231** and survives reboots |
| Old Android app pushed time automatically every ~30s | Replaced with a manual **"Synchroniser l'heure"** button in Settings (on-demand `POST /api/time`) |

---

## 1. Hardware — wiring the DS3231 HW-084 to the 40-pin header

The DS3231 is a cheap, accurate I2C real-time clock with a built-in
temperature-compensated crystal (TCXO). The "HW-084" breakout is the common
Zener-diode-protected variant sold for Raspberry Pi / Jetson headers.

On the Jetson Orin Nano, the **40-pin header's I2C bus is bus 7** (the
`i2c-7` adapter), and the DS3231 has a **fixed 7-bit address of `0x68`**.

### 1.1 Pin mapping

| HW-084 pin | 40-pin header pin | Net |
|------------|-------------------|-----|
| `VCC` | pin 1 | 3.3V |
| `GND` | pin 6 | GND |
| `SDA` | pin 3 | I2C bus 7 SDA |
| `SCL` | pin 5 | I2C bus 7 SCL |

> The Orin Nano 40-pin header exposes I2C bus 7 on pins 3 (SDA) / 5 (SCL).
> If you are on a **different Jetson variant**, the bus number may differ —
> probe each `/dev/i2c-N` with `i2cget -y <N> 0x68 0x00` (see §2 for why not
> `i2cdetect`), and adjust the `i2c_bus` var in
> `ansible/playbooks/system/configure_rtc.yml` accordingly.

### 1.2 ⚠️ Power it from 3.3V, NOT 5V — CR2032 vs LIR2032

The HW-084 module has a **battery charge circuit** meant for a **rechargeable
LIR2032** coin cell. If you fit a **non-rechargeable CR2032** (the common,
cheap kind) and power the module from **5V**, the charge circuit will try to
charge the CR2032 — which a primary (non-rechargeable) lithium cell cannot
take, leading to swelling, leakage, or rupture over time.

**Rule:** with a CR2032, wire `VCC` to **3.3V (pin 1)**, not 5V. At 3.3V the
charge circuit does not energize (the LIR2032 charge path needs the higher
input voltage), so the CR2032 only powers the RTC's timekeeping when the
Jetson is off — which is exactly what a primary cell is for. The DS3231 logic
level and the Jetson header are both 3.3V anyway, so 3.3V is the correct
choice regardless of the battery.

If you actually want to use a **LIR2032** (rechargeable) and let the module
keep it topped up, then 5V is the documented wiring — but for this project
the recommendation is **CR2032 + 3.3V** (long shelf life, no charge circuit,
no safety concern).

---

## 2. Detection — confirm the module is visible

After wiring, power on the Jetson and probe I2C bus 7 **with a real register
read** (over SSH):

```bash
sudo i2cget -y 7 0x68 0x00
```

A healthy DS3231 returns a hex byte (e.g. `0x19`). Once the `rtc-ds1307`
driver is bound (after `rtc-ds3231.service` has registered it), `i2cget`
returns `EBUSY` — in that state, presence is proved by the **sysfs device
node** instead:

```bash
ls /sys/bus/i2c/devices/7-0068      # exists once the driver claimed 0x68
```

> ⚠️ **Do not use `i2cdetect -y 7` to detect the DS3231.** The DS3231 does NOT
> ACK quick-write probes, so `i2cdetect` shows `--` at `0x68` (not `68`) even
> when the module is wired correctly. This is a known DS3231 quirk. Use
> `i2cget -y 7 0x68 0x00` (real read) or the sysfs node. The `detect-ds3231.sh`
> boot script uses exactly these two checks (i2cget first, sysfs fallback).

If `i2cget` errors out and the sysfs node is absent, the module is not wired
correctly (or is on a different bus). Re-check pins 3/5/6/1 and the bus number.

---

## 3. Setup — installing the RTC config

The RTC config is shipped as `ansible/playbooks/system/configure_rtc.yml`,
which is **imported into `prepare_system.yml`** (before the k3s install
block) so a fresh `prepare_system` run sets it up automatically. There are two
ways to apply it on an already-prepared Jetson.

### 3.1 Via the standalone wrapper (preferred — works on the hotspot AND the LAN)

```bash
./scripts/install_rtc_standalone.sh
./scripts/install_rtc_standalone.sh --check      # ansible dry-run
./scripts/install_rtc_standalone.sh --tags rtc   # extra ansible args
```

The wrapper mirrors `scripts/install_companion_standalone.sh` and resolves
the Jetson IP for **both** modes (no editing of `.env.local` needed):

1. **Explicit `JETSON_IP`** in `.env.local` → use it (fast path, no scan).
2. **Quick SSH probe of `JETSON_HOTSPOT_IP`** (4s, no nmap) → if reachable,
   use it. This is the **hotspot mode** path: the PC is on the Jetson's WiFi
   hotspot, the Jetson is right there at the fixed hotspot IP
   (`192.168.100.1`), so it is detected in ~4s with no network scan.
3. **`jetson_discover.sh`** (nmap scan of `WIFI_NETWORK` + SSH probe) → LAN
   mode. In hotspot mode the PC has no route to `WIFI_NETWORK`, so this finds
   nothing and the wrapper falls through to step 4.
4. **Fallback to `JETSON_HOTSPOT_IP`** (CIDR stripped).

The wrapper loads `.env.local`, validates `JETSON_PASSWORD`, pauses for a
manual checkpoint, checks SSH reachability, then runs the playbook. It
prints the verification commands at the end (see §5).

### 3.2 Via raw ansible (if `JETSON_IP` is already exported)

```bash
set -a; source .env.local; set +a
ansible-playbook -i ansible/inventory/jetsons.yml \
                 ansible/playbooks/system/configure_rtc.yml
```

### 3.3 What the playbook does

`configure_rtc.yml` is a standalone playbook (`hosts: all`, `become: true`,
`gather_facts: yes`) that:

1. **Installs `i2c-tools` if absent** (provides `i2cget`/`i2cdetect` for the
   runtime probe). **JetPack 6.2 ships `i2c-tools` preinstalled**
   (`4.3-2build1`), so on a prepared Jetson the `apt` task is **skipped**
   (`when: i2cdetect_check.rc != 0`) — no network needed, works offline. The
   playbook never installs anything else (no pip, no module): everything else
   is local file copies + systemd + i2c reads + `hwclock`.
2. **Writes `/usr/local/bin/detect-ds3231.sh`** (mode 0755) — probes I2C bus 7
   for `0x68` with `i2cget -y 7 0x68 0x00` (real register read), and falls back
   to the sysfs node `/sys/bus/i2c/devices/7-0068` (present once the driver is
   bound, when i2cget returns EBUSY). Exits `0` present / `1` absent. Pure
   detection, no side effects. (Uses `i2cget`, **not** `i2cdetect`, because
   the DS3231 does not ACK quick-write probes — see §2.)
3. **Writes `/usr/local/bin/rtc-ds3231-init.sh`** (mode 0755) — the boot
   action. It: runs `detect-ds3231.sh` (absent → clean `exit 0`); if the sysfs
   device is not yet registered, writes `echo ds1307 0x68 >
   /sys/class/i2c-adapter/i2c-7/new_device`; then **finds the bound RTC char
   device dynamically** via `/sys/bus/i2c/devices/7-0068/rtc/rtc*` →
   `/dev/rtcN` (N is **not** hardcoded — the Jetson has two onboard Tegra
   RTCs, so the DS3231 is typically `/dev/rtc2`); then **only does
   `hwclock --hctosys --rtc=/dev/rtcN` if the RTC year ≥ 2024** (year-sanity
   gate — an uninitialized DS3231 with the OSF flag set reads year 2000 and
   must not reset the system clock).
4. **Writes `/etc/systemd/system/rtc-ds3231.service`** (mode 0644):
   - `Type=oneshot`, `RemainAfterExit=yes`.
   - `After=systemd-modules-load.service` (i2c adapter ready),
     `Before=k3s-clock-ready.service` (clock sane before the k3s gate).
   - `ExecStart`: runs `rtc-ds3231-init.sh` (detect → register if needed →
     find the dynamic `/dev/rtcN` → `hctosys` only if the RTC year is sane).
   - `WantedBy=multi-user.target`.
5. **Enables + starts the service** (with `daemon_reload`).
6. **Writes `/usr/local/bin/init-ds3231-from-ntp.sh`** (mode 0755) — the
   install-time one-shot. It enables `systemd-timesyncd`, polls up to 24s for
   `NTPSynchronized=yes`, then `hwclock --systohc --rtc=/dev/rtcN` (the DS3231
   found dynamically by driver name `ds1307`) to persist the NTP-corrected
   system clock into the DS3231, then **disables `systemd-timesyncd` again**
   (production is offline). Offline → prints `offline — DS3231 left as-is`
   and exits 0 (the Android sync button initializes it later).
7. **Runs `init-ds3231-from-ntp.sh`** (best-effort, `failed_when: false`) — so
   a fresh install on an **online** Jetson starts with an accurate DS3231,
   and an **offline** install (hotspot) cleanly skips it.
8. A handler reloads systemd + restarts the service when the script/unit
   content changes, so a re-run picks up new code (and the second run is
   idempotent — `changed=0` when nothing changed).

It is **idempotent** (content-matched `copy` + systemd `service` module) and
**safe to re-run**.

---

## 4. How it works — the boot clock stack

### 4.1 The fallback chain

At boot, the clock is set in this order (first that applies wins, later ones
are harmless re-sets):

1. **`rtc-ds3231.service`** (this playbook) — runs at boot, *before*
   `k3s-clock-ready.service`. If the DS3231 is present on I2C bus 7, it
   registers it as `/dev/rtcN` (dynamic) and copies the RTC time into the
   system clock (`hwclock --hctosys --rtc=/dev/rtcN`) **only if the RTC year
   ≥ 2024**. If absent (or the RTC is uninitialized at year 2000), it exits
   cleanly and the chain falls through.
2. **`fake-hwclock`** — restores the last-saved clock (saved at shutdown).
   This is only as good as the last shutdown, so it is wrong after a long
   power cut, but it is always present (it is installed unconditionally).
3. **The companion service** ([`docs/09_jetson_companion.md`]) — exposes
   `/api/time`, which the Android app can POST to **on demand** (the
   "Synchroniser l'heure" button) to set the exact current time. This is the
   only source that is always correct *right now*, but it requires a phone
   present.

### 4.2 k3s prefers the DS3231, falls back to fake-hwclock

The k3s `ExecStartPre` used to be `/sbin/fake-hwclock load` directly. BL-74
reworks it into a **runtime wrapper script**, `/usr/local/bin/k3s-clock-load.sh`
(mode 0755), created by `install_k3s_with_docker_tasks.yml`:

```sh
RTC=""
for np in /sys/class/rtc/*/device/name; do
  [ -e "$np" ] || continue
  [ "$(cat "$np" 2>/dev/null)" = ds1307 ] || continue
  RTC="/dev/$(basename "$(dirname "$(dirname "$np")")")"
  break
done
if [ -n "$RTC" ] && [ -e "$RTC" ]; then
  /sbin/hwclock --hctosys --rtc="$RTC" 2>/dev/null
else
  /sbin/fake-hwclock load 2>/dev/null
fi
```

The wrapper finds the DS3231 **dynamically by driver name** (`ds1307`), so it
never accidentally reads an onboard Tegra RTC (`rtc0`/`rtc1`, both stuck at
1970 — hardcoding `/dev/rtc1` would set the clock to 1970). The k3s override's
`ExecStartPre` calls the wrapper, and the k3s unit gains
`rtc-ds3231.service` in its `After=` line (after `k3s-clock-ready.service`),
so k3s starts only once the RTC service has had a chance to set the clock.
`fake-hwclock.service` stays in `Requires=` because it is still the tertiary
fallback when the RTC is absent. `k3s-clock-ready.sh` and
`k3s-clock-ready.service` are **unchanged** — the `Before=` ordering means
the RTC sets the clock before the sanity gate runs, so there is no redundant
`hwclock --hctosys` in the gate (no double mechanism).

> **Already-deployed Jetsons** (k3s installed before BL-74) still have the old
> `ExecStartPre=/sbin/fake-hwclock load`. This is harmless: `rtc-ds3231.service`
> already set the clock from the DS3231 *before* k3s starts (it runs
> `Before=k3s-clock-ready.service`), so the k3s `ExecStartPre` is just a
> redundant tertiary reload. The wrapper above only lands on a **fresh** k3s
> install (via `install_k3s_with_docker_tasks.yml`). No need to re-apply it to
> a working Jetson.

For the full background on why the clock stack exists at all (no RTC
battery, dummy0 interface, the late-RTC-sync problem the `k3s-clock-ready`
gate solves), see [`docs/12_jetson_network_k3s_boot.md`].

### 4.3 NTP daemon — off in production

Production is offline, so the NTP daemon (`systemd-timesyncd`) is useless
there and is **disabled** (`timedatectl set-ntp false`). The DS3231 is the
boot source; the Android "Synchroniser l'heure" button is the corrector. The
only time NTP is used is the **install-time one-shot** (`init-ds3231-from-ntp.sh`,
§3.3 step 6) when the Jetson is online at install — it syncs once, persists to
the DS3231, then disables NTP again. If the Jetson later gets permanent
internet, you can re-enable NTP manually (`sudo timedatectl set-ntp true`),
but the default is off.

### 4.4 Android — on-demand AND durable

The old Android app ran a ~30s keep-alive loop that re-probed the Jetson and
pushed time automatically. BL-74 **removes the entire keep-alive loop** and
replaces the automatic time push with a manual **"Synchroniser l'heure"**
button in the Settings tab:

- `JetsonConnectionManager` loses `KEEP_ALIVE_INTERVAL_MS`,
  `keepAliveJob`, `startKeepAliveIfOnWifi()`, and the `postTime()` calls from
  `rescan()` / `onAvailable` / `onLost` / `stop()`. `rescan()` is now for IP
  selection only. A new public `suspend fun syncTime(): SyncResult` reuses
  the private `postTime()` and probe logic: if `activeIp` is set it uses it
  directly, otherwise it runs a fresh probe, then `POST /api/time` and
  returns success/failure.
- `SettingsViewModel` exposes a `syncResult` StateFlow
  (`Idle` / `Syncing` / `Success` / `Failure`). `syncTime()` sets it to
  `Syncing`, calls `JetsonConnectionManager.syncTime()`, and on `Success`
  launches a `delay(5000)` coroutine that resets to `Idle` (auto-clear); on
  `Failure` it persists until the next user action (`clearSyncResult()`
  resets it manually for a retry).
- `SettingsScreen` renders the button below the IP fields and observes
  `syncResult`: `Idle` → enabled button; `Syncing` → disabled + loading
  indicator; `Success` → green "Heure synchronisée ✓" (auto-clears);
  `Failure` → red "Échec de la synchronisation" (persists).

The `NetworkCallback` `onAvailable` / `onLost` still drive the reachability
banner, so IP selection and the HotSpot/LAN banner keep working without the
keep-alive loop.

**The key durability fix (BL-74):** the companion `POST /api/time` used to
set only the system clock (`timedatectl set-time` + `set-timezone`), so a
manual sync was lost on the next reboot (the drifted DS3231 reset it). It now
**also persists the correction into the DS3231**: after `set-time`, the
companion runs `hwclock --systohc --rtc=/dev/rtcN` (the DS3231 found
dynamically by driver name `ds1307`). So a manual Android sync now survives
reboots — the next boot, `rtc-ds3231.service` reads the corrected DS3231 and
the clock is sane without a phone. Best-effort: a no-op if the DS3231 is
absent; it never fails the time-set operation. See
[`docs/09_jetson_companion.md`] for the `/api/time` reference.

---

## 5. Verification (post-deploy, on the Jetson)

```bash
# detection (real read, NOT i2cdetect — see §2)
sudo i2cget -y 7 0x68 0x00          # returns a hex byte (e.g. 0x19); EBUSY once bound
ls /sys/bus/i2c/devices/7-0068      # exists once the driver claimed 0x68

# the DS3231's rtc char device (DYNAMIC — typically /dev/rtc2 on the Orin Nano,
# NOT /dev/rtc1 which is an onboard Tegra RTC stuck at 1970)
for np in /sys/class/rtc/*/device/name; do
  [ "$(cat "$np" 2>/dev/null)" = ds1307 ] && echo "DS3231 = /dev/$(basename "$(dirname "$(dirname "$np")")")"
done

systemctl is-active rtc-ds3231     # active
sudo hwclock -r --rtc=/dev/rtc2     # sane date (2026+), not 1970/2000
timedatectl                        # "RTC time:" line shows the DS3231; NTP=disabled
```

`timedatectl` will report a single hardware clock; once the DS3231 is the
registered `/dev/rtcN`, the system "RTC" it reads is the DS3231. `NTP=`
should read `no` (disabled in production — see §4.3).

To confirm a manual Android sync persisted, run it then check the DS3231
moved:

```bash
sudo hwclock -r --rtc=/dev/rtc2     # before
# (Android) Settings → Synchroniser l'heure
sudo hwclock -r --rtc=/dev/rtc2     # after — should match the phone's time
```

---

## 6. Troubleshooting

- **`i2cdetect -y 7` shows `--` at `0x68`.** This is **expected** — the DS3231
  does not ACK quick-write probes. Use `sudo i2cget -y 7 0x68 0x00` (real
  register read) or check `/sys/bus/i2c/devices/7-0068`. If `i2cget` also
  errors, re-check the wiring (pins 3/5/6/1) and the bus number (try
  `i2cget -y <N> 0x68 0x00` for each `/dev/i2c-N` on other Jetson variants),
  and that the module's battery is seated.
- **`/dev/rtc2` (the DS3231) does not appear after a reboot.** Check
  `systemctl status rtc-ds3231` and `journalctl -u rtc-ds3231`. The detect
  script (`detect-ds3231.sh`) exits 1 if the module is absent → the service
  is a clean no-op (expected if the module is not wired). The init script
  (`rtc-ds3231-init.sh`) finds the RTC dynamically; it never hardcodes
  `/dev/rtc1` (which is an onboard Tegra RTC, not the DS3231).
- **Clock is still 1970/2000 after boot with the DS3231 present.** The
  year-sanity gate skipped `hctosys` because the DS3231 reads year < 2024
  (uninitialized — the OSF flag was set, the battery was out, or it was
  never initialized). Initialize it once: either run
  `sudo /usr/local/bin/init-ds3231-from-ntp.sh` on an **online** Jetson
  (NTP one-shot → `systohc`), or use the Android **"Synchroniser l'heure"**
  button (which now persists to the DS3231), or manually
  `sudo hwclock --systohc --rtc=/dev/rtc2` after setting the system clock.
  Once initialized, it stays correct across power cuts.
- **`rtc-ds1307` module not available.** The `ds1307` name written to
  `new_device` triggers the kernel to load `rtc-ds1307`. On JetPack 6.2 this
  module is standard; if it is missing, the registration fails — check
  `journalctl -u rtc-ds3231` for the modprobe error.
- **NTP keeps re-enabling itself.** It should not — the one-shot
  `init-ds3231-from-ntp.sh` disables it at the end, and the companion runs
  `set-ntp false` before every `set-time`. If another service re-enables it,
  `sudo timedatectl set-ntp false` and check
  `systemctl status systemd-timesyncd`.

For the broader clock-stack / k3s-boot troubleshooting, see
[`docs/14_troubleshooting.md`] and [`docs/12_jetson_network_k3s_boot.md`].