# 13 — DS3231 RTC (HW-084) install + on-demand time sync (BL-74)

The Jetson Orin Nano has **no coin-cell battery and no working onboard RTC**,
so on every power cut the system clock falls back to the build date (or
`1970-01-01`). The existing clock stack ([`docs/12_jetson_network_k3s_boot.md`])
covers this with `fake-hwclock` (rough, restored-at-boot clock) and the
[companion service][`docs/09_jetson_companion.md`] (phone pushes exact time
over the hotspot). But both need either a previous good shutdown
(`fake-hwclock` saves the clock on shutdown, so it is wrong after a long
power cut) or a phone present (companion). A **hardware RTC** is the only
source that survives a power cut *without* a phone and sets the clock
*before* userspace starts counting.

This document covers the **DS3231 HW-084** module — wiring, the boot service
that detects it at runtime, the fallback chain that keeps `fake-hwclock` as a
tertiary, and the Android "Synchroniser l'heure" button that replaces the old
automatic ~30s keep-alive time-push loop.

---

## TL;DR

| Concern | Solution |
|---------|----------|
| No RTC battery → clock resets on every power cut | Add a **DS3231 HW-084** module on the 40-pin header (I2C bus 7, addr `0x68`) |
| RTC must not break a Jetson with the module removed | `rtc-ds3231.service` does **runtime I2C detection** at boot — absent = clean no-op, present = register + `hwclock --hctosys` |
| `new_device` sysfs write is not idempotent on all kernels | Service guards the write with `[ -e /dev/rtc1 ]` (skip if already registered) |
| k3s must prefer the RTC but still boot without it | `k3s-clock-load.sh` wrapper: `/dev/rtc1` present → `hwclock --hctosys --rtc=/dev/rtc1`; absent → `fake-hwclock load` (tertiary fallback) |
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
> run `i2cdetect -y <N>` for each `/dev/i2c-N` to find the one that shows
> `0x68`, and adjust the `i2c_bus` var in
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

After wiring, power on the Jetson and run (over SSH):

```bash
sudo i2cdetect -y 7
```

A healthy DS3231 shows `68` in the grid (or `UU` if a kernel driver has
already claimed the address — which happens once `rtc-ds3231.service` has
registered it):

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- 68 -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --
```

If the grid is empty / shows no `68`, the module is not wired correctly (or
is on a different bus). Re-check pins 3/5/6/1 and the bus number.

---

## 3. Setup — installing the RTC config

The RTC config is shipped as `ansible/playbooks/system/configure_rtc.yml`,
which is **imported into `prepare_system.yml`** (before the k3s install
block) so a fresh `prepare_system` run sets it up automatically. There are two
ways to apply it on an already-prepared Jetson.

### 3.1 Via the standalone wrapper (preferred — over the hotspot)

```bash
./scripts/install_rtc_standalone.sh
./scripts/install_rtc_standalone.sh --check      # ansible dry-run
./scripts/install_rtc_standalone.sh --tags rtc   # extra ansible args
```

The wrapper mirrors `scripts/install_companion_standalone.sh`: it loads
`.env.local`, derives `JETSON_IP` from `JETSON_HOTSPOT_IP` (or accepts a plain
`JETSON_IP`), validates `JETSON_PASSWORD`, pauses for a manual checkpoint,
checks SSH reachability, then runs the playbook. It prints the verification
commands at the end (see §5).

### 3.2 Via raw ansible (if `JETSON_IP` is already exported)

```bash
set -a; source .env.local; set +a
ansible-playbook -i ansible/inventory/jetsons.yml \
                 ansible/playbooks/system/configure_rtc.yml
