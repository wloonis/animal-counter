package com.animalcounter.ui.settings

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.animalcounter.data.DEFAULT_HOTSPOT_IP
import com.animalcounter.data.DEFAULT_JETSON_IP
import com.animalcounter.data.DEFAULT_LAN_IP
import com.animalcounter.data.SettingsRepository
import com.animalcounter.net.JetsonConnectionManager
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Debounce window (ms) before a typed IP is persisted to DataStore. */
private const val IP_PERSIST_DEBOUNCE_MS = 500L

/**
 * State holder for the Settings screen (BL-73).
 *
 * Bridges the four configurable settings in [SettingsRepository] with the
 * composable fields, debouncing writes so the user can type freely. Each
 * field is backed by a local [MutableStateFlow] seeded once from DataStore
 * (one-shot [first]); subsequent edits update the local field immediately
 * and schedule a debounced persist.
 *
 * Behavior:
 *  - **Auto-select toggle**: flipping to `true` re-enables auto-select and
 *    triggers [JetsonConnectionManager.rescan] (the parallel probe picks up
 *    the candidate IPs again). Flipping to `false` just persists the flag
 *    (the manual IP field becomes the effective address).
 *  - **Manual IP field**: typing flips `autoSelect = false` (the manual
 *    override is now the active source) and persists the value; a debounced
 *    [JetsonConnectionManager.rescan] re-probes the manual IP.
 *  - **Candidate IP fields** (hotspot/lan): a debounced persist followed by
 *    [JetsonConnectionManager.rescan] so the parallel selection uses the new
 *    candidates on the next probe.
 *
 * Constructed with the default [AndroidViewModel] factory, which wires the
 * [Application] for the [SettingsRepository]'s DataStore.
 */
class SettingsViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = SettingsRepository(app)

    private val _autoSelect = MutableStateFlow(true)
    /** Whether auto-select is enabled (drives the toggle + manual field state). */
    val autoSelect: StateFlow<Boolean> = _autoSelect.asStateFlow()

    private val _manualIp = MutableStateFlow(DEFAULT_JETSON_IP)
    /** Manual-override Jetson IP (effective when [autoSelect] is `false`). */
    val manualIp: StateFlow<String> = _manualIp.asStateFlow()

    private val _hotspotIp = MutableStateFlow(DEFAULT_HOTSPOT_IP)
    /** Hotspot candidate IP probed by the auto-select parallel probe. */
    val hotspotIp: StateFlow<String> = _hotspotIp.asStateFlow()

    private val _lanIp = MutableStateFlow(DEFAULT_LAN_IP)
    /** LAN candidate IP probed by the auto-select parallel probe. */
    val lanIp: StateFlow<String> = _lanIp.asStateFlow()

    /** Whether the initial DataStore values have been loaded. */
    private var loaded = false

    /** Pending debounced persist jobs, one per field (so cross-field edits don't cancel each other). */
    private var manualPersistJob: Job? = null
    private var hotspotPersistJob: Job? = null
    private var lanPersistJob: Job? = null

    init {
        // Seed the fields from DataStore (DEFAULT_* until first emit).
        viewModelScope.launch {
            _autoSelect.value = repo.autoSelect.first()
            _manualIp.value = repo.jetsonIp.first()
            _hotspotIp.value = repo.hotspotIp.first()
            _lanIp.value = repo.lanIp.first()
            loaded = true
        }
    }

    /**
     * Toggle auto-select. Re-enabling auto triggers a fresh parallel
     * selection probe so the banner resolves quickly.
     */
    fun setAutoSelect(value: Boolean) {
        _autoSelect.value = value
        viewModelScope.launch {
            repo.setAutoSelect(value)
            if (value) JetsonConnectionManager.rescan()
        }
    }

    /**
     * Manual-override IP field edit. Typing flips [autoSelect] to `false`
     * (the manual override becomes the active source) and (after a
     * debounce) persists the value + re-probes the manual IP.
     */
    fun onManualIpChange(value: String) {
        _manualIp.value = value
        _autoSelect.value = false
        manualPersistJob?.cancel()
        manualPersistJob = viewModelScope.launch {
            delay(IP_PERSIST_DEBOUNCE_MS)
            repo.setAutoSelect(false)
            repo.setJetsonIp(value)
            JetsonConnectionManager.rescan()
        }
    }

    /**
     * Hotspot candidate IP field edit. Debounced persist + re-probe so the
     * next parallel selection uses the new candidate.
     */
    fun onHotspotIpChange(value: String) {
        _hotspotIp.value = value
        hotspotPersistJob?.cancel()
        hotspotPersistJob = viewModelScope.launch {
            delay(IP_PERSIST_DEBOUNCE_MS)
            repo.setHotspotIp(value)
            JetsonConnectionManager.rescan()
        }
    }

    /**
     * LAN candidate IP field edit. Debounced persist + re-probe so the
     * next parallel selection uses the new candidate.
     */
    fun onLanIpChange(value: String) {
        _lanIp.value = value
        lanPersistJob?.cancel()
        lanPersistJob = viewModelScope.launch {
            delay(IP_PERSIST_DEBOUNCE_MS)
            repo.setLanIp(value)
            JetsonConnectionManager.rescan()
        }
    }
}