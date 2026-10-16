package app.piko.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import app.piko.android.core.Batch
import app.piko.android.core.EventData
import app.piko.android.core.EventStore
import app.piko.android.core.EventStoreContract
import app.piko.android.core.NewEvent
import app.piko.android.core.SendResult
import app.piko.android.core.SyncConfig
import app.piko.android.core.SyncEngine
import app.piko.android.core.SyncOutcome
import app.piko.android.data.SqliteEventStore
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.util.UUID

private val context: Context get() = ApplicationProvider.getApplicationContext()

/** The same contract the JVM fake satisfies, run against the real SQLite store. */
class SqliteEventStoreContractTest : EventStoreContract() {
    private val opened = ArrayList<SqliteEventStore>()
    private val names = ArrayList<String>()

    override fun newStore(capacity: Int): EventStore {
        val name = "contract-${UUID.randomUUID()}.db"
        names += name
        return SqliteEventStore(context, name, capacity).also { opened += it }
    }

    @After fun cleanUp() {
        opened.forEach { it.close() }
        names.forEach { context.deleteDatabase(it) }
    }
}

/** Process death is simulated by closing the helper and opening a new one on the same file. */
class QueueDurabilityTest {
    private val name = "durability-${UUID.randomUUID()}.db"

    @After fun cleanUp() {
        context.deleteDatabase(name)
    }

    private fun open() = SqliteEventStore(context, name)

    private fun event(id: String) = NewEvent(id, Instant.parse("2026-10-16T10:00:00Z"), EventData.Battery(40, false))

    @Test fun anEventIsOnDiskBeforeAnyNetworkAttempt() {
        open().use { it.enqueue(event("a"), 0) } // "process dies" before a send was even tried
        open().use { store ->
            assertEquals(1, store.counts().queued)
            assertEquals(listOf("a"), store.nextBatch(10)!!.events.map { it.eventId })
        }
    }

    @Test fun anInDoubtBatchSurvivesProcessDeathAndIsResentWithTheSameId() {
        val batchId = open().use { store ->
            store.enqueue(event("a"), 0); store.enqueue(event("b"), 0)
            store.nextBatch(10)!!.batchId // sent; the response never arrived
        }
        open().use { store ->
            val retry = store.nextBatch(10)!!
            assertEquals(batchId, retry.batchId)
            assertEquals(listOf("a", "b"), retry.events.map { it.eventId })
        }
    }

    @Test fun acknowledgedEventsDoNotComeBackAfterARestart() {
        open().use { store ->
            store.enqueue(event("a"), 0); store.enqueue(event("b"), 0)
            val batch = store.nextBatch(1)!!
            store.applyAck(batch.batchId, setOf("a"), emptySet(), emptyMap(), 123)
        }
        open().use { store ->
            val counts = store.counts()
            assertEquals(1, counts.acknowledgedTotal)
            assertEquals(123L, counts.lastAcknowledgedAtMs)
            assertEquals(listOf("b"), store.nextBatch(10)!!.events.map { it.eventId })
        }
    }

    @Test fun aBacklogAcrossARestartIsDeliveredCompletelyInBoundedBatches() {
        open().use { store -> repeat(250) { store.enqueue(event("e$it"), 0) } }
        val delivered = LinkedHashSet<String>()
        val sizes = ArrayList<Int>()
        open().use { store ->
            val engine = SyncEngine(store, { batch: Batch ->
                sizes += batch.events.size
                delivered += batch.events.map { it.eventId }
                SendResult.Ack(batch.events.map { it.eventId }.toSet(), emptySet(), emptyMap())
            }, { System.currentTimeMillis() }, config = SyncConfig(maxBatchEvents = 100))
            assertEquals(SyncOutcome.Done(250, false), engine.syncOnce())
        }
        assertEquals(250, delivered.size)
        assertTrue(sizes.all { it <= 100 })
    }

    @Test fun clearForgetsEverythingOnDisk() {
        open().use { store -> store.enqueue(event("a"), 0); store.clear() }
        open().use { assertEquals(0, it.counts().pending) }
    }
}
