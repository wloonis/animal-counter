package com.animalcounter.ui.startups

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.animalcounter.R
import com.animalcounter.net.Startup
import com.animalcounter.ui.common.OfflineBanner
import com.animalcounter.ui.timesync.ProbeState
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

/**
 * Démarrages tab — chronological list of Jetson boot events from
 * `GET /api/startups`, sorted newest-first by `boot_at`.
 *
 * Visual language: Material 3 — `LargeTopAppBar` with collapsing scroll
 * behavior + a top-app-bar Refresh action; `LazyColumn` of flat M3 `Card`
 * rows (one per startup) with a `ListItem`-style inner layout:
 *  - leading `Icon` (PowerSettingsNew — the boot metaphor),
 *  - `boot_at` rendered in the device locale (`labelSmall`),
 *  - `image_tag` as the row title (`titleMedium`),
 *  - `git_commit` in a monospace `bodySmall`,
 *  - `mode` as a tonal `AssistChip`,
 *  - `config_notable` key/value pairs as compact rows.
 *
 * `PullToRefreshBox` (current M3 pull-to-refresh) for manual refresh,
 * `LinearProgressIndicator` for loading, empty/error/out-of-range states
 * in `OutlinedCard`s with icon + text, and a reachability banner keyed
 * on [ProbeState] (reuses the Time sync banner style).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StartupsScreen() {
    val vm: StartupsViewModel = viewModel()
    val state by vm.state.collectAsState()
    val probeState by vm.probeState.collectAsState()

    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val pullState = rememberPullToRefreshState()
    val isRefreshing = state is StartupsUiState.Loading

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = {
            LargeTopAppBar(
                title = { Text(stringResource(R.string.tab_startups)) },
                actions = {
                    IconButton(onClick = vm::load) {
                        Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.refresh))
                    }
                },
                scrollBehavior = scrollBehavior,
            )
        },
    ) { innerPadding ->
        PullToRefreshBox(
            isRefreshing = isRefreshing,
            onRefresh = vm::load,
            state = pullState,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .nestedScroll(scrollBehavior.nestedScrollConnection),
        ) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                // Reachability banner (always present, pinned at the top).
                item { ReachabilityBanner(probeState = probeState) }

                when (val s = state) {
                    is StartupsUiState.Loading -> item {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                    }
                    is StartupsUiState.Loaded -> {
                        if (s.offline) item { OfflineBanner(cachedAt = s.cachedAt) }
                        if (s.startups.isEmpty()) {
                            item { EmptyCard() }
                        } else {
                            items(s.startups, key = { it.bootAt ?: it.hashCode() }) { startup ->
                                StartupRowCard(startup = startup)
                            }
                        }
                    }
                    is StartupsUiState.Empty -> item { EmptyCard() }
                    is StartupsUiState.OutOfRange -> item { OutOfRangeCard() }
                    is StartupsUiState.Error -> item { ErrorCard(message = s.message) }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Startup row card
// ---------------------------------------------------------------------------

@Composable
private fun StartupRowCard(startup: Startup) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // Header row: boot icon + image_tag (title) + mode chip (trailing).
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Filled.PowerSettingsNew,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(22.dp),
                )
                Spacer(Modifier.size(10.dp))
                Text(
                    text = startup.imageTag ?: "—",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                startup.mode?.let { mode ->
                    ModeChip(mode = mode)
                }
            }

            // boot_at in the device locale.
            Text(
                text = "${stringResource(R.string.startup_boot_at)}: ${formatBootAt(startup.bootAt)}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            // git_commit in monospace.
            startup.gitCommit?.let { commit ->
                Text(
                    text = "${stringResource(R.string.startup_git_commit)}: $commit",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            // config_notable key/value rows.
            startup.configNotable?.let { renderConfigNotable(it) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModeChip(mode: String) {
    AssistChip(
        onClick = {},
        enabled = false,
        label = { Text(mode, style = MaterialTheme.typography.labelMedium) },
        leadingIcon = {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(
                        color = MaterialTheme.colorScheme.tertiary,
                        shape = CircleShape,
                    ),
            )
        },
        colors = AssistChipDefaults.assistChipColors(
            disabledContainerColor = MaterialTheme.colorScheme.tertiaryContainer,
            disabledLabelColor = MaterialTheme.colorScheme.onTertiaryContainer,
        ),
    )
}

// ---------------------------------------------------------------------------
// config_notable renderer — key/value rows (defensive over JSONObject keys)
// ---------------------------------------------------------------------------

@Composable
private fun renderConfigNotable(config: JSONObject) {
    val keys = config.keys().asSequence().toList()
    if (keys.isEmpty()) return
    Spacer(Modifier.height(2.dp))
    Text(
        text = stringResource(R.string.startup_config_notable),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    keys.forEach { key ->
        val value = config.opt(key)
        val valueStr = when (value) {
            null -> "—"
            is JSONObject -> value.toString()
            else -> value.toString()
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Text(
                text = key,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = valueStr,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.weight(2f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// Empty / error / out-of-range cards
// ---------------------------------------------------------------------------

@Composable
private fun EmptyCard() {
    InfoCard(
        icon = Icons.Outlined.Inbox,
        title = stringResource(R.string.empty_startups),
        body = "",
    )
}

@Composable
private fun OutOfRangeCard() {
    InfoCard(
        icon = Icons.Filled.WifiOff,
        title = stringResource(R.string.error_out_of_range),
        body = stringResource(R.string.jetson_out_of_range),
    )
}

@Composable
private fun ErrorCard(message: String) {
    InfoCard(
        icon = Icons.Outlined.ErrorOutline,
        title = stringResource(R.string.error_load),
        body = message,
    )
}

@Composable
private fun InfoCard(icon: ImageVector, title: String, body: String) {
    OutlinedCard(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Column {
                Text(title, style = MaterialTheme.typography.titleSmall)
                if (body.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = body,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Reachability banner (reuses the Time sync ProbeState style)
// ---------------------------------------------------------------------------

@Composable
private fun ReachabilityBanner(probeState: ProbeState) {
    val container: Color
    val onContainer: Color
    val message: String
    val icon: ImageVector
    when (probeState) {
        ProbeState.Reachable -> {
            container = MaterialTheme.colorScheme.primaryContainer
            onContainer = MaterialTheme.colorScheme.onPrimaryContainer
            message = stringResource(R.string.jetson_connected)
            icon = Icons.Filled.Wifi
        }
        ProbeState.OutOfRange -> {
            container = MaterialTheme.colorScheme.errorContainer
            onContainer = MaterialTheme.colorScheme.onErrorContainer
            message = stringResource(R.string.jetson_out_of_range)
            icon = Icons.Filled.WifiOff
        }
        ProbeState.Probing, ProbeState.Idle -> {
            container = MaterialTheme.colorScheme.surfaceVariant
            onContainer = MaterialTheme.colorScheme.onSurfaceVariant
            message = stringResource(R.string.jetson_checking)
            icon = Icons.Filled.Wifi
        }
    }
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

// ---------------------------------------------------------------------------
// Date formatting helpers
// ---------------------------------------------------------------------------

/** Format `boot_at` (ISO-8601 offset datetime) in the device locale, or `"—"` on failure. */
private fun formatBootAt(iso: String?): String {
    if (iso.isNullOrBlank()) return "—"
    val instant = parseInstant(iso) ?: return iso
    val zoned = instant.atZone(ZoneId.systemDefault())
    val formatter = DateTimeFormatter
        .ofPattern("yyyy-MM-dd HH:mm:ss", Locale.ROOT)
        .withZone(ZoneId.systemDefault())
    return formatter.format(zoned)
}

/** Parse an ISO-8601 offset datetime (or bare datetime) into an [Instant]; null on failure. */
private fun parseInstant(iso: String): Instant? {
    return runCatching {
        try {
            OffsetDateTime.parse(iso, DateTimeFormatter.ISO_OFFSET_DATE_TIME).toInstant()
        } catch (e: DateTimeParseException) {
            java.time.LocalDateTime.parse(iso.take(19))
                .atZone(ZoneId.systemDefault())
                .toInstant()
        }
    }.getOrNull()
}