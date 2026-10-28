package app.piko.android.journeys.tracking

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
import androidx.core.content.ContextCompat
import app.piko.android.collect.BatteryCollector
import app.piko.android.collect.LocationCollector
import app.piko.android.collect.hasPreciseLocation
import app.piko.android.core.ModePlan
import app.piko.android.graph
import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.ArrivalPolicy
import app.piko.android.journeys.domain.ArrivalVerdict
import app.piko.android.journeys.domain.BatteryPolicy
import app.piko.android.journeys.domain.Fix
import app.piko.android.journeys.domain.GeoPoint
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingResult
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.ui.MainActivity
import java.util.concurrent.Executors

/**
 * Notices arrival by location, and only while the user is following a journey and chose "use this phone's
 * location". It runs as a visible foreground service with a Pause and a Stop action, reads no position unless
 * the current leg has a destination the user picked, keeps the last few readings in memory only (no trail is
 * stored), and is never restarted by the system on its own (`START_NOT_STICKY`): after a kill the screen says it is
 * not running and offers a restart. A reading is never taken as arrival by itself (see [ArrivalPolicy]).
 */
class JourneyTrackingService : Service() {
    private val worker = Executors.newSingleThreadExecutor()
    private val fixes = ArrayDeque<Fix>()
    private var collector: LocationCollector? = null
    private var battery: BatteryCollector? = null
    private var batteryOk = true
    private var running = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == null) {
            // Started with startForegroundService: Android requires this promptly, even if we then decide to stop.
            try {
                startForeground(NOTIFICATION_ID, notification("Following your journey. Watching for arrival."), ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            } catch (_: SecurityException) {
                stopSelf() // location permission was withdrawn between the check and now
                return START_NOT_STICKY
            }
        }
        val journeyId = graph.journeys.followed()?.journeyId
        when (intent?.action) {
            ACTION_PAUSE -> if (journeyId != null) worker.execute { JourneyActions.pause(applicationContext, journeyId) }
            ACTION_STOP -> if (journeyId != null) worker.execute { JourneyActions.stop(applicationContext, journeyId) }
        }
        val session = graph.journeys.followed()
        val wanted = session != null && session.state == TrackingState.ACTIVE && session.locationDetection && hasPreciseLocation()
        if (!wanted || intent?.action == ACTION_PAUSE || intent?.action == ACTION_STOP) {
            shutDown()
            return START_NOT_STICKY
        }
        if (!running) {
            running = true
            battery = BatteryCollector(this) { percent, charging -> worker.execute { onBattery(percent, charging) } }.also { it.start() }
            startLocation()
        }
        return START_NOT_STICKY
    }

    private fun startLocation() {
        val started = collector?.start(PLAN) ?: LocationCollector(this) { onFix(it) }.also { collector = it }.start(PLAN)
        JourneyRuntime.update {
            it.copy(
                detecting = started && batteryOk,
                note = if (!started) "No location source is available." else if (!batteryOk) "Paused: battery is low." else null,
            )
        }
    }

    private fun onBattery(percent: Int, charging: Boolean) {
        val allowed = BatteryPolicy.allowsLocation(percent, charging, batteryOk)
        if (allowed == batteryOk) return
        batteryOk = allowed
        if (allowed) {
            startLocation()
        } else {
            collector?.stop()
            JourneyRuntime.update { it.copy(detecting = false, note = "Paused: battery is low. Confirm arrivals yourself, or charge your phone.") }
            JourneyNotifier.notifyOnce(
                this, "battery:${graph.journeys.followed()?.journeyId}:${graph.clock.nowMs() / 3_600_000}", "Location detection paused",
                "Your battery is low, so Piko stopped using your location. You can still confirm each arrival yourself.",
            )
        }
    }

    private fun onFix(location: Location) {
        worker.execute {
            val g = graph
            val session = g.journeys.followed()?.takeIf { it.state == TrackingState.ACTIVE } ?: return@execute
            fixes.addLast(Fix(GeoPoint(location.latitude, location.longitude), if (location.hasAccuracy()) location.accuracy.toDouble() else null, location.time))
            while (fixes.size > MAX_FIXES) fixes.removeFirst()
            JourneyRuntime.update { it.copy(lastFixAtMs = location.time, lastAccuracyM = if (location.hasAccuracy()) location.accuracy.toDouble() else null) }
            val journey = g.journeys.get(session.journeyId) ?: return@execute
            val current = TrackingController(g.journeys, g.journeys).progress(journey).current ?: return@execute
            val target = current.destinationPoint
            if (target == null) {
                JourneyRuntime.update { it.copy(note = "This leg has no destination position, so arrival is confirmed by you.") }
                return@execute
            }
            when (val verdict = ArrivalPolicy.evaluate(target, fixes.toList(), g.clock.nowMs())) {
                ArrivalVerdict.Arrived -> {
                    val result = JourneyActions.confirmArrival(applicationContext, session.journeyId, current.id, ArrivalBasis.DETECTED)
                    fixes.clear()
                    if (result is TrackingResult.Ok) {
                        JourneyNotifier.notifyOnce(
                            this, "arrived:${session.journeyId}:${current.id}",
                            if (result.completed) "Journey complete" else "Arrival noticed",
                            "Piko noticed you reached ${current.destination} using your phone's location. If that is wrong, open Piko.",
                        )
                        if (result.completed) shutDown()
                    }
                }
                ArrivalVerdict.NotYet -> JourneyRuntime.update { it.copy(note = null) }
                is ArrivalVerdict.Uncertain -> JourneyRuntime.update { it.copy(note = verdict.reason + " Arrival is not assumed.") }
            }
        }
    }

    private fun shutDown() {
        collector?.stop()
        battery?.stop()
        collector = null
        battery = null
        running = false
        fixes.clear()
        JourneyRuntime.update { it.copy(detecting = false) }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        collector?.stop()
        battery?.stop()
        JourneyRuntime.update { it.copy(detecting = false) }
        worker.shutdown()
        super.onDestroy()
    }

    private fun notification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Following a journey", NotificationManager.IMPORTANCE_LOW)
                .apply { description = "Shown while Piko uses your location to notice arrival" },
        )
        fun action(name: String, label: String, code: Int) = Notification.Action.Builder(
            null, label,
            PendingIntent.getService(this, code, Intent(this, JourneyTrackingService::class.java).setAction(name), PendingIntent.FLAG_IMMUTABLE),
        ).build()
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN, JourneyNotifier.OPEN)
                .setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle("Piko is using your location")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(action(ACTION_PAUSE, "Pause", 1))
            .addAction(action(ACTION_STOP, "Stop following", 2))
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .build()
    }

    companion object {
        private const val CHANNEL = "journey_tracking"
        private const val NOTIFICATION_ID = 31
        private const val MAX_FIXES = 12
        const val ACTION_PAUSE = "app.piko.android.journeys.PAUSE"
        const val ACTION_STOP = "app.piko.android.journeys.STOP"

        // Balanced power, a reading about a minute apart or every 25 m: enough for a 2-minute dwell, no GPS burst.
        private val PLAN = ModePlan(syncIntervalMs = 60_000, locationIntervalMs = 60_000, minDistanceMeters = 25f, highAccuracy = false, flushOnEvent = false)

        /** Starts the service if the stored session wants location, otherwise stops it. */
        fun sync(context: Context) {
            val app = context.applicationContext
            val s = app.graph.journeys.followed()
            val intent = Intent(app, JourneyTrackingService::class.java)
            if (s != null && s.state == TrackingState.ACTIVE && s.locationDetection && app.hasPreciseLocation()) {
                ContextCompat.startForegroundService(app, intent)
            } else {
                app.stopService(intent)
            }
        }
    }
}
