# Plan: BL-74 — DS3231 RTC (HW-084) install + companion on-demand fallback

## Summary

Add a DS3231 hardware real-time clock to the Jetson with runtime I2C detection at boot, rework the k3s clock stack to prefer the RTC over fake-hwclock (keeping fake-hwclock as tertiary fallback), and replace the Android app's automatic ~30s keep-alive time-push loop with a manual on-demand "Synchroniser l'heure" button in Settings. The companion service stays installed as fallback.

## In Scope

- New ansible playbook `configure_rtc.yml` with boot-time `rtc-ds3231.service` (I2C bus 7, addr 0x68, `rtc-ds1307` registration → `/dev/rtc1` → `hwclock --hctosys`)
- Import `configure_rtc.yml` into `prepare_system.yml` before the k3s import
- Rework k3s `ExecStartPre` to a runtime wrapper script (`k3s-clock-load.sh`) that prefers RTC, falls back to fake-hwclock
- New standalone wrapper `scripts/install_rtc_standalone.sh`
- Android: remove keep-alive loop + automatic `POST /api/time` from `JetsonConnectionManager`; add public `syncTime()` method
- Android: add "Synchroniser l'heure" button in Settings with inline result (auto-clear ~5s on success, persist on failure)
- New `docs/13_rtc_install.md` with hardware wiring, safety notes, detection, setup commands
- Renumber docs: troubleshooting → 14, reset → 15 (new RTC doc takes slot 13, troubleshooting/reset stay last)
- Update `docs/02_setup.md`, `docs/12_jetson_network_k3s_boot.md`, `README.md` TOC with cross-refs

## Out of Scope

- No changes to `app/` (counting pipeline) — jetson-validate auto-skips
- No changes to the companion service itself (`configure_companion.yml` / `jetson-companion` script)
- No changes to `k3s-clock-ready.sh` script logic (stays as sanity gate, no RTC awareness)
- No changes to fake-hwclock installation (kept as tertiary fallback)
- No app/counting business validation

## Architecture Decisions

- **k3s-clock-ready.sh stays unchanged** — `rtc-ds3231.service` runs `Before=k3s-clock-ready.service`, so the RTC sets the clock before the gate runs. No redundant `hwclock --hctosys` in k3s-clock-ready.sh (no double mechanism).
- **k3s ExecStartPre becomes a wrapper script** (`/usr/local/bin/k3s-clock-load.sh`) — checks `/dev/rtc1` at runtime: present → `hwclock --hctosys --rtc=/dev/rtc1`; absent → `fake-hwclock load` (tertiary fallback). This avoids templating the override.conf conditionally at install time and handles hot-swap of the RTC module.
- **rtc-ds3231.service does runtime detection at boot** — `i2cdetect -y 7` checks for 0x68; if absent, service exits cleanly (Type=oneshot, no error). If present: `echo ds1307 0x68 > /sys/class/i2c-adapter/i2c-7/new_device` then `hwclock --hctosys --rtc=/dev/rtc1`. Idempotent: `new_device` write is guarded by checking if `/dev/rtc1` already exists.
- **Android: remove entire keep-alive loop, not just the time push** — the `KEEP_ALIVE_INTERVAL_MS`, `keepAliveJob`, and `startKeepAliveIfOnWifi()` are all removed. The NetworkCallback `onAvailable` still calls `rescan()` (for IP selection) but without the `postTime()` call. `rescan()` no longer calls `postTime()` on a successful probe.
- **Android: syncTime() exposed on JetsonConnectionManager** — reuses the existing private `postTime()` and probe logic. If `activeIp` is set, uses it directly; if not, runs a fresh `rescan()`-style probe first. Returns a result enum/sealed class for the Settings UI.
- **Doc renumbering: RTC takes slot 13** — the original issue referenced `docs/15_rtc_install.md`, but the confirmed decision is to insert as `docs/13_rtc_install.md` and renumber troubleshooting → 14, reset → 15, keeping troubleshooting/reset last.
- **Standalone wrapper created** — `scripts/install_rtc_standalone.sh` mirrors `install_companion_standalone.sh` (env loading, validation, manual checkpoint, ansible-playbook invocation) for re-running just the RTC config on an already-prepared Jetson.

## Tasks

- [x] **Task 1: CREATE** `ansible/playbooks/system/configure_rtc.yml` — New playbook. Installs `i2c-tools` package. Creates `/usr/local/bin/detect-ds3231.sh` script (runs `i2cdetect -y 7`, greps for `68`, exits 0/1). Creates `/etc/systemd/system/rtc-ds3231.service` (Type=oneshot, RemainAfterExit=yes, After=systemd-modules-load.service, Before=k3s-clock-ready.service, WantedBy=multi-user.target). The service ExecStart runs detect-ds3231.sh; if RTC present: guard `/dev/rtc1` existence (skip if already registered), `echo ds1307 0x68 > /sys/class/i2c-adapter/i2c-7/new_device`, `hwclock --hctosys --rtc=/dev/rtc1`; if absent: exit 0 (clean no-op). Enables + starts the service. Reloads systemd daemon. Idempotent (service module + copy with content matching). Standalone-callable (has its own `hosts: all`, `become: true`, `gather_facts: yes` header like other system playbooks).

