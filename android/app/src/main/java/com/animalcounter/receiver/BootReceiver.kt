package com.animalcounter.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.animalcounter.data.SyncEvent
import com.animalcounter.data.SyncLog
import com.animalcounter.service.TimeSyncService
import java.time.Instant

/**
 * Re-starts [TimeSyncService] once the device has finished booting.
 *
 * On `BOOT_COMPLETED` we simply ask Android to bring the foreground service
 * back up; the service then re-registers its own `NetworkCallback`, so the
 * first push happens naturally when the phone next joins the Jetson HotSpot.
 * There is **no direct time push at boot** — the service owns all syncing.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return

        SyncLog.add(
            SyncEvent(
                timestamp = Instant.now(),
                type = SyncEvent.Type.Sync,
                outcome = SyncEvent.Outcome.Network,
                detail = "Boot completed — starting time sync service",
            ),
        )

        val serviceIntent = Intent(context, TimeSyncService::class.java)
        ContextCompat.startForegroundService(context, serviceIntent)
    }
}