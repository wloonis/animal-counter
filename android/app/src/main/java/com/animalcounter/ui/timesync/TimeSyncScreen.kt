package com.animalcounter.ui.timesync

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.animalcounter.R

/**
 * Time sync screen — scaffold placeholder.
 *
 * The full screen (Jetson IP field, DataStore persistence, reachability
 * probe banner, Sync/Refresh buttons, bounded ring-buffer log view) lands
 * in BL-65 Task 19. This minimal composable keeps the hub nav wired and
 * the build green in the meantime.
 */
@Composable
fun TimeSyncScreen() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = stringResource(R.string.tab_time_sync),
            style = MaterialTheme.typography.headlineMedium,
        )
        Text(
            text = stringResource(R.string.time_sync_placeholder),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}