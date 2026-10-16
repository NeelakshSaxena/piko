package app.piko.android.core

import kotlin.random.Random

data class SyncConfig(
    val maxBatchEvents: Int = 100,
    /** Bounds the work of one run so a large backlog cannot monopolise the radio or the thread. */
    val maxBatchesPerRun: Int = 20,
    /** A single event that fails this many times while the server is healthy is given up on. */
    val maxAttempts: Int = 10,
    val baseBackoffMs: Long = 5_000,
    val maxBackoffMs: Long = 15 * 60_000,
    /** A server that acknowledged something this recently is considered up when judging poison events. */
    val healthyWindowMs: Long = 10 * 60_000,
)

enum class RetryReason { NETWORK, RATE_LIMITED, SERVER_ERROR }

sealed interface SyncOutcome {
    /** No failure. [moreWaiting] means the per-run bound was hit and more batches are queued. */
    data class Done(val acknowledged: Int, val moreWaiting: Boolean) : SyncOutcome

    data class RetryAfter(val delayMs: Long, val reason: RetryReason) : SyncOutcome

    /** The server no longer accepts this device. Nothing was deleted; sending must stop. */
    data object CredentialRevoked : SyncOutcome
}

/**
 * Drains the durable queue through a [Transport]. Rules, all covered by unit tests:
 *  - an event is deleted only when the server acknowledged it (accepted or duplicate);
 *  - an in-doubt batch (network failure) is re-sent unchanged, so retries are idempotent;
 *  - a partial ack never loses the unmentioned events;
 *  - retries back off exponentially with jitter up to a cap; rate limits honour Retry-After;
 *  - a server error halves the batch size to isolate a poison event, which is only given up on
 *    while the server is otherwise acknowledging events (an outage never costs data);
 *  - events are never rewritten: `occurred_at` is whatever was captured.
 */
class SyncEngine(
    private val store: EventStore,
    private val transport: Transport,
    private val clock: Clock,
    private val random: Random = Random.Default,
    private val config: SyncConfig = SyncConfig(),
) {
    private var consecutiveFailures = 0
    private var batchLimit = config.maxBatchEvents
    private var lastAckMs: Long? = null
    private val strikes = HashMap<String, Int>()

    fun syncOnce(): SyncOutcome {
        var acknowledged = 0
        repeat(config.maxBatchesPerRun) {
            val batch = store.nextBatch(batchLimit) ?: return SyncOutcome.Done(acknowledged, false)
            when (val result = transport.send(batch)) {
                is SendResult.Ack -> {
                    store.applyAck(batch.batchId, result.accepted, result.duplicates, result.rejected, clock.nowMs())
                    val done = batch.events.count { it.eventId in result.accepted || it.eventId in result.duplicates }
                    acknowledged += done
                    if (done > 0) lastAckMs = clock.nowMs()
                    consecutiveFailures = 0
                    batchLimit = minOf(config.maxBatchEvents, batchLimit * 2)
                }
                // In doubt: leave the batch SUBMITTED so the identical batch is retried.
                is SendResult.Network -> return retryAfter(RetryReason.NETWORK, null)
                is SendResult.RateLimited -> return retryAfter(RetryReason.RATE_LIMITED, result.retryAfterSeconds)
                is SendResult.ServerError -> {
                    handleServerError(batch)
                    return retryAfter(RetryReason.SERVER_ERROR, null)
                }
                SendResult.Unauthorized -> return SyncOutcome.CredentialRevoked
                is SendResult.Refused ->
                    store.rejectBatch(batch.batchId, "refused by server (HTTP ${result.status}${result.code?.let { " $it" } ?: ""})")
            }
        }
        return SyncOutcome.Done(acknowledged, moreWaiting = true)
    }

    private fun handleServerError(batch: Batch) {
        val single = batch.events.size == 1
        if (single) {
            val serverHealthy = lastAckMs?.let { clock.nowMs() - it <= config.healthyWindowMs } == true
            val id = batch.events.first().eventId
            // A strike only counts while the server is acknowledging other events; an outage
            // (nothing acknowledged) therefore never costs data, however long it lasts.
            val count = if (serverHealthy) (strikes.merge(id, 1, Int::plus) ?: 1) else (strikes[id] ?: 0)
            if (count >= config.maxAttempts) {
                strikes.remove(id)
                store.rejectBatch(batch.batchId, "server failed on this event $count times")
                return
            }
        }
        // Attempts only order the queue (repeat offenders go last), so they always count.
        store.releaseBatch(batch.batchId, countAttempt = single)
        batchLimit = maxOf(1, batch.events.size / 2)
    }

    /** Exponential backoff with equal jitter: half the delay is fixed, half is random. */
    private fun retryAfter(reason: RetryReason, retryAfterSeconds: Long?): SyncOutcome.RetryAfter {
        consecutiveFailures++
        val exponent = minOf(consecutiveFailures - 1, 30)
        val ceiling = minOf(config.maxBackoffMs, config.baseBackoffMs shl exponent)
        val jittered = ceiling / 2 + random.nextLong(ceiling / 2 + 1)
        val server = retryAfterSeconds?.let { (it * 1000).coerceIn(1_000, config.maxBackoffMs) } ?: 0
        return SyncOutcome.RetryAfter(maxOf(jittered, server), reason)
    }
}
