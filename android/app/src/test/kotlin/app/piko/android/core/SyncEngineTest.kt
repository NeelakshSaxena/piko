package app.piko.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import kotlin.random.Random

/** A server that stores durably and de-duplicates by event id, like the real backend. */
private class FakeServer {
    val stored = LinkedHashSet<String>()
    val sentBatches = ArrayList<Pair<String, List<String>>>()

    fun accept(batch: Batch): SendResult.Ack {
        sentBatches += batch.batchId to batch.events.map { it.eventId }
        val accepted = LinkedHashSet<String>()
        val duplicates = LinkedHashSet<String>()
        for (e in batch.events) (if (stored.add(e.eventId)) accepted else duplicates) += e.eventId
        return SendResult.Ack(accepted, duplicates, emptyMap())
    }
}

class SyncEngineTest {
    private var now = 1_000_000L
    private val clock = Clock { now }
    private val store = InMemoryEventStore()
    private val server = FakeServer()

    private fun fill(n: Int, prefix: String = "e") {
        repeat(n) { i ->
            store.enqueue(NewEvent("$prefix$i", Instant.parse("2026-10-16T10:00:00Z").plusSeconds(i.toLong()), EventData.Battery(50, null)), now)
        }
    }

    private fun engine(config: SyncConfig = SyncConfig(), seed: Int = 1, transport: Transport) =
        SyncEngine(store, transport, clock, Random(seed), config)

    @Test fun deliversEverythingAndDeletesOnlyAfterAck() {
        fill(7)
        val outcome = engine(transport = { server.accept(it) }).syncOnce()
        assertEquals(SyncOutcome.Done(7, false), outcome)
        assertEquals(7, server.stored.size)
        assertEquals(0, store.counts().pending)
        assertEquals(7, store.counts().acknowledgedTotal)
    }

    @Test fun networkLossAfterTheServerStoredTheBatchRetriesTheSameBatchAndStoresItOnce() {
        fill(5)
        var calls = 0
        val e = engine(transport = {
            val ack = server.accept(it)
            if (++calls == 1) SendResult.Network("SocketTimeoutException") else ack // response lost on the first try
        })
        assertTrue(e.syncOnce() is SyncOutcome.RetryAfter)
        assertEquals(5, store.counts().submitted) // still pending: nothing was acknowledged
        assertEquals(SyncOutcome.Done(5, false), e.syncOnce())
        assertEquals(5, server.stored.size)
        assertEquals(server.sentBatches[0], server.sentBatches[1]) // identical batch id and events
        assertEquals(0, store.counts().pending)
    }

    @Test fun partialAcknowledgementNeverLosesTheRest() {
        fill(5)
        var first = true
        val e = engine(transport = { batch ->
            if (first) {
                first = false
                val ids = batch.events.take(2).map { it.eventId }.toSet()
                server.stored += ids
                SendResult.Ack(ids, emptySet(), emptyMap())
            } else server.accept(batch)
        })
        assertEquals(SyncOutcome.Done(5, false), e.syncOnce())
        assertEquals(5, server.stored.size)
        assertEquals(0, store.counts().pending)
    }

    @Test fun duplicateRetriesAreAcknowledgedAndCleared() {
        fill(3)
        server.stored += listOf("e0", "e1", "e2") // an earlier attempt already landed
        assertEquals(SyncOutcome.Done(3, false), engine(transport = { server.accept(it) }).syncOnce())
        assertEquals(0, store.counts().pending)
    }

    @Test fun serverSideRejectionsAreKeptVisibleAndNotRetried() {
        fill(3)
        val e = engine(transport = { b ->
            SendResult.Ack(setOf(b.events[0].eventId), emptySet(), mapOf(b.events[1].eventId to "latitude out of range", b.events[2].eventId to "x"))
        })
        e.syncOnce()
        assertEquals(2, store.counts().rejected)
        assertEquals(0, store.counts().pending)
        assertEquals(SyncOutcome.Done(0, false), e.syncOnce())
    }

    @Test fun backoffGrowsWithJitterIsCappedAndResetsAfterSuccess() {
        fill(1)
        var fail = true
        val config = SyncConfig(baseBackoffMs = 5_000, maxBackoffMs = 60_000)
        val e = engine(config, transport = { if (fail) SendResult.Network("x") else server.accept(it) })
        val delays = (1..8).map { (e.syncOnce() as SyncOutcome.RetryAfter).delayMs }
        delays.forEachIndexed { i, d ->
            val ceiling = minOf(60_000L, 5_000L shl i)
            assertTrue("attempt ${i + 1}: $d not in [${ceiling / 2}, $ceiling]", d in ceiling / 2..ceiling)
        }
        assertTrue(delays.last() <= 60_000)
        assertTrue(delays.toSet().size > 1) // jittered, not a fixed schedule
        fail = false
        e.syncOnce()
        fail = true
        fill(1, "next")
        val afterReset = (e.syncOnce() as SyncOutcome.RetryAfter).delayMs
        assertTrue("backoff must restart from the base", afterReset <= 5_000)
    }

