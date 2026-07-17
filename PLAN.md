# Plan: BL-65 — Android time-sync companion app

## Summary
Greenfield Kotlin 2.0 + Jetpack Compose + Material 3 Android app under `android/` (`com.animalcounter`, launcher "Animal Counter") that POSTs the phone's current ISO8601 time + IANA timezone to the Jetson companion (BL-64, `POST http://<jetson_ip>:8090/api/time`, default `192.168.100.1`) whenever the phone joins the Jetson WiFi hotspot. A `dataSync` foreground service + boot receiver push without the app open; a 3-tab hub UI (Time sync live, Live count + Videos as "Bientôt disponible" placeholders) is the extensible shell for BL-66/BL-67.

## In Scope
- Gradle project: AGP 8.7, Kotlin 2.0, Compose BOM + Material 3, minSdk 33 / compileSdk 35 / targetSdk 35, build-tools 34.0.0.
- `local.properties` → `sdk.dir=~/Android/Sdk` (gitignored, generated).
- HTTP via stdlib `HttpURLConnection` only (no OkHttp). `POST /api/time` body `{"time":"<Instant.now() ISO8601>","tz":"<ZoneId.systemDefault().id IANA>"}`; `GET /api/identify` connectivity probe.
- Hub `MainActivity` + 3-tab `NavigationBar`: Time sync (`schedule`), Live count (`visibility`), Videos (`video_library`). Tabs 2 & 3 enabled "Bientôt disponible" placeholders.
- **Out-of-range HotSpot status**: when the app is open and the phone is NOT connected to the Jetson hotspot, the UI shows a clear message that the companion services are unavailable while out of HotSpot range (driven by the same `NetworkCallback` `onAvailable`/`onLost` state the service already tracks).
- **Localization (FR + EN, phone default)**: all user-facing strings live in `res/values/strings.xml` (English — default/fallback) and `res/values-fr/strings.xml` (French); the OS picks the file matching the phone's default locale automatically. No hard-coded user-facing strings in Kotlin/composables — everything goes through `stringResource(...)`. No extra i18n library.
- Time sync screen: Jetson IP `OutlinedTextField` (default `192.168.100.1`, persisted via Jetpack DataStore Preferences), "Sync now" test button, scrollable status/log view.
- Foreground service `TimeSyncService` (`foregroundServiceType=dataSync`, persistent notification) registering `ConnectivityManager.registerNetworkCallback(NetworkRequest TRANSPORT_WIFI)` so push works with app closed.
- `BootReceiver` on `BOOT_COMPLETED` starts the foreground service (re-register; no direct push at boot).
- Shared in-memory bounded ring buffer of `SyncEvent` exposed as `StateFlow<List<SyncEvent>>`, shared by foreground service + "Sync now" button + UI screen.
- App identity: launcher "Animal Counter"; adaptive icon with stylized pig motif (`mipmap-anydpi-v33` adaptive XML + legacy `mipmap` PNG fallbacks); Material 3 dynamic color (Material You) with **dark theme forced**.
- Permissions: `INTERNET`, `ACCESS_NETWORK_STATE`, `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS`. No location permission.
- Validation = `cd android && ./gradlew assembleDebug` (JDK 17 `~/jdk-17` = JAVA_HOME, Android SDK `~/Android/Sdk` = ANDROID_HOME).

## Out of Scope
- BL-66 live count display and BL-67 video browser/download (placeholder tabs only).
- Jetson/video validation, real-device testing, Python validation, running the companion.