- [ ] **Task 2: EDIT** `ansible/playbooks/system/prepare_system.yml` — Add `import_tasks: configure_rtc.yml` with `tags: rtc` immediately BEFORE the existing `import_tasks: install_k3s_with_docker_tasks.yml` block (around line 80, after the optimize block). This ensures the RTC service is installed before the k3s clock stack is configured.

- [ ] **Task 3: EDIT** `ansible/playbooks/system/install_k3s_with_docker_tasks.yml` — Rework the k3s clock stack: (a) Add a new task to create `/usr/local/bin/k3s-clock-load.sh` (mode 0755) — a wrapper script that checks `[ -e /dev/rtc1 ]` → if present runs `hwclock --hctosys --rtc=/dev/rtc1`; else runs `/sbin/fake-hwclock load`. (b) Change the k3s override.conf `ExecStartPre` from `/sbin/fake-hwclock load` to `/usr/local/bin/k3s-clock-load.sh`. (c) Add `rtc-ds3231.service` to the k3s override `[Unit] After=` line (after `k3s-clock-ready.service`). (d) Keep `fake-hwclock.service` in `Requires=` (still needed as tertiary fallback when RTC absent). (e) Keep `k3s-clock-ready.service` in `After=` unchanged. (f) Do NOT modify `k3s-clock-ready.sh` or `k3s-clock-ready.service`.

- [ ] **Task 4: CREATE** `scripts/install_rtc_standalone.sh` — Mirror `scripts/install_companion_standalone.sh` structure: load `.env.local`, validate `JETSON_PASSWORD` + `JETSON_HOTSPOT_IP` (or `JETSON_IP`), default `JETSON_USER=nano-counter`, strip CIDR, manual checkpoint prompt, SSH reachability check, export env, run `ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/configure_rtc.yml "$@"`. Support `--check` (dry-run) and `--tags` passthrough. Print verification commands at the end (`i2cdetect -y 7`, `systemctl is-active rtc-ds3231`, `ls /dev/rtc1`).

- [ ] **Task 5: EDIT** `android/app/src/main/java/com/animalcounter/net/JetsonConnectionManager.kt` — Remove: `KEEP_ALIVE_INTERVAL_MS` constant, `keepAliveJob` field, `startKeepAliveIfOnWifi()` method, `postTime()` calls inside `rescan()` (line ~175), `postTime()` call in keep-alive loop, `keepAliveJob` cancel in `rescan()` OutOfRange branch, `keepAliveJob` cancel in `onLost`, `keepAliveJob` cancel + null in `stop()`. Keep: `rescan()` for IP selection only (remove `postTime(resolved, network)` call and `startKeepAliveIfOnWifi()` call from the success branch), `onAvailable` → `rescan()` (no time push), `onLost` → out-of-range banner, one-time ON_START probe in `start()`. Keep `postTime()` as private but add a new public `suspend fun syncTime(): SyncResult` that: checks `repo?.activeIp?.value` — if set, uses it directly; if blank/null, runs a fresh probe (reuse `parallelProbe`/`singleProbe` logic); then calls `postTime()` and returns success/failure. Update KDoc to reflect removal of keep-alive loop.

- [ ] **Task 6: EDIT** `android/app/src/main/java/com/animalcounter/ui/settings/SettingsViewModel.kt` — Add a `syncResult` StateFlow (sealed class or enum: Idle, Syncing, Success, Failure with optional message). Add a `syncTime()` method that launches in `viewModelScope`: sets state to Syncing, calls `JetsonConnectionManager.syncTime()`, sets state to Success or Failure. On Success: launch a coroutine that `delay(5000)` then resets to Idle. On Failure: leave state as Failure (persists until next user action). Add a `clearSyncResult()` method to manually reset to Idle (for retry).

- [ ] **Task 7: EDIT** `android/app/src/main/java/com/animalcounter/ui/settings/SettingsScreen.kt` — Add a "Synchroniser l'heure" button (Button composable) below the existing IP fields. Observe `vm.syncResult` state. Show: Idle → button enabled with label; Syncing → button disabled with loading indicator; Success → green "Synchronisé ✓" text (auto-clears via VM); Failure → red "Échec de synchronisation" text (persists). Button onClick → `vm.syncTime()`.

- [ ] **Task 8: EDIT** `android/app/src/main/res/values/strings.xml` — Add: `settings_sync_time` ("Synchronize clock"), `settings_sync_success` ("Clock synchronized ✓"), `settings_sync_failure` ("Sync failed"), `settings_syncing` ("Synchronizing…").

- [ ] **Task 9: EDIT** `android/app/src/main/res/values-fr/strings.xml` — Add FR translations: `settings_sync_time` ("Synchroniser l'heure"), `settings_sync_success` ("Heure synchronisée ✓"), `settings_sync_failure` ("Échec de la synchronisation"), `settings_syncing` ("Synchronisation…").

