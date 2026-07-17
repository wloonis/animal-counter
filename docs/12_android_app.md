# 12 — Android companion app (BL-65)

The Android app that pushes the phone's current time + IANA timezone to the
Jetson companion service ([BL-64](./11_jetson_companion.md),
`POST http://<jetson_ip>:8090/api/time`) whenever the phone joins the Jetson
WiFi hotspot. The Jetson has no RTC and no internet (offline hotspot), so it
relies on the phone to set its clock.

**Architecture:** phone = client, Jetson = server. The Jetson hotspot runs
continuously (fixed IP `192.168.100.1`); the phone auto-joins the saved hotspot
and pushes time in the background — no app open required.

---

## Features

- **Background time push** — a foreground service registers a
  `ConnectivityManager.NetworkCallback` on `TRANSPORT_WIFI`; when the phone
  joins the Jetson hotspot, it POSTs `Instant.now()` + `ZoneId.systemDefault()`
  to `/api/time` automatically. Re-registered at boot via `BOOT_COMPLETED`.
- **« Jetson hors de portée » banner** — when the app is open, the Time sync
  screen probes `GET /api/identify` and shows a localized status banner:
  « Jetson connecté » (green) / « Jetson hors de portée » (amber). Foreground
  only; the background push fires regardless of app-open state.
- **Manual « Sync now »** — fires the POST on demand for testing/debugging.
- **Multilingual (FR/EN)** — follows the phone's default system locale.
  `res/values/strings.xml` (English fallback) + `res/values-fr/strings.xml`
  (French). Structure ready for more locales via `values-<lang>/`.
- **3-tab hub** — Time sync (active), Live count + Videos (enabled placeholder
  screens, « Bientôt disponible » / « Coming soon »), extensible for future
  BL-66/BL-67.
- **Configurable Jetson IP** — persisted via Jetpack DataStore Preferences
  (default `192.168.100.1`).
- **Material 3** dynamic color (Material You) + dark theme forced. Adaptive pig
  launcher icon. App name « Animal Counter ».

---

## Prerequisites

1. **Jetson companion service running** (BL-64) on port `8090`
   (`/api/identify` + `/api/time`). See [11_jetson_companion.md](./11_jetson_companion.md).
2. **Jetson WiFi hotspot active** — SSID + password from `.env.local`
   (`JETSON_HOTSPOT_SSID` / `JETSON_HOTSPOT_PASSWORD`), gateway IP
   `192.168.100.1`. Activated via `ansible/playbooks/system/hotspot_setup.yml`.
3. **The phone** — Android 13+ (minSdk 33), e.g. Samsung Galaxy S20.

---

## Jetson companion — the bridge (install on the Jetson)

The Android app talks to the **Jetson companion service** (BL-64): a small
stdlib-only Python HTTP server running on the Jetson **host** (not k3s) on port
**8090**, exposing `GET /api/identify` (reachability probe) and
`POST /api/time` (set the clock). **Without it, the app has nothing to talk
to** — the « Jetson hors de portée » banner will stay amber and every push
will fail. It must be installed on the Jetson **before** the app is usable.

The companion is the only system playbook that deploys **offline, over the
Jetson's WiFi hotspot** (no internet needed — it's stdlib Python, no
apt/pip/docker-pull), which is exactly the situation once the Jetson is in
HotSpot mode (the same network the app will join).

### Prerequisites (`.env.local`)

Make sure these are set in `.env.local` (gitignored — never committed):

```ini
JETSON_HOTSPOT_IP=192.168.100.1/24   # Jetson hotspot IP with CIDR
JETSON_PASSWORD=********             # sudo/SSH password on the Jetson
JETSON_USER=nano-counter             # SSH user (default nano-counter)
JETSON_HOTSPOT_SSID=********         # hotspot SSID (for the phone to join)
JETSON_HOTSPOT_PASSWORD=********     # hotspot password
```

### Steps

1. **Switch the Jetson to WiFi HotSpot mode** (if not already):
   ```bash
   set -a; source .env.local; set +a
   ansible-playbook -i ansible/inventory/jetsons.yml \
     ansible/playbooks/system/hotspot_setup.yml
   ```
   The Jetson reboots and comes up as an access point on `192.168.100.1`.
   (Requires internet once for the apt packages; see
   [03_deployment.md](./03_deployment.md).)

2. **Connect this PC to the Jetson hotspot** (join the SSID from
   `JETSON_HOTSPOT_SSID`). The standalone deploy runs over this isolated LAN —
   no internet.

