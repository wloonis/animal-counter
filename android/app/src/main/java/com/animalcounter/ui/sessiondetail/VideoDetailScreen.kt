package com.animalcounter.ui.sessiondetail

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.animalcounter.R
import com.animalcounter.net.SessionDetail
import java.util.Locale

/**
 * Détail vidéo — simplified video-centric view reached from the History tab.
 *
 * Shows only the video facts the operator cares about: filename, start,
 * video duration, net count + directional/tracking breakdown, guards, and a
 * simple running/ended status. Session-level diagnostics (end_reason,
 * heartbeats, config, thermal, events timeline) are deliberately NOT shown
 * here — those live in the Session detail reached from the Dashboard
 * "Sessions" entry. Reuses [SessionDetailViewModel] (same `/api/sessions/<id>`
 * fetch) keyed by the `video/{sessionId}` nav arg.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VideoDetailScreen(
    onBack: () -> Unit = {},
) {
    val vm: SessionDetailViewModel = viewModel()
    val state by vm.state.collectAsState()
    val probeState by vm.probeState.collectAsState()

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.video_detail_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.detail_back),
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(innerPadding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(
                start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item { ReachabilityBanner(probeState = probeState) }

            when (val s = state) {
                is SessionDetailUiState.Loading -> item {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                is SessionDetailUiState.Loaded -> {
                    val d = s.detail
                    item { VideoHeaderCard(d) }
                    item { CountingCard(d) }
                    item { GuardsCard(d) }
                }
                is SessionDetailUiState.OutOfRange -> item { OutOfRangeCard() }
                is SessionDetailUiState.Error -> item { ErrorCard(message = s.message) }
            }
        }
    }
}

/** A — En-tête vidéo: filename, start, video duration, status (En cours / Terminé). */
@Composable
private fun VideoHeaderCard(d: SessionDetail) {
    val start = d.start
    val end = d.end
    val rawVideo = end?.video?.path ?: d.heartbeats.lastOrNull()?.lastSegment
    val video = displayFilename(rawVideo, d.status)
    val startStr = formatIso(start?.startAt)
    val videoDur = formatSeconds(end?.video?.duration)
        ?: durationBetween(start?.startAt, d.endAt ?: end?.endAt)
    GroupCard(
        icon = Icons.Filled.PlayCircle,
        title = stringResource(R.string.detail_video),
    ) {
        KeyValueRow(R.string.detail_video, video ?: "—")
        KeyValueRow(R.string.detail_start, startStr)
        if (videoDur != null) KeyValueRow(R.string.detail_duration, videoDur)
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            KeyValueLabel(R.string.detail_status)
            SimpleStatusPill(d.status)
        }
    }
}

/** Simple running/ended pill — En cours / Terminé (no end_reason). */
@Composable
private fun SimpleStatusPill(status: String) {
    val running = status == "running"
    val (dotColor, label) = if (running) {
        MaterialTheme.colorScheme.primary to stringResource(R.string.filter_status_running)
    } else {
        MaterialTheme.colorScheme.tertiary to stringResource(R.string.status_ended)
    }
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        shape = MaterialTheme.shapes.small,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Spacer(
                modifier = Modifier
                    .size(8.dp)
                    .background(color = dotColor, shape = CircleShape),
            )
            Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium)
        }
    }
}

/** Display the video filename: basename, with `tmp-` stripped once ended. */
private fun displayFilename(videoPath: String?, status: String): String? {
    if (videoPath == null) return null
    val base = videoPath.substringAfterLast('/')
    return if (status != "running" && base.startsWith("tmp-")) base.removePrefix("tmp-") else base
}

/** Format a duration in seconds as `H:MM:SS` / `MM:SS` / `SSs`, null when null. */
private fun formatSeconds(seconds: Double?): String? {
    if (seconds == null || seconds < 0 || seconds.isNaN()) return null
    val total = seconds.toLong()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return when {
        h > 0 -> String.format(Locale.ROOT, "%d:%02d:%02d", h, m, s)
        m > 0 -> String.format(Locale.ROOT, "%d:%02d", m, s)
        else -> String.format(Locale.ROOT, "%ds", s)
    }
}