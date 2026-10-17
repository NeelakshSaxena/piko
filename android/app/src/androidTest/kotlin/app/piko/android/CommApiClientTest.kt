package app.piko.android

import app.piko.android.core.CommItem
import app.piko.android.core.CommKind
import app.piko.android.core.CommResult
import app.piko.android.core.CommState
import app.piko.android.core.Fetch
import app.piko.android.core.RemoteMessageStatus
import app.piko.android.core.RemoteSos
import app.piko.android.net.ApiClient
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket

/** The SOS/message calls of the HTTP client: the status mapping decides whether anything may be dropped. */
class CommApiClientTest {
    private var server: MiniServer? = null

    @After fun stop() { server?.close() }

    private fun item(kind: CommKind) =
        CommItem("id-1", kind, "2026-10-17T10:00:00Z", "help", null, CommState.SUBMITTED, 0, null, null, null, null, null)

    private fun deliver(
        status: Int,
        body: String = "{}",
        kind: CommKind = CommKind.SOS,
        headers: Map<String, String> = emptyMap(),
    ): CommResult {
        val s = MiniServer(status, body, headers).also { server?.close(); server = it }
        return ApiClient(s.base, "dev-1", "secret-token").deliver(item(kind))
    }

    @Test fun sosGoesToTheIncidentEndpointWithTheBearerCredentialAndItsOwnId() {
        val r = deliver(201, """{"incident_id":"id-1","status":"open","acknowledged_at":null,"resolved_at":null}""")
        assertEquals(CommResult.Delivered("open", null, null), r)
        assertTrue(server!!.requestLine.startsWith("POST /api/v1/sos/incidents"))
        assertEquals("Bearer secret-token", server!!.requestHeaders["authorization"])
        val body = JSONObject(server!!.requestBody.decodeToString())
        assertEquals("id-1", body.getString("incident_id"))
        assertEquals("dev-1", body.getString("device_id"))
    }

    @Test fun aReplayAnswer200IsDeliveredToo() {
        val r = deliver(200, """{"status":"acknowledged","acknowledged_at":"2026-10-17T10:05:00Z","resolved_at":null}""")
        assertEquals(CommResult.Delivered("acknowledged", "2026-10-17T10:05:00Z", null), r)
    }

    @Test fun messagesUseTheirOwnEndpoint() {
        deliver(201, """{"status":"delivered","acknowledged_at":null}""", CommKind.MESSAGE)
        assertTrue(server!!.requestLine.startsWith("POST /api/v1/messages "))
        assertEquals("id-1", JSONObject(server!!.requestBody.decodeToString()).getString("message_id"))
    }

    @Test fun statusCodesMapToTheRightRecovery() {
        assertEquals(CommResult.Unauthorized, deliver(401))
        assertEquals(CommResult.RateLimited(9), deliver(429, headers = mapOf("Retry-After" to "9")))
        assertEquals(CommResult.ServerError(503), deliver(503))
        assertEquals(CommResult.ServerError(201), deliver(201, "garbage")) // unreadable: not confirmed, re-sent by id
        assertEquals(CommResult.Refused(409, "CONFLICT"), deliver(409, """{"error":{"code":"CONFLICT"}}"""))
    }

    @Test fun nothingListeningIsANetworkFailure() {
        val dead = ServerSocket(0).use { it.localPort }
        assertTrue(ApiClient("http://127.0.0.1:$dead", "d", "t").deliver(item(CommKind.SOS)) is CommResult.Network)
    }

    @Test fun fetchParsesIncidentsAndKeepsOnlyParentMessages() {
        val s1 = MiniServer(
            200,
            """{"incidents":[{"incident_id":"a","status":"resolved","acknowledged_at":"2026-10-17T10:01:00Z","resolved_at":"2026-10-17T10:02:00Z"}],"total_count":1,"has_more":false}""",
        ).also { server = it }
        val sos = ApiClient(s1.base, "d", "t").fetchSos() as Fetch.Ok
        assertEquals(listOf(RemoteSos("a", "resolved", "2026-10-17T10:01:00Z", "2026-10-17T10:02:00Z")), sos.value)
        s1.close()
        val s2 = MiniServer(
            200,
            """{"messages":[
            {"message_id":"p1","device_id":"d","sender":"parent","body":"dinner","sent_at":"2026-10-17T10:00:00Z","received_at":"2026-10-17T10:00:01Z","status":"delivered","acknowledged_at":null},
            {"message_id":"c1","device_id":"d","sender":"device","body":"mine","sent_at":"2026-10-17T10:00:00Z","received_at":"2026-10-17T10:00:01Z","status":"delivered","acknowledged_at":null}],
            "total_count":2,"has_more":false}""",
        ).also { server = it }
        val msgs = ApiClient(s2.base, "d", "t").fetchParentMessages() as Fetch.Ok
        assertEquals(listOf("p1"), msgs.value.map { it.id })
        assertTrue(s2.requestLine.startsWith("GET /api/v1/messages"))
    }

    @Test fun fetchOwnMessagesAsksForTheDevicesOwnMessagesAndParsesTheirStatus() {
        val s = MiniServer(200, """{"messages":[{"message_id":"c1","device_id":"d","sender":"device","body":"x","sent_at":"2026-10-17T10:00:00Z","received_at":"2026-10-17T10:00:01Z","status":"acknowledged","acknowledged_at":"2026-10-17T10:05:00Z"}],"total_count":1,"has_more":false}""").also { server = it }
        val r = ApiClient(s.base, "d", "t").fetchOwnMessages() as Fetch.Ok
        assertEquals(listOf(RemoteMessageStatus("c1", "acknowledged", "2026-10-17T10:05:00Z")), r.value)
        assertTrue(s.requestLine.contains("sender=device"))
    }

    @Test fun fetchFailuresAreUnavailableOrUnauthorizedNeverAnEmptyList() {
        assertEquals(Fetch.Unauthorized, ApiClient(MiniServer(401, "{}").also { server?.close(); server = it }.base, "d", "t").fetchSos())
        assertEquals(Fetch.Unavailable, ApiClient(MiniServer(503, "{}").also { server?.close(); server = it }.base, "d", "t").fetchSos())
        assertEquals(Fetch.Unavailable, ApiClient(MiniServer(200, "garbage").also { server?.close(); server = it }.base, "d", "t").fetchParentMessages())
    }
}
