package app.piko.android.core

import java.util.UUID

/** Test fake with the same observable behaviour as SqliteEventStore (see EventStoreContract). */
class InMemoryEventStore(private val capacity: Int = 1_000) : EventStore {
    private data class Row(
        val seq: Long,
        val event: NewEvent,
        var state: DeliveryState = DeliveryState.QUEUED,
        var attempts: Int = 0,
        var batchId: String? = null,
        var reason: String? = null,
    )

    private val rows = ArrayList<Row>()
    private var nextSeq = 1L
    private var dropped = 0L
    private var acked = 0L
    private var lastAck: Long? = null

    @Synchronized override fun enqueue(event: NewEvent, nowMs: Long): EnqueueResult {
        if (rows.any { it.event.eventId == event.eventId }) return EnqueueResult.AlreadyQueued
        val row = Row(nextSeq++, event)
        rows += row
        var droppedNow = 0
        while (rows.size > capacity) {
            val victim = rows.firstOrNull { it.state == DeliveryState.QUEUED && it.event.priority == EventPriority.NORMAL } ?: break
            rows -= victim
            droppedNow++
        }
        dropped += droppedNow
        val rejected = rows.filter { it.state == DeliveryState.REJECTED }
        if (rejected.size > 200) rows -= rejected.sortedBy { it.seq }.take(rejected.size - 200).toSet()
        return EnqueueResult.Stored(row.seq, droppedNow)
    }

    @Synchronized override fun nextBatch(maxEvents: Int): Batch? {
        rows.filter { it.state == DeliveryState.SUBMITTED }.minByOrNull { it.seq }?.batchId?.let { id ->
            return Batch(id, rows.filter { it.batchId == id && it.state == DeliveryState.SUBMITTED }.sortedBy { it.seq }.map(::toQueued))
        }
        val chosen = rows.filter { it.state == DeliveryState.QUEUED }
            .sortedWith(compareByDescending<Row> { it.event.priority.value }.thenBy { it.attempts >= 3 }.thenBy { it.seq })
            .take(maxEvents)
        if (chosen.isEmpty()) return null
        val id = UUID.randomUUID().toString()
        chosen.forEach { it.state = DeliveryState.SUBMITTED; it.batchId = id }
        return Batch(id, chosen.sortedBy { it.seq }.map(::toQueued))
    }

    @Synchronized override fun applyAck(
        batchId: String, accepted: Set<String>, duplicates: Set<String>, rejected: Map<String, String>, nowMs: Long,
    ) {
        var n = 0L
        for (row in rows.filter { it.batchId == batchId && it.state == DeliveryState.SUBMITTED }.toList()) {
            val id = row.event.eventId
            when {
                id in accepted || id in duplicates -> { rows -= row; n++ }
                id in rejected -> { row.state = DeliveryState.REJECTED; row.batchId = null; row.reason = rejected.getValue(id) }
                else -> { row.state = DeliveryState.QUEUED; row.batchId = null }
            }
        }
        if (n > 0) { acked += n; lastAck = nowMs }
    }

    @Synchronized override fun releaseBatch(batchId: String, countAttempt: Boolean) {
        rows.filter { it.batchId == batchId && it.state == DeliveryState.SUBMITTED }.forEach {
            it.state = DeliveryState.QUEUED; it.batchId = null; if (countAttempt) it.attempts++
        }
    }

    @Synchronized override fun rejectBatch(batchId: String, reason: String) {
        rows.filter { it.batchId == batchId && it.state == DeliveryState.SUBMITTED }.forEach {
            it.state = DeliveryState.REJECTED; it.batchId = null; it.reason = reason
        }
    }

    @Synchronized override fun counts(): QueueCounts {
        val pending = rows.filter { it.state != DeliveryState.REJECTED }.minByOrNull { it.seq }
        return QueueCounts(
            queued = rows.count { it.state == DeliveryState.QUEUED },
            submitted = rows.count { it.state == DeliveryState.SUBMITTED },
            rejected = rows.count { it.state == DeliveryState.REJECTED },
            droppedTotal = dropped,
            acknowledgedTotal = acked,
            lastAcknowledgedAtMs = lastAck,
            oldestPendingOccurredAt = pending?.event?.occurredAt?.toString(),
        )
    }

    @Synchronized override fun clear(): Int {
        val n = rows.size
        rows.clear(); dropped = 0; acked = 0; lastAck = null
        return n
    }

    private fun toQueued(r: Row) = QueuedEvent(
        r.seq, r.event.eventId, r.event.data.type, r.event.occurredAt.toString(), r.event.data.toJson(),
        r.event.priority, r.state, r.attempts, r.batchId, r.reason,
    )
}
