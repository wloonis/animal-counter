package com.animalcounter.ui.common

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.animalcounter.R

/**
 * The app launcher icon, sized for use as the leading `navigationIcon` of a
 * Material 3 top app bar — always present top-left, in front of the screen
 * title, at a size that suits the bar (~36 dp).
 */
@Composable
fun AppNavIcon(modifier: Modifier = Modifier) {
    Image(
        painter = painterResource(R.mipmap.ic_launcher_round),
        contentDescription = null,
        modifier = modifier.size(36.dp),
    )
}