    @Test fun retryAfterFromTheServerIsHonouredAndClamped() {
        fill(1)
        var seconds = 120L
        val e = engine(transport = { SendResult.RateLimited(seconds) })
        assertTrue((e.syncOnce() as SyncOutcome.RetryAfter).delayMs >= 120_000)
        seconds = 100_000L
        assertEquals(SyncConfig().maxBackoffMs, (e.syncOnce() as SyncOutcome.RetryAfter).delayMs)
    }

    @Test fun revokedCredentialStopsSendingAndKeepsEveryEvent() {
        fill(4)
        assertEquals(SyncOutcome.CredentialRevoked, engine(transport = { SendResult.Unauthorized }).syncOnce())
        assertEquals(4, store.counts().pending)
        assertEquals(0, store.counts().rejected)
    }

    @Test fun anUnreadableSuccessResponseAcknowledgesNothing() {
        fill(3)
        assertTrue(engine(transport = { SendResult.ServerError(202) }).syncOnce() is SyncOutcome.RetryAfter)
        assertEquals(3, store.counts().pending)
        assertEquals(0, store.counts().acknowledgedTotal)
    }

    @Test fun aRefusedBatchIsRejectedAndLaterBatchesStillGo() {
        fill(4)
        var n = 0
        val e = engine(SyncConfig(maxBatchEvents = 2), transport = { if (++n == 1) SendResult.Refused(400, "VALIDATION_ERROR") else server.accept(it) })
        assertEquals(SyncOutcome.Done(2, false), e.syncOnce())
        assertEquals(2, store.counts().rejected)
        assertEquals(2, server.stored.size)
    }

    @Test fun oneRunIsBoundedEvenWithALargeBacklog() {
        fill(12)
        val e = engine(SyncConfig(maxBatchEvents = 1, maxBatchesPerRun = 5), transport = { server.accept(it) })
        assertEquals(SyncOutcome.Done(5, moreWaiting = true), e.syncOnce())
        assertEquals(7, store.counts().pending)
    }

    @Test fun flappingNetworkStillDeliversEveryEventExactlyOnce() {
        fill(40)
        var call = 0
        val e = engine(SyncConfig(maxBatchEvents = 5), transport = { b ->
            val ack = server.accept(b)
            if (call++ % 2 == 0) SendResult.Network("reset") else ack // every other response is lost
        })
        repeat(200) { if (store.counts().pending > 0) e.syncOnce() }
        assertEquals(0, store.counts().pending)
        assertEquals(40, server.stored.size)
        assertEquals(40L, store.counts().acknowledgedTotal)
    }

    @Test fun aPoisonEventIsIsolatedAndRejectedWhileEverythingElseIsDelivered() {
        store.enqueue(NewEvent("poison", Instant.parse("2026-10-16T09:00:00Z"), EventData.Battery(1, null)), now)
        fill(20)
        val e = engine(transport = { b ->
            if (b.events.any { it.eventId == "poison" }) SendResult.ServerError(500) else server.accept(b)
        })
        var runs = 0
        while (store.counts().pending > 0 && runs < 100) { e.syncOnce(); runs++ }
        assertEquals(20, server.stored.size)
        assertEquals(1, store.counts().rejected)
        assertEquals(0, store.counts().pending)
        assertTrue("took $runs runs", runs < 40)
    }

    @Test fun aLongOutageNeverCostsAnyData() {
        fill(30)
        val e = engine(SyncConfig(maxAttempts = 5), transport = { SendResult.ServerError(503) })
        repeat(300) { e.syncOnce() }
        assertEquals(30, store.counts().pending)
        assertEquals(0, store.counts().rejected)
        // And the moment the server is back, everything is delivered.
        val back = engine(transport = { server.accept(it) })
        back.syncOnce()
        assertEquals(30, server.stored.size)
    }

    @Test fun batchSizeNeverExceedsTheConfiguredLimit() {
        fill(25)
        engine(SyncConfig(maxBatchEvents = 10), transport = { server.accept(it) }).syncOnce()
        assertTrue(server.sentBatches.all { it.second.size <= 10 })
    }
}