3. **Deploy the companion (offline standalone):**
   ```bash
   ./scripts/install_companion_standalone.sh
   ```
   The wrapper sources `.env.local`, derives the target IP from
   `JETSON_HOTSPOT_IP` (CIDR stripped → `192.168.100.1`), checks SSH
   reachability, pauses for a manual checkpoint (it cannot switch the Jetson to
   hotspot itself — confirm `y`), then runs the Ansible playbook
   `ansible/playbooks/system/configure_companion.yml`. This installs
   `/usr/local/bin/jetson-companion` (mode `0755`) + the systemd unit
   `/etc/systemd/system/jetson-companion.service`, enables + starts it
   (`User=root`, needed for `timedatectl set-time`). Idempotent — safe to re-run.

   Flags: `--check` (Ansible dry-run), `--tags <t>` (extra Ansible args).

4. **Verify the bridge is up:**
   ```bash
   # reachability probe (from this PC, on the hotspot)
   curl http://192.168.100.1:8090/api/identify
   # expected: {"service":"jetson-companion","version":"1"}

   # service status on the Jetson
   ssh nano-counter@192.168.100.1 'systemctl is-active jetson-companion'   # active
   ssh nano-counter@192.168.100.1 'systemctl is-enabled jetson-companion'  # enabled
   ```

5. **Test a manual time push** (before using the app):
   ```bash
   curl -X POST http://192.168.100.1:8090/api/time \
     -H 'Content-Type: application/json' \
     -d '{"time":"2025-07-15T14:30:00+02:00","tz":"Europe/Paris"}'
   # expected: {"status":"ok",...}
   ssh nano-counter@192.168.100.1 'timedatectl | grep "Local time"'
   ```

Once `/api/identify` returns the JSON above, the Android app's « Jetson
connecté » banner will go green and the background push will work. Full
companion reference (endpoints, NTP note, why port 8090, raw-ansible deploy,
curl examples): [11_jetson_companion.md](./11_jetson_companion.md).

---

## Build the APK

The build environment is already installed on the dev WSL host.

```bash
export JAVA_HOME="$HOME/jdk-17"
export ANDROID_HOME="$HOME/Android/Sdk"

cd android
./gradlew assembleDebug
```

Output:

```
android/app/build/outputs/apk/debug/app-debug.apk   (~58 MB)
```

> The debug APK is signed with the debug key (good for testing, not for the Play
> Store). No Jetson/video round-trip is required — the only validation is a
> successful Gradle build.

---

## Install the app on the phone

The phone install is a **debug install** (no Play Store). Two methods: **ADB
over USB** (recommended) or **sideload the APK**.

### Method A — ADB over USB (recommended)

This requires a host with a **physical USB connection** to the phone. On this
setup, run it from **Windows** (the dev environment is WSL, which has no USB
access).

#### 1. Enable Developer options on the Samsung S20 (One UI)

1. On the phone, open **Settings → About phone → Software information**.
2. Find **Build number** and tap it **7 times** rapidly.
3. You'll see « Developer mode has been enabled ».

#### 2. Enable USB debugging

1. Go back to **Settings → Developer options** (now visible at the bottom of
   Settings).
2. Toggle **USB debugging** ON.
3. (Optional but recommended) toggle **Wireless debugging** OFF for now — USB
   is simpler.
4. (Recommended) **Disable battery optimization** for the app after install:
   **Settings → Apps → Animal Counter → Battery → Unrestricted**. This prevents
   Android killing the foreground service that does the background time push.

#### 3. Install ADB on Windows

Download **Platform Tools** from Google and unzip:

```
https://developer.android.com/tools/releases/platform-tools
→ download "SDK Platform-Tools for Windows"
→ unzip to e.g. C:\platform-tools
```

Open **PowerShell** (or cmd) in the unzipped folder, or add it to `PATH`.

#### 4. Connect + authorize

1. Plug the phone into the PC with a **USB cable** (data cable, not charge-only).
2. On the phone, select the USB mode **Transferring files / Android Auto** (not
   « charge only »).
3. A dialog « Allow USB debugging? » appears — tick **Always allow from this
   computer** and tap **Allow / OK**.
4. Verify the connection:

```powershell
adb devices
# should list a device, e.g.:
# List of devices attached
# R58Mxxxxxxx    device
```

If you see `unauthorized`, re-plug and accept the prompt. If you see nothing,
check the cable and the USB mode.

#### 5. Copy the APK to Windows + install

Copy the built APK from WSL to Windows (the Windows filesystem is mounted in
WSL under `/mnt/c/`):

```bash
# from WSL
cp android/app/build/outputs/apk/debug/app-debug.apk /mnt/c/Users/<you>/Desktop/
```

Then install from Windows PowerShell:

```powershell
adb install "%USERPROFILE%\Desktop\app-debug.apk"
```

Expected:

```
Success
```

> `adb install` reinstalls the app if already present. Use `adb install -r` to
> reinstall while keeping data. If you get `INSTALL_FAILED_UPDATE_INCOMPATIBLE`,
> uninstall first: `adb uninstall com.animalcounter`.

#### 6. Launch + grant the notification permission

