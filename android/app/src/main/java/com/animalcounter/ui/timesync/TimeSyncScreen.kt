package com.animalcounter.ui.timesync

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.animalcounter.R
import com.animalcounter.data.SyncEvent
import com.animalcounter.data.SyncLog
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Time sync screen — the BL-65 hub's primary tab.
 *
 * - Editable Jetson IP field persisted via DataStore (debounced).
 * - "Sync now" button → immediate `POST /api/time` clock push, logged.
 * - HotSpot reachability banner driven by [SyncLog.hotspotConnected]
 *   (updated by the foreground service's `NetworkCallback`): a clear
 *   "out of range" notice when the phone is NOT on the Jetson HotSpot.
 * - Scrollable, newest-bottom log of recent [SyncEvent]s from the
 *   shared [SyncLog], auto-scrolled to the latest entry, with per-event
 *   timestamp + type + status color.
 *
 * All user-facing text is localized via `stringResource(R.string.*)`
 * (no hard-coded strings). Developer-facing log details stay as the
 * raw English debug text carried by [SyncEvent.detail].
 */
@Composable
fun TimeSyncScreen() {
    val vm: TimeSyncViewModel = viewModel()
    val ip by vm.ip.collectAsState()
    val syncing by vm.syncing.collectAsState()
    val connected by SyncLog.hotspotConnected.collectAsState()
    val events by SyncLog.events.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        HotspotBanner(connected = connected)

        Spacer(Modifier.height(12.dp))

        OutlinedTextField(
            value = ip,
            onValueChange = vm::onIpChange,
            label = { Text(stringResource(R.string.jetson_ip_label)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(12.dp))

        Button(
            onClick = vm::syncNow,
            enabled = !syncing,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (syncing) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
                Spacer(Modifier.size(8.dp))
            }
            Text(stringResource(R.string.sync_now))
        }

        Spacer(Modifier.height(16.dp))

        Text(
            text = stringResource(R.string.tab_time_sync),
            style = MaterialTheme.typography.titleMedium,
        )

        Spacer(Modifier.height(8.dp))

        EventLog(events = events)
    }
}

/**
 * Prominent Material 3 status banner showing whether the phone is
 * connected to the Jetson HotSpot. When out of range, uses error-
 * container coloring + [Icons.Filled.WifiOff] so the unavailability
 * of the companion services is unmistakable.
 */
@Composable
private fun HotspotBanner(connected: Boolean) {
    val container = if (connected) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.errorContainer
    }
    val onContainer = if (connected) {
        MaterialTheme.colorScheme.onPrimaryContainer
    } else {
        MaterialTheme.colorScheme.onErrorContainer
    }
    val message = stringResource(
        if (connected) R.string.jetson_connected else R.string.jetson_out_of_range,
    )
    val icon = if (connected) Icons.Filled.Wifi else Icons.Filled.WifiOff

    Surface(
        color = container,
        contentColor = onContainer,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(icon, contentDescription = null)
            Text(message, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

/**
 * Scrollable list of recent [SyncEvent]s, oldest at top / newest at
 * bottom, auto-scrolled to the latest entry. Empty state shows the
 * localized "No events yet" hint.
 */
@Composable
private fun EventLog(events: List<SyncEvent>) {
    if (events.isEmpty()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = stringResource(R.string.log_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }

    // Display newest at the bottom → reverse the newest-first source list.
    val displayed = remember(events) { events.asReversed() }
    val listState = rememberLazyListState()

    // Auto-scroll to the freshly appended (bottom) entry.
    LaunchedEffect(displayed.size) {
        if (displayed.isNotEmpty()) {
            listState.animateScrollToItem(displayed.lastIndex)
        }
    }

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items(displayed.size) { index ->
            EventRow(event = displayed[index])
        }
    }
}

/** One log line: timestamp, type, colored status, and raw detail. */
@Composable
private fun EventRow(event: SyncEvent) {
    val statusColor = statusColor(event.outcome)
    val typeLabel = stringResource(
        if (event.type is SyncEvent.Type.Probe) R.string.type_probe else R.string.type_sync,
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = formatInstant(event.timestamp),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = typeLabel,
                style = MaterialTheme.typography.labelMedium,
                color = statusColor,
            )
        }
        Text(
            text = event.detail.ifBlank { "—" },
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

/** Color a log line by its outcome (success vs. failure variants). */
@Composable
private fun statusColor(outcome: SyncEvent.Outcome): Color = when (outcome) {
    SyncEvent.Outcome.Success -> MaterialTheme.colorScheme.primary
    SyncEvent.Outcome.BadRequest -> MaterialTheme.colorScheme.error
    SyncEvent.Outcome.ServerError -> MaterialTheme.colorScheme.error
    SyncEvent.Outcome.Network -> MaterialTheme.colorScheme.error
}

/** Render an [Instant] as a short local timestamp for the log. */
private fun formatInstant(instant: Instant): String {
    val zone = ZoneId.systemDefault()
    val formatter = DateTimeFormatter
        .ofPattern("yyyy-MM-dd HH:mm:ss", Locale.ROOT)
        .withZone(zone)
    return formatter.format(instant)
}