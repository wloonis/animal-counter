# Plan: BL-73 — Auto-select the Jetson companion IP (Android/Kotlin)

## Summary

Make the Android app auto-select the Jetson companion IP by probing two
candidates (hotspot `192.168.100.1` + LAN `192.168.0.180`) in parallel with
strict `/api/identify` service-name validation, expose the resolved IP as a
shared `activeIp` consumed by all tabs, re-scope clock sync to the app
lifecycle (foreground only) via a ~30s keep-alive re-probe loop, add a Settings
screen for manual override + auto-select toggle, and remove the Synchro tab +
the foreground `TimeSyncService` + `BootReceiver`. Kotlin-only; no `app/`
(Jetson) changes, so the `jetson-validate` node auto-skips.

## In Scope

- Strict `JetsonClient.identify()` validation: HTTP 200 + valid JSON +
  `json.service == "jetson-companion"` (exact). **No version check.** Reject
  otherwise. Fix the stale docstring (it says `"animal-counter-companion"`;
  the real companion returns `{"service":"jetson-companion","version":"4"}`).
- `SettingsRepository`: two configurable candidate IPs (`jetson_ip_hotspot`
  default `192.168.100.1`, `jetson_ip_lan` default `192.168.0.180`), an
  `auto_select` Boolean (default `true`), a manual-override IP, and an
  `activeIp: StateFlow<String>` resolved by a parallel WiFi-bound probe.
- App-lifecycle-scoped sync: `POST /api/time` runs ONLY while the app is
  open (foreground/process alive) — on app open, on WiFi join while the app
  is open (`NetworkCallback` registered on the app process), and via the
  keep-alive loop. NOT in the background, NOT at boot. Everything stops when
  the app is closed.
- Keep-alive loop (app-scoped, ~30s on WiFi): re-probe active IP; on failure
  re-run the parallel selection probe; on (re)found Jetson → `POST /api/time`
  + clear banner; on none → out-of-range banner. Paused off-WiFi. **This loop,
  the WiFi `NetworkCallback`, and every `POST /api/time` run ONLY while the
  application is open (foreground/process alive) — they are fully stopped
  (`stop()` cancels the coroutine loop + unregisters the callback) the moment
  the app is closed/backgrounded, and NEVER run at boot or in the background.**
- Remove `TimeSyncService` (foreground service + notification) + `BootReceiver`
  (+ `RECEIVE_BOOT_COMPLETED`). Drop `FOREGROUND_SERVICE`,
  `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`.
  Keep only `INTERNET` + `ACCESS_NETWORK_STATE`.
- Remove the Synchro tab (`TIME_SYNC` nav item + route + `TimeSyncScreen`).
  Surface "Jetson connecté / hors de portée" via the existing reachability
  banner (Dashboard + Live count). Relocate the `ProbeState` enum (currently in
  `TimeSyncViewModel`, imported by 6 ViewModels + 2 screens).
- New Settings bottom-nav tab (replacing Synchro): auto-select toggle + manual
  override IP field (typing flips `auto_select=false`; toggle re-enables auto)
  + the two candidate IPs as editable fields.
- `MainActivity`: drop the `POST_NOTIFICATIONS` runtime request + the
  `startForegroundService` LaunchedEffect (replaced by manager start/stop).
- Strings: prune now-unused `tab_time_sync` / notification / sync-log strings;
  add Settings labels (both `values/` and `values-fr/`).
- Unit-test the strict identify validation (extract a pure validator, no HTTP).

## Out of Scope

- Any changes under `app/` (Jetson Python). `jetson-validate` auto-detects an
  empty `git diff --name-only main...HEAD -- app/` and signals VALIDATED.
- SSID-based selection or `ACCESS_FINE_LOCATION`.
- Version validation (explicitly dropped per user).
- Background / boot time sync.
- Changing the read-only history/count ViewModels' fetch/state-machine logic
  beyond swapping the IP source and the probe/banner source.

## Architecture Decisions

- **ProbeState relocation**: move the `ProbeState` enum out of `TimeSyncViewModel`
  into `net/ProbeState.kt` (shared, no Android deps) so it survives the
  TimeSyncScreen deletion. All 6 history/count ViewModels + Dashboard/LiveCount
  screens import it from there.
