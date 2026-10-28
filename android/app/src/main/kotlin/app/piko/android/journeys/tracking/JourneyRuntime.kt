package app.piko.android.journeys.tracking

import android.content.Context
import app.piko.android.collect.ConnectivityMonitor
import app.piko.android.graph
import app.piko.android.journeys.data.JourneySync
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant

/** What the location part of following is really doing, for the screen. Not persisted: a new process starts at "not running". */
data class TrackerStatus(
    val detecting: Boolean = false,
    /** Why detection is not running although the user asked for it, in words for the user. */
    val note: String? = null,
    val lastFixAtMs: Long? = null,
    val lastAccuracyM: Double? = null,
)

/**
 * Process-wide observers that exist only while a journey is being followed. Connectivity is watched so a
 * return of the network is recorded and a waiting backup is sent. It only runs while this process is alive; after a
 * process death the sync job (which waits for a network) does the sending, and no "network restored" event is
 * invented for the time in between.
 */
object JourneyRuntime {
    private val _status = MutableStateFlow(TrackerStatus())
    val status: StateFlow<TrackerStatus> = _status.asStateFlow()

    private var monitor: ConnectivityMonitor? = null
    private var wasOnline: Boolean? = null

    fun update(change: (TrackerStatus) -> TrackerStatus) {
        _status.value = change(_status.value)
    }

    /** Starts or stops the observers to match the stored session. Safe to call any time. */
    @Synchronized
    fun ensure(context: Context) {
        val app = context.applicationContext
        val following = app.graph.journeys.followed()?.state == TrackingState.ACTIVE
        if (following && monitor == null) {
            wasOnline = null
            monitor = ConnectivityMonitor(app) { _, online -> onNetwork(app, online) }.also { it.start() }
        } else if (!following) {
            monitor?.stop()
            monitor = null
            wasOnline = null
        }
    }

    private fun onNetwork(context: Context, online: Boolean) {
        val previous = wasOnline
        wasOnline = online
        if (online && previous == false) {
            val graph = context.graph
            TrackingController(graph.journeys, graph.journeys, { graph.journeyPrefs.backupEnabled }).networkRestored(Instant.ofEpochMilli(graph.clock.nowMs()))
            JourneySync.request(context)
        }
    }
}
