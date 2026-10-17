package app.piko.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import app.piko.android.core.CommEngine
import app.piko.android.core.CommItem
import app.piko.android.core.CommKind
import app.piko.android.core.CommResult
import app.piko.android.core.CommState
import app.piko.android.core.CommStore
import app.piko.android.core.CommStoreContract
import app.piko.android.core.CommTransport
import app.piko.android.core.Fetch
import app.piko.android.core.NewComm
import app.piko.android.core.RemoteMessage
import app.piko.android.core.RemoteMessageStatus
import app.piko.android.core.RemoteSos
import app.piko.android.core.SyncOutcome
import app.piko.android.data.SqliteCommStore
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant
import java.util.UUID

private val context: Context get() = ApplicationProvider.getApplicationContext()

/** The same outbox contract the JVM fake satisfies, run against the real SQLite store. */
class SqliteCommStoreContractTest : CommStoreContract() {
    private val opened = ArrayList<SqliteCommStore>()
    private val names = ArrayList<String>()

    override fun newStore(): CommStore {
        val name = "comm-contract-${UUID.randomUUID()}.db"
        names += name
        return SqliteCommStore(context, name).also { opened += it }
    }

    @After fun cleanUp() {
        opened.forEach { it.close() }
        names.forEach { context.deleteDatabase(it) }
    }
}

/** Process death is simulated by closing the helper and opening a new one on the same file. */
class CommDurabilityTest {
    private val name = "comm-durability-${UUID.randomUUID()}.db"

    @After fun cleanUp() {
        context.deleteDatabase(name)
    }

    private fun open() = SqliteCommStore(context, name)

    private fun sos(id: String) = NewComm(id, CommKind.SOS, Instant.parse("2026-10-17T10:00:00Z"), "help")

    @Test fun anSosIsOnDiskBeforeAnyNetworkAttemptAndSurvivesRestarts() {
        open().use { it.enqueue(sos("a"), 0) } // "process dies" before a send was even tried
        open().use { store ->
            assertEquals(1, store.pendingCount())
            assertEquals("a", store.next()!!.id)
        }
        open().use { assertEquals(CommState.QUEUED, it.items().single().state) }
    }

    @Test fun anInDoubtSosStaysSubmittedAcrossARestartAndIsOfferedAgain() {
        open().use { it.enqueue(sos("a"), 0); it.markSubmitted("a") }
        open().use { store ->
            val again = store.next()!!
            assertEquals("a", again.id)
            assertEquals(CommState.SUBMITTED, again.state)
        }
    }

    @Test fun deliveredStateAndRemoteStatusSurviveARestart() {
        open().use { it.enqueue(sos("a"), 0); it.markSubmitted("a"); it.markDelivered("a", "open", null, null, 7) }
        open().use { it.applyRemote("a", "acknowledged", "2026-10-17T10:05:00Z", null) }
        open().use { store ->
            val item = store.items().single()
            assertEquals(CommState.DELIVERED, item.state)
            assertEquals("acknowledged", item.remoteStatus)
            assertEquals(0, store.pendingCount())
        }
    }

    @Test fun engineDrainsABacklogAcrossARestartExactlyOncePerId() {
        open().use { s -> repeat(3) { s.enqueue(sos("s$it"), 0) } }
        val seen = ArrayList<String>()
        open().use { store ->
            val transport = object : CommTransport {
                override fun deliver(item: CommItem): CommResult {
                    seen += item.id
                    return CommResult.Delivered("open", null, null)
                }
                override fun fetchSos() = Fetch.Ok(emptyList<RemoteSos>())
                override fun fetchParentMessages() = Fetch.Ok(emptyList<RemoteMessage>())
                override fun fetchOwnMessages() = Fetch.Ok(emptyList<RemoteMessageStatus>())
                override fun acknowledgeMessage(id: String) = CommResult.Delivered("acknowledged", null, null)
            }
            assertEquals(SyncOutcome.Done(3, false), CommEngine(store, transport, { System.currentTimeMillis() }).drain())
        }
        assertEquals(listOf("s0", "s1", "s2"), seen)
        open().use { assertEquals(0, it.pendingCount()) }
    }
}
