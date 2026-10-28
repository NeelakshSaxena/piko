package app.piko.android.journeys.tracking

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.provider.Settings
import app.piko.android.graph
import app.piko.android.journeys.data.JourneySync
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.domain.TransportMode
import java.time.Instant

/**
 * Offline flight mode, the part that can be done honestly: while a FLIGHT leg is the current one and backup is on,
 * Android is asked to run a small job about every 20 minutes. It stores one reading (battery, charging, whether the
 * phone has a working connection, whether airplane mode is on) on the phone and sends the readings when a connection is
 * back. No location is read here. Android decides when the job really runs: it can be late, skipped in power saving,
 * or not run at all after a force-stop, and nothing here is described as exact.
 */
object JourneyObservations {
    private const val JOB_ID = 6003
    private const val PERIOD_MS = 20 * 60_000L
    private const val MAX_WAITING = 300

    /** Schedules the periodic job if the stored state calls for it, otherwise cancels it. */
    fun reconcile(context: Context) {
        val app = context.applicationContext
        val scheduler = app.getSystemService(JobScheduler::class.java)
        if (wanted(app)) {
            val job = JobInfo.Builder(JOB_ID, ComponentName(app, JourneyObservationJobService::class.java))
                .setPeriodic(PERIOD_MS)
                .setRequiresBatteryNotLow(true) // a low battery is the one time a sample is not worth taking
                .setPersisted(true)
                .build()
            // Keep an existing schedule so a re-check does not push the next run back.
            if (scheduler.getPendingJob(JOB_ID) == null) scheduler.schedule(job)
        } else {
            scheduler.cancel(JOB_ID)
        }
    }

    private fun currentLegIsFlight(context: Context, journeyId: String): Boolean {
        val graph = context.graph
        val journey = graph.journeys.get(journeyId) ?: return false
        return TrackingController(graph.journeys, graph.journeys).progress(journey).current?.mode == TransportMode.FLIGHT
    }

    private fun wanted(context: Context): Boolean {
        val graph = context.graph
        val s = graph.journeys.followed() ?: return false
        return s.state == TrackingState.ACTIVE && graph.journeyPrefs.backupEnabled && currentLegIsFlight(context, s.journeyId)
    }

    /** Stores one reading if the state still calls for it. Returns whether one was stored. */
    fun record(context: Context): Boolean {
        val graph = context.graph
        if (!wanted(context)) return false
        val journeyId = graph.journeys.followed()?.journeyId ?: return false
        if (graph.journeys.pendingEvents(journeyId, MAX_WAITING + 1).size > MAX_WAITING) return false // bounded queue
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val status = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val caps = manager.getNetworkCapabilities(manager.activeNetwork)
        val data = buildMap<String, Any?> {
            if (level >= 0 && scale > 0) put("battery_percent", (level * 100f / scale).toInt().coerceIn(0, 100))
            put("charging", status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL)
            put("connected", caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true)
            put("airplane_mode", Settings.Global.getInt(context.contentResolver, Settings.Global.AIRPLANE_MODE_ON, 0) == 1)
        }
        TrackingController(graph.journeys, graph.journeys, { graph.journeyPrefs.backupEnabled })
            .record(journeyId, "observation", Instant.ofEpochMilli(graph.clock.nowMs()), data)
        return true
    }
}

class JourneyObservationJobService : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        Thread {
            try {
                if (JourneyObservations.record(applicationContext)) JourneySync.request(applicationContext)
            } finally {
                jobFinished(params, false)
            }
        }.start()
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean = false // the next period takes another reading
}
