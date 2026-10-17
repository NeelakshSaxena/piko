package app.piko.android.core

import java.time.Instant
import kotlin.random.Random

/**
 * SOS and family messages (Phase 6, ADR-022). Pure Kotlin like the rest of `core`.
 *
 * Both are generated on the phone with their own id and stored durably BEFORE anything is sent.
 * The server stores by that id, so re-sending after a lost response can never create a second
 * incident or message. States are never collapsed into one "sent":
 * QUEUED (only on this phone) -> SUBMITTED (a send is in flight, not confirmed) -> DELIVERED (the
 * server durably stored it; it does NOT mean a parent has seen it) -> remote status acknowledged /
 * resolved as reported by the server. FAILED means the server permanently refused it.
 */
enum class CommKind { SOS, MESSAGE }

enum class CommState { QUEUED, SUBMITTED, DELIVERED, FAILED }

class InvalidComm(message: String) : IllegalArgumentException(message)

/** A position the phone has just measured. Never an old reading (the server stamps it with the SOS time). */
data class SosPoint(val latitude: Double, val longitude: Double, val accuracyMeters: Double?) {
    init {
        if (!latitude.isFinite() || latitude !in -90.0..90.0) throw InvalidComm("latitude")
        if (!longitude.isFinite() || longitude !in -180.0..180.0) throw InvalidComm("longitude")
        if (accuracyMeters != null && (!accuracyMeters.isFinite() || accuracyMeters !in 0.0..10000.0)) {
            throw InvalidComm("accuracy")
        }
    }
}

data class NewComm(
    val id: String,
    val kind: CommKind,
    val createdAt: Instant,
    val text: String?,
    val location: SosPoint? = null,
) {
    init {
        if (text != null && text.any(::isForbiddenControl)) throw InvalidComm("control characters")
        when (kind) {
            CommKind.SOS -> if ((text?.length ?: 0) > MAX_SOS_TEXT) throw InvalidComm("sos text too long")
            CommKind.MESSAGE -> {
                if (text.isNullOrBlank()) throw InvalidComm("message is empty")
                if (text.length > MAX_MESSAGE_TEXT) throw InvalidComm("message too long")
                if (location != null) throw InvalidComm("a message carries no location")
            }
        }
    }

    companion object {
        /** The server refuses control characters other than newline, carriage return and tab (audit F-02). */
        fun isForbiddenControl(c: Char): Boolean =
            (c < ' ' && c != '\n' && c != '\r' && c != '\t') || c == '\u007f'

        /** Removes them instead of refusing: an SOS must never fail because of a pasted invisible character. */
        fun sanitize(text: String): String = text.filterNot(::isForbiddenControl)

        const val MAX_SOS_TEXT = 280
        const val MAX_MESSAGE_TEXT = 500
    }
}

data class CommItem(
    val id: String,
    val kind: CommKind,
    val createdAtIso: String,
    val text: String?,
    val location: SosPoint?,
    val state: CommState,
    val attempts: Int,
    val failReason: String?,
    val deliveredAtMs: Long?,
    /** SOS: open / acknowledged / resolved. Message: delivered / acknowledged. Null until DELIVERED. */
    val remoteStatus: String?,
    val acknowledgedAtIso: String?,
    val resolvedAtIso: String?,
) {
    val pending: Boolean get() = state == CommState.QUEUED || state == CommState.SUBMITTED
}

const val POISON_AFTER = 3

/** Higher rank = further along. The server never goes backwards, and neither does what we show. */
internal fun remoteRank(kind: CommKind, status: String?): Int = when (kind) {
    CommKind.SOS -> when (status) { "open" -> 1; "acknowledged" -> 2; "resolved" -> 3; else -> 0 }
    CommKind.MESSAGE -> when (status) { "delivered" -> 1; "acknowledged" -> 2; else -> 0 }
}

/** Durable outbox. Every call is atomic and durable before returning; safe from several threads. */
interface CommStore {
    /** Idempotent on id: returns false if it already exists. */
    fun enqueue(comm: NewComm, nowMs: Long): Boolean

    /**
     * Next item to send: in-doubt (SUBMITTED) and QUEUED, SOS before messages, then oldest first.
     * An item the server has failed on [POISON_AFTER] times goes after every other item, so one bad
     * item cannot block the rest of the outbox (audit F-02). It is still retried, never dropped.
     */
    fun next(): CommItem?

    fun markSubmitted(id: String)

    fun markDelivered(id: String, remoteStatus: String, acknowledgedAtIso: String?, resolvedAtIso: String?, nowMs: Long)

    /** Retryable failure: back to QUEUED; [countAttempt] only orders/diagnoses, nothing is ever dropped. */
    fun release(id: String, countAttempt: Boolean)

    /** Permanent refusal by the server: stays visible as FAILED. */
    fun markFailed(id: String, reason: String)

    /** Applies the server's current status to a DELIVERED item. True only if it moved forward. */
    fun applyRemote(id: String, remoteStatus: String, acknowledgedAtIso: String?, resolvedAtIso: String?): Boolean