- **Shared connection state**: a new singleton `JetsonConnectionManager`
  (`net/JetsonConnectionManager.kt`) owns the WiFi `NetworkCallback`, the ~30s
  keep-alive coroutine loop, the parallel selection probe, and `POST /api/time`.
  It exposes `probeState: StateFlow<ProbeState>` (the app-wide banner) and
  writes the resolved IP into `SettingsRepository.activeIp` via
  `setActiveIp(...)`. This replaces the per-ViewModel `probe()` methods and the
  foreground service. Rationale: one canonical reachability state, no
  background service, no new permissions.
- **activeIp ownership**: `SettingsRepository` owns `_activeIp:
  MutableStateFlow<String>` (default = hotspot default) and exposes
  `activeIp: StateFlow<String>`; `JetsonConnectionManager` is its only writer.
  ViewModels read `repo.activeIp` (drop the old `repo.jetsonIp` seeding).
  This honors the decision that the repository exposes `activeIp`.
- **ViewModel probeState delegation**: each ViewModel keeps its
  `probeState: StateFlow<ProbeState>` property but now returns
  `JetsonConnectionManager.probeState` directly (one-line delegate), so screens
  that read `vm.probeState` need no changes. The ViewModels' `probe()` methods
  and init-probe calls are removed.
- **Re-fetch on activeIp change**: ViewModels observe `repo.activeIp` and
  re-fetch when it changes (the manager resolves it shortly after app open).
  Initial activeIp is the hotspot default; a fetch may run with the default
  before resolution then re-fetch on the resolved IP — acceptable, since
  fetch failures already degrade gracefully.
- **App lifecycle scoping without a new dependency**: tie
  `JetsonConnectionManager.start/stop` to the `MainActivity` lifecycle via a
  `DisposableEffect` + `LifecycleEventObserver` (`ON_START`→start,
  `ON_STOP`→stop) in `AnimalCounterApp`, reusing the existing pattern from
  `LiveCountScreen`. No `lifecycle-process`/`ProcessLifecycleOwner` dependency
  is added (activity ON_STOP ≈ app backgrounded).
- **Strict identify, testable**: extract `internal fun isValidIdentifyBody(body:
  String): Boolean` (parses JSON, checks `service == "jetson-companion"` exact)
  so the unit test can validate it without HTTP. `identify()` returns
  `Outcome.Success` only when HTTP 200 AND `isValidIdentifyBody(body)`.
