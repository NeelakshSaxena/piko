package app.piko.android.journeys

import app.piko.android.journeys.data.ApiJourneyTransport
import app.piko.android.journeys.data.JourneyCodec
import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyEvent
import app.piko.android.journeys.domain.JourneySyncEngine
import app.piko.android.journeys.domain.JourneySyncOutcome
import app.piko.android.journeys.domain.JourneyTransport
import app.piko.android.journeys.domain.SyncCall
import app.piko.android.journeys.domain.TransportMode
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

private class FakeTransport(
    var put: (Journey) -> SyncCall = { SyncCall.Ok },
    var delete: (String) -> SyncCall = { SyncCall.Ok },
    var events: (String, List<JourneyEvent>) -> SyncCall = { _, _ -> SyncCall.Ok },
) : JourneyTransport {
    val puts = ArrayList<String>()
    val deletes = ArrayList<String>()
    val batches = ArrayList<Pair<String, List<String>>>()
    val revisions = ArrayList<Long>()
    override fun put(journey: Journey, revision: Long): SyncCall =
        put.invoke(journey).also { puts += journey.id; revisions += revision }
    override fun delete(id: String): SyncCall = delete.invoke(id).also { deletes += id }
    override fun events(journeyId: String, events: List<JourneyEvent>): SyncCall =
        this.events.invoke(journeyId, events).also { batches += journeyId to events.map { it.id } }
}

class JourneySyncEngineTest {
    private val store = InMemoryJourneyStore()

    private fun engine(transport: FakeTransport, enabled: Boolean = true) = JourneySyncEngine(store, store, transport) { enabled }

    private fun backedUp(id: String) {
        store.save(journey(id, listOf(leg("leg-$id")), updated = "2026-10-28T10:00:00Z"))
        store.markSynced(id, Instant.parse("2026-10-28T10:00:00Z"))
    }

    @Test fun nothingIsUploadedWhileBackupIsOff() {
        store.save(journey("j", listOf(leg("a"))))
        val t = FakeTransport()
        assertEquals(JourneySyncOutcome.Done(0, 0, 0), engine(t, enabled = false).drain())
        assertTrue(t.puts.isEmpty())
        assertEquals(1, store.dirty().size)
    }

    @Test fun dirtyJourneysAreUploadedOnceAndThenLeftAlone() {
        store.save(journey("j", listOf(leg("a"))))
        val t = FakeTransport()
        assertEquals(JourneySyncOutcome.Done(1, 0, 0), engine(t).drain())
        assertEquals(JourneySyncOutcome.Done(0, 0, 0), engine(t).drain())
        assertEquals(listOf("j"), t.puts)
    }

    @Test fun anOfflineFailureKeepsTheJourneyForALaterRun() {
        store.save(journey("j", listOf(leg("a"))))
        assertEquals(JourneySyncOutcome.RetryLater, engine(FakeTransport(put = { SyncCall.Retry() })).drain())
        assertEquals(1, store.dirty().size)
        assertEquals(JourneySyncOutcome.Done(1, 0, 0), engine(FakeTransport()).drain())
    }