    /** Newest first. */
    fun items(limit: Int = 50): List<CommItem>

    fun pendingCount(): Int

    /** Used when the phone is re-paired: old items must never be sent to a different family. */
    fun clear(): Int
}

data class RemoteSos(val id: String, val status: String, val acknowledgedAtIso: String?, val resolvedAtIso: String?)

data class RemoteMessage(
    val id: String,
    val body: String,
    val sentAtIso: String,
    val receivedAtIso: String,
    val status: String,
)

/** What the server says about a message this phone sent (for example: a parent marked it as seen). */
data class RemoteMessageStatus(val id: String, val status: String, val acknowledgedAtIso: String?)

sealed interface CommResult {
    /** 200/201: the server durably stored it (a replay answers 200 with the stored state). */
    data class Delivered(val remoteStatus: String, val acknowledgedAtIso: String?, val resolvedAtIso: String?) : CommResult

    data class Network(val cause: String) : CommResult
    data class RateLimited(val retryAfterSeconds: Long?) : CommResult
    data class ServerError(val status: Int) : CommResult
    data object Unauthorized : CommResult
    data class Refused(val status: Int, val code: String?) : CommResult
}

sealed interface Fetch<out T> {
    data class Ok<T>(val value: T) : Fetch<T>
    data object Unavailable : Fetch<Nothing>
    data object Unauthorized : Fetch<Nothing>
}

interface CommTransport {
    fun deliver(item: CommItem): CommResult
    fun fetchSos(): Fetch<List<RemoteSos>>

    /** Messages from parents to this phone. */
    fun fetchParentMessages(): Fetch<List<RemoteMessage>>

    /** The server's current status of the messages this phone sent. */
    fun fetchOwnMessages(): Fetch<List<RemoteMessageStatus>>

    /** The child confirms it saw a parent's message. */
    fun acknowledgeMessage(id: String): CommResult
}

/** What changed when remote state was pulled in: only genuinely new information. */
data class RefreshResult(
    val parentMessages: List<RemoteMessage>,
    /** SOS ids whose status moved forward, with the new status (for a notification). */
    val sosAdvanced: List<Pair<String, String>>,
)

sealed interface RefreshOutcome {
    data class Ok(val result: RefreshResult) : RefreshOutcome
    data object Unavailable : RefreshOutcome
    data object CredentialRevoked : RefreshOutcome
}

/**
 * Sends the outbox. Rules (unit-tested): SOS go first; an item leaves QUEUED/SUBMITTED only when the
 * server answered that it stored it (or permanently refused it); a lost response leaves the item
 * SUBMITTED and the identical id is re-sent, which the server de-duplicates; retries back off
 * exponentially with jitter; nothing retryable is ever dropped.
 */
class CommEngine(
    private val store: CommStore,
    private val transport: CommTransport,
    private val clock: Clock,
    private val random: Random = Random.Default,
    private val config: SyncConfig = SyncConfig(),
) {
    private var consecutiveFailures = 0

    fun drain(): SyncOutcome {
        var delivered = 0
        repeat(MAX_PER_RUN) {
            val item = store.next() ?: return SyncOutcome.Done(delivered, false)
            store.markSubmitted(item.id)
            when (val result = transport.deliver(item)) {
                is CommResult.Delivered -> {
                    store.markDelivered(item.id, result.remoteStatus, result.acknowledgedAtIso, result.resolvedAtIso, clock.nowMs())
                    delivered++
                    consecutiveFailures = 0
                }
                // In doubt: left SUBMITTED, the same id is sent again.
                is CommResult.Network -> return retry(RetryReason.NETWORK, null)
                is CommResult.RateLimited -> {
                    store.release(item.id, countAttempt = false)
                    return retry(RetryReason.RATE_LIMITED, result.retryAfterSeconds)
                }
                is CommResult.ServerError -> {
                    store.release(item.id, countAttempt = true)
                    return retry(RetryReason.SERVER_ERROR, null)
                }
                CommResult.Unauthorized -> return SyncOutcome.CredentialRevoked
                is CommResult.Refused ->
                    store.markFailed(item.id, "refused by server (HTTP ${result.status}${result.code?.let { " $it" } ?: ""})")
            }
        }
        return SyncOutcome.Done(delivered, moreWaiting = true)
    }

    /** Pulls the server's view: SOS status changes and parents' messages. Never invents state. */
    fun refresh(): RefreshOutcome {
        val sos = when (val r = transport.fetchSos()) {
            is Fetch.Ok -> r.value
            Fetch.Unavailable -> return RefreshOutcome.Unavailable
            Fetch.Unauthorized -> return RefreshOutcome.CredentialRevoked
        }
        val advanced = ArrayList<Pair<String, String>>()
        for (remote in sos) {
            if (store.applyRemote(remote.id, remote.status, remote.acknowledgedAtIso, remote.resolvedAtIso)) {
                advanced += remote.id to remote.status
            }
        }
        // Best effort: a failure here must not hide parents' messages or SOS news already gathered.
        when (val own = transport.fetchOwnMessages()) {
            is Fetch.Ok -> own.value.forEach { store.applyRemote(it.id, it.status, it.acknowledgedAtIso, null) }
            Fetch.Unauthorized -> return RefreshOutcome.CredentialRevoked
            Fetch.Unavailable -> Unit
        }
        val messages = when (val r = transport.fetchParentMessages()) {
            is Fetch.Ok -> r.value
            Fetch.Unavailable -> return RefreshOutcome.Ok(RefreshResult(emptyList(), advanced))
            Fetch.Unauthorized -> return RefreshOutcome.CredentialRevoked
        }
        return RefreshOutcome.Ok(RefreshResult(messages, advanced))
    }

    private fun retry(reason: RetryReason, retryAfterSeconds: Long?): SyncOutcome.RetryAfter {
        consecutiveFailures++
        return SyncOutcome.RetryAfter(
            Backoff.delayMs(consecutiveFailures, config, random, retryAfterSeconds),
            reason,
        )
    }

    private companion object {
        const val MAX_PER_RUN = 50
    }
}

