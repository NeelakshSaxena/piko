package app.piko.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import kotlin.random.Random

class InMemoryCommStoreContractTest : CommStoreContract() {
    override fun newStore(): CommStore = InMemoryCommStore()
}

/** A server that stores by id and de-duplicates, like the real backend (201 first, 200 on replay). */
private class FakeCommServer {
    val stored = LinkedHashMap<String, String>() // id -> status
    val attempts = ArrayList<String>()
    var parentMessages = listOf<RemoteMessage>()

    fun accept(item: CommItem): CommResult.Delivered {
        attempts += item.id
        stored.putIfAbsent(item.id, if (item.kind == CommKind.SOS) "open" else "delivered")
        return CommResult.Delivered(stored.getValue(item.id), null, null)
    }
}

class CommEngineTest {
    private var now = 1_000_000L
    private val clock = Clock { now }
    private val store = InMemoryCommStore()
    private val server = FakeCommServer()

    private fun sos(id: String) = NewComm(id, CommKind.SOS, Instant.parse("2026-10-17T10:00:00Z"), "help")
    private fun msg(id: String) = NewComm(id, CommKind.MESSAGE, Instant.parse("2026-10-17T10:00:00Z"), "hi")

    private fun transport(
        onDeliver: (CommItem) -> CommResult = { server.accept(it) },
        sosList: Fetch<List<RemoteSos>> = Fetch.Ok(emptyList()),
        messages: Fetch<List<RemoteMessage>> = Fetch.Ok(emptyList()),
        own: Fetch<List<RemoteMessageStatus>> = Fetch.Ok(emptyList()),
    ) = object : CommTransport {
        override fun deliver(item: CommItem) = onDeliver(item)
        override fun fetchSos() = sosList
        override fun fetchParentMessages() = messages
        override fun fetchOwnMessages() = own
        override fun acknowledgeMessage(id: String): CommResult = CommResult.Delivered("acknowledged", null, null)
    }

    private fun engine(t: CommTransport) = CommEngine(store, t, clock, Random(1))

    @Test fun deliversOnlyAfterTheServerSaysItStoredIt() {
        store.enqueue(sos("s1"), now)
        var seenWhileSending: CommState? = null
        val e = engine(transport(onDeliver = { item ->
            seenWhileSending = store.items().first { it.id == item.id }.state
            server.accept(item)
        }))
        assertEquals(SyncOutcome.Done(1, false), e.drain())
        assertEquals(CommState.SUBMITTED, seenWhileSending) // never "delivered" before the answer
        assertEquals(CommState.DELIVERED, store.items().single().state)
        assertEquals("open", store.items().single().remoteStatus)
    }

    @Test fun offlineSosIsRetainedAndSentExactlyOnceOnReconnect() {
        store.enqueue(sos("s1"), now)
        var online = false
        val e = engine(transport(onDeliver = { if (online) server.accept(it) else CommResult.Network("UnknownHostException") }))
        repeat(3) { assertTrue(e.drain() is SyncOutcome.RetryAfter) }
        assertEquals(1, store.pendingCount()) // retained through three failures
        assertTrue(server.stored.isEmpty())
        online = true
        assertEquals(SyncOutcome.Done(1, false), e.drain())
        assertEquals(1, server.stored.size)
        assertEquals(0, store.pendingCount())
        assertEquals(SyncOutcome.Done(0, false), e.drain()) // nothing is sent a second time
        assertEquals(1, server.attempts.size)
    }

    @Test fun aLostResponseResendsTheSameIdAndTheServerKeepsOneIncident() {
        store.enqueue(sos("s1"), now)
        var calls = 0
        val e = engine(transport(onDeliver = {
            val ok = server.accept(it) // the server stored it...
            if (++calls == 1) CommResult.Network("SocketTimeoutException") else ok // ...but the answer was lost
        }))
        assertTrue(e.drain() is SyncOutcome.RetryAfter)
        assertEquals(CommState.SUBMITTED, store.items().single().state) // in doubt, not "delivered"
        assertEquals(SyncOutcome.Done(1, false), e.drain())
        assertEquals(listOf("s1", "s1"), server.attempts) // identical id both times
        assertEquals(1, server.stored.size)
    }

    @Test fun sosGoesBeforeMessagesAfterReconnect() {
        store.enqueue(msg("m1"), now); store.enqueue(sos("s1"), now); store.enqueue(msg("m2"), now)
        engine(transport()).drain()
        assertEquals(listOf("s1", "m1", "m2"), server.attempts)
    }

