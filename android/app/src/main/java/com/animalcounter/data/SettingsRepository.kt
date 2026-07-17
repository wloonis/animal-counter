package com.animalcounter.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * Default Jetson companion IP (the Jetson HotSpot gateway address).
 * Used before the user has explicitly saved an IP, so "Sync now" works
 * out of the box.
 */
const val DEFAULT_JETSON_IP: String = "192.168.100.1"

/** Process-wide [DataStore] delegate (single instance per [Context]). */
private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(
    name = "animal_counter_settings",
)

/**
 * Persistence layer for the few user-configurable settings, backed by
 * Jetpack DataStore Preferences (coroutine-friendly, lifecycle-safe).
 *
 * Currently stores the Jetson companion IP the phone POSTs time to
 * (BL-64 `POST http://<ip>:8090/api/time`). The IP is exposed as a
 * Compose-observable [Flow] that emits [DEFAULT_JETSON_IP] until the
 * user writes a new value, and is updated via [setJetsonIp].
 */
class SettingsRepository(private val context: Context) {

    private val jetsonIpKey = stringPreferencesKey(JETSON_IP_KEY)

    /**
     * The configured Jetson IP. Emits [DEFAULT_JETSON_IP] when no value
     * has been written yet.
     */
    val jetsonIp: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[jetsonIpKey] ?: DEFAULT_JETSON_IP
    }

    /**
     * Persist [ip] as the Jetson companion IP. Empty/blank values are
     * coerced to [DEFAULT_JETSON_IP] so the store never holds an unusable
     * address.
     */
    suspend fun setJetsonIp(ip: String) {
        val normalized = ip.trim().ifBlank { DEFAULT_JETSON_IP }
        context.dataStore.edit { prefs ->
            prefs[jetsonIpKey] = normalized
        }
    }

    private companion object {
        const val JETSON_IP_KEY = "jetson_ip"
    }
}