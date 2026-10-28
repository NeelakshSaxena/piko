package app.piko.android.journeys.data

import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import app.piko.android.comms.CommsRunner
import app.piko.android.graph
import app.piko.android.journeys.domain.JourneySyncEngine
import app.piko.android.journeys.domain.JourneySyncOutcome
import app.piko.android.net.ApiClient

/**
 * Triggers for journey backup: after the user saves or deletes, when the Journeys screen opens, and a
 * JobScheduler job that waits for a network while work remains. Never sends anything unless the user turned
 * backup on, except deletes of journeys the server already holds.
 */
object JourneySync {
    private val lock = Any()
    private const val JOB_ID = 6002
    private const val EVENT_KEEP_DAYS = 30L // undelivered events older than this are dropped; delivered ones go at once

    /** Where the last run ended, for the UI. Null: not run in this process. */
    @Volatile var lastOutcome: JourneySyncOutcome? = null
        private set

    private fun hasWork(context: Context): Boolean {
        val graph = context.graph
        return graph.journeys.pendingDeletes().isNotEmpty() ||
            (graph.journeyPrefs.backupEnabled && (graph.journeys.dirty().isNotEmpty() || graph.journeys.journeysWithPendingEvents().isNotEmpty()))
    }

    /** Call from the UI after a change. Returns immediately; the work runs on its own thread. */
    fun request(context: Context) {
        val app = context.applicationContext
        if (!hasWork(app)) return
        schedule(app)
        Thread { runOnce(app) }.start()
    }

    private fun schedule(context: Context) {
        val job = JobInfo.Builder(JOB_ID, ComponentName(context, JourneySyncJobService::class.java))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setPersisted(true)
            .setBackoffCriteria(30_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
            .build()
        context.getSystemService(JobScheduler::class.java).schedule(job)
    }

    /** True if the run was cut short and should be repeated later. */
    fun runOnce(context: Context): Boolean = synchronized(lock) {
        val graph = context.graph
        val enrollment = graph.vault.load() ?: return false
        if (graph.vault.credentialRevoked) return false
        val engine = JourneySyncEngine(
            graph.journeys,
            graph.journeys,
            ApiJourneyTransport(ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential)),
        ) { graph.journeyPrefs.backupEnabled }
        graph.journeys.pruneEvents(java.time.Instant.ofEpochMilli(graph.clock.nowMs()).minusSeconds(EVENT_KEEP_DAYS * 86_400))
        val outcome = engine.drain()
        lastOutcome = outcome
        when (outcome) {
            JourneySyncOutcome.RetryLater -> true
            JourneySyncOutcome.CredentialRevoked -> {
                CommsRunner.revoke(context)
                context.getSystemService(JobScheduler::class.java).cancel(JOB_ID)
                false
            }
            is JourneySyncOutcome.Done -> {
                if (!hasWork(context)) context.getSystemService(JobScheduler::class.java).cancel(JOB_ID)
                false
            }
        }
    }
}