```

### 3.3 What the playbook does

`configure_rtc.yml` is a standalone playbook (`hosts: all`, `become: true`,
`gather_facts: yes`) that:

1. Installs `i2c-tools` (provides `i2cdetect` for the runtime probe).
2. Writes `/usr/local/bin/detect-ds3231.sh` (mode 0755) — probes I2C bus 7
   for `0x68`, accepts `68` **or** `UU` (already-claimed) as "present",
   exits `0` present / `1` absent. Pure detection, no side effects.
3. Writes `/etc/systemd/system/rtc-ds3231.service` (mode 0644):
   - `Type=oneshot`, `RemainAfterExit=yes`.
   - `After=systemd-modules-load.service` (i2c adapter ready),
     `Before=k3s-clock-ready.service` (clock sane before the k3s gate).
   - `ExecStart`: runs `detect-ds3231.sh`; if absent → `exit 0` (clean
     no-op); if present → guard `[ -e /dev/rtc1 ]` (skip the `new_device`
     write if already registered, so the service is idempotent on
     re-runs), then `echo ds1307 0x68 > /sys/class/i2c-adapter/i2c-7/new_device`,
     then `hwclock --hctosys --rtc=/dev/rtc1`.
   - `WantedBy=multi-user.target`.
4. Enables + starts the service (with `daemon_reload`).
5. A handler reloads systemd + restarts the service when the script/unit
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
   registers it as `/dev/rtc1` and copies the RTC time into the system
   clock (`hwclock --hctosys --rtc=/dev/rtc1`). If absent, it exits cleanly
   and the chain falls through.
2. **`fake-hwclock`** — restores the last-saved clock (saved at shutdown).
   This is only as good as the last shutdown, so it is wrong after a long
   power cut, but it is always present (it is installed unconditionally).
3. **The companion service** ([`docs/09_jetson_companion.md`]) — exposes
   `/api/time`, which the Android app can POST to on demand to set the
   exact current time. This is the only source that is always correct
   *right now*, but it requires a phone present.

### 4.2 k3s prefers the RTC, falls back to fake-hwclock

The k3s `ExecStartPre` used to be `/sbin/fake-hwclock load` directly. BL-74
reworks it into a **runtime wrapper script**, `/usr/local/bin/k3s-clock-load.sh`
(mode 0755), created by `install_k3s_with_docker_tasks.yml`:

```sh
if [ -e /dev/rtc1 ]; then
  hwclock --hctosys --rtc=/dev/rtc1
else
  /sbin/fake-hwclock load 2>/dev/null
fi
```

and the k3s override's `ExecStartPre` now calls the wrapper instead of
`fake-hwclock` directly. The k3s unit also gains `rtc-ds3231.service` in its
`After=` line (after `k3s-clock-ready.service`), so k3s starts only once the
RTC service has had a chance to set the clock. `fake-hwclock.service` stays
in `Requires=` because it is still the tertiary fallback when the RTC is
absent. `k3s-clock-ready.sh` and `k3s-clock-ready.service` are **unchanged**
— the `Before=` ordering means the RTC sets the clock before the sanity gate
runs, so there is no redundant `hwclock --hctosys` in the gate (no double
mechanism).

This avoids templating the override conditionally at install time and
handles hot-swap of the RTC module (remove the DS3231 and the next boot
silently falls back to `fake-hwclock`).

For the full background on why the clock stack exists at all (no RTC
battery, dummy0 interface, the late-RTC-sync problem the `k3s-clock-ready`
gate solves), see [`docs/12_jetson_network_k3s_boot.md`].

### 4.3 Android — on-demand instead of automatic

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

---

## 5. Verification (post-deploy, on the Jetson)

```bash
sudo i2cdetect -y 7                       # shows 68 (or UU once registered)
systemctl is-active rtc-ds3231           # active
ls /dev/rtc1                             # exists
sudo hwclock -r --rtc=/dev/rtc1          # sane date, not 1970
timedatectl                              # "RTC time:" line shows the DS3231
```

`timedatectl` will report a single hardware clock; once `/dev/rtc1` is the
registered DS3231, the system "RTC" it reads is the DS3231.

---

## 6. Troubleshooting

- **`i2cdetect -y 7` shows nothing at `0x68`.** Re-check the wiring (pins
  3/5/6/1), the bus number (try `i2cdetect -y 0`, `-y 1`, … on other Jetson
  variants), and that the module's battery is seated. The DS3231 keeps
  timekeeping alive off the coin cell even when the Jetson is off.
- **`/dev/rtc1` does not appear after a reboot.** Check
  `systemctl status rtc-ds3231` — if the detect script exited 1 (module
  absent) the service is a clean no-op, which is expected if the module is
  not wired. If it failed for another reason, `journalctl -u rtc-ds3231`
  shows the `i2cdetect` output and the `new_device` write error.
- **`rtc-ds1307` module not available.** The `ds1307` name written to
  `new_device` triggers the kernel to load `rtc-ds1307`. On JetPack 6.2 this
  module is standard; if it is missing, the registration fails — check
  `journalctl -u rtc-ds3231` for the modprobe error.
- **Clock is still wrong after boot with the RTC present.** The DS3231 only
  keeps good time if its battery was never removed for long. If the battery
  died or was never installed, the RTC itself defaults to a wrong date —
  set it once manually (`sudo hwclock -w --rtc=/dev/rtc1` after setting the
  system clock via the Android "Synchroniser l'heure" button or `date`),
  then it stays correct across power cuts.

For the broader clock-stack / k3s-boot troubleshooting, see
[`docs/14_troubleshooting.md`] and [`docs/12_jetson_network_k3s_boot.md`].