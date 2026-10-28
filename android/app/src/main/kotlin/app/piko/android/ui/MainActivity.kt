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
import app.piko.android.afterLinking
import app.piko.android.collect.hasLocationPermission
import app.piko.android.comms.CommsNotifier
import app.piko.android.comms.CommsRunner
import app.piko.android.push.PushSupport
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import app.piko.android.core.CommKind
import kotlinx.coroutines.launch
import app.piko.android.graph
import app.piko.android.journeys.data.JourneySync
import app.piko.android.journeys.tracking.JourneyNotifier
import app.piko.android.journeys.ui.JourneysHost
import app.piko.android.service.SharingService

private enum class Screen { Role, Pair, Home, Transparency, Messages, Journeys }

class MainActivity : ComponentActivity() {
    /** Where a tapped notification wants to go ("messages" or "home"); consumed once by [Root]. */
    private val openRequest = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        openRequest.value = intent?.getStringExtra(EXTRA_OPEN)
        setContent { PikoTheme { Root() } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        openRequest.value = intent.getStringExtra(EXTRA_OPEN)
    }

    companion object {
        const val EXTRA_OPEN = "app.piko.android.extra.OPEN"
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
        var commItems by remember { mutableStateOf(app.comms.items()) }
        val parent by app.parentMessages.collectAsStateWithLifecycle()
        var notificationsAllowed by remember { mutableStateOf(CommsNotifier.canNotify(context)) }
        var commsError by remember { mutableStateOf<String?>(null) }

        // Refresh counts and "x seconds ago" text only while the screen is visible.
        val lifecycle = LocalLifecycleOwner.current.lifecycle
        LaunchedEffect(lifecycle) {
            lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    counts = app.store.counts()
                    commItems = app.comms.items()
                    nowMs = app.clock.nowMs()
                    notificationsAllowed = CommsNotifier.canNotify(context)
                    kotlinx.coroutines.delay(1_000)
                }
            }
        }
        // While the app is open: deliver anything waiting and pull replies (rate-limited inside).
        LaunchedEffect(lifecycle, enrollment) {
            lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    if (app.vault.load() != null) {
                        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { CommsRunner.runOnce(context) }
                    }
                    kotlinx.coroutines.delay(30_000)
                }
            }
        }
        val alertsLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            notificationsAllowed = CommsNotifier.canNotify(context)
            if (!notificationsAllowed) {
                startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
            }
        }
        // A tapped notification opens the right screen, but only for a paired phone.
        val requested = openRequest.value
        LaunchedEffect(requested, enrollment) {
            if (requested != null && enrollment != null) {
                screen = when (requested) {
                    CommsNotifier.OPEN_MESSAGES -> Screen.Messages
                    JourneyNotifier.OPEN -> Screen.Journeys
                    else -> Screen.Home
                }
                openRequest.value = null
            }
        }
        val canSend = enrollment != null && !app.vault.credentialRevoked && runtime.sharing !is SharingState.CredentialRevoked
        val scope = androidx.compose.runtime.rememberCoroutineScope()

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
                    onPaired = { e, _ ->
                        // A freshly linked phone is no longer "unlinked": clear the in-memory state a previous
                        // revocation left behind, or the SOS button would stay disabled until a restart.
                        app.update { it.afterLinking() }
                        PushSupport.start(context)
                        enrollment = e
                        screen = Screen.Home
                    },
                    pair = { base, code, name ->
                        runPair(base, code, name, BuildConfig.VERSION_NAME, discard = { app.journeys.forgetSync(); app.store.clear() + app.comms.clear() }, save = { app.vault.save(it) })
                    },
                )
                current == null -> RoleScreen(onChild = { screen = Screen.Pair })
                screen == Screen.Journeys -> JourneysHost(
                    store = app.journeys,
                    prefs = app.journeyPrefs,
                    nowMs = { app.clock.nowMs() },
                    onChanged = { JourneySync.request(context) },
                    onExit = { screen = Screen.Home },
                )
                screen == Screen.Messages -> MessagesScreen(
                    items = commItems,
                    parent = parent,
                    nowMs = nowMs,
                    canSend = canSend,
                    notificationsAllowed = notificationsAllowed,
                    onBack = { screen = Screen.Home },
                    onSend = { text ->
                        CommsRunner.validate(CommKind.MESSAGE, text)
                            ?: CommsRunner.submitMessage(context, text).let { if (it.accepted) null else it.reason }
                    },
                    onGotIt = { id ->
                        scope.launch {
                            commsError = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                                CommsRunner.acknowledgeMessage(context, id)
                            }
                        }
                    },
                    onRefresh = {
                        scope.launch { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { CommsRunner.runOnce(context, forceRefresh = true) } }
                    },
                    onAllowAlerts = {
                        if (Build.VERSION.SDK_INT >= 33) alertsLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                    },
                    error = commsError,
                    backgroundAlerts = when (PushSupport.status(context)) {
                        PushSupport.Status.NOT_CONFIGURED ->
                            "Background alerts are not set up in this build, so replies are only fetched while this app is open or sharing is on."
                        PushSupport.Status.WAITING_FOR_TOKEN ->
                            "Background alerts: waiting for Google to issue this phone's address. Until then replies are fetched while the app is open."
                        PushSupport.Status.REGISTRATION_PENDING ->
                            "Background alerts: not registered with Piko yet (no connection, or the phone is not linked). They will start when it is."
                        PushSupport.Status.REGISTERED ->
                            "Background alerts: registered. A notice can wake this app to fetch replies; delivery still depends on Android, your network and battery settings."
                    },
                )
                screen == Screen.Transparency -> TransparencyScreen(
                    current,
                    onBack = { screen = Screen.Home },
                    onUnlink = {
                        SharingService.stop(context)
                        scope.launch {
                            // Tell the server to stop notifying this phone while the credential still exists.
                            withContext(Dispatchers.IO) { PushSupport.unregister(context) }
                            app.store.clear()
                            app.comms.clear()
                            app.journeys.forgetSync()
                            app.setParentMessages(app.parentMessages.value.copy(messages = emptyList(), loadedAtMs = null))
                            app.vault.clearEnrollment()
                            app.update { it.copy(sharing = SharingState.Stopped) }
                            enrollment = null
                            screen = Screen.Role
                        }
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
                    comms = commItems,
                    unreadMessages = parent.messages.count { it.status == "delivered" },
                    canSend = canSend,
                    onSos = { note ->
                        val sent = CommsRunner.submitSos(context, note)
                        commsError = if (sent.accepted) null else sent.reason
                        commItems = app.comms.items()
                    },
                    onMessages = { screen = Screen.Messages },
                    onJourneys = { screen = Screen.Journeys },
                )
            }
        }
    }
}
