# Plan: BL-65 — Android time-sync companion app

## Summary
A greenfield Kotlin 2.0 + Jetpack Compose + Material 3 Android app in a new
`android/` mono-repo folder (package `com.animalcounter`, launcher name
"Animal Counter") that POSTs the phone's current ISO8601 time + IANA
timezone to the Jetson companion (BL-64, `POST http://<jetson_ip>:8090/api/time`)
whenever the phone joins the Jetson WiFi hotspot — via a foreground service +
`ConnectivityManager.registerNetworkCallback(TRANSPORT_WIFI)` that fires with
no app open, re-registered on `BOOT_COMPLETED`. The app ships a polished 3-tab
hub (Time sync / Live count / Videos), multilingual EN + fr, dark theme forced
+ Material You dynamic color, an adaptive pig icon, DataStore-persisted Jetson
IP (default `192.168.100.1`), a foreground-only out-of-range banner driven by a
`GET /api/identify` reachability probe, and a bounded ring-buffer log exposed
as `StateFlow<List<SyncEvent>>`. Validation = `cd android && ./gradlew
assembleDebug` (build APK only; no device/Jetson round-trip).

## In Scope
- New `android/` Gradle project: AGP 8.7, Kotlin 2.0, minSdk 33,
  compileSdk/target 35, build-tools 34.0.0, JDK 17 (`~/jdk-17`=`JAVA_HOME`),
  Android SDK at `~/Android/Sdk` (`ANDROID_HOME`); `local.properties` pointing
  there, gitignored.
- Package `com.animalcounter`; launcher name "Animal Counter"; adaptive icon
  with a stylized pig motif.
- Theme: Material 3 dynamic color (Material You) + dark theme forced.
- Hub `MainActivity` with extensible 3-tab bottom-nav: 1) Time sync
  (`schedule`), 2) Live count (`visibility`), 3) Videos (`video_library`).
  Tabs 2 & 3 are enabled placeholder screens (localized "Coming soon" /
  "Bientôt disponible").
- Multilingual via `res/values/strings.xml` (EN fallback) +
  `res/values-fr/strings.xml` (FR); all user-visible text via
  `stringResource(R.string.*)`; structure ready for more `values-<lang>/`.
- Time sync screen: Jetson IP `OutlinedTextField` (default `192.168.100.1`,
  persisted via Jetpack DataStore Preferences), localized "Sync now" button
  (manual `POST /api/time`), localized "Refresh" button (reachability probe),
  prominent out-of-range banner (green "Jetson connecté" on success;
  amber/red "Jetson hors de portée" / "Jetson out of range" on
  timeout/refused/wrong IP) — foreground-only, scrollable status/log view.
- Reachability probe: `GET http://<jetson_ip>:8090/api/identify` with short
  timeout, on screen open and on manual refresh.
- Foreground service `TimeSyncService` (foregroundServiceType=`dataSync`) with
  a persistent notification; registers
  `ConnectivityManager.registerNetworkCallback(NetworkRequest TRANSPORT_WIFI)`
  so the time push fires without the app open.
- `BootReceiver` on `RECEIVE_BOOT_COMPLETED` starts the foreground service
  (re-register on boot).
- Permissions: `INTERNET`, `ACCESS_NETWORK_STATE`,
  `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE`,
  `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS`. No location permission.
- HTTP via `HttpURLConnection` (stdlib, no extra dep). Body
  `{"time":"<Instant.now() ISO8601>","tz":"<ZoneId.systemDefault().id IANA>"}`.
  Companion returns 200 / 400 / 500 — all handled + logged. Also
  `GET /api/identify` for the probe.
- Shared in-memory log: process-wide bounded ring buffer of `SyncEvent` as
  `StateFlow<List<SyncEvent>>` (consumed by the log view + banner).
- `.gitignore`: add `android/local.properties` (gitignored).

