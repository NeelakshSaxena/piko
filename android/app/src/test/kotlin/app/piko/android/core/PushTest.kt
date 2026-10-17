package app.piko.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PushPayloadTest {
    private val id = "3f1b7c3e-9d5a-4b1c-8a2e-0c9d4e5f6a7b"

    @Test fun aWellFormedPushIsParsed() {
        assertEquals(PushEvent(PushType.SOS_CREATED, id), PushPayload.parse(mapOf("v" to "1", "type" to "sos_created", "id" to id)))
        assertEquals(PushType.SOS_UPDATE, PushPayload.parse(mapOf("v" to "1", "type" to "sos_update", "id" to id))!!.type)
        assertEquals(PushType.MESSAGE, PushPayload.parse(mapOf("v" to "1", "type" to "message", "id" to id.uppercase()))!!.type)
        assertEquals(id, PushPayload.parse(mapOf("v" to "1", "type" to "message", "id" to id.uppercase()))!!.id) // normalised
    }

    @Test fun anythingUnexpectedIsIgnored() {
        assertNull(PushPayload.parse(emptyMap()))
        assertNull(PushPayload.parse(mapOf("v" to "2", "type" to "message", "id" to id))) // unknown version
        assertNull(PushPayload.parse(mapOf("v" to "1", "type" to "sos_resolve_everything", "id" to id))) // unknown type
        assertNull(PushPayload.parse(mapOf("v" to "1", "type" to "message", "id" to "not-a-uuid")))
        assertNull(PushPayload.parse(mapOf("v" to "1", "type" to "message", "id" to "$id; drop table")))
        assertNull(PushPayload.parse(mapOf("type" to "message", "id" to id))) // no version
    }

    @Test fun extraFieldsAreIgnoredAndNeverUsed() {
        val e = PushPayload.parse(mapOf("v" to "1", "type" to "message", "id" to id, "body" to "secret", "url" to "http://evil"))
        assertEquals(PushEvent(PushType.MESSAGE, id), e) // the event has no place to carry them
    }
}

private class PushMemoryTokens(override var current: String? = null, override var confirmed: String? = null) : TokenStore

private class PushFakeServer(var put: PushCall = PushCall.Ok, var delete: PushCall = PushCall.Ok) : TokenServer {
    val puts = ArrayList<String>()
    var deletes = 0
    override fun put(token: String): PushCall { puts += token; return put }
    override fun delete(): PushCall { deletes++; return delete }
}

class TokenSyncTest {
    private val store = PushMemoryTokens()
    private val server = PushFakeServer()
    private val sync = TokenSync(store, server)

    @Test fun nothingHappensBeforeFirebaseHasGivenAToken() {
        assertEquals(TokenSyncResult.NOTHING_TO_DO, sync.sync())
        assertTrue(server.puts.isEmpty())
    }

    @Test fun aNewTokenIsRegisteredOnceAndNotRepeated() {
        sync.onNewToken("t1")
        assertEquals(TokenSyncResult.REGISTERED, sync.sync())
        assertEquals(TokenSyncResult.UP_TO_DATE, sync.sync())
        assertEquals(listOf("t1"), server.puts)
        assertEquals("t1", store.confirmed)
    }

    @Test fun rotationReplacesTheServersTokenAndOnlyThen() {
        sync.onNewToken("t1"); sync.sync()
        sync.onNewToken("t2")
        assertEquals("t1", store.confirmed) // the server still has the old one until it is told
        assertEquals(TokenSyncResult.REGISTERED, sync.sync())
        assertEquals(listOf("t1", "t2"), server.puts)
        assertEquals("t2", store.confirmed)
    }

    @Test fun aFailedRegistrationStaysPendingAndIsRetried() {
        sync.onNewToken("t1")
        server.put = PushCall.Retry
        assertEquals(TokenSyncResult.RETRY_LATER, sync.sync())
        assertNull(store.confirmed)
        server.put = PushCall.Ok
        assertEquals(TokenSyncResult.REGISTERED, sync.sync())
    }

    @Test fun aRevokedCredentialIsReportedAndNothingIsConfirmed() {
        sync.onNewToken("t1")
        server.put = PushCall.Unauthorized
        assertEquals(TokenSyncResult.CREDENTIAL_REVOKED, sync.sync())
        assertNull(store.confirmed)
    }

    @Test fun aRefusedTokenIsNotConfirmed() {
        sync.onNewToken("t1")
        server.put = PushCall.Refused(400)
        assertEquals(TokenSyncResult.REJECTED, sync.sync())
        assertNull(store.confirmed)
    }

    @Test fun unregisteringTellsTheServerAndForgetsTheConfirmation() {
        sync.onNewToken("t1"); sync.sync()
        assertEquals(PushCall.Ok, sync.unregister())
        assertEquals(1, server.deletes)
        assertNull(store.confirmed)
        // the next sync (after re-pairing) registers again instead of assuming the server still has it
        assertEquals(TokenSyncResult.REGISTERED, sync.sync())
    }

    @Test fun anUnregisterThatCannotReachTheServerStillClearsLocalState() {
        sync.onNewToken("t1"); sync.sync()
        server.delete = PushCall.Retry
        assertEquals(PushCall.Retry, sync.unregister())
        assertNull(store.confirmed)
    }
}
