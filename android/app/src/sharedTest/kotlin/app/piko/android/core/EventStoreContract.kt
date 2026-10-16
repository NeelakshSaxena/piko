package app.piko.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * One behavioural contract for the durable queue. It runs against an in-memory fake on the JVM and
 * against the real SQLite store on a device/emulator, so the fake can never drift from reality.
 */
abstract class EventStoreContract {
    abstract fun newStore(capacity: Int = 1_000): EventStore

    private var counter = 0
    protected fun event(
        id: String = "e${++counter}",
        at: String = "2026-10-16T10:00:00Z",
        priority: EventPriority = EventPriority.NORMAL,
        data: EventData = EventData.Battery(50, false),
    ) = NewEvent(id, Instant.parse(at), data, priority)

    private fun EventStore.add(vararg events: NewEvent) = events.forEach { enqueue(it, 0) }
    private fun Batch.ids() = events.map { it.eventId }

    @Test fun enqueueIsIdempotentOnEventId() {
        val store = newStore()
        assertTrue(store.enqueue(event("same"), 0) is EnqueueResult.Stored)
        assertEquals(EnqueueResult.AlreadyQueued, store.enqueue(event("same"), 0))
        assertEquals(1, store.counts().queued)
    }

    @Test fun claimsCriticalFirstThenOldestAndReturnsTheBatchInSequenceOrder() {
        val store = newStore()
        store.add(event("a"), event("b"), event("c", priority = EventPriority.CRITICAL), event("d"))
        // Capacity for three: the critical event and the two oldest normal ones; "d" waits.
        assertEquals(listOf("a", "b", "c"), store.nextBatch(3)!!.ids())
        store.applyAck(store.nextBatch(3)!!.batchId, setOf("a", "b", "c"), emptySet(), emptyMap(), 1)
        assertEquals(listOf("d"), store.nextBatch(3)!!.ids())
    }

    @Test fun criticalEventsOvertakeOlderNormalOnesWhenTheBatchIsSmall() {
        val store = newStore()
        store.add(event("a"), event("b"), event("c", priority = EventPriority.CRITICAL))
        assertEquals(listOf("c"), store.nextBatch(1)!!.ids())
    }

    @Test fun occurrenceTimeIsStoredExactlyAndNeverRewritten() {
        val store = newStore()
        store.add(event("a", at = "2026-10-16T09:59:58.123Z"))
        val first = store.nextBatch(10)!!
        store.releaseBatch(first.batchId, countAttempt = true)
        val again = store.nextBatch(10)!!
        assertEquals("2026-10-16T09:59:58.123Z", first.events.single().occurredAtIso)
        assertEquals("2026-10-16T09:59:58.123Z", again.events.single().occurredAtIso)
    }

    @Test fun inDoubtBatchIsRetriedUnchangedUntilAcknowledged() {
        val store = newStore()
        store.add(event("a"), event("b"))
        val first = store.nextBatch(10)!!
        store.add(event("c")) // arrives while the first batch is in doubt
        val retry = store.nextBatch(10)!!
        assertEquals(first.batchId, retry.batchId)
        assertEquals(listOf("a", "b"), retry.ids())
        store.applyAck(first.batchId, setOf("a", "b"), emptySet(), emptyMap(), 1)
        val next = store.nextBatch(10)!!
        assertNotEquals(first.batchId, next.batchId)
        assertEquals(listOf("c"), next.ids())
    }

    @Test fun acknowledgedAndDuplicateEventsAreDeletedAndCounted() {
        val store = newStore()
        store.add(event("a"), event("b"))
        val batch = store.nextBatch(10)!!
        store.applyAck(batch.batchId, setOf("a"), setOf("b"), emptyMap(), 5_000)
        val counts = store.counts()
        assertEquals(0, counts.pending)
        assertEquals(2, counts.acknowledgedTotal)
        assertEquals(5_000L, counts.lastAcknowledgedAtMs)
        assertNull(store.nextBatch(10))
    }

    @Test fun partialAckKeepsTheUnmentionedEventsQueued() {
        val store = newStore()
        store.add(event("a"), event("b"), event("c"))
        val batch = store.nextBatch(10)!!
        store.applyAck(batch.batchId, setOf("a"), emptySet(), emptyMap(), 1)
        assertEquals(listOf("b", "c"), store.nextBatch(10)!!.ids())
        assertEquals(1, store.counts().acknowledgedTotal)
    }