## Out of Scope
- BL-66 (live count) and BL-67 (video browser) beyond the placeholder screens.
- Any change to the Jetson companion (BL-64) — contract is fixed:
  `GET /api/identify` → `{"service":"jetson-companion","version":"1"}`;
  `POST /api/time` body `{"time":"<ISO8601>","tz":"<IANA>"}` → 200/400/500.
- Location permission / geolocation; auth/token (companion v1 is open on the
  closed HotSpot LAN).
- Re-enabling NTP or changing `timedatectl` behavior on the Jetson.
- Running the app on a device/emulator or any on-device Jetson round-trip
  (build-only validation).

## Architecture Decisions
- **Greenfield Gradle scaffold** — `android/` does not exist yet; build the
  full project (settings, version catalog, `build.gradle.kts`, manifest,
  Gradle wrapper) from scratch. Use the version-catalog
  (`gradle/libs.versions.toml`) pattern so dependency versions are centralized.
- **Package `com.animalcounter`** — neutral, not tied to a person's name.
- **HttpURLConnection (stdlib)** over OkHttp — zero extra deps, matches the
  "minimal" constraint and the companion's stdlib-only philosophy. Both the
  `POST /api/time` push and the `GET /api/identify` probe run on IO
  dispatchers; results map to a sealed `SyncResult` (Success/BadRequest/
  ServerError/Network) logged to the ring buffer.
- **DataStore Preferences** for IP persistence (modern, Compose-friendly)
  over SharedPreferences. `JetsonIpStore` exposes a `Flow<String>` + write
  suspend; default `192.168.100.1` when unset.
- **Foreground service `dataSync` + BootReceiver** for Android 14+ robustness
  over background-callback-only. `TimeSyncService` holds a persistent
  notification, owns the `NetworkCallback` lifecycle, and performs the push on
  `onAvailable`/`onCapabilitiesChanged`. `BootReceiver` (with
  `RECEIVE_BOOT_COMPLETED`) re-starts the service after reboot so hotspot
  joins pre-app-launch still sync.
- **Dark theme forced + Material You dynamic color** — `Theme.kt` sets
  `darkColorScheme` built from `dynamicDarkColorScheme(context)` when
  available (API 31+) else a fixed dark fallback palette; the manifest theme
  has no `dayNight` variant so dark is always applied.
- **Multilingual via `values-<lang>/`** — Android auto-selects the matching
  locale at runtime; no manual locale switching. EN fallback in `values/`,
  FR in `values-fr/`. Adding a locale = adding one `values-<lang>/strings.xml`.
- **Bounded ring buffer of `SyncEvent` as `StateFlow<List<SyncEvent>>`** —
  single process-wide singleton (`SyncLog`) cap ~200 entries; consumed by the
  log view (reverse-chronological) and feeds banner state. `SyncEvent`
  captures timestamp, type (probe/sync), outcome, and a raw detail string (UI
  localizes labels).
- **Reachability probe is foreground-only** — the banner reflects the last
  `GET /api/identify` result; the background push (NetworkCallback) fires
  regardless of app-open state. The probe uses a short connect/read timeout
  (~2s) to fail fast when off-hotspot.
- **Adaptive pig icon** — `mipmap-anydpi-v26/ic_launcher.xml` (+
  `ic_launcher_round.xml`) referencing a vector `ic_launcher_foreground.xml`
  (stylized pig) over a `ic_launcher_background.xml` color; minSdk 33 means
  adaptive icons are always supported, so no legacy PNG density set is needed.