## Architecture Decisions
- **HttpURLConnection (stdlib)** — no extra dependency; keeps the build self-contained for the offline field workflow.
- **Foreground service (not bare NetworkCallback)** — Android 14+ robustness; `BOOT_COMPLETED` only re-starts the service, no direct push at boot.
- **Trust-on-200** — isolated hotspot, no location permission needed.
- **Bounded ring buffer `SyncEvent` `StateFlow`** — single process-wide shared log source (service + button + UI all observe one stream).
- **DataStore Preferences** (not SharedPreferences) for IP persistence — Coroutines-friendly, lifecycle-safe.
- **Dynamic color (Material You) + dark theme forced** via `values-night`/theme override.
- **Repo conventions** — per AGENTS.md, validation is the project's actual build (`gradlew assembleDebug`), NOT `python3 -m py_compile` / `bun run` (this is a Kotlin module, not the Python app).

## Tasks

### Project scaffold
- [x] Task 1: CREATE `android/settings.gradle.kts` — root settings: pluginManagement + dependencyResolutionManagement (Google + Maven Central + Gradle Plugin Portal), `include(":app")`, project name "Animal Counter".
- [x] Task 2: CREATE `android/build.gradle.kts` (root) — declare AGP 8.7 + Kotlin 2.0 plugins with `apply false`; repos in settings.
- [x] Task 3: CREATE `android/gradle.properties` — `org.gradle.jvmargs`, `android.useAndroidX=true`, `kotlin.code.style=official`, `android.nonTransitiveRClass=true`, `org.gradle.caching=true`.
- [x] Task 4: CREATE `android/gradle/wrapper/gradle-wrapper.properties` — Gradle 8.10.2 (compatible with AGP 8.7), `distributionUrl` pointing at gradle-8.10.2-bin.zip.
- [x] Task 5: CREATE `android/gradlew` + `android/gradlew.bat` — standard wrapper scripts (executable bit on `gradlew`).
- [x] Task 6: CREATE `android/local.properties` — `sdk.dir=~/Android/Sdk` (expand `~` to absolute `/home/<user>/Android/Sdk`); gitignored.
- [x] Task 7: UPDATE `.gitignore` (repo root) — append `android/local.properties`, `android/.gradle/`, `android/build/`, `android/app/build/`, `android/.idea/`, `*.iml`, `local.properties`, `.cxx/` so the Android build artifacts stay out of git.

### App module build config
- [x] Task 8: CREATE `android/app/build.gradle.kts` — `com.android.application` + `org.jetbrains.kotlin.android` + `org.jetbrains.kotlin.plugin.compose` plugins; `namespace="com.animalcounter"`, `compileSdk=35`, `buildToolsVersion="34.0.0"`; `defaultConfig` applicationId `com.animalcounter`, minSdk 33, targetSdk 35, versionCode 1/versionName "1.0"; buildTypes release minify false; `compileOptions` Java 17; `kotlinOptions jvmTarget=17`; Compose `buildFeatures { compose = true }` + Compose compiler; Compose BOM + Material3 + activity-compose + lifecycle-viewmodel-compose + datastore-preferences + coroutines deps; `packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }`.
- [ ] Task 9: CREATE `android/app/proguard-rules.pro` — empty/default rules (release minify disabled; keep stub for future).

### Manifest + permissions
- [x] Task 10: CREATE `android/app/src/main/AndroidManifest.xml` — package-less manifest (namespace in gradle); `<uses-permission>` for INTERNET, ACCESS_NETWORK_STATE, RECEIVE_BOOT_COMPLETED, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS; `<application>` with MainActivity (exported, LAUNCHER), TimeSyncService (`android:foregroundServiceType="dataSync"`, exported=false), BootReceiver (`BOOT_COMPLETED` intent-filter); `android:theme` pointing at the Material3 theme; `android:label="@string/app_name"`; adaptive icon refs (`android:icon`/`android:roundIcon`).

