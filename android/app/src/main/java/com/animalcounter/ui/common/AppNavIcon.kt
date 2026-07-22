package com.animalcounter.ui.common

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.colorResource
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.animalcounter.R

/**
 * The app launcher icon, sized for use as the leading `navigationIcon` of a
 * Material 3 top app bar — always present top-left, in front of the screen
 * title, at a size that suits the bar (~36 dp).
 *
 * Renders the launcher **foreground** (a raster PNG) over the launcher
 * background color, clipped to a circle, so it matches the on-disk app icon.
 * We deliberately reference `R.drawable.ic_launcher_foreground` (a PNG) and NOT
 * `R.mipmap.ic_launcher*` — on API 26+ the mipmap resolves to an
 * `<adaptive-icon>` XML, and `painterResource` only handles `<vector>` /
 * raster assets, throwing
 * `IllegalArgumentException: Only VectorDrawables and rasterized asset types
 * are supported` for an adaptive icon (which crashed the app at launch).
 */
@Composable
fun AppNavIcon(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(36.dp)
            .clip(CircleShape)
            .background(colorResource(R.color.ic_launcher_background)),
        contentAlignment = Alignment.Center,
    ) {
        Image(
            painter = painterResource(R.drawable.ic_launcher_foreground),
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier.fillMaxSize(),
        )
    }
}