- **Settings screen placement (implementer's call → decided)**: a new
  bottom-nav **Settings tab replacing Synchro** (5 tabs: Dashboard / Live /
  History / Startups / Settings). Rationale: keeps IP editing one tap away and
  preserves the 5-tab layout users already know.
- **Candidate-IP exposure (implementer's call → decided)**: expose both
  candidate IPs (hotspot/lan) as editable fields in Settings (they are
  "configurable" per decision 3) alongside the auto-select toggle and the
  single manual-override IP field. Typing the manual IP flips
  `auto_select=false`; toggling re-enables auto.
- **Per-task compile check** is the Gradle build (NOT `python3 -m py_compile`):
  `cd android && export JAVA_HOME=$HOME/.local/jdk/jdk-17.0.19+10 && export
  ANDROID_HOME=$HOME/Android/Sdk && ./gradlew :app:assembleDebug --no-daemon
  --console=plain`. Commit per task. Toolchain already installed (AGENTS.md §9).

## Tasks

Tasks are ordered so the Gradle build is green after every commit. The
implement node does ONE task per fresh session, runs the Gradle build, and
commits.

- [x] Task 1: RELOCATE `ProbeState` — create
  `android/app/src/main/java/com/animalcounter/net/ProbeState.kt` containing the
  `enum class ProbeState { Idle, Probing, Reachable, OutOfRange }`. Remove the
  enum from `ui/timesync/TimeSyncViewModel.kt`. Update the `import` in all
  consumers to `com.animalcounter.net.ProbeState`: `DashboardViewModel`,
  `LiveCountViewModel`, `HistoryViewModel`, `StartupsViewModel`,
  `SessionsViewModel`, `SessionDetailViewModel`, `DashboardScreen`,
  `LiveCountScreen`, and `TimeSyncViewModel`. Build green.

- [x] Task 2: STRICT `identify()` — in
  `android/app/src/main/java/com/animalcounter/net/JetsonClient.kt`, extract
  `internal fun isValidIdentifyBody(body: String): Boolean` (parses JSON;
  returns true only when `json.optString("service") == "jetson-companion"`).
  Change `identify()` so the `code == 200` branch returns
  `SyncEvent.Outcome.Success` only when `isValidIdentifyBody(body)` is true,
  else a `Network`/failure outcome with the raw body. Fix the class docstring:
  the companion returns `{"service":"jetson-companion","version":"<v>"}` (not
  `animal-counter-companion`). Add unit tests in
  `android/app/src/test/java/com/animalcounter/net/JetsonClientParsingTest.kt`
  for `isValidIdentifyBody` (valid, wrong service, non-JSON, missing service).
  Run `./gradlew :app:testDebugUnitTest`. Build green.

- [x] Task 3: EXTEND `SettingsRepository` — in
  `android/app/src/main/java/com/animalcounter/data/SettingsRepository.kt`, add
  DataStore-backed flows + setters: `hotspotIp` (key `jetson_ip_hotspot`,
  default `192.168.100.1`), `lanIp` (key `jetson_ip_lan`, default
  `192.168.0.180`), `autoSelect` (key `auto_select`, Boolean, default `true`),
  and keep `jetsonIp`/`setJetsonIp` as the manual-override IP (key `jetson_ip`).
  Add `booleanPreferencesKey` import. Add `_activeIp:
  MutableStateFlow<String>(DEFAULT_HOTSPOT_IP)` + `activeIp: StateFlow<String>`
  + `suspend fun setActiveIp(ip: String)`. Keep `DEFAULT_JETSON_IP` constant for
  the manual default. Build green.

- [x] Task 4: CREATE `JetsonConnectionManager` — create
  `android/app/src/main/java/com/animalcounter/net/JetsonConnectionManager.kt`
  as a singleton `object`. It exposes `probeState: StateFlow<ProbeState>` and
  `activeIp` (delegated to `SettingsRepository`). Methods `start(context)` /
  `stop()`: register a `TRANSPORT_WIFI` `NetworkCallback` (onAvailable →
  rescan + POST time; onLost → out-of-range banner, pause keep-alive);
  `rescan()` runs a PARALLEL probe of both candidate IPs (or the manual IP when
  `autoSelect=false`) bound via `activeWifiNetwork(cm)`, ~1500ms timeout,
  `JetsonClient.identify(ip, network=...)`, picks the first strict-valid hit →
  `repo.setActiveIp(ip)` + `probeState=Reachable` + `POST /api/time`; none →
  `probeState=OutOfRange`. A ~30s keep-alive coroutine loop (only while on
  WiFi) re-probes the active IP; on failure calls `rescan()`; on found → POST
  time + Reachable; on none → OutOfRange. Uses `SettingsRepository(appContext)`
  for settings, `JetsonClient.postTime`/`identify`, `nowIsoForCompanion()`,
  and logs to `SyncLog`. Not wired to the lifecycle yet. Build green.

- [x] Task 5: WIRE manager to app lifecycle — in
  `android/app/src/main/java/com/animalcounter/ui/nav/AnimalCounterApp.kt`,
  remove the `LaunchedEffect(Unit) { ContextCompat.startForegroundService(...) }`
  block and the `TimeSyncService`/`Intent`/`ContextCompat` imports. Add a
  `DisposableEffect(lifecycleOwner)` with a `LifecycleEventObserver` that calls
  `JetsonConnectionManager.start(context)` on `ON_START` and
  `JetsonConnectionManager.stop()` on `ON_STOP` (reuse the pattern from
  `LiveCountScreen`'s polling `DisposableEffect`). Build green.

- [x] Task 6: CONVERT Dashboard + LiveCount ViewModels — in
  `DashboardViewModel.kt` and `LiveCountViewModel.kt`: replace the
  `repo.jetsonIp.collect { _ip.value = saved; if(!loaded){loaded=true;probe();refresh()} }`
  init with `repo.activeIp.collect { _ip.value = it; refresh()/load() }`
  (re-fetch on each activeIp change). Replace `_probeState`/`probeState` with a
  delegate to `JetsonConnectionManager.probeState` (`val probeState =
  JetsonConnectionManager.probeState`). Remove the `probe()` method, the
  `_probeState` MutableStateFlow, the `loaded` flag, and the now-unused
  `activeWifiNetwork`/`SyncEvent`/`identify` imports. Screens unchanged (they
  still read `vm.probeState`). Build green.

- [x] Task 7: CONVERT History + Startups + Sessions ViewModels — apply the
  same activeIp + delegated-probeState conversion to `HistoryViewModel.kt`,
  `StartupsViewModel.kt`, `SessionsViewModel.kt`: seed `_ip` from
  `repo.activeIp` (re-fetch on change), delegate `probeState` to
  `JetsonConnectionManager.probeState`, remove `probe()` + `_probeState` +
  `loaded` flag + unused imports. Build green.

- [x] Task 8: CONVERT SessionDetail + VideoDetail ViewModels — in
  `SessionDetailViewModel.kt`: same activeIp + delegated-probeState
  conversion (remove `probe()`, delegate `probeState`). In
  `VideoDetailViewModel.kt`: it has no `probeState`/`probe()`; replace
  `repo.jetsonIp.first()` (in `loadDetail`) and the `repo.jetsonIp.collect`
  init with `repo.activeIp` (collect into `_ip`; `loadDetail` uses
  `repo.activeIp.value`). Build green.

- [x] Task 9: CREATE Settings screen — create
  `android/app/src/main/java/com/animalcounter/ui/settings/SettingsScreen.kt`
  and `SettingsViewModel.kt`. The screen renders: an auto-select toggle
  (`autoSelect` from repo), a manual-override IP `OutlinedTextField` (enabled
  when `autoSelect=false`; typing flips `autoSelect=false` via
  `setAutoSelect(false)` + `setJetsonIp(value)`), and two candidate IP fields
  (`hotspotIp`, `lanIp`) persisted via `setHotspotIp`/`setLanIp`. Toggling
  auto-select back to true re-enables auto and triggers
  `JetsonConnectionManager.rescan()`; editing a candidate IP also triggers
  `rescan()`. Use existing Material 3 idioms (`OutlinedTextField`, `Switch`,
  `Scaffold` + `TopAppBar`) and `stringResource` for all labels. Build green.

- [x] Task 10: WIRE Settings tab + drop Synchro route — in
  `AnimalCounterApp.kt`: remove the `TIME_SYNC` `NavigationBarItem` and the
  `composable(Destinations.TIME_SYNC) { TimeSyncScreen() }` route + the
  `TimeSyncScreen` import. Add `SETTINGS = "settings"` to `Destinations`, a
  `NavigationBarItem` (Settings, `Icons.Filled.Settings`) and
  `composable(Destinations.SETTINGS) { SettingsScreen() }`. Remove the
  `Icons.Filled.Schedule` import. Build green (`TimeSyncScreen.kt` remains on
  disk, unreferenced — it compiles; deleted next task).

- [x] Task 11: DELETE dead files — delete
  `android/app/src/main/java/com/animalcounter/service/TimeSyncService.kt`,
  `receiver/BootReceiver.kt`,
  `ui/timesync/TimeSyncScreen.kt`, and
  `ui/timesync/TimeSyncViewModel.kt` (and the now-empty
  `service/`/`receiver/`/`ui/timesync/` package dirs if empty). Grep for any
  remaining references first; fix them. Build green.

- [x] Task 12: CLEAN manifest — in
  `android/app/src/main/AndroidManifest.xml`: remove the `<service
  android:name=".service.TimeSyncService" .../>` element, the `<receiver
  android:name=".receiver.BootReceiver" .../>` element, and the
  `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE`,
  `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS` `<uses-permission>`
  lines. Keep only `INTERNET` + `ACCESS_NETWORK_STATE`. Build green.

- [x] Task 13: CLEAN MainActivity — in
  `android/app/src/main/java/com/animalcounter/MainActivity.kt`: remove the
  `requestPostNotificationsIfNeeded()` call + method, the
  `requestNotificationPermission` `ActivityResultLauncher` field, and the
  `Manifest`/`Build`/`ActivityResultContracts` imports that become unused.
  Build green.

- [x] Task 14: STRINGS — in `android/app/src/main/res/values/strings.xml` and
  `values-fr/strings.xml`: add `tab_settings`, `settings_title`,
  `settings_auto_select`, `settings_manual_ip`, `settings_hotspot_ip`,
  `settings_lan_ip` (English + French). Grep the codebase for usages before
  removing; prune now-unused strings: `tab_time_sync`,
  `notification_channel_*`, `foreground_notification_*`, `time_sync_placeholder`,
  `sync_now`, `refresh`, `log_empty`, `type_probe`, `type_sync`, `outcome_*`
  (keep `jetson_connected`/`jetson_out_of_range`/`jetson_checking` — still used
  by banners; keep `jetson_ip_label` if reused by Settings, else replace with
  the new settings labels). Build green.

- [x] Task 15: FINAL build + APK — run the full Gradle build
  (`./gradlew :app:assembleDebug --no-daemon --console=plain`) and the unit
  tests (`./gradlew :app:testDebugUnitTest`). Confirm
  `android/app/build/outputs/apk/debug/app-debug.apk` is produced. Optionally
  copy it to the Desktop as `animal-counter-bl73-debug.apk` per the AGENTS.md §9
  convention (do NOT commit the APK or `local.properties`).

## Validation

- Per-task: `cd android && export JAVA_HOME=$HOME/.local/jdk/jdk-17.0.19+10
  && export ANDROID_HOME=$HOME/Android/Sdk && ./gradlew :app:assembleDebug
  --no-daemon --console=plain` (must succeed after every task commit).
- Unit tests: `./gradlew :app:testDebugUnitTest` (Task 2 adds
  `isValidIdentifyBody` cases; existing parsing tests must still pass).
- No `app/` diff: `git diff --name-only main...HEAD -- app/` is empty →
  `jetson-validate` auto-signals VALIDATED (no `scripts/validate_on_jetson.sh`
  run).
- Manual/functional (post-build, on-phone): with the phone on the Jetson
  hotspot, the Dashboard/Live reachability banner shows "Jetson connecté" and
  data loads without manually setting an IP; switching to the LAN WiFi
  re-selects `192.168.0.180` within ~30s; leaving WiFi shows "hors de portée";
  the Settings tab lets the operator toggle auto-select off and type a manual
  IP; the Synchro tab is gone; no foreground-service notification appears.

## Risks

- **Parallel-probe timing vs. first fetch**: ViewModels may fetch once with the
  default hotspot IP before the manager resolves `activeIp`, then re-fetch on
  the resolved IP. Mitigation: ViewModels re-fetch on every `activeIp` change;
  fetch failures already degrade to cached/out-of-range gracefully, so a
  transient wrong-IP fetch is invisible to the user.
- **`ProbeState` import breakage on deletion**: deleting `TimeSyncViewModel`
  would break 6+ importers. Mitigation: Task 1 relocates `ProbeState` first;
  Task 11 deletes the TimeSync files only after the route/import is removed
  (Task 10), so the build is green at every step.
- **Stale string references**: removing strings still referenced by code would
  break the build. Mitigation: Task 14 greps for each string's `R.string.<name>`
  usage before removing it.
- **`local.properties` / APK committed by mistake**: both are machine-local.
  Mitigation: Task 15 stages only source files; `local.properties` is already
  documented as never-committed in AGENTS.md §9.
- **Manual-override + keep-alive interaction**: when `autoSelect=false`, the
  manager must still probe the manual IP for reachability and POST time, not
  skip the loop. Mitigation: Task 4 specifies the manual-override path probes
  the single manual IP (no parallel selection) and still POSTs time on found.