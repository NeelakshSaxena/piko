package app.piko.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/** One contract for the SOS/message outbox: the JVM fake and the real SQLite store must both pass. */
abstract class CommStoreContract {
    abstract fun newStore(): CommStore

    private var counter = 0
    private fun sos(id: String = "s${++counter}", text: String? = "help", point: SosPoint? = null) =
        NewComm(id, CommKind.SOS, Instant.parse("2026-10-17T10:00:00Z"), text, point)

    private fun msg(id: String = "m${++counter}", text: String = "hi") =
        NewComm(id, CommKind.MESSAGE, Instant.parse("2026-10-17T10:00:01Z"), text)

    @Test fun enqueueIsIdempotentOnId() {
        val store = newStore()
        assertTrue(store.enqueue(sos("same"), 0))
        assertFalse(store.enqueue(sos("same"), 0))
        assertEquals(1, store.items().size)
        assertEquals(1, store.pendingCount())
    }

    @Test fun anEnqueuedItemIsQueuedAndKeepsItsFieldsExactly() {
        val store = newStore()
        store.enqueue(sos("a", "at the gate", SosPoint(40.7128, -74.006, 12.5)), 0)
        val item = store.items().single()
        assertEquals(CommState.QUEUED, item.state)
        assertEquals("2026-10-17T10:00:00Z", item.createdAtIso) // occurrence time is never rewritten
        assertEquals("at the gate", item.text)
        assertEquals(SosPoint(40.7128, -74.006, 12.5), item.location)
        assertNull(item.remoteStatus)
        assertEquals(0, item.attempts)
    }

    @Test fun sosIsSentBeforeMessagesEvenIfQueuedLater() {
        val store = newStore()
        store.enqueue(msg("m1"), 0)
        store.enqueue(msg("m2"), 0)
        store.enqueue(sos("s1"), 0)
        assertEquals("s1", store.next()!!.id)
        store.markSubmitted("s1")
        store.markDelivered("s1", "open", null, null, 5)
        assertEquals("m1", store.next()!!.id) // then oldest first
    }

    @Test fun anInDoubtItemIsReturnedAgainWithTheSameId() {
        val store = newStore()
        store.enqueue(sos("a"), 0)
        store.markSubmitted("a") // sent; the answer never arrived
        val again = store.next()!!
        assertEquals("a", again.id)
        assertEquals(CommState.SUBMITTED, again.state)
        assertEquals(1, store.pendingCount())
    }

    @Test fun deliveredLeavesThePendingSetButStaysVisible() {
        val store = newStore()
        store.enqueue(sos("a"), 0)
        store.markSubmitted("a")
        store.markDelivered("a", "open", null, null, 99)
        assertEquals(0, store.pendingCount())
        assertNull(store.next())
        val item = store.items().single()
        assertEquals(CommState.DELIVERED, item.state)
        assertEquals("open", item.remoteStatus)
        assertEquals(99L, item.deliveredAtMs)
    }

    @Test fun releaseReturnsToQueuedAndCountsAttemptsOnlyWhenAsked() {
        val store = newStore()
        store.enqueue(msg("a"), 0)
        store.markSubmitted("a"); store.release("a", countAttempt = false)
        store.markSubmitted("a"); store.release("a", countAttempt = true)
        val item = store.items().single()
        assertEquals(CommState.QUEUED, item.state)
        assertEquals(1, item.attempts)
        assertEquals(1, store.pendingCount())
    }

    @Test fun aPermanentRefusalStaysVisibleAndIsNotRetried() {
        val store = newStore()
        store.enqueue(msg("a"), 0)
        store.markSubmitted("a")
        store.markFailed("a", "refused by server (HTTP 400 VALIDATION_ERROR)")
        assertNull(store.next())
        assertEquals(0, store.pendingCount())
        val item = store.items().single()
        assertEquals(CommState.FAILED, item.state)
        assertEquals("refused by server (HTTP 400 VALIDATION_ERROR)", item.failReason)
    }

    @Test fun aDeliveredItemCannotBecomeFailedOrQueuedAgain() {
        val store = newStore()
        store.enqueue(sos("a"), 0)
        store.markSubmitted("a")
        store.markDelivered("a", "open", null, null, 1)
        store.markFailed("a", "late")
        store.release("a", true)
        store.markSubmitted("a")
        assertEquals(CommState.DELIVERED, store.items().single().state)
    }

    @Test fun remoteStatusOnlyMovesForward() {
        val store = newStore()
        store.enqueue(sos("a"), 0)
        store.markSubmitted("a")
        store.markDelivered("a", "open", null, null, 1)
        assertTrue(store.applyRemote("a", "acknowledged", "2026-10-17T10:05:00Z", null))
        assertFalse(store.applyRemote("a", "acknowledged", "2026-10-17T10:05:00Z", null)) // no change, no second alert
        assertFalse(store.applyRemote("a", "open", null, null)) // never backwards
        assertTrue(store.applyRemote("a", "resolved", null, "2026-10-17T10:09:00Z"))
        val item = store.items().single()
        assertEquals("resolved", item.remoteStatus)
        assertEquals("2026-10-17T10:05:00Z", item.acknowledgedAtIso) // earlier fact kept
        assertEquals("2026-10-17T10:09:00Z", item.resolvedAtIso)
    }

    @Test fun remoteStatusIsIgnoredForItemsNotYetDeliveredOrUnknown() {
        val store = newStore()
        store.enqueue(sos("a"), 0)
        assertFalse(store.applyRemote("a", "acknowledged", null, null)) // still only on this phone
        assertEquals(CommState.QUEUED, store.items().single().state)
        assertFalse(store.applyRemote("ghost", "resolved", null, null))
    }

    @Test fun itemsAreNewestFirstAndBounded() {
        val store = newStore()
        repeat(5) { store.enqueue(msg("m$it"), 0) }
        assertEquals(listOf("m4", "m3"), store.items(2).map { it.id })
    }

    @Test fun anItemTheServerKeepsFailingOnGoesAfterEveryOtherItemButIsNeverDropped() {
        val store = newStore()
        store.enqueue(sos("bad"), 0)
        store.enqueue(msg("m1"), 0)
        store.enqueue(sos("good"), 0)
        repeat(POISON_AFTER) { store.markSubmitted("bad"); store.release("bad", countAttempt = true) }
        assertEquals("good", store.next()!!.id) // other SOS first, the poisoned one no longer blocks
        store.markSubmitted("good"); store.markDelivered("good", "open", null, null, 1)
        assertEquals("m1", store.next()!!.id) // then the message, still ahead of the poisoned SOS
        store.markSubmitted("m1"); store.markDelivered("m1", "delivered", null, null, 1)
        assertEquals("bad", store.next()!!.id) // finally retried: it was never given up on
        assertEquals(1, store.pendingCount())
    }

    @Test fun anItemBelowThePoisonThresholdKeepsItsPlaceInLine() {
        val store = newStore()
        store.enqueue(sos("first"), 0)
        store.enqueue(sos("second"), 0)
        repeat(POISON_AFTER - 1) { store.markSubmitted("first"); store.release("first", countAttempt = true) }
        assertEquals("first", store.next()!!.id)
    }

    @Test fun clearForgetsEverything() {
        val store = newStore()
        store.enqueue(sos("a"), 0); store.enqueue(msg("b"), 0)
        assertEquals(2, store.clear())
        assertEquals(0, store.items().size)
        assertNull(store.next())
        assertTrue(store.enqueue(sos("a"), 0)) // the id is free again
    }
}
