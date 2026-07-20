package com.animalcounter.net

import com.animalcounter.data.SyncEvent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL

/**
 * Companion-side HTTP contract (BL-64 `companion.py`):
 *  - `GET  /api/identify` → `{"service":"animal-counter-companion","version":"<v>"}`
 *  - `POST /api/time`     → body `{"time":"<ISO8601>","tz":"<IANA>"}` → 200 on success,
 *    400 on a malformed/unparseable time/tz, 5xx if the Jetson cannot apply it.
 *
 * All requests target `http://<ip>:8090/...` (cleartext; the Jetson HotSpot is an
 * isolated network — see `AndroidManifest.xml` `usesCleartextTraffic`).
 */
/**
 * Find a network that carries WIFI transport, or null.
 *
 * Why this matters: when the phone has mobile data (5G) AND is joined to the
 * Jetson HotSpot WiFi (which has no internet), Android's *active/default*
 * network is the mobile one (it has internet), so [ConnectivityManager.activeNetwork]
 * returns the carrier network — routing `http://192.168.100.1:8090/...` over 5G
 * where it never reaches the Jetson. We must therefore NOT rely on the active
 * network: scan ALL networks and pick the one with WIFI transport, then bind
 * the [HttpURLConnection] to it via [Network.openConnection] so the request
 * goes onto the HotSpot regardless of mobile data being the default uplink.
 * Callers that already have a [Network] from a
 * [ConnectivityManager.NetworkCallback] (the foreground service) pass it
 * directly; foreground/UI callers use this helper.
 */
fun activeWifiNetwork(cm: ConnectivityManager): Network? {
    @Suppress("DEPRECATION")
    for (network in cm.allNetworks) {
        val caps = cm.getNetworkCapabilities(network) ?: continue
        if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return network
    }
    return null
}

/**
 * Current instant formatted as an ISO-8601 LOCAL offset datetime truncated to
 * microseconds, e.g. `2025-07-15T16:30:00.123456+02:00`.
 *
 * Why not `Instant.now().toString()` (UTC `...Z` with nanoseconds):
 *  1. The Jetson companion parses with Python `datetime.fromisoformat`, which
 *     on Python 3.10 (Jetson JetPack) rejects the `Z` suffix and >6 fractional
 *     digits → HTTP 400 "invalid ISO8601 time".
 *  2. The companion strips the offset and uses the wall-clock value as the
 *     LOCAL time (it sets the timezone separately via `set-timezone`), so a
 *     UTC instant would set the clock off by the UTC offset.
 * A local [java.time.OffsetDateTime] truncated to microseconds is accepted by
 * `fromisoformat` and carries the correct local wall time.
 */
fun nowIsoForCompanion(): String {
    val odt = java.time.OffsetDateTime.now(java.time.ZoneId.systemDefault())
        .truncatedTo(java.time.temporal.ChronoUnit.MICROS)
    return odt.format(java.time.format.DateTimeFormatter.ISO_OFFSET_DATE_TIME)
}

private const val JETSON_PORT = 8090

/** Read/connect timeout for the companion probe/push. */
private const val CONNECT_TIMEOUT_MS = 5_000

/** Read timeout for the companion probe/push. */
private const val READ_TIMEOUT_MS = 5_000

/**
 * Minimal HTTP client for the Jetson companion, built on stdlib
 * [HttpURLConnection] only (no OkHttp) so the build stays self-contained
 * for the offline field workflow.
 *
 * Both entry points run on [Dispatchers.IO] and map the raw HTTP result
 * onto [SyncEvent] so the caller can feed it straight into the shared
 * [com.animalcounter.data.SyncLog]. Failures never throw — they surface
 * as [SyncEvent.Outcome.Network] events.
 */
object JetsonClient {