### Data layer (shared state + persistence)
- [x] Task 11: CREATE `android/app/src/main/java/com/animalcounter/data/SyncEvent.kt` — sealed/immutable data class `SyncEvent(timestamp: Instant, type: SyncType, status: SyncStatus, message: String?)` with enum-ish `SyncType` (MANUAL, WIFI_JOIN, IDENTIFY, BOOT) and `SyncStatus` (INFO, SUCCESS, ERROR) — the unit of the shared log.
- [x] Task 12: CREATE `android/app/src/main/java/com/animalcounter/data/SyncLog.kt` — object (process-wide singleton) holding a bounded ring buffer (cap ~200) of `SyncEvent` exposed as `StateFlow<List<SyncEvent>>` via `MutableStateFlow` + `_events.update { ... }` (dropOldest on overflow); `append(event)` + `clear()` API; cold-start empty list. Also exposes a `hotspotConnected: StateFlow<Boolean>` (default `false`) with `setConnected(connected)` updated by the service's NetworkCallback — this is the shared connectivity state the UI observes to show the out-of-range message. This is the shared log + connectivity state for service + button + UI.
- [x] Task 13: CREATE `android/app/src/main/java/com/animalcounter/data/SettingsRepository.kt` — wraps `DataStore<Preferences>` (Context.dataStore via `preferencesDataStore` delegate); suspend `getJetsonIp(): Flow<String>` (default `"192.168.100.1"` when unset) + `setJetsonIp(ip)`. Keys defined locally.

### Network client
- [ ] Task 14: CREATE `android/app/src/main/java/com/animalcounter/net/JetsonClient.kt` — suspend funcs over `HttpURLConnection` (run on `Dispatchers.IO`): `identify(ip): IdentifyResult` (`GET /api/identify`, parse `{"service","version"}`), `postTime(ip, timeIso: String, tz: String): PostResult` (`POST /api/time`, body `{"time":"...","tz":"..."}`, `Content-Type: application/json`, read status code 200/400/500 + body). Returns sealed result types capturing code + body + error. JSON parsed with `org.json` (stdlib on Android) — no extra dep.

### Foreground service + boot receiver
- [ ] Task 15: CREATE `android/app/src/main/java/com/animalcounter/service/TimeSyncService.kt` — `Service` subclass; `onStartCommand` builds + starts a `dataSync` foreground notification (NotificationCompat, channel `time_sync`, low/importance), then registers `ConnectivityManager.registerNetworkCallback(NetworkRequest.Builder().addTransportType(TRANSPORT_WIFI).build(), networkCallback)`; `onAvailable` (hotspot join) sets `SyncLog.setConnected(true)`, logs INFO, and triggers an IO coroutine that reads current IP from `SettingsRepository`, calls `JetsonClient.postTime(ip, Instant.now().toString(), ZoneId.systemDefault().id)`, appends `SyncEvent` to `SyncLog`; `onLost` sets `SyncLog.setConnected(false)` and logs INFO (this drives the UI out-of-range message). `onDestroy`/`onTaskRemoved` unregister callback + `setConnected(false)`. Foreground service start guard (try `startForeground` on Android 14+ restrictions). Returns `START_STICKY`.
- [ ] Task 16: CREATE `android/app/src/main/java/com/animalcounter/receiver/BootReceiver.kt` — `BroadcastReceiver` for `BOOT_COMPLETED`; in `onReceive` start `TimeSyncService` via `ContextCompat.startForegroundService(context, Intent(...))` (no direct time push at boot; service re-registers its own NetworkCallback).

### UI — theme + app shell
- [x] Task 17: CREATE `android/app/src/main/java/com/animalcounter/ui/theme/Color.kt`, `Theme.kt`, `Type.kt` — Material 3 color schemes; `Theme.kt` uses `dynamicLightColorScheme`/`dynamicDarkColorScheme` when `Build.VERSION.SDK_INT >= S` else fallback schemes, with **dark theme forced** (`darkTheme = true`, `dynamicColor = true`) in the `AnimalCounterTheme` composable; Typography defaults.

