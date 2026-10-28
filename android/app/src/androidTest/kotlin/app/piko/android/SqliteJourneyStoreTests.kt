package app.piko.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import app.piko.android.journeys.JourneyStoreContract
import app.piko.android.journeys.TrackingStoreContract
import app.piko.android.journeys.data.SqliteJourneyStore
import app.piko.android.journeys.domain.JourneyStore
import app.piko.android.journeys.domain.TrackingStore
import app.piko.android.journeys.journey
import app.piko.android.journeys.leg
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.util.UUID

private val context: Context get() = ApplicationProvider.getApplicationContext()

/** The same storage contract the JVM fake satisfies, run against the real SQLite store. */
class SqliteJourneyStoreContractTest : JourneyStoreContract() {
    private val opened = ArrayList<SqliteJourneyStore>()
    private val names = ArrayList<String>()

    override fun newStore(): JourneyStore {
        val name = "journey-contract-${UUID.randomUUID()}.db"
        names += name
        return SqliteJourneyStore(context, name).also { opened += it }
    }

    @After fun cleanUp() {
        opened.forEach { it.close() }
        names.forEach { context.deleteDatabase(it) }
    }
}

/** The tracking tables live in the same database file as the journeys they belong to. */
class SqliteTrackingStoreContractTest : TrackingStoreContract() {
    private val opened = ArrayList<SqliteJourneyStore>()
    private val names = ArrayList<String>()

    override fun newStores(): Pair<JourneyStore, TrackingStore> {
        val name = "tracking-contract-${UUID.randomUUID()}.db"
        names += name
        val store = SqliteJourneyStore(context, name).also { opened += it }
        return store to store
    }

    @After fun cleanUp() {
        opened.forEach { it.close() }
        names.forEach { context.deleteDatabase(it) }
    }
}

/** Process death is simulated by closing the helper and opening a new one on the same file. */
class JourneyDurabilityTest {
    private val name = "journey-durability-${UUID.randomUUID()}.db"

    @After fun cleanUp() {
        context.deleteDatabase(name)
    }

    private fun open() = SqliteJourneyStore(context, name)

    @Test fun aSavedJourneySurvivesARestartInOrder() {
        open().use { it.save(journey("j", listOf(leg("a"), leg("b"), leg("c")))) }
        open().use { assertEquals(listOf("a", "b", "c"), it.get("j")!!.legs.map { l -> l.id }) }
    }

    @Test fun aDeleteSurvivesARestart() {
        open().use { it.save(journey("j", listOf(leg("a")))); it.delete("j") }
        open().use { assertEquals(0, it.list().size) }
    }
}

/** A phone that already ran the phase-1 build has a version-1 database; opening it must keep its journeys. */
class JourneyMigrationTest {
    private val name = "journey-migration-${UUID.randomUUID()}.db"

    @After fun cleanUp() {
        context.deleteDatabase(name)
    }

    @Test fun aVersionOneDatabaseUpgradesWithItsJourneysIntact() {
        context.openOrCreateDatabase(name, Context.MODE_PRIVATE, null).use { db ->
            db.execSQL("CREATE TABLE journeys(id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execSQL(
                """CREATE TABLE journey_legs(id TEXT PRIMARY KEY, journey_id TEXT NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                   sequence INTEGER NOT NULL, mode TEXT NOT NULL, service_number TEXT, origin TEXT NOT NULL, destination TEXT NOT NULL,
                   departure_at TEXT, departure_zone TEXT, arrival_at TEXT, arrival_zone TEXT, UNIQUE(journey_id, sequence))""",
            )
            db.execSQL("INSERT INTO journeys VALUES('old', 'Old trip', 'PLANNED', '2026-10-01T00:00:00Z', '2026-10-02T00:00:00Z')")
            db.execSQL(
                "INSERT INTO journey_legs VALUES('l1', 'old', 0, 'TRAIN', '12607', 'A', 'B', '2026-11-01T02:15:00Z', 'Asia/Kolkata', '2026-11-01T06:00:00Z', 'Asia/Kolkata')",
            )
            db.version = 1
        }
        SqliteJourneyStore(context, name).use { store ->
            val old = store.get("old")
            assertNotNull(old)
            assertEquals("Old trip", old!!.title)
            assertEquals(listOf("l1"), old.legs.map { it.id })
            assertEquals(listOf("old"), store.dirty().map { it.id }) // nothing was backed up before
            // The new tables work on the upgraded file.
            assertEquals(null, store.session("old"))
            store.claimAlert("k", java.time.Instant.EPOCH)
        }
    }
}
