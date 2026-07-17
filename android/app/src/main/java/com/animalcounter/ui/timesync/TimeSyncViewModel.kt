package com.animalcounter.ui.timesync

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.animalcounter.data.DEFAULT_JETSON_IP
import com.animalcounter.data.SettingsRepository
import com.animalcounter.data.SyncEvent
import com.animalcounter.data.SyncLog
import com.animalcounter.net.JetsonClient
import com.animalcounter.net.activeWifiNetwork
import com.animalcounter.net.nowIsoForCompanion
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId

/** Debounce window (ms) before a typed IP is persisted to DataStore. */
private const val IP_PERSIST_DEBOUNCE_MS = 500L

/**
 * State holder for the Time sync screen.
 *
 * Bridges the persisted Jetson IP ([SettingsRepository]) with the
 * composable text field, debouncing writes so the user can type freely.
 * Exposes the shared [SyncLog] connectivity + event stream to the screen
 * (the log itself is a process-wide singleton the foreground service
 * also writes to). "Sync now" is dispatched here on [Dispatchers.IO]
 * (inside [JetsonClient]) so the UI never blocks.
 *
 * Constructed with the default [AndroidViewModel] factory, which wires
 * the [Application] for the [SettingsRepository]'s DataStore.
 */
/** Probe state for the « Jetson connecté / hors de portée » banner. */
enum class ProbeState { Idle, Probing, Reachable, OutOfRange }

class TimeSyncViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = SettingsRepository(app)

    private val _ip = MutableStateFlow(DEFAULT_JETSON_IP)
    /** Current Jetson IP text-field value (source of truth for the field). */
    val ip: StateFlow<String> = _ip.asStateFlow()

    private val _syncing = MutableStateFlow(false)
    /** True while a "Sync now" push is in flight (disables the button). */
    val syncing: StateFlow<Boolean> = _syncing.asStateFlow()

    private val _probeState = MutableStateFlow(ProbeState.Idle)
    /** Reachability probe result driving the out-of-range banner. */
    val probeState: StateFlow<ProbeState> = _probeState.asStateFlow()

    /** Whether the initial DataStore value has been loaded into [_ip]. */
    private var loaded = false

    /** Pending debounced persist job, cancelled on each keystroke. */
    private var persistJob: Job? = null

    init {
        // Seed the field from DataStore (DEFAULT_JETSON_IP until first emit).
        viewModelScope.launch {
            repo.jetsonIp.collect { saved ->
                if (!loaded) {
                    _ip.value = saved
                    loaded = true
                    // Probe the Jetson once the configured IP is known.
                    probe()
                }
            }
        }
    }

    /**
     * Update the IP text-field value and (re)schedule a debounced write
     * to DataStore. Blank input is preserved in the field so the user
     * can clear/retype; [setJetsonIp] normalizes blanks to the default.
     */
    fun onIpChange(value: String) {
        _ip.value = value
        persistJob?.cancel()
        persistJob = viewModelScope.launch {
            delay(IP_PERSIST_DEBOUNCE_MS)
            repo.setJetsonIp(value)
        }
    }

    /**
     * Reachability probe — `GET /api/identify`, bound to the active WiFi
     * network so it reaches the Jetson HotSpot even with mobile data (5G) up.
     * Drives [probeState] (the banner) and logs the result. Called on screen
     * open (init) and by the « Refresh » button.
     */
    fun probe() {
        if (_probeState.value == ProbeState.Probing) return
        _probeState.value = ProbeState.Probing
        viewModelScope.launch {
            try {
                val cm = getApplication<Application>()
                    .getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                val wifi = cm?.let { activeWifiNetwork(it) }
                val event = JetsonClient.identify(ip = _ip.value, network = wifi)
                SyncLog.add(event)
                _probeState.value =
                    if (event.outcome == SyncEvent.Outcome.Success) ProbeState.Reachable
                    else ProbeState.OutOfRange
            } catch (t: Throwable) {
                _probeState.value = ProbeState.OutOfRange
            }
        }
    }

    /**
     * Trigger an immediate `POST /api/time` clock push using the current
     * IP field value + the phone's instant/timezone, appending the result
     * to the shared [SyncLog]. No-op if a push is already in flight.
     */
    fun syncNow() {
        if (_syncing.value) return
        _syncing.value = true
        viewModelScope.launch {
            try {
                // Bind to the active WiFi network so the request reaches the
                // Jetson HotSpot even when mobile data (5G) is the default
                // internet uplink (Android would otherwise route 192.168.100.1
                // over the carrier network and fail).
                val cm = getApplication<Application>().getSystemService(
                    android.content.Context.CONNECTIVITY_SERVICE,
                ) as? ConnectivityManager
                val wifi = cm?.let { activeWifiNetwork(it) }
                val event = JetsonClient.postTime(
                    ip = _ip.value,
                    timeIso = nowIsoForCompanion(),
                    tz = ZoneId.systemDefault().id,
                    network = wifi,
                )
                SyncLog.add(event)
            } finally {
                _syncing.value = false
            }
        }
    }
}