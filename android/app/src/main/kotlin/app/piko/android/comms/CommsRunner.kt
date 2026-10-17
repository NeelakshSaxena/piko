package app.piko.android.comms

import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import app.piko.android.CommsView
import app.piko.android.SharingState
import app.piko.android.core.CommEngine
import app.piko.android.core.CommKind
import app.piko.android.core.CommResult
import app.piko.android.core.InvalidComm
import app.piko.android.core.NewComm
import app.piko.android.core.RefreshOutcome
import app.piko.android.core.SosLocationPolicy
import app.piko.android.core.SosPoint
import app.piko.android.core.SyncOutcome
import app.piko.android.graph
import app.piko.android.net.ApiClient
import app.piko.android.push.PushSupport
import java.time.Instant
import java.util.UUID

/**
 * Glue between the durable outbox and the network. Everything that sends or fetches goes through
 * [runOnce], which is serialised so the app, the job and the sharing service cannot interleave.
 *
 * What triggers it (all documented in ADR-022, none of them a guarantee):
 *  - right after the user sends (immediate attempt);
 *  - a JobScheduler job that waits for ANY network and survives process death and reboot, backed
 *    off by the system until the outbox is empty;
 *  - the open app (every 30 s while visible) and the sharing service's sync loop.
 * With the app closed and sharing off, only the job runs: replies from parents are NOT fetched
 * then, and the UI says so.
 */
object CommsRunner {
    private val lock = Any()
    private const val JOB_ID = 6001
    private const val REFRESH_SPACING_MS = 30_000L

    /** When the server's state was last read successfully (0 = never in this process). */
    @Volatile var lastRefreshMs = 0L
        private set

    data class SendResultInfo(val accepted: Boolean, val reason: String? = null)

    /** Stores an SOS durably FIRST, then tries to send. Returns before the network answers. */
    fun submitSos(context: Context, text: String?): SendResultInfo {
        val graph = context.graph
        val now = graph.clock.nowMs()
        val snapshot = graph.runtime.value
        // Only a position measured moments ago is attached (see SosLocationPolicy).
        val point: SosPoint? = SosLocationPolicy.attachable(snapshot.lastFix, snapshot.lastLocationAtMs, now)
        val note = text?.let(NewComm::sanitize)?.trim()?.ifEmpty { null }
        return try {
            submit(context, NewComm(UUID.randomUUID().toString(), CommKind.SOS, Instant.ofEpochMilli(now), note, point))
        } catch (e: InvalidComm) {
            SendResultInfo(false, "The note cannot be sent. Remove it and try again.")
        }
    }

    fun submitMessage(context: Context, text: String): SendResultInfo {
        val now = context.graph.clock.nowMs()
        return try {
            submit(context, NewComm(UUID.randomUUID().toString(), CommKind.MESSAGE, Instant.ofEpochMilli(now), NewComm.sanitize(text).trim(), null))
        } catch (e: InvalidComm) {
            SendResultInfo(false, validate(CommKind.MESSAGE, text) ?: "That cannot be sent.")
        }
    }

    private fun submit(context: Context, comm: NewComm): SendResultInfo {
        val graph = context.graph
        if (graph.vault.load() == null) return SendResultInfo(false, "This phone is not linked to a family.")
        if (graph.vault.credentialRevoked) {
            return SendResultInfo(false, "This phone was unlinked, so nothing can be sent. Link it again first.")
        }
        graph.comms.enqueue(comm, graph.clock.nowMs()) // on disk before any network attempt
        schedule(context)
        Thread { runOnce(context, forceRefresh = true) }.start()
        return SendResultInfo(true)
    }

    /** Makes sure the system will run [OutboxJobService] once a network exists. Idempotent. */
    fun schedule(context: Context) {
        val scheduler = context.getSystemService(JobScheduler::class.java)
        val job = JobInfo.Builder(JOB_ID, ComponentName(context, OutboxJobService::class.java))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setPersisted(true)
            .setBackoffCriteria(30_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
            .build()
        scheduler.schedule(job)
    }

    private fun cancelJob(context: Context) = context.getSystemService(JobScheduler::class.java).cancel(JOB_ID)

    /**
     * Sends whatever is pending, then (rate-limited) pulls the server's view. Returns true if more
     * work remains and the caller should be run again (the job reports this to the system).
     */
    fun runOnce(context: Context, forceRefresh: Boolean = false): Boolean = synchronized(lock) {
        val graph = context.graph
        val enrollment = graph.vault.load() ?: return false
        if (graph.vault.credentialRevoked) return false
        PushSupport.syncToken(context) // a token that rotated while offline reaches the server on the next run
        val client = ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential)
        val engine = CommEngine(graph.comms, client, graph.clock)
        when (engine.drain()) {
            is SyncOutcome.RetryAfter -> return true
            SyncOutcome.CredentialRevoked -> {
                revoke(context)
                return false
            }
            is SyncOutcome.Done -> Unit
        }
        val now = graph.clock.nowMs()
        if (forceRefresh || now - lastRefreshMs >= REFRESH_SPACING_MS) {
            when (val refreshed = engine.refresh()) {
                is RefreshOutcome.Ok -> {
                    lastRefreshMs = now
                    graph.setParentMessages(CommsView(refreshed.result.parentMessages, now))
                    CommsNotifier.announce(context, refreshed.result)
                }
                RefreshOutcome.Unavailable -> Unit
                RefreshOutcome.CredentialRevoked -> {
                    revoke(context)
                    return false
                }
            }
        }
        val more = graph.comms.pendingCount() > 0
        if (!more) cancelJob(context)
        more
    }

    /** The child sees a parent's message and says so. Returns an error message, or null on success. */
    fun acknowledgeMessage(context: Context, id: String): String? {
        val graph = context.graph
        val enrollment = graph.vault.load() ?: return "This phone is not linked to a family."
        val client = ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential)
        return when (val r = client.acknowledgeMessage(id)) {
            is CommResult.Delivered -> {
                runOnce(context, forceRefresh = true)
                null
            }
            is CommResult.Network -> "No connection. Try again when you are online."
            CommResult.Unauthorized -> { revoke(context); "This phone was unlinked." }
            else -> "The server could not record that (${r.javaClass.simpleName})."
        }
    }

    private fun revoke(context: Context) {
        val graph = context.graph
        graph.vault.credentialRevoked = true
        graph.vault.sharingRequested = false
        graph.update { it.copy(sharing = SharingState.CredentialRevoked) }
        cancelJob(context)
    }

    /** Validation errors from the UI layer are shown as text, never crash. */
    fun validate(kind: CommKind, text: String?): String? = try {
        NewComm("x", kind, Instant.EPOCH, text?.trim())
        null
    } catch (e: InvalidComm) {
        when (e.message) {
            "message is empty" -> "Write a message first."
            "message too long" -> "Messages can be at most ${NewComm.MAX_MESSAGE_TEXT} characters."
            "sos text too long" -> "The note can be at most ${NewComm.MAX_SOS_TEXT} characters."
            "control characters" -> "That contains characters Piko cannot send."
            else -> "That cannot be sent."
        }
    }
}