    /**
     * Reachability probe — `GET /api/identify`.
     *
     * @return a [SyncEvent] typed [SyncEvent.Type.Probe] capturing the
     *   companion's `service`/`version` on success, or a failure outcome.
     */
    suspend fun identify(ip: String, network: Network? = null): SyncEvent = withContext(Dispatchers.IO) {
        val now = java.time.Instant.now()
        try {
            val url = URL("http://${sanitizeIp(ip)}:$JETSON_PORT/api/identify")
            val conn = (openBound(url, network) as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                instanceFollowRedirects = false
                useCaches = false
            }
            try {
                val code = conn.responseCode
                val body = conn.readBody(code)
                if (code == 200) {
                    val parsed = runCatching {
                        val json = JSONObject(body)
                        "${json.optString("service")} ${json.optString("version")}".trim()
                    }.getOrNull()
                    val detail = parsed?.ifBlank { body } ?: body
                    SyncEvent(now, SyncEvent.Type.Probe, SyncEvent.Outcome.Success, detail)
                } else {
                    SyncEvent(
                        now, SyncEvent.Type.Probe,
                        outcomeFor(code),
                        "HTTP $code: $body",
                    )
                }
            } finally {
                conn.disconnect()
            }
        } catch (t: Throwable) {
            SyncEvent(
                now, SyncEvent.Type.Probe, SyncEvent.Outcome.Network,
                t.message ?: t.javaClass.simpleName,
            )
        }
    }

    /**
     * Clock push — `POST /api/time`.
     *
     * @param timeIso an ISO-8601 instant, e.g. `Instant.now().toString()`.
     * @param tz an IANA zone id, e.g. `ZoneId.systemDefault().id`.
     * @return a [SyncEvent] typed [SyncEvent.Type.Sync] capturing the
     *   companion's response on success, or a failure outcome.
     */
    suspend fun postTime(
        ip: String,
        timeIso: String,
        tz: String,
        network: Network? = null,
    ): SyncEvent = withContext(Dispatchers.IO) {
        val now = java.time.Instant.now()
        try {
            val url = URL("http://${sanitizeIp(ip)}:$JETSON_PORT/api/time")
            val payload = JSONObject()
                .put("time", timeIso)
                .put("tz", tz)
                .toString()
            val conn = (openBound(url, network) as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                doOutput = true
                instanceFollowRedirects = false
                useCaches = false
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Accept", "application/json")
            }
            try {
                conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
                val code = conn.responseCode
                val body = conn.readBody(code)
                if (code == 200) {
                    SyncEvent(
                        now, SyncEvent.Type.Sync, SyncEvent.Outcome.Success,
                        body.ifBlank { "200 OK" },
                    )
                } else {
                    SyncEvent(
                        now, SyncEvent.Type.Sync,
                        outcomeFor(code),
                        "HTTP $code: $body",
                    )
                }
            } finally {
                conn.disconnect()
            }
        } catch (t: Throwable) {
            SyncEvent(
                now, SyncEvent.Type.Sync, SyncEvent.Outcome.Network,
                t.message ?: t.javaClass.simpleName,
            )
        }
    }

    /** Open a connection bound to [network] when non-null (routes over the WiFi
     *  HotSpot even when mobile data is the default internet uplink), else the
     *  default network. */
    private fun openBound(url: URL, network: Network?): java.net.URLConnection =
        network?.openConnection(url) ?: url.openConnection()

    /** Map an HTTP status code to the matching [SyncEvent.Outcome]. */
    private fun outcomeFor(code: Int): SyncEvent.Outcome = when (code) {
        in 200..299 -> SyncEvent.Outcome.Success
        400 -> SyncEvent.Outcome.BadRequest
        in 500..599 -> SyncEvent.Outcome.ServerError
        else -> SyncEvent.Outcome.Network
    }

    /** Read the response body, draining the error stream when code >= 400. */
    private fun HttpURLConnection.readBody(code: Int): String {
        val stream = if (code in 200..299) inputStream else errorStream ?: inputStream
        return runCatching { stream?.bufferedReader()?.use { it.readText() } }.getOrNull()
            ?.trim()
            .orEmpty()
    }

    /** Strip any scheme/port the user may have pasted; keep a bare host. */
    private fun sanitizeIp(ip: String): String =
        ip.trim()
            .removePrefix("http://")
            .removePrefix("https://")
            .substringBefore(':')
            .ifBlank { "192.168.100.1" }

