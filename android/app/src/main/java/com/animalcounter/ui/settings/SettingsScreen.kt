package com.animalcounter.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.animalcounter.R
import com.animalcounter.ui.common.AppNavIcon

/**
 * Settings tab (BL-73) — operator configuration for Jetson IP selection.
 *
 * Renders:
 *  - an **auto-select** [Switch] (when on, the manager polls both candidate
 *    IPs in parallel and picks the first reachable one);
 *  - a **manual-override IP** [OutlinedTextField] (typing flips auto-select
 *    off; this becomes the active Jetson address);
 *  - the two **candidate IP** fields (hotspot + lan) used by the parallel
 *    auto-select probe.
 *
 * Every edit is persisted to DataStore (debounced in [SettingsViewModel])
 * and triggers a [com.animalcounter.net.JetsonConnectionManager.rescan]
 * where appropriate so the reachability banner re-resolves quickly.
 *
 * All user-facing text is localized via `stringResource(R.string.*)`
 * (no hard-coded strings).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen() {
    val vm: SettingsViewModel = viewModel()
    val autoSelect by vm.autoSelect.collectAsState()
    val manualIp by vm.manualIp.collectAsState()
    val hotspotIp by vm.hotspotIp.collectAsState()
    val lanIp by vm.lanIp.collectAsState()
    val syncState by vm.syncResult.collectAsState()

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.settings_title)) },
                navigationIcon = { AppNavIcon() },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Auto-select toggle.
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = stringResource(R.string.settings_auto_select),
                    style = MaterialTheme.typography.bodyLarge,
                )
                Switch(
                    checked = autoSelect,
                    onCheckedChange = vm::setAutoSelect,
                )
            }

            // Manual-override IP. Typing here flips auto-select off; the
            // field stays editable so the operator can type even with
            // auto-select on (the toggle then flips off automatically).
            OutlinedTextField(
                value = manualIp,
                onValueChange = vm::onManualIpChange,
                label = { Text(stringResource(R.string.settings_manual_ip)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(8.dp))

            // Candidate IPs probed by the auto-select parallel selection.
            OutlinedTextField(
                value = hotspotIp,
                onValueChange = vm::onHotspotIpChange,
                label = { Text(stringResource(R.string.settings_hotspot_ip)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = lanIp,
                onValueChange = vm::onLanIpChange,
                label = { Text(stringResource(R.string.settings_lan_ip)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(8.dp))

            // On-demand clock sync (BL-74). Pushes the current device time to
            // the Jetson (POST /api/time) via JetsonConnectionManager.syncTime.
            // The button is disabled while a sync is in flight; the inline
            // status line reflects the outcome (green success auto-clears via
            // the VM after ~5s, red failure persists until the next action).
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Button(
                    onClick = vm::syncTime,
                    enabled = syncState !is SettingsViewModel.SyncState.Syncing,
                ) {
                    if (syncState is SettingsViewModel.SyncState.Syncing) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                        )
                        Spacer(Modifier.size(8.dp))
                    }
                    Text(stringResource(R.string.settings_sync_time))
                }

                when (syncState) {
                    is SettingsViewModel.SyncState.Idle -> { /* no inline status */ }
                    is SettingsViewModel.SyncState.Syncing -> {
                        Text(
                            text = stringResource(R.string.settings_syncing),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    is SettingsViewModel.SyncState.Success -> {
                        Text(
                            text = stringResource(R.string.settings_sync_success),
                            color = Color(0xFF2E7D32),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    is SettingsViewModel.SyncState.Failure -> {
                        Text(
                            text = stringResource(R.string.settings_sync_failure),
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
        }
    }
}