    @Test fun rejectedEventsStayVisibleWithTheServersReason() {
        val store = newStore()
        store.add(event("a"), event("b"))
        val batch = store.nextBatch(10)!!
        store.applyAck(batch.batchId, setOf("a"), emptySet(), mapOf("b" to "latitude out of range"), 1)
        assertEquals(1, store.counts().rejected)
        assertNull(store.nextBatch(10)) // a rejected event is never retried
    }

    @Test fun acknowledgementOnlyAffectsEventsOfThatBatch() {
        val store = newStore()
        store.add(event("a"))
        val batch = store.nextBatch(10)!!
        store.add(event("later"))
        store.applyAck(batch.batchId, setOf("a", "later", "ghost"), emptySet(), emptyMap(), 1)
        assertEquals(listOf("later"), store.nextBatch(10)!!.ids()) // "later" was not acknowledged
        assertEquals(1, store.counts().acknowledgedTotal)
    }

    @Test fun releasingABatchRequeuesWithAFreshBatchIdAndCountsAttempts() {
        val store = newStore()
        store.add(event("a"))
        val first = store.nextBatch(10)!!
        store.releaseBatch(first.batchId, countAttempt = true)
        val second = store.nextBatch(10)!!
        assertNotEquals(first.batchId, second.batchId)
        assertEquals(1, second.events.single().attempts)
        store.releaseBatch(second.batchId, countAttempt = false)
        assertEquals(1, store.nextBatch(10)!!.events.single().attempts)
    }

    @Test fun rejectingABatchKeepsItVisibleAndStopsRetrying() {
        val store = newStore()
        store.add(event("a"), event("b"))
        val batch = store.nextBatch(10)!!
        store.rejectBatch(batch.batchId, "refused")
        assertEquals(2, store.counts().rejected)
        assertNull(store.nextBatch(10))
    }

    @Test fun eventsThatKeepFailingGoAfterFreshOnesSoTheyCannotBlockTheQueue() {
        val store = newStore()
        store.add(event("poison"))
        repeat(3) { store.releaseBatch(store.nextBatch(1)!!.batchId, countAttempt = true) }
        store.add(event("fresh1"), event("fresh2"))
        assertEquals(listOf("fresh1", "fresh2"), store.nextBatch(2)!!.ids())
    }

    @Test fun fullQueueDropsOldestNormalEventsAndCountsThemButNeverCriticalOnes() {
        val store = newStore(capacity = 3)
        store.add(event("crit", priority = EventPriority.CRITICAL), event("n1"), event("n2"))
        val result = store.enqueue(event("n3"), 0) as EnqueueResult.Stored
        assertEquals(1, result.droppedToMakeRoom)
        assertEquals(1, store.counts().droppedTotal)
        assertEquals(listOf("crit", "n2", "n3"), store.nextBatch(10)!!.ids())
    }

    @Test fun sequenceNumbersIncreaseAndAreNeverReused() {
        val store = newStore()
        store.add(event("a"))
        val first = store.nextBatch(10)!!
        val seqA = first.events.single().seq
        store.applyAck(first.batchId, setOf("a"), emptySet(), emptyMap(), 1)
        store.add(event("b"))
        assertTrue(store.nextBatch(10)!!.events.single().seq > seqA)
    }

    @Test fun clearRemovesEverythingIncludingCounters() {
        val store = newStore()
        store.add(event("a"), event("b"))
        val batch = store.nextBatch(1)!!
        store.applyAck(batch.batchId, setOf("a"), emptySet(), emptyMap(), 1)
        assertEquals(1, store.clear())
        val counts = store.counts()
        assertEquals(0, counts.pending + counts.rejected)
        assertEquals(0, counts.acknowledgedTotal)
        assertNull(store.nextBatch(10))
    }

    @Test fun oldestPendingReadingIsReported() {
        val store = newStore()
        store.add(event("a", at = "2026-10-16T08:00:00Z"), event("b", at = "2026-10-16T09:00:00Z"))
        assertEquals("2026-10-16T08:00:00Z", store.counts().oldestPendingOccurredAt)
    }
}