/** Request bodies for `POST /sos/incidents` and `POST /messages`. */
object CommCodec {
    fun sos(deviceId: String, item: CommItem): String = buildString {
        append("{\"incident_id\":").append(str(item.id))
        append(",\"device_id\":").append(str(deviceId))
        append(",\"triggered_at\":").append(str(item.createdAtIso))
        item.text?.let { append(",\"message\":").append(str(it)) }
        item.location?.let {
            append(",\"location\":{\"latitude\":").append(fmt(it.latitude, 7))
            append(",\"longitude\":").append(fmt(it.longitude, 7))
            it.accuracyMeters?.let { a -> append(",\"accuracy_meters\":").append(fmt(a, 2)) }
            append('}')
        }
        append('}')
    }

    fun message(item: CommItem): String =
        "{\"message_id\":${str(item.id)},\"body\":${str(item.text.orEmpty())},\"sent_at\":${str(item.createdAtIso)}}"

    /** User-typed text goes through here, so every control character is escaped. */
    internal fun str(value: String): String = buildString {
        append('"')
        for (c in value) {
            when {
                c == '"' || c == '\\' -> append('\\').append(c)
                c < ' ' -> append(String.format("\\u%04x", c.code))
                else -> append(c)
            }
        }
        append('"')
    }
}

enum class Tone { PENDING, OK, WARN, BAD }

data class CommLabel(val text: String, val tone: Tone)

/**
 * The only place that turns delivery state into words, so the screen cannot say "sent" for
 * something that is only queued, or "seen" for something only stored.
 */
object CommLabels {
    fun of(item: CommItem): CommLabel = when (item.kind) {
        CommKind.SOS -> sos(item)
        CommKind.MESSAGE -> message(item)
    }

    private fun sos(item: CommItem): CommLabel = when (item.state) {
        CommState.QUEUED ->
            CommLabel("Saved on this phone. NOT sent yet. It will be sent when there is a connection.", Tone.WARN)
        CommState.SUBMITTED ->
            CommLabel("Saved on this phone. Sending… the server has not answered yet, so it will be retried.", Tone.WARN)
        CommState.DELIVERED -> when (item.remoteStatus) {
            "acknowledged" -> CommLabel("A parent confirmed they saw your SOS.", Tone.OK)
            "resolved" -> CommLabel("A parent marked this SOS as resolved.", Tone.OK)
            else -> CommLabel("Delivered to your family's Piko server. No parent has confirmed seeing it yet.", Tone.PENDING)
        }
        CommState.FAILED ->
            CommLabel("Could not be sent (${item.failReason ?: "refused"}). Contact your family another way.", Tone.BAD)
    }

    private fun message(item: CommItem): CommLabel = when (item.state) {
        CommState.QUEUED -> CommLabel("Saved on this phone, not sent yet", Tone.WARN)
        CommState.SUBMITTED -> CommLabel("Sending…", Tone.WARN)
        CommState.DELIVERED ->
            if (item.remoteStatus == "acknowledged") CommLabel("Seen by a parent", Tone.OK)
            else CommLabel("Delivered to the server, not yet seen", Tone.PENDING)
        CommState.FAILED -> CommLabel("Not sent (${item.failReason ?: "refused"})", Tone.BAD)
    }
}

/**
 * Which position an SOS may carry. The server stamps a position sent with an SOS with the SOS time,
 * so only a fix measured moments ago qualifies; anything older is left out and the server attaches
 * its latest known position under that position's own, honest capture time.
 */
object SosLocationPolicy {
    const val MAX_FIX_AGE_MS = 2 * 60_000L

    fun attachable(fix: SosPoint?, capturedAtMs: Long?, nowMs: Long): SosPoint? =
        if (fix != null && capturedAtMs != null && nowMs - capturedAtMs in 0..MAX_FIX_AGE_MS) fix else null
}