## Tasks
- [x] Task 1: CREATE `android/settings.gradle.kts` + `android/gradle.properties` + `android/gradle/libs.versions.toml` — root project "AnimalCounter", `pluginManagement`/`dependencyResolutionManagement` repos (google, mavenCentral), version catalog pinning AGP 8.7.x, Kotlin 2.0.x, Compose BOM, androidx core/kotlinx-coroutines/datastore-preferences; `gradle.properties` sets `org.gradle.jvmargs`, `android.useAndroidX=true`, `kotlin.code.style=official`, non-transitive R classes.
- [x] Task 2: CREATE `android/build.gradle.kts` — root module applying `com.android.application` + `org.jetbrains.kotlin.android` + `org.jetbrains.kotlin.plugin.compose` via the version catalog; `android {}` block: `compileSdk=35`, `defaultConfig` (`applicationId="com.animalcounter"`, `minSdk=33`, `targetSdk=35`, `versionCode=1`, `versionName="1.0"`), `buildFeatures { compose = true }`, `compileOptions`/`kotlinOptions` JVM 17, `buildToolsVersion="34.0.0"`; dependencies from catalog (androidx core-ktx, lifecycle, activity-compose, compose-bom, material3, navigation-compose, datastore-preferences, kotlinx-coroutines).
- [x] Task 3: CREATE the Gradle wrapper — `android/gradle/wrapper/gradle-wrapper.properties` (Gradle 8.9 distribution URL, compatible with AGP 8.7 + JDK 17), `android/gradle/wrapper/gradle-wrapper.jar`, `android/gradlew`, `android/gradlew.bat` (executable `gradlew`). Committed so `./gradlew assembleDebug` works without a system Gradle.
- [x] Task 4: CREATE `android/local.properties` (gitignored) with `sdk.dir` pointing at the absolute `~/Android/Sdk` path AND append `android/local.properties` to the repo `.gitignore` — keeps the SDK path out of git per repo convention.
- [x] Task 5: CREATE `android/app/src/main/AndroidManifest.xml` — `<uses-permission>` for INTERNET, ACCESS_NETWORK_STATE, RECEIVE_BOOT_COMPLETED, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS; `<application>` with `android:label="@string/app_name"`, `android:icon`/`roundIcon`="@mipmap/ic_launcher"`, theme `@style/Theme.AnimalCounter`; `MainActivity` (exported, LAUNCHER); `TimeSyncService` (`android:foregroundServiceType="dataSync"`, exported=false); `BootReceiver` (`<receiver android:name=".receiver.BootReceiver" exported=true` with `<action android:name="android.intent.action.BOOT_COMPLETED"/>`).
- [x] Task 6: CREATE `android/app/src/main/res/values/strings.xml` — English fallback: `app_name`="Animal Counter"; tab labels (`tab_time_sync`="Time sync", `tab_live_count`="Live count", `tab_videos`="Videos"); time-sync screen labels (`jetson_ip_label`, `sync_now`, `refresh`, `jetson_connected`="Jetson connected", `jetson_out_of_range`="Jetson out of range"); placeholder `coming_soon`="Coming soon"; notification channel + foreground notification titles/texts; log outcome labels.
- [x] Task 7: CREATE `android/app/src/main/res/values-fr/strings.xml` — French translations mirroring every key in `values/strings.xml`: `app_name`="Animal Counter", `tab_time_sync`="Synchronisation", `tab_live_count`="Comptage en direct", `tab_videos`="Vidéos", `sync_now`="Synchroniser", `refresh`="Actualiser", `jetson_connected`="Jetson connecté", `jetson_out_of_range`="Jetson hors de portée", `coming_soon`="Bientôt disponible", etc.
- [x] Task 8: CREATE `android/app/src/main/res/values/themes.xml` + `res/values/colors.xml` — `Theme.AnimalCounter` parent that forces dark (`<item name="android:windowBackground">` dark) and sets Material 3 attributes consumed by the Compose `Theme.kt`; `colors.xml` holds the icon background color + any non-dynamic fallback swatches.
- [x] Task 9: CREATE the adaptive icon — `res/mipmap-anydpi-v26/ic_launcher.xml` + `ic_launcher_round.xml` (`<adaptive-icon>` with `<background android:drawable="@color/ic_launcher_background"/>` + `<foreground android:drawable="@drawable/ic_launcher_foreground"/>`) and `res/drawable/ic_launcher_foreground.xml` (vector drawable: stylized pig motif on the 108x108dp safe-zone), plus `res/values/ic_launcher_background.xml` (color, e.g. a Material 3 amber/teal).
- [x] Task 10: CREATE `android/app/src/main/java/com/animalcounter/MainActivity.kt` — `ComponentActivity` `setContent { AnimalCounterApp() }`, dark theme forced via the Compose `Theme`, `enableEdgeToEdge()`; requests the runtime `POST_NOTIFICATIONS` permission on first launch; minimal — the hub scaffold lives in `ui/nav/AnimalCounterApp.kt`.
- [x] Task 11: CREATE `android/app/src/main/java/com/animalcounter/ui/theme/Theme.kt` + `Color.kt` + `Type.kt` — `AnimalCounterTheme` composable using `dynamicDarkColorScheme(LocalContext.current)` (API 31+) else a fixed dark fallback; always-dark. `Color.kt`/`Type.kt` hold the fallback palette + Material 3 typography.
- [x] Task 12: CREATE `android/app/src/main/java/com/animalcounter/ui/nav/AnimalCounterApp.kt` — `Scaffold` with a `NavigationBar` (3 items: Time sync `schedule`, Live count `visibility`, Videos `video_library` from Material icons) + `NavHost` switching between `TimeSyncScreen` and the `PlaceholderScreen` for tabs 2 & 3. Extensible: adding a tab = adding a `NavigationBarItem` + a composable destination.
- [x] Task 13: CREATE `android/app/src/main/java/com/animalcounter/ui/placeholder/PlaceholderScreen.kt` — `PlaceholderScreen(label: String)` showing a centered localized "Coming soon / Bientôt disponible" message; used by tabs 2 & 3.
- [x] Task 14: CREATE `android/app/src/main/java/com/animalcounter/data/SyncEvent.kt` + `SyncLog.kt` — `data class SyncEvent(val timestamp: Instant, val type: Type, val outcome: Outcome, val detail: String)` (sealed `Type` { Probe, Sync }; sealed `Outcome` { Success, BadRequest, ServerError, Network }); `object SyncLog` holds a process-wide bounded ring buffer (~200) exposed as `StateFlow<List<SyncEvent>>` with `add(event)` and `events` accessors (thread-safe via `MutableStateFlow` + `update`).
- [ ] Task 15: CREATE `android/app/src/main/java/com/animalcounter/data/JetsonIpStore.kt` — DataStore Preferences wrapper: `jetsonIpFlow: Flow<String>` (default `192.168.100.1`), `suspend fun setJetsonIp(ip: String)`. DataStore created via a top-level `preferencesDataStore` delegate.
- [ ] Task 16: CREATE `android/app/src/main/java/com/animalcounter/data/TimeSyncRepository.kt` — `suspend fun pushTime(jetsonIp: String): SyncResult` (builds `{"time":"<Instant.now()>","tz":"<ZoneId.systemDefault().id>"}`, `HttpURLConnection` POST to `http://<ip>:8090/api/time`, maps 200→Success, 400→BadRequest, 500→ServerError, exception→Network; logs a `SyncEvent(Sync)` to `SyncLog`) and `suspend fun probe(jetsonIp: String): Boolean` (GET `http://<ip>:8090/api/identify` with ~2s connect+read timeout, true on 200, false otherwise; logs a `SyncEvent(Probe)`). All IO on `Dispatchers.IO`.
- [ ] Task 17: CREATE `android/app/src/main/java/com/animalcounter/service/TimeSyncService.kt` — `Service` subclass; `onCreate` builds the notification channel + a persistent foreground notification (`foregroundServiceType=dataSync`, low-importance, ongoing); `onStartCommand` calls `startForeground(...)` then registers `ConnectivityManager.registerNetworkCallback(NetworkRequest(TRANSPORT_WIFI), callback)`; the callback's `onAvailable`/`onCapabilitiesChanged` triggers a coroutine that reads the latest IP from `JetsonIpStore` and calls `TimeSyncRepository.pushTime` — pushing without the app open; gated by an in-flight `Mutex`/debounce so a join yields one push, not a burst; `onDestroy` unregisters the callback + cancels the service scope.
- [ ] Task 18: CREATE `android/app/src/main/java/com/animalcounter/receiver/BootReceiver.kt` — `BroadcastReceiver` on `BOOT_COMPLETED` that `ContextCompat.startForegroundService(context, Intent(context, TimeSyncService::class.java))` (guards on `intent.action == BOOT_COMPLETED`), so the NetworkCallback is re-registered after reboot.
- [ ] Task 19: CREATE `android/app/src/main/java/com/animalcounter/ui/timesync/TimeSyncScreen.kt` — Compose screen: collects `JetsonIpStore.jetsonIpFlow`; `OutlinedTextField` for the IP (commits to DataStore); out-of-range banner (`Surface` green when last probe ok, amber/red when failed, hidden while probing); "Sync now" `Button` calls `TimeSyncRepository.pushTime`; "Refresh" `OutlinedButton` calls `probe`; runs the reachability probe on screen open (`LaunchedEffect`) and on Refresh; scrollable `LazyColumn` log view consuming `SyncLog.events` (reverse-chronological, localized outcome labels via `stringResource`). All user-visible text via `stringResource(R.string.*)`.
- [ ] Task 20: VERIFY — `cd android && ./gradlew assembleDebug` (with `JAVA_HOME=~/jdk-17`, `ANDROID_HOME=~/Android/Sdk`) builds the debug APK (`android/app/build/outputs/apk/debug/app-debug.apk`); confirm the build is green and no hardcoded user-visible strings remain (all via `stringResource`). No device/Jetson round-trip.

