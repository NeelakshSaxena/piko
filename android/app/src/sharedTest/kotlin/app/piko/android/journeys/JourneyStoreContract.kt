package app.piko.android.journeys

import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyRules
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.JourneyStore
import app.piko.android.journeys.domain.Leg
import app.piko.android.journeys.domain.TransportMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime

private val KOLKATA = ZoneId.of("Asia/Kolkata")
private val LONDON = ZoneId.of("Europe/London")

fun leg(
    id: String,
    mode: TransportMode = TransportMode.TRAIN,
    from: String = "A",
    to: String = "B",
    departure: ZonedDateTime? = ZonedDateTime.of(2026, 11, 1, 7, 45, 0, 0, KOLKATA),
    arrival: ZonedDateTime? = ZonedDateTime.of(2026, 11, 1, 11, 30, 0, 0, KOLKATA),
    number: String? = null,
) = Leg(id, mode, number, from, to, departure, arrival)

fun journey(id: String, legs: List<Leg>, updated: String = "2026-10-28T10:00:00Z", status: JourneyStatus = JourneyStatus.DRAFT) =
    Journey(id, "Trip $id", status, legs, Instant.parse("2026-10-28T09:00:00Z"), Instant.parse(updated))

/** One contract for local journey storage: the JVM fake and the real SQLite store must both pass. */
abstract class JourneyStoreContract {
    abstract fun newStore(): JourneyStore

    @Test fun aSavedJourneyComesBackExactlyWithLegsInOrder() {
        val store = newStore()
        val original = journey(
            "j1",
            listOf(
                leg("l1", TransportMode.TRAIN, "Katpadi", "Bengaluru", number = "12607"),
                leg("l2", TransportMode.TAXI, "Bengaluru", "Airport", departure = null, arrival = null),
                leg(
                    "l3", TransportMode.FLIGHT, "Bengaluru", "London", number = "BA 118",
                    departure = ZonedDateTime.of(2026, 11, 1, 23, 0, 0, 0, KOLKATA),
                    arrival = ZonedDateTime.of(2026, 11, 2, 5, 30, 0, 0, LONDON),
                ),
            ),
        )
        store.save(original)
        val loaded = store.get("j1")!!
        assertEquals(original.title, loaded.title)
        assertEquals(original.createdAt, loaded.createdAt)
        assertEquals(listOf("l1", "l2", "l3"), loaded.legs.map { it.id })
        assertNull(loaded.legs[1].departure) // a draft keeps a missing time missing
        assertEquals(LONDON, loaded.legs[2].arrival!!.zone) // the entered zone is kept, not the phone's
        assertEquals(original.legs[2].arrival!!.toInstant(), loaded.legs[2].arrival!!.toInstant())
        assertEquals("BA 118", loaded.legs[2].serviceNumber)
    }

    @Test fun savingAReorderedJourneyPersistsTheNewOrder() {
        val store = newStore()
        val legs = listOf(leg("a"), leg("b"), leg("c"))
        store.save(journey("j", legs))
        store.save(journey("j", JourneyRules.move(legs, 2, 0)))
        assertEquals(listOf("c", "a", "b"), store.get("j")!!.legs.map { it.id })
    }