    @Test fun aRetryableFailureStopsTheDrainAndBlocksNothingFromBeingRetriedLater() {
        store.enqueue(sos("s1"), now); store.enqueue(msg("m1"), now)
        val e = engine(transport(onDeliver = { CommResult.ServerError(503) }))
        val out = e.drain()
        assertTrue(out is SyncOutcome.RetryAfter && out.reason == RetryReason.SERVER_ERROR)
        assertEquals(2, store.pendingCount())
        assertEquals(1, store.items().first { it.id == "s1" }.attempts)
        assertEquals(CommState.QUEUED, store.items().first { it.id == "s1" }.state)
    }

    @Test fun nothingRetryableIsEverGivenUp() {
        store.enqueue(sos("s1"), now)
        val e = engine(transport(onDeliver = { CommResult.ServerError(500) }))
        repeat(60) { assertTrue(e.drain() is SyncOutcome.RetryAfter) }
        assertEquals(1, store.pendingCount())
        assertEquals(CommState.QUEUED, store.items().single().state)
    }

    @Test fun rateLimitHonoursRetryAfterAndDoesNotCountAnAttempt() {
        store.enqueue(msg("m1"), now)
        val e = engine(transport(onDeliver = { CommResult.RateLimited(120) }))
        val out = e.drain() as SyncOutcome.RetryAfter
        assertEquals(RetryReason.RATE_LIMITED, out.reason)
        assertTrue(out.delayMs >= 120_000)
        assertEquals(0, store.items().single().attempts)
    }

    @Test fun backoffGrowsAndIsCapped() {
        store.enqueue(msg("m1"), now)
        val e = engine(transport(onDeliver = { CommResult.Network("x") }))
        val delays = List(12) { (e.drain() as SyncOutcome.RetryAfter).delayMs }
        assertTrue(delays[0] in 2_500..5_000)
        assertTrue(delays[5] > delays[0])
        assertTrue(delays.all { it <= SyncConfig().maxBackoffMs })
    }

    @Test fun aRefusalMarksFailedWithAReasonAndMovesOn() {
        store.enqueue(msg("bad"), now); store.enqueue(msg("good"), now)
        val e = engine(transport(onDeliver = {
            if (it.id == "bad") CommResult.Refused(400, "VALIDATION_ERROR") else server.accept(it)
        }))
        assertEquals(SyncOutcome.Done(1, false), e.drain())
        val bad = store.items().first { it.id == "bad" }
        assertEquals(CommState.FAILED, bad.state)
        assertTrue(bad.failReason!!.contains("400"))
        assertEquals(CommState.DELIVERED, store.items().first { it.id == "good" }.state)
    }

    @Test fun aRevokedCredentialStopsAndKeepsTheItem() {
        store.enqueue(sos("s1"), now)
        assertEquals(SyncOutcome.CredentialRevoked, engine(transport(onDeliver = { CommResult.Unauthorized })).drain())
        assertEquals(1, store.pendingCount())
    }

    @Test fun refreshAdvancesSosStatusOnceAndReportsOnlyWhatChanged() {
        store.enqueue(sos("s1"), now)
        engine(transport()).drain()
        val ack = Fetch.Ok(listOf(RemoteSos("s1", "acknowledged", "2026-10-17T10:05:00Z", null)))
        val first = engine(transport(sosList = ack)).refresh() as RefreshOutcome.Ok
        assertEquals(listOf("s1" to "acknowledged"), first.result.sosAdvanced)
        val second = engine(transport(sosList = ack)).refresh() as RefreshOutcome.Ok
        assertTrue(second.result.sosAdvanced.isEmpty()) // the same news is not announced twice
        assertEquals("acknowledged", store.items().single().remoteStatus)
    }

    @Test fun refreshNeverMarksAnUndeliveredSosAsAcknowledged() {
        store.enqueue(sos("s1"), now) // still only on the phone
        val out = engine(transport(sosList = Fetch.Ok(listOf(RemoteSos("s1", "resolved", null, null))))).refresh() as RefreshOutcome.Ok
        assertTrue(out.result.sosAdvanced.isEmpty())
        assertEquals(CommState.QUEUED, store.items().single().state)
        assertNull(store.items().single().remoteStatus)
    }

