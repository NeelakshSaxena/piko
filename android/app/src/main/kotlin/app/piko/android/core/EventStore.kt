package app.piko.android.core

sealed interface EnqueueResult {
    data class Stored(val seq: Long, val droppedToMakeRoom: Int) : EnqueueResult
    data object AlreadyQueued : EnqueueResult
}

/**
 * The durable queue. Implementations must make every call atomic and durable before returning
 * (an event is on disk before any network attempt) and must be safe to use from several threads.
 */
interface EventStore {
    /** Idempotent on `eventId`. Over capacity, the oldest NORMAL-priority QUEUED events are dropped
     *  and counted; CRITICAL events are never dropped to make room. */
    fun enqueue(event: NewEvent, nowMs: Long): EnqueueResult

    /**
     * An unacknowledged in-doubt batch (SUBMITTED) is always returned first, with the same
     * `batchId` and the same events, so a retry is byte-for-byte idempotent. Otherwise claims up to
     * [maxEvents] QUEUED events, CRITICAL first and oldest first, into a new batch.
     */
    fun nextBatch(maxEvents: Int): Batch?

    /**
     * Applies a server acknowledgement. Only ids that belong to [batchId] are touched.
     * accepted/duplicate -> deleted and counted; rejected -> REJECTED with the server's reason;
     * ids the server did not mention go back to QUEUED (a partial ack never loses them).
     */
    fun applyAck(
        batchId: String,
        accepted: Set<String>,
        duplicates: Set<String>,
        rejected: Map<String, String>,
        nowMs: Long,
    )

    /** Retryable server failure: back to QUEUED (new batch id next time) and count an attempt. */
    fun releaseBatch(batchId: String, countAttempt: Boolean)

    /** Permanent failure of the whole batch: keep the events visible as REJECTED. */
    fun rejectBatch(batchId: String, reason: String)

    fun counts(): QueueCounts

    /** Removes everything (used when the device is re-paired so old data is never sent to a new family). */
    fun clear(): Int
}
