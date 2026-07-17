package com.animalcounter.ui.nav

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavController
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.animalcounter.R
import com.animalcounter.ui.placeholder.PlaceholderScreen
import com.animalcounter.ui.timesync.TimeSyncScreen

private object Destinations {
    const val TIME_SYNC = "time-sync"
    const val LIVE_COUNT = "live-count"
    const val VIDEOS = "videos"
}

@Composable
fun AnimalCounterApp() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = currentRoute == Destinations.TIME_SYNC,
                    onClick = { navController.navigateTo(Destinations.TIME_SYNC) },
                    icon = { Icon(Icons.Filled.Schedule, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_time_sync)) },
                )
                NavigationBarItem(
                    selected = currentRoute == Destinations.LIVE_COUNT,
                    onClick = { navController.navigateTo(Destinations.LIVE_COUNT) },
                    icon = { Icon(Icons.Filled.Visibility, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_live_count)) },
                )
                NavigationBarItem(
                    selected = currentRoute == Destinations.VIDEOS,
                    onClick = { navController.navigateTo(Destinations.VIDEOS) },
                    icon = { Icon(Icons.Filled.VideoLibrary, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_videos)) },
                )
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Destinations.TIME_SYNC,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            composable(Destinations.TIME_SYNC) { TimeSyncScreen() }
            composable(Destinations.LIVE_COUNT) {
                PlaceholderScreen(stringResource(R.string.tab_live_count))
            }
            composable(Destinations.VIDEOS) {
                PlaceholderScreen(stringResource(R.string.tab_videos))
            }
        }
    }
}

private fun NavController.navigateTo(route: String) {
    navigate(route) {
        popUpTo(graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}