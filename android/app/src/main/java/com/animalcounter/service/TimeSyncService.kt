package com.animalcounter.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.animalcounter.R
import com.animalcounter.data.SettingsRepository
import com.animalcounter.data.SyncEvent
import com.animalcounter.data.SyncLog
import com.animalcounter.net.JetsonClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId

/**
 * Foreground service that keeps the Jetson companion's clock in sync.
 *
 * Registers a [ConnectivityManager] `NetworkCallback` for `TRANSPORT_WIFI` so
 * that, whenever the phone joins the Jetson HotSpot, a `POST /api/time` is
 * fired automatically (even with the app closed). The same callback drives
 * [SyncLog.hotspotConnected], which the UI observes to show the out-of-range
 * banner when the phone is not on the HotSpot.
 *
 * Runs as a `dataSync` foreground service (Android 14+ requires the type be
 * declared both in the manifest and at runtime via [ServiceCompat.startForeground]).
 * [com.animalcounter.receiver.BootReceiver] re-starts this service after boot.
 */
class TimeSyncService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var connectivityManager: ConnectivityManager? = null

    private val settings by lazy { SettingsRepository(applicationContext) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat()
        registerNetworkCallback()
        return START_STICKY
    }

    /**
     * Promote to a foreground service, declaring the `dataSync` type required on
     * Android 14+. The notification is persistent for the service's lifetime.
     */
    private fun startForegroundCompat() {
        ensureNotificationChannel()
        val notification = buildNotification()
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        runCatching {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, type)
        }.onFailure {
            // Cannot enter foreground (e.g. restrictions) — record and keep going.
            SyncLog.add(
                SyncEvent(
                    timestamp = Instant.now(),
                    type = SyncEvent.Type.Sync,
                    outcome = SyncEvent.Outcome.Network,
                    detail = "foreground start failed: ${it.message ?: it.javaClass.simpleName}",
                ),
            )
        }
    }

    private fun ensureNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        val id = getString(R.string.notification_channel_id)
        if (manager.getNotificationChannel(id) != null) return
        val channel = NotificationChannel(
            id,
            getString(R.string.notification_channel_title),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.notification_channel_desc)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, getString(R.string.notification_channel_id))
            .setContentTitle(getString(R.string.foreground_notification_title))
            .setContentText(getString(R.string.foreground_notification_text))
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()

    /**
     * Subscribe to WiFi transport changes. `onAvailable` = joined the HotSpot →
     * push the clock; `onLost` = left the HotSpot → mark out-of-range.
     */
    private fun registerNetworkCallback() {
        if (networkCallback != null) return
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return
        connectivityManager = cm
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                SyncLog.setConnected(true)
                SyncLog.add(
                    SyncEvent(
                        timestamp = Instant.now(),
                        type = SyncEvent.Type.Sync,
                        outcome = SyncEvent.Outcome.Success,
                        detail = "WiFi joined — pushing time",
                    ),
                )
                pushTime()
            }

            override fun onLost(network: Network) {
                SyncLog.setConnected(false)
                SyncLog.add(
                    SyncEvent(
                        timestamp = Instant.now(),
                        type = SyncEvent.Type.Sync,
                        outcome = SyncEvent.Outcome.Network,
                        detail = "WiFi lost — out of HotSpot range",
                    ),
                )
            }
        }
        runCatching { cm.registerNetworkCallback(request, callback) }
            .onFailure {
                SyncLog.add(
                    SyncEvent(
                        timestamp = Instant.now(),
                        type = SyncEvent.Type.Sync,
                        outcome = SyncEvent.Outcome.Network,
                        detail = "registerNetworkCallback failed: ${it.message ?: it.javaClass.simpleName}",
                    ),
                )
            }
        networkCallback = callback
    }

    /**
     * Read the configured Jetson IP and POST the current time + zone. Runs on
     * a service-scoped coroutine; failures surface as [SyncEvent]s in the log.
     */
    private fun pushTime() {
        scope.launch {
            val ip = settings.jetsonIp.first()
            val event = JetsonClient.postTime(
                ip = ip,
                timeIso = Instant.now().toString(),
                tz = ZoneId.systemDefault().id,
            )
            SyncLog.add(event)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterNetworkCallback()
        SyncLog.setConnected(false)
        scope.cancel()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        // Keep the callback alive — the service is foreground and sticky.
    }

    private fun unregisterNetworkCallback() {
        val cm = connectivityManager ?: return
        val cb = networkCallback ?: return
        runCatching { cm.unregisterNetworkCallback(cb) }
        networkCallback = null
    }

    private companion object {
        private const val NOTIFICATION_ID = 1001
    }
}