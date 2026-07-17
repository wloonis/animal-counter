package com.animalcounter.ui.timesync

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.animalcounter.data.DEFAULT_JETSON_IP
import com.animalcounter.data.SettingsRepository
import com.animalcounter.data.SyncEvent
import com.animalcounter.data.SyncLog
import com.animalcounter.net.JetsonClient
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
class TimeSyncViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = SettingsRepository(app)

    private val _ip = MutableStateFlow(DEFAULT_JETSON_IP)
    /** Current Jetson IP text-field value (source of truth for the field). */
    val ip: StateFlow<String> = _ip.asStateFlow()

    private val _syncing = MutableStateFlow(false)
    /** True while a "Sync now" push is in flight (disables the button). */
    val syncing: StateFlow<Boolean> = _syncing.asStateFlow()

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
     * Trigger an immediate `POST /api/time` clock push using the current
     * IP field value + the phone's instant/timezone, appending the result
     * to the shared [SyncLog]. No-op if a push is already in flight.
     */
    fun syncNow() {
        if (_syncing.value) return
        _syncing.value = true
        viewModelScope.launch {
            try {
                val event = JetsonClient.postTime(
                    ip = _ip.value,
                    timeIso = Instant.now().toString(),
                    tz = ZoneId.systemDefault().id,
                )
                SyncLog.add(event)
            } finally {
                _syncing.value = false
            }
        }
    }
}