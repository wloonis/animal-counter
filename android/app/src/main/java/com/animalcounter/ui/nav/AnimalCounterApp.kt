package com.animalcounter.ui.nav

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Schedule
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
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.animalcounter.R
import com.animalcounter.ui.dashboard.DashboardScreen
import com.animalcounter.ui.history.HistoryScreen
import com.animalcounter.ui.livecount.LiveCountScreen
import com.animalcounter.ui.sessiondetail.SessionDetailScreen
import com.animalcounter.ui.sessiondetail.VideoDetailScreen
import com.animalcounter.ui.sessions.SessionsScreen
import com.animalcounter.ui.startups.StartupsScreen
import com.animalcounter.ui.timesync.TimeSyncScreen

private object Destinations {
    const val TIME_SYNC = "time-sync"
    const val LIVE_COUNT = "live-count"
    const val HISTORY = "history"
    const val DASHBOARD = "dashboard"
    const val STARTUPS = "startups"
    const val SESSION_DETAIL = "session/{sessionId}"
    const val VIDEO_DETAIL = "video/{sessionId}"
    const val SESSIONS = "sessions?days={days}"
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
                    selected = currentRoute == Destinations.DASHBOARD,
                    onClick = { navController.navigateTo(Destinations.DASHBOARD) },
                    icon = { Icon(Icons.Filled.BarChart, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_dashboard)) },
                )
                NavigationBarItem(
                    selected = currentRoute == Destinations.LIVE_COUNT,
                    onClick = { navController.navigateTo(Destinations.LIVE_COUNT) },
                    icon = { Icon(Icons.Filled.Visibility, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_live_count)) },
                )
                NavigationBarItem(
                    selected = currentRoute == Destinations.HISTORY,
                    onClick = { navController.navigateTo(Destinations.HISTORY) },
                    icon = { Icon(Icons.Filled.History, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_history)) },
                )
                NavigationBarItem(
                    selected = currentRoute == Destinations.STARTUPS,
                    onClick = { navController.navigateTo(Destinations.STARTUPS) },
                    icon = { Icon(Icons.Filled.PowerSettingsNew, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_startups)) },
                )
                NavigationBarItem(
                    selected = currentRoute == Destinations.TIME_SYNC,
                    onClick = { navController.navigateTo(Destinations.TIME_SYNC) },
                    icon = { Icon(Icons.Filled.Schedule, contentDescription = null) },
                    label = { Text(stringResource(R.string.tab_time_sync)) },
                )
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Destinations.DASHBOARD,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            composable(Destinations.TIME_SYNC) { TimeSyncScreen() }
            composable(Destinations.LIVE_COUNT) { LiveCountScreen() }
            composable(Destinations.HISTORY) { HistoryScreen(navController) }
            composable(Destinations.DASHBOARD) {
                DashboardScreen(onSessionsClick = { days ->
                    navController.navigate("sessions?days=$days")
                })
            }
            composable(Destinations.STARTUPS) { StartupsScreen() }
            composable(
                route = Destinations.VIDEO_DETAIL,
                arguments = listOf(
                    navArgument("sessionId") {
                        type = NavType.StringType
                        nullable = false
                    },
                ),
            ) {
                VideoDetailScreen(onBack = { navController.popBackStack() })
            }
            composable(
                route = Destinations.SESSIONS,
                arguments = listOf(
                    navArgument("days") {
                        type = NavType.StringType
                        defaultValue = "1"
                    },
                ),
            ) {
                SessionsScreen(navController, onBack = { navController.popBackStack() })
            }
            composable(
                route = Destinations.SESSION_DETAIL,
                arguments = listOf(
                    navArgument("sessionId") {
                        type = NavType.StringType
                        nullable = false
                    },
                ),
            ) { backStackEntry ->
                SessionDetailScreen(
                    sessionId = backStackEntry.arguments?.getString("sessionId"),
                    onBack = { navController.popBackStack() },
                )
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