### UI — hub + screens
- [x] Task 18: CREATE `android/app/src/main/java/com/animalcounter/MainActivity.kt` — `ComponentActivity`; `setContent { AnimalCounterTheme { AnimalCounterApp() } }`; enables edge-to-edge; requests `POST_NOTIFICATIONS` runtime permission on launch (Android 13+); starts `TimeSyncService` via `ContextCompat.startForegroundService` on create (so push works even before first boot).
- [x] Task 19: CREATE `android/app/src/main/java/com/animalcounter/ui/AnimalCounterApp.kt` — root composable: `Scaffold` with `NavigationBar` (3 items: Time sync `schedule`, Live count `visibility`, Videos `video_library`, each with a localized label via `stringResource`) + a `when (currentTab)` body routing to `TimeSyncScreen` / `PlaceholderScreen`/`PlaceholderScreen`. Icons from `androidx.compose.material:material-icons-extended` (or core `Icons.Default.*` if available — prefer core to avoid the extended icon module; use `Icons.Filled.*` mapping). Tab state in a simple `rememberSaveable`. No hard-coded user-facing strings.
- [x] Task 20: CREATE `android/app/src/main/java/com/animalcounter/ui/PlaceholderScreen.kt` — composable taking a title; centered Material 3 placeholder with the localized "coming soon" string (`stringResource(R.string.coming_soon)`) + a muted `Text` + an icon, polished Material styling. No hard-coded user-facing strings.
- [ ] Task 21: CREATE `android/app/src/main/java/com/animalcounter/ui/TimeSyncScreen.kt` — `ViewModel`-backed composable (lifecycle-viewmodel-compose): collects IP from `SettingsRepository` into an `OutlinedTextField` (default `192.168.100.1`), persists on change (debounced); "Sync now" `Button` (label via `stringResource`) launches an IO coroutine calling `JetsonClient.postTime(ip, Instant.now().toString(), ZoneId.systemDefault().id)` + appends a `SyncEvent`; collects `SyncLog.hotspotConnected` and — when `false` — shows a prominent Material 3 status banner/message (localized via `stringResource(R.string.hotspot_out_of_range)`, error-container coloring + `Icons.Filled.WifiOff`), and when `true` shows a connected indicator (`stringResource(R.string.hotspot_connected)`); scrollable `LazyColumn` observing `SyncLog.events` (newest-bottom, auto-scroll) rendering each `SyncEvent` with timestamp + type + status color. State + side-effects via `LaunchedEffect`/`collectAsState`. No hard-coded user-facing strings.

### Resources — strings, themes, colors
- [x] Task 22: CREATE `android/app/src/main/res/values/strings.xml` — **English (default/fallback)** user-facing strings: `app_name="Animal Counter"`, `notification_channel_time_sync`, `notification_title_time_sync` ("Time sync"), `notification_text_time_sync`, tab labels ("Time sync", "Count", "Videos"), "Coming soon" placeholder, "Sync now", IP field label/hint, out-of-range message ("Out of HotSpot range — services unavailable"), connected message ("Connected to HotSpot"). All UI text referenced via `stringResource(R.string.*)` — no hard-coded strings in composables.
- [x] Task 22b: CREATE `android/app/src/main/res/values-fr/strings.xml` — **French** translations of every key from Task 22: `app_name="Animal Counter"`, `notification_title_time_sync="Synchronisation horaire"`, tab labels ("Synchronisation", "Compteur", "Vidéos"), "Bientôt disponible", "Synchroniser maintenant", out-of-range message "Hors de portée du HotSpot — services indisponibles", connected message "Connecté au HotSpot", etc. Android automatically selects `values-fr/` when the phone's default locale is French, falling back to `values/` (English) otherwise.
- [x] Task 23: CREATE `android/app/src/main/res/values/themes.xml` + `android/app/src/main/res/values-night/themes.xml` — base Material 3 theme (`Theme.Material3.DayNight.NoActionBar` or app-custom `AnimalCounter` parent) referencing the Compose theme; `values-night` forces dark to satisfy "dark theme forced". Add `res/values/colors.xml` if a non-dynamic fallback palette is referenced.
- [ ] Task 24: CREATE `android/app/src/main/res/xml/backup_rules.xml` + `android/app/src/main/res/xml/data_extraction_rules.xml` — empty/allow-all backup rules referenced by manifest (Android 12+ backup attributes), to avoid lint errors.

