package app.piko.android.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.location.Location
import android.os.IBinder
import app.piko.android.R
import app.piko.android.SharingState
import app.piko.android.SyncStatus
import app.piko.android.collect.BatteryCollector
import app.piko.android.collect.ConnectivityMonitor
import app.piko.android.collect.LocationCollector
import app.piko.android.collect.hasLocationPermission
import app.piko.android.comms.CommsRunner
import app.piko.android.core.BatteryThrottle
import app.piko.android.core.ConnectivityThrottle
import app.piko.android.core.EventData
import app.piko.android.core.InvalidComm
import app.piko.android.core.InvalidEvent
import app.piko.android.core.SosPoint
import app.piko.android.core.ModePlan
import app.piko.android.core.SyncEngine
import app.piko.android.core.SyncOutcome
import app.piko.android.core.plan
import app.piko.android.data.Enrollment
import app.piko.android.graph
import app.piko.android.net.ApiClient
import app.piko.android.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * The visible foreground service that is the only thing that collects and uploads. It is started
 * only from the open activity, always shows a notification with a Stop action, and runs only
 * while the user has sharing switched on. It is not restarted by the system (START_NOT_STICKY):
 * if it dies the UI reports "stopped" instead of pretending.
 */
class SharingService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var syncJob: Job? = null
    private var location: LocationCollector? = null
    private var battery: BatteryCollector? = null
    private var connectivity: ConnectivityMonitor? = null

    private val online = MutableStateFlow(false)
    private val eventWake = Channel<Unit>(Channel.CONFLATED)
    private val networkWake = Channel<Unit>(Channel.CONFLATED)
    private val batteryThrottle = BatteryThrottle()
    private val connectivityThrottle = ConnectivityThrottle()
    private var plan: ModePlan = app.piko.android.core.SyncMode.POLLING.plan()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSharing(userRequested = true)
            return START_NOT_STICKY
        }
        startSharing()
        return START_NOT_STICKY
    }

    private fun startSharing() {
        val app = applicationContext.graph
        try {
            startForeground(NOTIFICATION_ID, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } catch (e: Exception) {
            app.update { it.copy(sharing = SharingState.Stopped, message = "Android did not allow sharing to start (${e.javaClass.simpleName}).") }
            stopSelf()
            return
        }
        val enrollment = app.vault.load()
        if (enrollment == null) {
            app.update { it.copy(sharing = SharingState.Stopped, message = "This phone is not paired.") }
            stopSelf()
            return
        }
        if (!hasLocationPermission()) {
            app.vault.sharingRequested = false
            app.update { it.copy(sharing = SharingState.PermissionMissing("Location permission is off"), message = null) }
            stopSelf()
            return
        }
        stopWork() // switching mode restarts the collectors with the new plan
        val mode = app.vault.mode
        plan = mode.plan()
        app.vault.sharingRequested = true
        app.update { it.copy(sharing = SharingState.Running(mode), message = null) }
        startCollectors()
        syncJob = scope.launch { syncLoop(enrollment) }
    }

    private fun startCollectors() {
        val app = applicationContext.graph
        location = LocationCollector(this) { fix -> scope.launch { onFix(fix) } }.also { collector ->
            if (!collector.start(plan)) {
                app.update { it.copy(message = "No location provider is available on this phone.") }
            }
        }
        battery = BatteryCollector(this) { percent, charging ->
            scope.launch {
                app.update { it.copy(batteryPercent = percent, batteryCharging = charging) }
                if (batteryThrottle.shouldEmit(percent, charging, app.clock.nowMs())) {
                    record(EventData.Battery(percent, charging))
                }
            }
        }.also { it.start() }
        connectivity = ConnectivityMonitor(this) { type, isOnline ->
            scope.launch {
                val was = online.value
                online.value = isOnline
                app.update { it.copy(networkType = type) }
                if (connectivityThrottle.shouldEmit(type)) record(EventData.Connectivity(type))
                if (isOnline && !was) networkWake.trySend(Unit)
            }
        }.also { it.start() }
    }

    private fun onFix(fix: Location) {
        val app = applicationContext.graph
        val accuracy = if (fix.hasAccuracy()) fix.accuracy.toDouble() else null
        try {
            record(EventData.Location(fix.latitude, fix.longitude, accuracy), capturedAtMs = fix.time)
            app.update {
                it.copy(
                    lastLocationAtMs = fix.time.coerceAtMost(app.clock.nowMs()),
                    lastLocationAccuracyM = accuracy,
                    lastFix = SosPoint(fix.latitude, fix.longitude, accuracy),
                )
            }
        } catch (_: InvalidEvent) {
            // A malformed reading from the platform is dropped, never queued.
        } catch (_: InvalidComm) {
            // Same for the in-memory copy kept for SOS.
        }
    }

    private fun record(data: EventData, capturedAtMs: Long = applicationContext.graph.clock.nowMs()) {
        applicationContext.graph.recorder.record(data, capturedAtMs)
        if (plan.flushOnEvent) eventWake.trySend(Unit)
    }

    private suspend fun syncLoop(enrollment: Enrollment) {
        val app = applicationContext.graph
        val client = ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential) { size ->
            app.update { it.copy(lastPayload = size) }
        }
        val engine = SyncEngine(app.store, client, app.clock)
        var lastAttemptMs = 0L
        while (currentCoroutineContext().isActive) {
            if (!online.value) {
                setSync(SyncStatus.WaitingForNetwork) // no timers while offline: wake on the network callback
                online.first { it }
                continue
            }
            if (app.recorder.heartbeatDue()) {
                app.recorder.record(EventData.Connectivity(app.runtime.value.networkType?.takeIf { it != "none" } ?: "other"))
            }
            // At least a few seconds between attempts however often events or the network wake us.
            delay((MIN_ATTEMPT_SPACING_MS - (app.clock.nowMs() - lastAttemptMs)).coerceAtLeast(0))
            lastAttemptMs = app.clock.nowMs()
            setSync(SyncStatus.Syncing)
            // An SOS or message waiting in the outbox goes before routine telemetry.
            CommsRunner.runOnce(applicationContext)
            when (val outcome = engine.syncOnce()) {
                is SyncOutcome.Done -> {
                    setSync(SyncStatus.Idle)
                    if (!outcome.moreWaiting) waitIdle()
                }
                is SyncOutcome.RetryAfter -> {
                    setSync(SyncStatus.BackingOff(app.clock.nowMs() + outcome.delayMs, outcome.reason.name.lowercase()))
                    // Events do not cut a backoff short; only the network coming back does.
                    withTimeoutOrNull(outcome.delayMs) { networkWake.receive() }
                }
                SyncOutcome.CredentialRevoked -> {
                    app.vault.credentialRevoked = true
                    app.vault.sharingRequested = false
                    app.update { it.copy(sharing = SharingState.CredentialRevoked, sync = SyncStatus.Idle) }
                    stopWork()
                    stopForegroundAndSelf()
                    return
                }
            }
        }
    }

    /** POLLING checks every [ModePlan.syncIntervalMs]; REALTIME also wakes shortly after each event. */
    private suspend fun waitIdle() {
        val woke = withTimeoutOrNull(plan.syncIntervalMs) {
            if (plan.flushOnEvent) {
                kotlinx.coroutines.selects.select<Unit> {
                    eventWake.onReceive { }
                    networkWake.onReceive { }
                }
            } else {
                networkWake.receive()
            }
        }
        if (woke != null && plan.flushOnEvent) delay(DEBOUNCE_MS) // coalesce a burst into one upload
    }

    private fun setSync(status: SyncStatus) = applicationContext.graph.update { it.copy(sync = status) }

    private fun stopSharing(userRequested: Boolean) {
        val app = applicationContext.graph
        stopWork()
        if (userRequested) app.vault.sharingRequested = false
        app.update { if (it.sharing is SharingState.Running) it.copy(sharing = SharingState.Stopped, sync = SyncStatus.Idle) else it }
        stopForegroundAndSelf()
    }

    private fun stopWork() {
        syncJob?.cancel()
        syncJob = null
        location?.stop(); location = null
        battery?.stop(); battery = null
        connectivity?.stop(); connectivity = null
    }

    private fun stopForegroundAndSelf() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopWork()
        scope.cancel()
        val app = applicationContext.graph
        // If the system (not the user) ended us, the UI must say so instead of showing "sharing".
        app.update { if (it.sharing is SharingState.Running) it.copy(sharing = SharingState.Stopped, sync = SyncStatus.Idle) else it }
        super.onDestroy()
    }

    private fun notification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.notification_channel_name), NotificationManager.IMPORTANCE_LOW)
                .apply { description = getString(R.string.notification_channel_description) },
        )
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, SharingService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle(getString(R.string.notification_title))
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, getString(R.string.notification_stop), stop).build())
            .setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    companion object {
        const val ACTION_STOP = "app.piko.android.action.STOP"
        private const val CHANNEL_ID = "sharing"
        private const val NOTIFICATION_ID = 1
        private const val MIN_ATTEMPT_SPACING_MS = 3_000L
        private const val DEBOUNCE_MS = 1_500L

        fun start(context: Context) {
            context.startForegroundService(Intent(context, SharingService::class.java))
        }

        fun stop(context: Context) {
            context.startService(Intent(context, SharingService::class.java).setAction(ACTION_STOP))
        }
    }
}