- [ ] **Task 10: CREATE** `docs/13_rtc_install.md` — Hardware wiring section (DS3231 HW-084 → 40-pin header: VCC→pin1 3.3V, GND→pin6, SDA→pin3, SCL→pin5). 3.3V-not-5V safety note (the HW-084 module has a charge circuit for LIR2032; with a non-rechargeable CR2032, do NOT supply 5V — use 3.3V to avoid the charge circuit). CR2032-vs-LIR2032 charge-circuit caveat. Detection section (`i2cdetect -y 7` → 0x68). Standalone setup commands (direct `ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/configure_rtc.yml` and `scripts/install_rtc_standalone.sh`). How it works section (rtc-ds3231.service, k3s-clock-load.sh, fallback chain). Cross-ref to `docs/12_jetson_network_k3s_boot.md` for the clock stack background.

- [ ] **Task 11: RENAME** `docs/13_troubleshooting.md` → `docs/14_troubleshooting.md` — Git mv, update internal title/heading if it references its own number.

- [ ] **Task 12: RENAME** `docs/14_reset.md` → `docs/15_reset.md` — Git mv, update internal title/heading if it references its own number.

- [ ] **Task 13: EDIT** `docs/02_setup.md` — Enhance the existing DS3231 mention in the Hardware section (around line 18) with a cross-ref to `docs/13_rtc_install.md`. Update the playbook table in §5 to include `configure_rtc.yml` (new row, step 3, before `install_k3s_with_docker_tasks.yml`).

- [ ] **Task 14: EDIT** `docs/12_jetson_network_k3s_boot.md` — Add a cross-ref/note in §5 (the fake-hwclock / k3s-clock-ready section) pointing to `docs/13_rtc_install.md` for the RTC-based clock source that supersedes fake-hwclock when a DS3231 is installed. Update the TL;DR table row about "no RTC battery" to note the DS3231 option.

- [ ] **Task 15: EDIT** `README.md` — Update the Table of contents table: insert `docs/13_rtc_install.md` row, renumber troubleshooting to 14, reset to 15. Update all internal cross-references that link to `docs/13_troubleshooting.md` → `docs/14_troubleshooting.md` and `docs/14_reset.md` → `docs/15_reset.md`.

- [ ] **Task 16: EDIT** all other docs/files with cross-references to renumbered docs — grep for `13_troubleshooting` and `14_reset` across all docs and update links to the new numbers (`14_troubleshooting`, `15_reset`). This includes any cross-refs in `docs/01_quickstart.md`, `docs/02_setup.md`, `docs/03_deployment.md`, etc.

## Validation

- **Ansible syntax**: `ansible-playbook --syntax-check ansible/playbooks/system/configure_rtc.yml` and `ansible-playbook --syntax-check ansible/playbooks/system/prepare_system.yml`
- **Standalone script**: `bash -n scripts/install_rtc_standalone.sh` (syntax check)
- **Android build**: `cd android && ./gradlew assembleDebug` (compiles; no runtime test needed since no counting changes)
- **Kotlin compile**: Verify `JetsonConnectionManager.kt` compiles with removed keep-alive loop and new `syncTime()` method
- **Doc cross-refs**: `grep -r '13_troubleshooting\|14_reset' docs/ README.md` returns no results after renumbering (all updated to 14/15)
- **Jetson-validate**: auto-skips (no `app/` changes)
- **Manual on-Jetson verification** (post-deploy, if hardware available): `i2cdetect -y 7` shows `68`, `systemctl is-active rtc-ds3231` is `active`, `/dev/rtc1` exists, `hwclock -r --rtc=/dev/rtc1` returns a sane date

## Risks

- **I2C bus number may differ across Jetson models** — The Orin Nano uses bus 7 for the 40-pin header, but this could differ on other Jetson variants. Mitigation: document the bus number in `docs/13_rtc_install.md` and note it's specific to the Orin Nano.
- **`new_device` sysfs write is not idempotent on all kernels** — Writing `ds1307 0x68` to `new_device` when the device is already registered can error. Mitigation: guard with `[ -e /dev/rtc1 ]` check before the write.
- **Removing keep-alive loop changes connection monitoring** — Without the 30s re-probe, the app won't auto-detect a HotSpot→LAN migration while open. The NetworkCallback `onAvailable` still fires on WiFi changes, so IP selection still works. The on-demand sync button covers time needs. Mitigation: verified that `onAvailable`/`onLost` still drive the reachability banner.
- **Doc renumbering breaks external links** — Renaming `13_troubleshooting.md` → `14` and `14_reset.md` → `15` could break bookmarked URLs. Mitigation: this is a private repo with no external doc hosting; all cross-refs are updated in-task.
- **`rtc-ds1307` module may not be auto-loaded** — The `ds1307` name written to `new_device` triggers the kernel to load the `rtc-ds1307` module. If the module isn't available, registration fails. Mitigation: `i2c-tools` + the kernel module are standard on JetPack 6.2; document troubleshooting in `docs/13_rtc_install.md`.