### App icon (adaptive pig)
- [x] Task 25: CREATE `android/app/src/main/res/drawable/ic_launcher_foreground.xml` — vector drawable: stylized pig motif (simple body + ears + snout) in a single-tone foreground suitable for adaptive masking.
- [x] Task 26: CREATE `android/app/src/main/res/drawable/ic_launcher_background.xml` (or `res/values/colors.xml` `ic_launcher_background` color) — solid background for the adaptive icon.
- [x] Task 27: CREATE `android/app/src/main/res/mipmap-anydpi-v33/ic_launcher.xml` + `ic_launcher_round.xml` — `<adaptive-icon>` referencing `ic_launcher_foreground` + background; minSdk 33 means adaptive XML is the primary form.
- [ ] Task 28: CREATE legacy `mipmap-*` PNG fallbacks — generate placeholder launcher PNGs in `mipmap-mdpi/hdpi/xhdpi/xxhdpi/ic_launcher.png` + `ic_launcher_round.png` (simple solid-color squares; adaptive XML is primary on minSdk 33). If generating binary PNGs is impractical, provide a `tools:`-scoped fallback or rely on the adaptive XML + a `mipmap` color fallback documented in the task; the build must still `assembleDebug` without a missing-resource error.

## Validation
- `cd android && ./gradlew assembleDebug` builds the debug APK (`app/build/outputs/apk/debug/app-debug.apk`).
- Confirm the APK packages `com.animalcounter` and that `aapt dump badging` shows launcher name "Animal Counter" + the three declared permissions + the foreground service + boot receiver (manual spot-check, optional).
- No Jetson, device, or video validation for this task — build success is the gate.

## Risks
- **Gradle/AGP/Kotlin/Compose-BOM version interplay**: AGP 8.7 needs Gradle 8.9+; Kotlin 2.0 needs the Compose compiler Gradle plugin (`org.jetbrains.kotlin.plugin.compose`), not the legacy `composeOptions.kotlinCompilerExtensionVersion`. Picking a compatible Compose BOM (e.g. 2024.09.x) is required for the build to pass.
- **Adaptive-icon PNG fallbacks** under minSdk 33: the `anydpi-v33` XML covers the target device, but lint/aapt may still require a legacy `mipmap` entry. A minimal fallback (color or simple vector-backed PNG) avoids `aapt`/lint failure.
- **Android 14+ foreground service start restrictions**: `startForeground` must be called promptly after `startForegroundService`; the service must declare `dataSync` type both in manifest (`android:foregroundServiceType`) and at runtime (`ServiceCompat.startForeground(..., FOREGROUND_SERVICE_TYPE_DATA_SYNC)`).
- **`HttpURLConnection` cleartext**: posting to `http://` (not https) needs `android:usesCleartextTraffic="true"` (or a network-security config) for the Jetson HTTP endpoint — must be added to the manifest or the POST will be blocked on Android 9+.
- **Coroutines in a `Service`**: needs a `CoroutineScope` tied to `onDestroy`; avoid leaking on `onTaskRemoved`/unregister.
- **DataStore first-run default**: `getJetsonIp()` must emit `192.168.100.1` before any value is written, so the "Sync now" button works out of the box.
- **No device testing available**: build success is the only automated gate; runtime behavior (NetworkCallback firing on hotspot join, notification, POST round-trip) is unverified until field testing.
- **Localization discipline**: every new user-facing string must be added to BOTH `values/strings.xml` (English) and `values-fr/strings.xml` (French); a string present in only one file compiles but falls back silently — review must catch missing-French keys. Keep `SyncEvent.message` (the field-debug log) unlocalized English since it is developer-facing debug text, not user-facing.