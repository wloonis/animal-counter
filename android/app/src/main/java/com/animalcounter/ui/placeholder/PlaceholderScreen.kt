package com.animalcounter.ui.placeholder

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
 * Placeholder for not-yet-implemented hub tabs (Live count, Videos).
 * Shows the tab label + a localized "Coming soon" message.
 */
@Composable
fun PlaceholderScreen(label: String) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.titleLarge,
        )
        Text(
            text = stringResource(R.string.coming_soon),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}