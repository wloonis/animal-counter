package com.animalcounter.ui.history

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.animalcounter.data.DEFAULT_JETSON_IP
import com.animalcounter.data.OfflineCache
import com.animalcounter.data.SettingsRepository
import com.animalcounter.net.ApiResult
import com.animalcounter.net.HistoryPage
import com.animalcounter.net.JetsonClient
import com.animalcounter.net.SessionSummary
import com.animalcounter.net.activeWifiNetwork
import com.animalcounter.net.parseHistory
import com.animalcounter.ui.timesync.ProbeState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/** Page size for `/api/history` (matches the brief's `limit=50`). */
private const val HISTORY_LIMIT = 50
private const val CACHE_KEY = "history"

/**
 * UI state for the Historique tab.
 *
 * - [Loading]: initial page fetch in flight (no rows yet) — show a
 *   `LinearProgressIndicator`.
 * - [Loaded]: one or more pages loaded; [rows] holds the accumulated
 *   (filter-applied) summaries, [hasMore] is true when `offset < total`.
 * - [Empty]: a page was fetched successfully but it contained zero rows
 *   (and no filter is active) — show the empty-history card.
 * - [OutOfRange]: the Jetson is unreachable (probe failed) AND no page
 *   could be fetched — show the out-of-range banner + empty card.
 * - [Error]: a fetch returned a non-recoverable HTTP error — show the
 *   error card.
 */
sealed interface HistoryUiState {
    /** Initial load in progress (no rows yet). */
    data object Loading : HistoryUiState
    /** Rows available; [hasMore] true when more pages can be appended. */
    data class Loaded(
        val rows: List<SessionSummary>,
        val total: Int,
        val hasMore: Boolean,
        val loadingMore: Boolean,
        val offline: Boolean = false,
        val cachedAt: Instant? = null,
    ) : HistoryUiState
    /** A page was fetched but contained zero sessions (no filter active). */
    data object Empty : HistoryUiState
    /** Jetson out of reach (probe + fetch both failed). */
    data object OutOfRange : HistoryUiState
    /** Recoverable or HTTP error while fetching a page. */
    data class Error(val message: String) : HistoryUiState
}

/**
 * Status filter values exposed by the History screen's `FilterChip` group.
 *
 * The clean/power-loss/unknown classification lives in the **separate**
 * `end_reason` field (verified against `tests/companion_history_reader.py`),
 * NOT in `status` (which is only `"ended"` | `"running"`). These filter keys
 * therefore branch on `end_reason` (+ a dedicated `running` chip that
 * matches `status == "running"`), mirroring the pill color mapping.
 */
enum class HistoryStatusFilter(val key: String) {
    ALL("all"),
    RUNNING("running"),
    CLEAN("clean"),
    POWER_LOSS("power-loss"),
    UNKNOWN("unknown");

    companion object {
        fun fromKey(key: String?): HistoryStatusFilter =
            entries.firstOrNull { it.key == key } ?: ALL
    }
}

/**
 * ViewModel backing the Historique tab.
 *
 * Maintains an accumulated, paginated view of `/api/history` with a light
 * in-memory cache (the accumulated [SessionSummary] list). Filtering is
 * client-side (the API has no server-side filter params): the selected
 * date ([LocalDate]) compares against a row's `start_at` (parsed to a
 * local date), and the selected status filter branches on `end_reason`
 * (+ `running`) per the verified status mapping.
 *
 * Exposes:
 *  - [state]: the current [HistoryUiState] (drives the screen body).
 *  - [probeState]: the reachability banner state (reuses the Time sync
 *    [ProbeState] so the banner style is identical).
 *  - [filterDate] / [filterStatus]: the active client-side filters.
 */
class HistoryViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = SettingsRepository(app)

    /** Current Jetson IP (seeded from DataStore; source of truth = Time sync tab). */
    private val _ip = MutableStateFlow(DEFAULT_JETSON_IP)
    val ip: StateFlow<String> = _ip.asStateFlow()

    private val _state = MutableStateFlow<HistoryUiState>(HistoryUiState.Loading)
    val state: StateFlow<HistoryUiState> = _state.asStateFlow()

    private val _probeState = MutableStateFlow(ProbeState.Idle)
    val probeState: StateFlow<ProbeState> = _probeState.asStateFlow()

    /** Selected date filter (null = no date filter). */
    private val _filterDate = MutableStateFlow<LocalDate?>(null)
    val filterDate: StateFlow<LocalDate?> = _filterDate.asStateFlow()

    /** Selected status filter (ALL = no status filter). */
    private val _filterStatus = MutableStateFlow(HistoryStatusFilter.ALL)
    val filterStatus: StateFlow<HistoryStatusFilter> = _filterStatus.asStateFlow()

    /** Whether the initial DataStore IP has been loaded (guards the first fetch). */
    private var loaded = false

    /** Accumulated raw (unfiltered) sessions — the light in-memory cache. */
    private val cache = ArrayList<SessionSummary>()

    /** Offline-cache flags — true when the current Loaded state is served from
     * the on-device cache (no Jetson connection). Reset to false on every
     * successful online fetch; set by [loadCachedHistory]. [publishFiltered]
     * reads them so a filter change keeps the offline banner. */
    private var offlineMode = false
    private var lastCachedAt: Instant? = null

    /** Next offset to fetch (== cache.size while loading the first page). */
    private var offset = 0

    /** Total session count reported by the API (drives [HistoryUiState.Loaded.hasMore]). */
    private var total = 0

    init {
        // Seed the IP from DataStore, then probe + load the first page once.
        viewModelScope.launch {
            repo.jetsonIp.collect { saved ->
                _ip.value = saved
                if (!loaded) {
                    loaded = true
                    probe()
                    loadFirstPage()
                }
            }
        }
    }

    /**
     * Refresh — clears the cache and re-fetches the first page (preserves
     * the active filters). Used by the top-app-bar Refresh action and by
     * pull-to-refresh.
     */
    fun loadFirstPage() {
        viewModelScope.launch {
            // Preserve a Loaded snapshot so a transient refresh failure doesn't
            // blank the list (only the banner flips to OutOfRange).
            val previous = _state.value
            if (previous !is HistoryUiState.Loaded) _state.value = HistoryUiState.Loading
            cache.clear()
            offset = 0
            total = 0
            fetchPage(append = false, previous = previous)
            if (_probeState.value != ProbeState.Probing) probe()
        }
    }

    /**
     * Append the next page (when the user scrolls near the end). No-op
     * when there is no more data, a page is already being fetched, or the
     * Jetson is known out of range.
     */
    fun loadNextPage() {
        val current = _state.value
        if (current !is HistoryUiState.Loaded) return
        if (current.loadingMore) return
        if (!current.hasMore) return
        viewModelScope.launch {
            _state.value = current.copy(loadingMore = true)
            fetchPage(append = true, previous = current)
        }
    }

    /** Set the date filter (null clears it) and re-apply the filter client-side. */
    fun setFilterDate(date: LocalDate?) {
        _filterDate.value = date
        reapplyFilter()
    }

    /** Set the status filter and re-apply the filter client-side. */
    fun setFilterStatus(filter: HistoryStatusFilter) {
        _filterStatus.value = filter
        reapplyFilter()
    }

    /**
     * Reachability probe — `GET /api/identify` bound to the active WiFi
     * network so it reaches the Jetson HotSpot even with mobile data (5G)
     * as the default internet uplink. Drives [probeState] (the banner).
     */
    fun probe() {
        if (_probeState.value == ProbeState.Probing) return
        _probeState.value = ProbeState.Probing
        viewModelScope.launch {
            try {
                val cm = cm()
                val wifi = if (cm != null) activeWifiNetwork(cm) else null
                val event = JetsonClient.identify(ip = _ip.value, network = wifi)
                _probeState.value =
                    if (event.outcome == com.animalcounter.data.SyncEvent.Outcome.Success)
                        ProbeState.Reachable
                    else ProbeState.OutOfRange
            } catch (t: Throwable) {
                _probeState.value = ProbeState.OutOfRange
            }
        }
    }

    /**
     * One `/api/history?limit=&offset=` fetch mapped onto [state]. On a
     * network failure we transition to [HistoryUiState.OutOfRange] only
     * when there is no cached snapshot to keep showing (so a transient
     * blip doesn't wipe a perfectly good list); on append failure we keep
     * the existing [HistoryUiState.Loaded] (just clear `loadingMore`).
     */
    private suspend fun fetchPage(append: Boolean, previous: HistoryUiState) {
        try {
            val cm = cm()
            val wifi = if (cm != null) activeWifiNetwork(cm) else null
            when (val result = JetsonClient.fetchRaw(
                ip = _ip.value,
                path = "/api/history?limit=$HISTORY_LIMIT&offset=$offset",
                network = wifi,
            )) {
                is ApiResult.Success -> {
                    val page: HistoryPage = parseHistory(result.data)
                    // Cache only the first (non-append) page for offline consult.
                    if (!append) OfflineCache.save(getApplication(), CACHE_KEY, result.data)
                    if (append) {
                        cache.addAll(page.sessions)
                    } else {
                        cache.clear()
                        cache.addAll(page.sessions)
                    }
                    total = page.total.coerceAtLeast(cache.size)
                    offset = cache.size
                    offlineMode = false
                    lastCachedAt = null
                    publishFiltered(hasMore = offset < total, loadingMore = false)
                    // A successful fetch implies the Jetson is reachable.
                    if (_probeState.value != ProbeState.Probing) {
                        _probeState.value = ProbeState.Reachable
                    }
                }
                is ApiResult.HttpError -> {
                    _state.value = if (previous is HistoryUiState.Loaded) {
                        previous.copy(loadingMore = false)
                    } else {
                        loadCachedHistory() ?: HistoryUiState.Error("HTTP ${result.code}")
                    }
                }
                is ApiResult.NetworkError -> {
                    _state.value = if (previous is HistoryUiState.Loaded) {
                        previous.copy(loadingMore = false)
                    } else {
                        loadCachedHistory() ?: HistoryUiState.OutOfRange
                    }
                }
            }
        } catch (t: Throwable) {
            _state.value = if (previous is HistoryUiState.Loaded) {
                previous.copy(loadingMore = false)
            } else {
                loadCachedHistory() ?: HistoryUiState.OutOfRange
            }
        }
    }

    /**
     * Offline fallback — serve the last cached first page of `/api/history`
     * so the history tab stays consultable with no Jetson connection. Fills
     * [cache]/[total]/[offset], sets [offlineMode]/[lastCachedAt], then
     * publishes via [publishFiltered]. Returns the resulting [HistoryUiState]
     * (Loaded or Empty), or null when there is no cache (caller falls back to
     * Error/OutOfRange).
     */
    private fun loadCachedHistory(): HistoryUiState? {
        val cached = OfflineCache.load(getApplication(), CACHE_KEY) ?: return null
        val page = runCatching { parseHistory(cached.json) }.getOrNull() ?: return null
        cache.clear()
        cache.addAll(page.sessions)
        total = page.total.coerceAtLeast(cache.size)
        offset = cache.size
        offlineMode = true
        lastCachedAt = cached.savedAt
        publishFiltered(hasMore = false, loadingMore = false)
        return _state.value
    }

    /**
     * Re-apply the active date + status filters to the in-memory cache and
     * republish [state]. Called after a filter change (no network).
     */
    private fun reapplyFilter() {
        if (cache.isEmpty()) {
            // No rows cached yet — keep the current load/empty/error state.
            if (_state.value is HistoryUiState.Loaded) {
                _state.value = HistoryUiState.Empty
            }
            return
        }
        publishFiltered(hasMore = offset < total, loadingMore = false)
    }

    /**
     * Apply the active filters to [cache] and publish the resulting
     * [HistoryUiState.Loaded] (or [HistoryUiState.Empty] when the filtered
     * set is empty AND no filter is active — a filter producing zero rows
     * is still [Loaded] so the user sees their filter took effect).
     */
    private fun publishFiltered(hasMore: Boolean, loadingMore: Boolean) {
        val date = _filterDate.value
        val status = _filterStatus.value
        val rows = cache.filter { matchesFilters(it, date, status) }
            // Running ("en cours") sessions first — they are the most
            // important visually — then newest start_at.
            .sortedWith(
                compareByDescending<SessionSummary> { it.status == "running" }
                    .thenByDescending { it.startAt ?: "" }
            )
        _state.value = when {
            cache.isEmpty() && date == null && status == HistoryStatusFilter.ALL ->
                HistoryUiState.Empty
            else -> HistoryUiState.Loaded(
                rows = rows,
                total = if (date == null && status == HistoryStatusFilter.ALL) total else rows.size,
                hasMore = hasMore && date == null && status == HistoryStatusFilter.ALL,
                loadingMore = loadingMore,
                offline = offlineMode,
                cachedAt = lastCachedAt,
            )
        }
    }

    /**
     * Client-side filter predicate.
     *
     * Date: compares [SessionSummary.startAt] (parsed to a local date) to
     * [date]. Rows whose `start_at` is absent or unparseable are excluded
     * when a date filter is active.
     *
     * Status: branches on `end_reason` (+ a dedicated `running` filter that
     * matches `status == "running"`) per the verified status mapping — NOT
     * on the `status` field, which is only `"ended"` | `"running"`.
     */
    private fun matchesFilters(
        s: SessionSummary,
        date: LocalDate?,
        status: HistoryStatusFilter,
    ): Boolean {
        if (date != null) {
            val rowDate = parseLocalDate(s.startAt)
            if (rowDate != date) return false
        }
        if (status != HistoryStatusFilter.ALL) {
            if (!matchesStatusFilter(s, status)) return false
        }
        return true
    }

    /** Branch on `end_reason` (+ `running` via `status`) per the verified mapping. */
    private fun matchesStatusFilter(s: SessionSummary, filter: HistoryStatusFilter): Boolean =
        when (filter) {
            HistoryStatusFilter.ALL -> true
            HistoryStatusFilter.RUNNING -> s.status == "running"
            HistoryStatusFilter.CLEAN -> s.endReason == "clean"
            HistoryStatusFilter.POWER_LOSS -> s.endReason == "power-loss"
            HistoryStatusFilter.UNKNOWN ->
                s.endReason == "unknown" || s.endReason == "sigterm" || s.endReason == null
        }

    /** Parse an ISO-8601 datetime (or bare date) into a [LocalDate], null on failure. */
    private fun parseLocalDate(iso: String?): LocalDate? {
        if (iso.isNullOrBlank()) return null
        return runCatching {
            // Prefer OffsetDateTime (the companion emits offset datetimes);
            // fall back to a bare LocalDate (YYYY-MM-DD) for robustness.
            try {
                OffsetDateTime.parse(iso, DateTimeFormatter.ISO_OFFSET_DATE_TIME).toLocalDate()
            } catch (e: DateTimeParseException) {
                LocalDate.parse(iso.take(10))
            }
        }.getOrNull()
    }

    /** Resolve the active WiFi network (null when not on the Jetson HotSpot). */
    private fun cm(): ConnectivityManager? = getApplication<Application>()
        .getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
}