1. Open **Animal Counter** from the app drawer.
2. On first launch, Android 13+ asks for the **Post notifications** permission
   (needed by the foreground service's persistent notification) — **Allow**.
3. The Time sync tab opens. Enter the Jetson IP if it's not the default
   `192.168.100.1`.

### Method B — Sideload the APK (no PC)

If you can't use ADB:

1. Copy `app-debug.apk` to the phone (Bluetooth, email, USB file transfer, a
   file manager on the Jetson hotspot's `filebrowser` at `:8080`, etc.).
2. On the phone, open the APK with **My Files** (or any file manager).
3. If prompted, enable **Install unknown apps** for the file manager
   (**Settings → Apps → [file manager] → Install unknown apps → Allow**).
4. Tap **Install** → **Open**.
5. Grant the **Post notifications** permission on first launch.

---

## Configuration & usage

1. **Jetson IP** — open the Time sync tab; the OutlinedTextField defaults to
   `192.168.100.1` (the Jetson hotspot gateway). Change it only if your hotspot
   uses a different gateway. The value is persisted across app restarts.
2. **Out-of-range banner** — with the app open, the screen probes
   `GET /api/identify` automatically. Green « Jetson connecté » = reachable;
   amber « Jetson hors de portée » = timeout / wrong IP / Jetson off. Tap
   **Refresh** / **Actualiser** to re-probe.
3. **Sync now** / **Synchroniser maintenant** — fires the POST manually; the
   result + timestamp appear in the scrollable log view (for field debugging).
4. **Background push** — once the foreground service is running (it starts on
   app launch and at boot), the phone pushes time automatically whenever it
   joins the Jetson hotspot WiFi. No app open needed. The persistent
   notification « Animal Counter — synchronisation horaire » indicates the
   service is active.
5. **Verify on the Jetson** — after a push, check the Jetson clock:
   ```bash
   ssh nano-counter@192.168.100.1 'timedatectl | grep "Local time"'
   ```
   And the companion journal:
   ```bash
   ssh nano-counter@192.168.100.1 'journalctl -u jetson-companion -n 20 --no-pager'
   ```

---

## Permissions

| Permission | Why |
|---|---|
| `INTERNET` | HTTP calls to the Jetson companion (`/api/identify`, `/api/time`). |
| `ACCESS_NETWORK_STATE` | `ConnectivityManager.registerNetworkCallback` — detect joining the Jetson hotspot. |
| `RECEIVE_BOOT_COMPLETED` | Re-start the foreground service after a phone reboot. |
| `FOREGROUND_SERVICE` | Run the `TimeSyncService` foreground service. |
| `FOREGROUND_SERVICE_DATA_SYNC` | The foreground service type (`dataSync`) on Android 14+. |
| `POST_NOTIFICATIONS` | The persistent notification (Android 13+ runtime permission). |

**No location permission** — the app trusts the Jetson's 200 response rather
than verifying the SSID. The Jetson hotspot is an isolated network.

---

## Troubleshooting

- **« Jetson hors de portée » permanently** — check the phone is joined to the
  Jetson hotspot (Settings → WiFi), the IP is `192.168.100.1`, and the companion
  is running (`curl http://192.168.100.1:8090/api/identify` from a browser).
- **No background push after reboot** — confirm the foreground service is
  running: the persistent notification should be visible. Some manufacturers
  (Samsung included) aggressively kill background services; set the app to
  **Unrestricted** battery and disable **Put unused apps to sleep**
  (Settings → Battery and device care → Background usage limits).
- **Time not set on the Jetson** — the companion calls
  `timedatectl set-ntp false` then `timedatectl set-time`; check
  `journalctl -u jetson-companion` for errors (e.g. NTP still active, or the
  service not running as root).
- **Build fails on WSL** — ensure `JAVA_HOME=$HOME/jdk-17` and
  `ANDROID_HOME=$HOME/Android/Sdk` are exported; `java -version` should report
  17. The first Gradle build downloads the Gradle 8.9 distribution (internet
  required once).
- **`adb devices` empty on Windows** — install the Samsung USB driver; use a
  data cable; select « Transferring files » USB mode; re-accept the USB
  debugging prompt.

---

## Source layout

```
android/
  app/src/main/
    AndroidManifest.xml
    java/com/animalcounter/
      MainActivity.kt
      data/SyncEvent.kt, SyncLog.kt
      service/TimeSyncService.kt
      receiver/BootReceiver.kt
      net/JetsonClient.kt
      ui/theme/, ui/nav/, ui/timesync/...
    res/
      values/strings.xml          (English fallback)
      values-fr/strings.xml       (Français)
      values/themes.xml, colors.xml
      mipmap-anydpi-v26/ic_launcher.xml + ic_launcher_background/foreground
  build.gradle.kts, settings.gradle.kts, gradle/wrapper/...
```