    @Test fun savingAgainReplacesTheLegsInsteadOfAddingToThem() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a"), leg("b"))))
        store.save(journey("j", listOf(leg("b", to = "Elsewhere"))))
        val loaded = store.get("j")!!
        assertEquals(listOf("b"), loaded.legs.map { it.id })
        assertEquals("Elsewhere", loaded.legs.single().destination)
        assertEquals(1, store.list().size)
    }

    @Test fun listIsNewestUpdatedFirst() {
        val store = newStore()
        store.save(journey("old", emptyList(), updated = "2026-10-01T00:00:00Z"))
        store.save(journey("new", emptyList(), updated = "2026-10-20T00:00:00Z"))
        assertEquals(listOf("new", "old"), store.list().map { it.id })
    }

    @Test fun deleteRemovesTheJourneyAndItsLegsAndReportsWhetherItExisted() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a"))))
        assertTrue(store.delete("j"))
        assertNull(store.get("j"))
        assertFalse(store.delete("j"))
        // The leg id is free to use again, so no orphan row is left behind.
        store.save(journey("k", listOf(leg("a"))))
        assertEquals(listOf("a"), store.get("k")!!.legs.map { it.id })
    }

    @Test fun statusIsStored() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a")), status = JourneyStatus.PLANNED))
        assertEquals(JourneyStatus.PLANNED, store.get("j")!!.status)
    }

    private fun stamp(text: String) = Instant.parse(text)

    @Test fun aSavedJourneyIsDirtyUntilTheServerAcknowledgesThatVersion() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        assertEquals(listOf("j"), store.dirty().map { it.id })
        assertTrue(store.markSynced("j", stamp("2026-10-28T10:00:00Z")))
        assertTrue(store.dirty().isEmpty())
        // An edit saved later is dirty again, and an acknowledgement of the OLD version does not clear it.
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T11:00:00Z"))
        assertEquals(listOf("j"), store.dirty().map { it.id })
        store.markSynced("j", stamp("2026-10-28T10:00:00Z"))
        assertEquals(listOf("j"), store.dirty().map { it.id })
        store.markSynced("j", stamp("2026-10-28T11:00:00Z"))
        assertTrue(store.dirty().isEmpty())
    }

    @Test fun everySaveRaisesTheRevisionAndAnOldAcknowledgementNeverCoversANewerSave() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        assertEquals(1L, store.dirtyUploads().single().revision)
        // A save with the SAME timestamp (the clock did not move, or moved back) is still a new revision.
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        assertEquals(2L, store.dirtyUploads().single().revision)
        assertTrue(store.markSynced("j", stamp("2026-10-28T10:00:00Z"), 1L))
        assertEquals(listOf("j"), store.dirty().map { it.id }) // revision 2 is still unsent
        assertTrue(store.markSynced("j", stamp("2026-10-28T10:00:00Z"), 2L))
        assertTrue(store.dirty().isEmpty())
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T09:00:00Z")) // clock stepped back
        assertEquals(3L, store.dirtyUploads().single().revision)
    }

    @Test fun rebasingRaisesTheNextRevisionAboveTheServersAndNeverLowersIt() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a"))))
        store.rebase("j", 9)
        assertEquals(10L, store.dirtyUploads().single().revision)
        store.rebase("j", 3)
        assertEquals(10L, store.dirtyUploads().single().revision)
        store.save(journey("j", listOf(leg("a"))))
        assertEquals(11L, store.dirtyUploads().single().revision)
    }

    @Test fun aJourneyWhoseUploadWasOnlyAttemptedStillOwesTheServerADelete() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a"))))
        store.markUploadAttempted("j") // the request went out; the reply never arrived
        store.delete("j")
        assertEquals(listOf("j"), store.pendingDeletes())
        store.save(journey("k", listOf(leg("b"))))
        store.markUploadAttempted("k")
        store.forgetSync() // a different server now: nothing is owed to it
        store.delete("k")
        assertEquals(listOf<String>(), store.pendingDeletes())
    }

    @Test fun onlyAJourneyTheServerHoldsOwesTheServerADelete() {
        val store = newStore()
        store.save(journey("never", listOf(leg("a"))))
        store.save(journey("backed", listOf(leg("b")), updated = "2026-10-28T10:00:00Z"))
        store.markSynced("backed", stamp("2026-10-28T10:00:00Z"))
        store.delete("never")
        assertTrue(store.pendingDeletes().isEmpty())
        store.delete("backed")
        assertEquals(listOf("backed"), store.pendingDeletes())
        store.markDeleteSynced("backed")
        assertTrue(store.pendingDeletes().isEmpty())
    }

    @Test fun acknowledgingAJourneyDeletedMeanwhileReportsItSoTheCopyCanBeRemoved() {
        val store = newStore()
        store.save(journey("j", listOf(leg("a"))))
        store.delete("j")
        assertFalse(store.markSynced("j", stamp("2026-10-28T10:00:00Z")))
        store.queueDelete("j")
        assertEquals(listOf("j"), store.pendingDeletes())
    }

    @Test fun forgettingSyncMakesEverythingDirtyAndDropsOwedDeletes() {
        val store = newStore()
        store.save(journey("a", listOf(leg("l1")), updated = "2026-10-28T10:00:00Z"))
        store.save(journey("b", listOf(leg("l2")), updated = "2026-10-28T10:00:00Z"))
        store.markSynced("a", stamp("2026-10-28T10:00:00Z"))
        store.markSynced("b", stamp("2026-10-28T10:00:00Z"))
        store.delete("b")
        store.forgetSync()
        assertEquals(listOf("a"), store.dirty().map { it.id })
        assertTrue(store.pendingDeletes().isEmpty())
    }

    @Test fun anEstimateSitsBesideTheScheduleAndSettingItDoesNotMakeTheJourneyDirty() {
        val store = newStore()
        val original = journey("j", listOf(leg("a"), leg("b")), updated = "2026-10-28T10:00:00Z")
        store.save(original)
        store.markSynced("j", Instant.parse("2026-10-28T10:00:00Z"))
        val later = original.legs[0].arrival!!.plusMinutes(50)
        val estimate = app.piko.android.journeys.domain.Estimate(null, later, Instant.parse("2026-10-30T08:00:00Z"))
        store.setEstimate("j", "a", estimate)
        val loaded = store.get("j")!!.legs[0]
        assertEquals(original.legs[0].arrival, loaded.arrival) // the schedule is untouched
        assertEquals(later.toInstant(), loaded.estimate!!.arrival!!.toInstant())
        assertNull(loaded.estimate!!.departure)
        assertEquals(Instant.parse("2026-10-30T08:00:00Z"), loaded.estimate!!.enteredAt)
        assertNull(store.get("j")!!.legs[1].estimate)
        assertTrue(store.dirty().isEmpty()) // an estimate is not part of the backup
        store.setEstimate("j", "a", null)
        assertNull(store.get("j")!!.legs[0].estimate)
    }

    @Test fun anEstimateSurvivesSavingTheJourneyWhenTheLegCarriesIt() {
        val store = newStore()
        val withEstimate = leg("a").copy(estimate = app.piko.android.journeys.domain.Estimate(null, leg("a").arrival!!.plusMinutes(20), Instant.parse("2026-10-30T08:00:00Z")))
        store.save(journey("j", listOf(withEstimate)))
        assertEquals(withEstimate.estimate!!.arrival!!.toInstant(), store.get("j")!!.legs[0].estimate!!.arrival!!.toInstant())
    }
}