    // -----------------------------------------------------------------------
    // BL-68 / BL-69 read-only history + count endpoints
    // -----------------------------------------------------------------------
    //
    // The five methods below all reuse the transport pattern of
    // [identify]/[postTime] (stdlib [HttpURLConnection], bound to the active
    // WiFi [Network] via [openBound], 5s connect/read timeouts,
    // `finally { conn.disconnect() }`, typed failures). They return an
    // [ApiResult] (Success/HttpError/NetworkError) instead of a [SyncEvent]
    // because the history tabs render structured data, not a log line.
    //
    // The JSON → data-class decoders live in [Models.kt] and are `internal`
    // so the unit tests can feed mock fixtures straight into them.

    /** `GET /api/count` → [LiveCount]. */
    suspend fun getCount(ip: String, network: Network? = null): ApiResult<LiveCount> =
        getJson(ip, "/api/count", network) { parseLiveCount(it) }

    /** `GET /api/sessions?limit=&offset=` → [SessionPage]. */
    suspend fun getHistory(
        ip: String,
        limit: Int = 50,
        offset: Int = 0,
        network: Network? = null,
    ): ApiResult<SessionPage> =
        getJson(ip, "/api/history?limit=$limit&offset=$offset", network) { parseSessions(it) }

    /** `GET /api/sessions/<id>` → [SessionDetail] (A–G groups, `end` may be null). */
    suspend fun getSession(
        ip: String,
        id: String,
        network: Network? = null,
    ): ApiResult<SessionDetail> =
        getJson(
            ip,
            "/api/sessions/" + URLEncoder.encode(id, "UTF-8"),
            network,
        ) { parseSessionDetail(it) }

    /** `GET /api/history/summary?days=N` → [Summary] (daily buckets). */
    suspend fun getSummary(
        ip: String,
        days: Int = 7,
        network: Network? = null,
    ): ApiResult<Summary> =
        getJson(ip, "/api/history/summary?days=$days", network) { parseSummary(it) }

    /** `GET /api/startups?limit=` → [StartupList] (newest boot first). */
    suspend fun getStartups(
        ip: String,
        limit: Int = 50,
        network: Network? = null,
    ): ApiResult<StartupList> =
        getJson(ip, "/api/startups?limit=$limit", network) { parseStartups(it) }

    /** `GET <path>` → raw response body string (for offline caching of the
     * history/dashboard/startups tabs). Same transport as the typed getters
     * (WiFi-bound, 5s timeouts, never throws); returns [ApiResult.Success]
     * with the body, or HttpError/NetworkError. The caller caches the body on
     * success and parses it with the `internal` parsers in [Models.kt]. */
    suspend fun fetchRaw(
        ip: String,
        path: String,
        network: Network? = null,
    ): ApiResult<String> = getJson(ip, path, network) { it }

    /**
     * Shared GET transport for the read-only history endpoints: binds to
     * [network] (the WiFi HotSpot) when non-null, applies the 5s timeouts,
     * drains the body, and maps HTTP 200 → [ApiResult.Success] (parsed via
     * [parse]), non-2xx → [ApiResult.HttpError], thrown/parse failure →
     * [ApiResult.NetworkError]. Never throws.
     */
    private suspend fun <T> getJson(
        ip: String,
        path: String,
        network: Network?,
        parse: (String) -> T,
    ): ApiResult<T> = withContext(Dispatchers.IO) {
        try {
            val url = URL("http://${sanitizeIp(ip)}:$JETSON_PORT$path")
            val conn = (openBound(url, network) as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                instanceFollowRedirects = false
                useCaches = false
                setRequestProperty("Accept", "application/json")
            }
            try {
                val code = conn.responseCode
                val body = conn.readBody(code)
                if (code == 200) {
                    ApiResult.Success(parse(body))
                } else {
                    ApiResult.HttpError(code)
                }
            } finally {
                conn.disconnect()
            }
        } catch (t: Throwable) {
            ApiResult.NetworkError(t.message ?: t.javaClass.simpleName)
        }
    }
}