## Validation
- `cd android && ./gradlew assembleDebug` builds the debug APK
  (`android/app/build/outputs/apk/debug/app-debug.apk`) with `JAVA_HOME=~/jdk-17`
  and `ANDROID_HOME=~/Android/Sdk`. Build must be green.
- Confirm all user-visible strings resolve through `stringResource(R.string.*)`
  in `TimeSyncScreen`, `PlaceholderScreen`, `AnimalCounterApp` (no hardcoded
  EN/FR text in Kotlin).
- Confirm `values/strings.xml` and `values-fr/strings.xml` define the same key
  set (locale fallback works).
- No Jetson / device / emulator round-trip required (build-only gate).

## Risks
- **Gradle wrapper jar provenance** — the wrapper jar is a binary; if it
  cannot be sourced from a template, the build fails. Mitigation: use the
  canonical Gradle 8.9 `gradle-wrapper.jar` (committed); `assembleDebug` is the
  gate that catches a broken wrapper.
- **Dynamic color on the forced-dark path** — `dynamicDarkColorScheme`
  requires API 31+; minSdk 33 satisfies this, but a fixed dark fallback palette
  is still provided in `Color.kt` for safety/preview.
- **NetworkCallback double-fire / rapid re-push** — hotspot joins can trigger
  multiple `onAvailable`/`onCapabilitiesChanged` callbacks. Mitigation: gate
  pushes with a short in-flight `Mutex`/debounce in the service so a join
  yields one `POST /api/time`, not a burst.
- **Companion ISO8601 parsing** — the companion uses Python
  `datetime.fromisoformat`; `Instant.now().toString()` yields
  `2025-07-15T14:30:00.123Z`, which `fromisoformat` accepts in Python 3.11+.
  If the Jetson runs an older Python, the `Z`/fractional seconds may need
  handling — but that is a BL-64 companion concern, explicitly out of scope
  here; the app emits a standard `Instant.toString()`.
- **POST_NOTIFICATIONS runtime grant (API 33+)** — the foreground notification
  requires the runtime `POST_NOTIFICATIONS` permission on Android 13+. The
  app requests it at first launch in `MainActivity` so the persistent
  notification shows; if denied, the service still runs but the notification
  is suppressed (Android 14+ may then block the FGS type). The build still
  succeeds regardless.