    @Test fun aRefusedJourneyStaysDirtyButDoesNotBlockTheOthers() {
        store.save(journey("bad", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        store.save(journey("good", listOf(leg("b")), updated = "2026-10-28T10:01:00Z"))
        val t = FakeTransport(put = { if (it.id == "bad") SyncCall.Refused(409) else SyncCall.Ok })
        assertEquals(JourneySyncOutcome.Done(1, 0, 1), engine(t).drain())
        assertEquals(listOf("bad"), store.dirty().map { it.id })
    }

    @Test fun aRevokedCredentialStopsEverything() {
        store.save(journey("j", listOf(leg("a"))))
        assertEquals(JourneySyncOutcome.CredentialRevoked, engine(FakeTransport(put = { SyncCall.Unauthorized })).drain())
    }

    @Test fun deletesAreDeliveredEvenWithBackupOffAndOnlyForJourneysTheServerHeld() {
        backedUp("j")
        store.delete("j")
        store.save(journey("never", listOf(leg("n"))))
        store.delete("never")
        val t = FakeTransport()
        assertEquals(JourneySyncOutcome.Done(0, 1, 0), engine(t, enabled = false).drain())
        assertEquals(listOf("j"), t.deletes)
        assertTrue(store.pendingDeletes().isEmpty())
    }

    @Test fun aFailedDeleteIsRetriedAndNoUploadIsAttemptedBeforeIt() {
        backedUp("j")
        store.delete("j")
        store.save(journey("other", listOf(leg("b"))))
        val t = FakeTransport(delete = { SyncCall.Retry() })
        assertEquals(JourneySyncOutcome.RetryLater, engine(t).drain())
        assertTrue(t.puts.isEmpty())
        assertEquals(listOf("j"), store.pendingDeletes())
    }

    @Test fun aDeleteTheServerCanNeverActOnIsDropped() {
        store.queueDelete("ghost")
        assertEquals(JourneySyncOutcome.Done(0, 1, 0), engine(FakeTransport(delete = { SyncCall.Refused(404) })).drain())
        assertTrue(store.pendingDeletes().isEmpty())
    }

    @Test fun aJourneyDeletedWhileItsUploadWasInFlightIsRemovedFromTheServerToo() {
        store.save(journey("j", listOf(leg("a"))))
        val t = FakeTransport()
        t.put = { store.delete(it.id); SyncCall.Ok } // the user deletes it during the request
        assertEquals(JourneySyncOutcome.Done(1, 1, 0), engine(t).drain())
        assertEquals(listOf("j"), t.deletes)
        assertFalse(store.pendingDeletes().contains("j"))
    }
}

class JourneyBackupRegressionTest {
    private val store = InMemoryJourneyStore()

    private fun engine(t: FakeTransport) = JourneySyncEngine(store, store, t) { true }

    // ---- M1: a lost upload reply followed by a delete ----
    @Test fun aDeleteAfterALostUploadReplyIsStillOwedToTheServerAndSurvivesRetries() {
        store.save(journey("j", listOf(leg("a"))))
        // The request reached the server but the answer never came back: the phone saw a network failure.
        assertEquals(JourneySyncOutcome.RetryLater, engine(FakeTransport(put = { SyncCall.Retry() })).drain())
        assertTrue(store.pendingDeletes().isEmpty())
        store.delete("j")
        assertEquals(listOf("j"), store.pendingDeletes()) // owed, although the journey was never acknowledged
        // Offline for a while: the debt stays, run after run.
        val down = FakeTransport(delete = { SyncCall.Retry() })
        repeat(3) { assertEquals(JourneySyncOutcome.RetryLater, engine(down).drain()) }
        assertEquals(listOf("j"), store.pendingDeletes())
        // Back online (a fresh engine over the same store, as after a restart): delivered exactly once.
        val up = FakeTransport()
        assertEquals(JourneySyncOutcome.Done(0, 1, 0), engine(up).drain())
        assertEquals(listOf("j"), up.deletes)
        assertTrue(store.pendingDeletes().isEmpty())
        assertEquals(JourneySyncOutcome.Done(0, 0, 0), engine(up).drain())
        assertEquals(1, up.deletes.size)
    }

    @Test fun aJourneyThatWasNeverSentOwesNoDelete() {
        store.save(journey("never", listOf(leg("a"))))
        store.delete("never")
        assertTrue(store.pendingDeletes().isEmpty())
    }

    @Test fun forgettingTheServerClearsWhatWasOwedToIt() {
        store.save(journey("j", listOf(leg("a"))))
        engine(FakeTransport(put = { SyncCall.Retry() })).drain()
        store.forgetSync() // the phone now talks to a different server
        store.delete("j")
        assertTrue(store.pendingDeletes().isEmpty())
    }

    @Test fun aJourneyDeletedAfterThePendingListWasReadIsNeverSent() {
        store.save(journey("a", listOf(leg("la")), updated = "2026-10-28T10:00:00Z"))
        store.save(journey("b", listOf(leg("lb")), updated = "2026-10-28T10:01:00Z"))
        val t = FakeTransport()
        t.put = { if (it.id == "a") store.delete("b"); SyncCall.Ok } // the user deletes b while a is in flight
        engine(t).drain()
        assertEquals(listOf("a"), t.puts) // b was gone before its turn: nothing is sent, and nothing is owed
        assertTrue(store.pendingDeletes().isEmpty())
    }

    // ---- M2/M4: revisions, not clocks, decide what the server keeps ----
    @Test fun everySavedEditGetsTheNextRevisionEvenWithTheSameOrAnEarlierTimestamp() {
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z")) // same instant
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T09:00:00Z")) // clock stepped back
        assertEquals(3L, store.dirtyUploads().single().revision)
    }

    @Test fun anEditWithTheSameTimestampAsTheSyncedOneIsStillUploaded() {
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        val t = FakeTransport()
        engine(t).drain()
        store.save(journey("j", listOf(leg("a"), leg("b")), updated = "2026-10-28T10:00:00Z")) // clock did not move
        assertEquals(1, store.dirty().size)
        assertEquals(JourneySyncOutcome.Done(1, 0, 0), engine(t).drain())
        assertEquals(listOf(1L, 2L), t.revisions)
    }

    @Test fun aSaveDuringTheUploadLeavesTheJourneyDirtyEvenWithTheSameTimestamp() {
        store.save(journey("j", listOf(leg("a")), updated = "2026-10-28T10:00:00Z"))
        val t = FakeTransport()
        t.put = { store.save(journey("j", listOf(leg("a"), leg("b")), updated = "2026-10-28T10:00:00Z")); SyncCall.Ok }
        engine(t).drain()
        assertEquals(1, store.dirty().size) // revision 2 was never sent
    }

    @Test fun aServerThatKeepsANewerRevisionIsNeverReportedAsBackedUp() {
        store.save(journey("j", listOf(leg("a"))))
        val t = FakeTransport(put = { SyncCall.Stale(serverRevision = 9) })
        assertEquals(JourneySyncOutcome.RetryLater, engine(t).drain())
        assertEquals(1, store.dirty().size) // visible as waiting in the UI
        // The next run uses a revision above the server's, so it applies.
        val fixed = FakeTransport()
        assertEquals(JourneySyncOutcome.Done(1, 0, 0), engine(fixed).drain())
        assertEquals(listOf(10L), fixed.revisions)
        assertTrue(store.dirty().isEmpty())
    }

    @Test fun theAnswerToAPutIsInterpretedByRevisionNotByTheFlagAlone() {
        fun answer(applied: Boolean, held: Long) = """{"applied":$applied,"journey":{"revision":$held}}"""
        assertEquals(SyncCall.Ok, ApiJourneyTransport.answerToPut(answer(true, 3), 3))
        assertEquals(SyncCall.Ok, ApiJourneyTransport.answerToPut(answer(false, 3), 3)) // the same edit again
        assertEquals(SyncCall.Stale(5), ApiJourneyTransport.answerToPut(answer(false, 5), 3))
        assertEquals(SyncCall.Refused(200), ApiJourneyTransport.answerToPut(answer(false, 1), 3))
        assertEquals(SyncCall.Refused(200), ApiJourneyTransport.answerToPut("not json", 3))
        assertEquals(SyncCall.Refused(200), ApiJourneyTransport.answerToPut("""{"applied":true}""", 3))
    }
}

class JourneyCodecTest {
    @Test fun theWireFormMatchesTheServerContract() {
        val json = JSONObject(
            JourneyCodec.put(
                journey(
                    "j",
                    listOf(
                        leg("a", TransportMode.FLIGHT, number = "6E 123"),
                        leg("b", TransportMode.TAXI, departure = null, arrival = null),
                    ),
                ),
                7,
            ),
        )
        assertEquals(7, json.getLong("revision"))
        assertEquals("Trip j", json.getString("title"))
        assertEquals("DRAFT", json.getString("status"))
        assertEquals("2026-10-28T10:00:00Z", json.getString("updated_at"))
        val legs = json.getJSONArray("legs")
        assertEquals("a", legs.getJSONObject(0).getString("id"))
        assertEquals("FLIGHT", legs.getJSONObject(0).getString("mode"))
        assertEquals("6E 123", legs.getJSONObject(0).getString("service_number"))
        assertEquals("2026-11-01T07:45:00+05:30", legs.getJSONObject(0).getString("departure_at"))
        assertEquals("Asia/Kolkata", legs.getJSONObject(0).getString("departure_zone"))
        assertTrue(legs.getJSONObject(1).isNull("departure_at"))
        assertTrue(legs.getJSONObject(1).isNull("departure_zone"))
        assertTrue(legs.getJSONObject(1).isNull("service_number"))
        // The server rejects unknown fields, so the top level must be exactly this.
        assertEquals(setOf("title", "status", "created_at", "updated_at", "revision", "legs"), json.keys().asSequence().toSet())
    }
}

class JourneyEventSyncTest {
    private val store = InMemoryJourneyStore()
    private val at = Instant.parse("2026-11-01T06:00:00Z")

    private fun engine(t: FakeTransport, enabled: Boolean = true) = JourneySyncEngine(store, store, t) { enabled }

    private fun event(id: String, journey: String = "j") = JourneyEvent(id, journey, "observation", at, mapOf("battery_percent" to 40))

    @Test fun eventsGoWithABackedUpJourneyOnceAndAreThenMarkedSent() {
        store.save(journey("j", listOf(leg("a"))))
        store.appendEvent(event("e1"))
        store.appendEvent(event("e2"))
        val t = FakeTransport()
        assertEquals(JourneySyncOutcome.Done(1, 0, 0, 2), engine(t).drain())
        assertEquals(listOf("j" to listOf("e1", "e2")), t.batches)
        assertEquals(JourneySyncOutcome.Done(0, 0, 0, 0), engine(t).drain())
        assertEquals(1, t.batches.size)
    }

    @Test fun eventsStayOnThePhoneWhileBackupIsOff() {
        store.save(journey("j", listOf(leg("a"))))
        store.appendEvent(event("e1"))
        val t = FakeTransport()
        engine(t, enabled = false).drain()
        assertTrue(t.batches.isEmpty())
        assertEquals(1, store.pendingEvents("j", 10).size)
    }

    @Test fun eventsWaitUntilTheJourneyItselfIsOnTheServer() {
        store.save(journey("j", listOf(leg("a"))))
        store.appendEvent(event("e1"))
        // The journey upload is refused, so it stays unsynced; its events must not be sent ahead of it.
        val t = FakeTransport(put = { SyncCall.Refused(409) })
        engine(t).drain()
        assertTrue(t.batches.isEmpty())
        assertEquals(1, store.pendingEvents("j", 10).size)
    }

    @Test fun anOfflineBatchIsKeptAndRetried() {
        store.save(journey("j", listOf(leg("a"))))
        store.appendEvent(event("e1"))
        assertEquals(JourneySyncOutcome.RetryLater, engine(FakeTransport(events = { _, _ -> SyncCall.Retry() })).drain())
        assertEquals(1, store.pendingEvents("j", 10).size)
        assertEquals(JourneySyncOutcome.Done(0, 0, 0, 1), engine(FakeTransport()).drain())
    }

    @Test fun largeBacklogsGoInBoundedBatches() {
        store.save(journey("j", listOf(leg("a"))))
        repeat(250) { store.appendEvent(event("e$it")) }
        val t = FakeTransport()
        engine(t).drain()
        assertEquals(listOf(100, 100, 50), t.batches.map { it.second.size })
    }

    @Test fun theEventBodyMatchesTheServerContract() {
        val json = org.json.JSONObject(JourneyCodec.events("b1", listOf(event("e1"))))
        assertEquals(setOf("batch_id", "events"), json.keys().asSequence().toSet())
        val e = json.getJSONArray("events").getJSONObject(0)
        assertEquals(setOf("event_id", "event_type", "occurred_at", "data"), e.keys().asSequence().toSet())
        assertEquals("2026-11-01T06:00:00Z", e.getString("occurred_at"))
        assertEquals(40, e.getJSONObject("data").getInt("battery_percent"))
    }
}
