package com.animalcounter.ui.startups

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.animalcounter.data.DEFAULT_JETSON_IP
import com.animalcounter.data.OfflineCache
import com.animalcounter.data.SettingsRepository
import com.animalcounter.net.ApiResult
import com.animalcounter.net.JetsonClient
import com.animalcounter.net.JetsonConnectionManager
import com.animalcounter.net.Startup
import com.animalcounter.net.activeWifiNetwork
import com.animalcounter.net.parseStartups
import com.animalcounter.net.ProbeState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/** Page size for `/api/startups` (matches the brief's `limit=50`). */
private const val STARTUPS_LIMIT = 50
private const val CACHE_KEY = "startups"

/**
 * UI state for the Démarrages tab.
 *
 * - [Loading]: a fetch is in flight (no rows yet) — show a
 *   `LinearProgressIndicator`.
 * - [Loaded]: a startup list was fetched successfully; [startups] holds
 *   the rows sorted newest-first (by `boot_at` descending).
 * - [Empty]: a list was fetched but contained zero startups — show the
 *   empty-startups card.
 * - [OutOfRange]: the Jetson is unreachable (probe failed AND no list could
 *   be fetched) — show the out-of-range banner + empty card.
 * - [Error]: a fetch returned a non-recoverable HTTP error — show the
 *   error card.
 */
sealed interface StartupsUiState {
    /** Initial load in progress (no rows yet). */
    data object Loading : StartupsUiState
    /** Startups loaded, sorted newest-first by `boot_at`. */
    data class Loaded(
        val startups: List<Startup>,
        val offline: Boolean = false,
        val cachedAt: Instant? = null,
    ) : StartupsUiState
    /** A list was fetched but contained zero startups. */
    data object Empty : StartupsUiState
    /** Jetson out of reach (probe + fetch both failed). */
    data object OutOfRange : StartupsUiState
    /** Recoverable or HTTP error while fetching the list. */
    data class Error(val message: String) : StartupsUiState
}

/**
 * ViewModel backing the Démarrages tab.
 *
 * Calls `JetsonClient.getStartups(ip, 50)` and sorts the result newest-first
 * by `boot_at` (parsed defensively — a startup whose `boot_at` is absent or
 * unparseable is pushed to the end while preserving relative order).
 *
 * Exposes:
 *  - [state]: the current [StartupsUiState] (drives the screen body).
 *  - [probeState]: the reachability banner state (reuses the Time sync
 *    [ProbeState] so the banner style is identical).
 */
class StartupsViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = SettingsRepository(app)

    /** Current Jetson IP (seeded from DataStore; source of truth = Time sync tab). */
    private val _ip = MutableStateFlow(DEFAULT_JETSON_IP)
    val ip: StateFlow<String> = _ip.asStateFlow()

    private val _state = MutableStateFlow<StartupsUiState>(StartupsUiState.Loading)
    val state: StateFlow<StartupsUiState> = _state.asStateFlow()

    /**
     * Reachability banner state — delegated to the app-wide
     * [JetsonConnectionManager] (the single canonical probe owner, BL-73).
     * Screens that read `vm.probeState` are unchanged.
     */
    val probeState: StateFlow<ProbeState>
        get() = JetsonConnectionManager.probeState

    init {
        // Re-seed the IP + refetch whenever the manager resolves a new active
        // Jetson IP (hotspot/LAN/manual). The first emission is the hotspot
        // default; a second follows once the parallel probe resolves.
        viewModelScope.launch {
            repo.activeIp.collect { ip ->
                _ip.value = ip
                load()
            }
        }
    }

    /**
     * Refresh — re-runs the probe + fetch. Used by the top-app-bar Refresh
     * action and by pull-to-refresh. Preserves a Loaded snapshot so a
     * transient failure doesn't blank the list (only the banner flips to
     * OutOfRange).
     */
    fun load() {
        viewModelScope.launch {
            val previous = _state.value
            if (previous !is StartupsUiState.Loaded) _state.value = StartupsUiState.Loading
            try {
                val cm = cm()
                val wifi = if (cm != null) activeWifiNetwork(cm) else null
                when (val result = JetsonClient.fetchRaw(
                    ip = _ip.value,
                    path = "/api/startups?limit=$STARTUPS_LIMIT",
                    network = wifi,
                )) {
                    is ApiResult.Success -> {
                        OfflineCache.save(getApplication(), CACHE_KEY, result.data)
                        val sorted = sortByBootAtDesc(parseStartups(result.data).startups)
                        _state.value = if (sorted.isEmpty()) {
                            StartupsUiState.Empty
                        } else {
                            StartupsUiState.Loaded(sorted)
                        }
                        // A successful fetch implies the Jetson is reachable;
                        // the manager owns the banner so nothing to set here.
                    }
                    is ApiResult.HttpError -> {
                        _state.value =
                            if (previous is StartupsUiState.Loaded) previous
                            else loadCachedStartups() ?: StartupsUiState.Error("HTTP ${result.code}")
                    }
                    is ApiResult.NetworkError -> {
                        _state.value =
                            if (previous is StartupsUiState.Loaded) previous
                            else loadCachedStartups() ?: StartupsUiState.OutOfRange
                    }
                }
            } catch (t: Throwable) {
                _state.value =
                    if (previous is StartupsUiState.Loaded) previous
                    else loadCachedStartups() ?: StartupsUiState.OutOfRange
            }
        }
    }

    /** Offline fallback — serve the last cached `/api/startups` response
     * so the user can consult the startups history with no Jetson connection.
     * Returns null when there is no cache (caller falls back to Error/OutOfRange). */
    /** Re-fetch (auto-refresh polling + pull-to-refresh).
     * Reachability probing is owned by [JetsonConnectionManager]. */
    fun refresh() {
        load()
    }

    private fun loadCachedStartups(): StartupsUiState.Loaded? {
        val cached = OfflineCache.load(getApplication(), CACHE_KEY) ?: return null
        val sorted = runCatching { sortByBootAtDesc(parseStartups(cached.json).startups) }
            .getOrNull() ?: return null
        return if (sorted.isEmpty()) null
        else StartupsUiState.Loaded(sorted, offline = true, cachedAt = cached.savedAt)
    }

    /**
     * Sort newest-first by `boot_at`. Rows whose `boot_at` is absent or
     * unparseable are pushed to the end while preserving their relative
     * order (stable sort on a min-instant sentinel).
     */
    private fun sortByBootAtDesc(rows: List<Startup>): List<Startup> {
        val instantMin = java.time.Instant.MIN
        return rows.sortedByDescending { parseBootInstant(it.bootAt) ?: instantMin }
    }

    /** Parse an ISO-8601 offset datetime (or bare datetime) into an [Instant]; null on failure. */
    private fun parseBootInstant(iso: String?): java.time.Instant? {
        if (iso.isNullOrBlank()) return null
        return runCatching {
            try {
                OffsetDateTime.parse(iso, DateTimeFormatter.ISO_OFFSET_DATE_TIME).toInstant()
            } catch (e: DateTimeParseException) {
                // Fall back to a bare local date-time (no offset).
                java.time.LocalDateTime.parse(iso.take(19))
                    .atZone(java.time.ZoneId.systemDefault())
                    .toInstant()
            }
        }.getOrNull()
    }

    /** Resolve the active WiFi network (null when not on the Jetson HotSpot). */
    private fun cm(): ConnectivityManager? = getApplication<Application>()
        .getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
}