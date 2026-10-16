package app.piko.android.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.background
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import app.piko.android.BuildConfig
import app.piko.android.SharingState
import app.piko.android.collect.hasLocationPermission
import app.piko.android.graph
import app.piko.android.service.SharingService

private enum class Screen { Role, Pair, Home, Transparency }

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { PikoTheme { Root() } }
    }

    @Composable
    private fun Root() {
        val app = applicationContext.graph
        val context = LocalContext.current
        val runtime by app.runtime.collectAsStateWithLifecycle()
        var enrollment by remember { mutableStateOf(app.vault.load()) }
        var screen by remember { mutableStateOf(if (enrollment == null) Screen.Role else Screen.Home) }
        var mode by remember { mutableStateOf(app.vault.mode) }
        var counts by remember { mutableStateOf(app.store.counts()) }
        var nowMs by remember { mutableLongStateOf(app.clock.nowMs()) }
        var interrupted by remember { mutableStateOf(app.vault.sharingRequested && runtime.sharing !is SharingState.Running) }

        // Refresh counts and "x seconds ago" text only while the screen is visible.
        val lifecycle = LocalLifecycleOwner.current.lifecycle
        LaunchedEffect(lifecycle) {
            lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    counts = app.store.counts()
                    nowMs = app.clock.nowMs()
                    kotlinx.coroutines.delay(1_000)
                }
            }
        }

        val notificationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            // Sharing works without the notification being visible in the shade; the service's
            // foreground notification is still shown in the task manager.
            SharingService.start(context)
        }
        val locationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            if (context.hasLocationPermission()) {
                if (Build.VERSION.SDK_INT >= 33) notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                else SharingService.start(context)
            } else {
                app.update { it.copy(sharing = SharingState.PermissionMissing("denied"), message = null) }
            }
        }

        fun startSharing() {
            interrupted = false
            if (context.hasLocationPermission()) {
                if (Build.VERSION.SDK_INT >= 33 &&
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
                ) notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) else SharingService.start(context)
            } else {
                locationLauncher.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
            }
        }

        Box(Modifier.fillMaxSize().background(Clay.Canvas)) {
            val current = enrollment
            when {
                current == null && screen == Screen.Pair -> PairScreen(
                    onBack = { screen = Screen.Role },
                    onPaired = { e, _ -> enrollment = e; screen = Screen.Home },
                    pair = { base, code, name ->
                        runPair(base, code, name, BuildConfig.VERSION_NAME, discard = { app.store.clear() }, save = { app.vault.save(it) })
                    },
                )
                current == null -> RoleScreen(onChild = { screen = Screen.Pair })
                screen == Screen.Transparency -> TransparencyScreen(
                    current,
                    onBack = { screen = Screen.Home },
                    onUnlink = {
                        SharingService.stop(context)
                        app.store.clear()
                        app.vault.clearEnrollment()
                        app.update { it.copy(sharing = SharingState.Stopped) }
                        enrollment = null
                        screen = Screen.Role
                    },
                )
                else -> HomeScreen(
                    enrollment = current,
                    runtime = runtime,
                    counts = counts,
                    nowMs = nowMs,
                    mode = mode,
                    revoked = app.vault.credentialRevoked,
                    interrupted = interrupted,
                    onToggleSharing = {
                        if (runtime.sharing is SharingState.Running) SharingService.stop(context) else startSharing()
                    },
                    onMode = {
                        mode = it
                        app.vault.mode = it
                        if (runtime.sharing is SharingState.Running) SharingService.start(context) // restarts with the new plan
                    },
                    onTransparency = { screen = Screen.Transparency },
                    onRelink = {
                        SharingService.stop(context)
                        app.vault.clearEnrollment()
                        enrollment = null
                        screen = Screen.Pair
                    },
                    onOpenSettings = {
                        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
                    },
                )
            }
        }
    }
}