    @Test fun aParentMarkingTheChildsMessageAsSeenReachesThePhoneAndOnlyThen() {
        store.enqueue(msg("m1"), now)
        assertEquals(RefreshOutcome.Ok(RefreshResult(emptyList(), emptyList())), engine(transport(own = Fetch.Ok(listOf(RemoteMessageStatus("m1", "acknowledged", "2026-10-17T10:09:00Z"))))).refresh())
        assertEquals(CommState.QUEUED, store.items().single().state) // not delivered yet, so nothing is claimed
        engine(transport()).drain()
        assertEquals("Delivered to the server, not yet seen", CommLabels.of(store.items().single()).text)
        engine(transport(own = Fetch.Ok(listOf(RemoteMessageStatus("m1", "acknowledged", "2026-10-17T10:09:00Z"))))).refresh()
        assertEquals("Seen by a parent", CommLabels.of(store.items().single()).text)
        engine(transport(own = Fetch.Ok(listOf(RemoteMessageStatus("m1", "delivered", null))))).refresh() // never backwards
        assertEquals("Seen by a parent", CommLabels.of(store.items().single()).text)
    }

    @Test fun aFailedStatusFetchDoesNotHideParentsMessages() {
        val msgs = listOf(RemoteMessage("p1", "hello", "2026-10-17T10:00:00Z", "2026-10-17T10:00:01Z", "delivered"))
        val out = engine(transport(messages = Fetch.Ok(msgs), own = Fetch.Unavailable)).refresh() as RefreshOutcome.Ok
        assertEquals(msgs, out.result.parentMessages)
        assertEquals(RefreshOutcome.CredentialRevoked, engine(transport(own = Fetch.Unauthorized)).refresh())
    }

    @Test fun refreshReportsUnavailableInsteadOfInventingAnEmptyInbox() {
        assertEquals(RefreshOutcome.Unavailable, engine(transport(sosList = Fetch.Unavailable)).refresh())
        assertEquals(RefreshOutcome.CredentialRevoked, engine(transport(sosList = Fetch.Unauthorized)).refresh())
        val msgs = listOf(RemoteMessage("p1", "dinner at 7", "2026-10-17T10:00:00Z", "2026-10-17T10:00:01Z", "delivered"))
        val ok = engine(transport(messages = Fetch.Ok(msgs))).refresh() as RefreshOutcome.Ok
        assertEquals(msgs, ok.result.parentMessages)
    }
}

class CommPoisonTest {
    private val store = InMemoryCommStore()
    private val clock = Clock { 1_000_000L }

    @Test fun oneItemTheServerRejectsWith500DoesNotBlockLaterSosOrMessages() {
        val delivered = ArrayList<String>()
        val transport = object : CommTransport {
            override fun deliver(item: CommItem): CommResult =
                if (item.id == "bad") CommResult.ServerError(500) else { delivered += item.id; CommResult.Delivered("open", null, null) }
            override fun fetchSos() = Fetch.Ok(emptyList<RemoteSos>())
            override fun fetchParentMessages() = Fetch.Ok(emptyList<RemoteMessage>())
            override fun fetchOwnMessages() = Fetch.Ok(emptyList<RemoteMessageStatus>())
            override fun acknowledgeMessage(id: String): CommResult = CommResult.Delivered("acknowledged", null, null)
        }
        val engine = CommEngine(store, transport, clock, Random(1))
        store.enqueue(NewComm("bad", CommKind.SOS, Instant.parse("2026-10-17T10:00:00Z"), "help"), 0)
        store.enqueue(NewComm("later-sos", CommKind.SOS, Instant.parse("2026-10-17T10:00:01Z"), "help2"), 0)
        store.enqueue(NewComm("msg", CommKind.MESSAGE, Instant.parse("2026-10-17T10:00:02Z"), "hi"), 0)
        repeat(POISON_AFTER) { assertTrue(engine.drain() is SyncOutcome.RetryAfter) } // the bad one fails each time
        engine.drain()
        engine.drain()
        assertEquals(listOf("later-sos", "msg"), delivered)
        assertEquals(1, store.pendingCount()) // only the poisoned item remains, and it is still queued
        assertEquals(CommState.QUEUED, store.items().first { it.id == "bad" }.state)
    }
}

