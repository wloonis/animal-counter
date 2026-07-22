package com.animalcounter.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map

/**
 * Default Jetson companion IP (the Jetson HotSpot gateway address).
 *
 * Two roles:
 *  - The default value of the manual-override IP (`jetson_ip`), so a user
 *    who clears the manual field still has a usable address.
 *  - The default value of the auto-select hotspot candidate
 *    (`jetson_ip_hotspot`), and thus the initial value of [activeIp].
 */
const val DEFAULT_HOTSPOT_IP: String = "192.168.100.1"

/** Default LAN candidate IP (Jetson when joined to the home/work WiFi). */
const val DEFAULT_LAN_IP: String = "192.168.0.180"

/**
 * Legacy alias kept for any code that still references the "Jetson IP" name.
 * Same value as [DEFAULT_HOTSPOT_IP] (the hotspot default).
 */
const val DEFAULT_JETSON_IP: String = DEFAULT_HOTSPOT_IP

/** Process-wide [DataStore] delegate (single instance per [Context]). */
private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(
    name = "animal_counter_settings",
)

/**
 * Persistence layer for the few user-configurable settings, backed by
 * Jetpack DataStore Preferences (coroutine-friendly, lifecycle-safe).
 *
 * Stores:
 *  - `jetson_ip_hotspot` / `jetson_ip_lan`: the two candidate IPs the
 *    auto-select probe polls (defaults [DEFAULT_HOTSPOT_IP] /
 *    [DEFAULT_LAN_IP]).
 *  - `auto_select`: whether auto-select is on (default `true`).
 *  - `jetson_ip`: the manual-override IP used when auto-select is off
 *    (default [DEFAULT_JETSON_IP]).
 *
 * Also owns the resolved `activeIp`: the single IP the rest of the app
 * (ViewModels) should talk to. [JetsonConnectionManager] is the only
 * writer of [activeIp] via [setActiveIp]; everyone else reads
 * [activeIp].
 */
class SettingsRepository(private val context: Context) {

    private val jetsonIpKey = stringPreferencesKey(JETSON_IP_KEY)
    private val hotspotIpKey = stringPreferencesKey(HOTSPOT_IP_KEY)
    private val lanIpKey = stringPreferencesKey(LAN_IP_KEY)
    private val autoSelectKey = booleanPreferencesKey(AUTO_SELECT_KEY)

    /**
     * The manual-override Jetson IP. Emits [DEFAULT_JETSON_IP] when no
     * value has been written yet.
     */
    val jetsonIp: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[jetsonIpKey] ?: DEFAULT_JETSON_IP
    }

    /**
     * The hotspot candidate IP. Emits [DEFAULT_HOTSPOT_IP] when unset.
     */
    val hotspotIp: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[hotspotIpKey] ?: DEFAULT_HOTSPOT_IP
    }

    /**
     * The LAN candidate IP. Emits [DEFAULT_LAN_IP] when unset.
     */
    val lanIp: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[lanIpKey] ?: DEFAULT_LAN_IP
    }

    /**
     * Whether auto-select is enabled. Emits `true` when unset.
     */
    val autoSelect: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[autoSelectKey] ?: true
    }

    /**
     * The resolved active Jetson IP the app should talk to. Defaults to
     * the hotspot default ([DEFAULT_HOTSPOT_IP]) until
     * [JetsonConnectionManager][com.animalcounter.net.JetsonConnectionManager]
     * resolves a reachable IP shortly after the app opens.
     */
    private val _activeIp: MutableStateFlow<String> =
        MutableStateFlow(DEFAULT_HOTSPOT_IP)
    val activeIp: StateFlow<String> = _activeIp.asStateFlow()

    /**
     * Persist [ip] as the manual-override Jetson IP. Empty/blank values
     * are coerced to [DEFAULT_JETSON_IP] so the store never holds an
     * unusable address.
     */
    suspend fun setJetsonIp(ip: String) {
        val normalized = ip.trim().ifBlank { DEFAULT_JETSON_IP }
        context.dataStore.edit { prefs ->
            prefs[jetsonIpKey] = normalized
        }
    }

    /**
     * Persist [ip] as the hotspot candidate IP. Blank coerced to
     * [DEFAULT_HOTSPOT_IP].
     */
    suspend fun setHotspotIp(ip: String) {
        val normalized = ip.trim().ifBlank { DEFAULT_HOTSPOT_IP }
        context.dataStore.edit { prefs ->
            prefs[hotspotIpKey] = normalized
        }
    }

    /**
     * Persist [ip] as the LAN candidate IP. Blank coerced to
     * [DEFAULT_LAN_IP].
     */
    suspend fun setLanIp(ip: String) {
        val normalized = ip.trim().ifBlank { DEFAULT_LAN_IP }
        context.dataStore.edit { prefs ->
            prefs[lanIpKey] = normalized
        }
    }

    /**
     * Persist [value] as the auto-select flag.
     */
    suspend fun setAutoSelect(value: Boolean) {
        context.dataStore.edit { prefs ->
            prefs[autoSelectKey] = value
        }
    }

    /**
     * Update the resolved active IP. Intended to be called only by
     * [JetsonConnectionManager][com.animalcounter.net.JetsonConnectionManager];
     * ViewModels read [activeIp].
     */
    suspend fun setActiveIp(ip: String) {
        _activeIp.value = ip
    }

    private companion object {
        const val JETSON_IP_KEY = "jetson_ip"
        const val HOTSPOT_IP_KEY = "jetson_ip_hotspot"
        const val LAN_IP_KEY = "jetson_ip_lan"
        const val AUTO_SELECT_KEY = "auto_select"
    }
}