class CommModelTest {
    @Test fun controlCharactersAreRefusedByTheModelAndRemovedByTheSanitiser() {
        for (bad in listOf("a\u0000b", "bell\u0007", "del\u007f")) {
            assertFalse(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, bad) }.isSuccess)
            assertFalse(runCatching { NewComm("a", CommKind.SOS, Instant.EPOCH, bad) }.isSuccess)
            assertTrue(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, NewComm.sanitize(bad) + "x") }.isSuccess)
        }
        assertEquals("axb", NewComm.sanitize("a\u0000x\u0007b"))
        // ordinary whitespace and non-Latin text are kept
        assertEquals("one\ntwo\ttab\r", NewComm.sanitize("one\ntwo\ttab\r"))
        assertTrue(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, "two\nlines\tअ") }.isSuccess)
    }

    @Test fun validation() {
        assertFalse(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, "   ") }.isSuccess)
        assertFalse(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, "x".repeat(501)) }.isSuccess)
        assertTrue(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, "x".repeat(500)) }.isSuccess)
        assertFalse(runCatching { NewComm("a", CommKind.SOS, Instant.EPOCH, "x".repeat(281)) }.isSuccess)
        assertTrue(runCatching { NewComm("a", CommKind.SOS, Instant.EPOCH, null) }.isSuccess)
        assertFalse(runCatching { NewComm("a", CommKind.MESSAGE, Instant.EPOCH, "hi", SosPoint(1.0, 2.0, null)) }.isSuccess)
        assertFalse(runCatching { SosPoint(91.0, 0.0, null) }.isSuccess)
        assertFalse(runCatching { SosPoint(0.0, 0.0, -1.0) }.isSuccess)
        assertFalse(runCatching { SosPoint(Double.NaN, 0.0, null) }.isSuccess)
    }

    private fun item(kind: CommKind, state: CommState, remote: String? = null, reason: String? = null) =
        CommItem("a", kind, "2026-10-17T10:00:00Z", null, null, state, 0, reason, null, remote, null, null)

    @Test fun queuedOrSubmittedIsNeverLabelledDeliveredOrSeen() {
        for (kind in CommKind.entries) {
            for (state in listOf(CommState.QUEUED, CommState.SUBMITTED)) {
                val text = CommLabels.of(item(kind, state)).text.lowercase()
                assertFalse("$kind $state: $text", "delivered" in text || "confirmed" in text || "seen by" in text)
            }
        }
        assertTrue("NOT sent" in CommLabels.of(item(CommKind.SOS, CommState.QUEUED)).text)
    }

    @Test fun deliveredIsNotTheSameAsSeenByAParent() {
        val delivered = CommLabels.of(item(CommKind.SOS, CommState.DELIVERED, "open"))
        assertTrue("No parent has confirmed" in delivered.text)
        assertEquals(Tone.PENDING, delivered.tone)
        assertTrue("saw your SOS" in CommLabels.of(item(CommKind.SOS, CommState.DELIVERED, "acknowledged")).text)
        assertTrue("resolved" in CommLabels.of(item(CommKind.SOS, CommState.DELIVERED, "resolved")).text)
        assertEquals("Delivered to the server, not yet seen", CommLabels.of(item(CommKind.MESSAGE, CommState.DELIVERED, "delivered")).text)
        assertEquals("Seen by a parent", CommLabels.of(item(CommKind.MESSAGE, CommState.DELIVERED, "acknowledged")).text)
    }

    @Test fun failureIsShownAsFailureWithAnAdvice() {
        val label = CommLabels.of(item(CommKind.SOS, CommState.FAILED, reason = "refused by server (HTTP 400)"))
        assertEquals(Tone.BAD, label.tone)
        assertTrue("Contact your family another way" in label.text)
    }

    @Test fun codecEscapesUserTextAndKeepsOccurrenceTime() {
        val sos = CommItem("id-1", CommKind.SOS, "2026-10-17T10:00:00Z", "say \"hi\"\n\\", SosPoint(1.5, -2.25, 10.0), CommState.QUEUED, 0, null, null, null, null, null)
        val json = CommCodec.sos("dev-1", sos)
        val parsed = org.json.JSONObject(json)
        assertEquals("id-1", parsed.getString("incident_id"))
        assertEquals("dev-1", parsed.getString("device_id"))
        assertEquals("2026-10-17T10:00:00Z", parsed.getString("triggered_at"))
        assertEquals("say \"hi\"\n\\", parsed.getString("message"))
        assertEquals(1.5, parsed.getJSONObject("location").getDouble("latitude"), 0.0)
        val m = org.json.JSONObject(CommCodec.message(sos.copy(kind = CommKind.MESSAGE, location = null)))
        assertEquals("id-1", m.getString("message_id"))
        assertFalse(m.has("location"))
    }

    @Test fun sosWithoutLocationOrNoteOmitsThem() {
        val sos = CommItem("id", CommKind.SOS, "2026-10-17T10:00:00Z", null, null, CommState.QUEUED, 0, null, null, null, null, null)
        val parsed = org.json.JSONObject(CommCodec.sos("d", sos))
        assertFalse(parsed.has("location"))
        assertFalse(parsed.has("message"))
    }
}
