package app.piko.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import app.piko.android.core.CommKind
import app.piko.android.core.NewComm
import app.piko.android.core.PushEvent
import app.piko.android.core.PushType
import app.piko.android.data.Enrollment
import app.piko.android.push.PikoMessagingService
import app.piko.android.push.PushHandler
import com.google.firebase.messaging.RemoteMessage
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.ServerSocket
import java.time.Instant

private val ID = "3f1b7c3e-9d5a-4b1c-8a2e-0c9d4e5f6a7b"

/**
 * The code a push triggers, on a real Android runtime. A local HTTP server stands in for the Piko API;
 * Firebase and Google's push service are NOT involved (a RemoteMessage is built by hand), so this tests what
 * the phone does with a push, not whether FCM delivers one. It uses the app's real vault and queue and
 * cleans up after itself, so run it on an emulator, not on a phone in use.
 */
class PushHandlingTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val graph get() = context.graph
    private var server: MiniServer? = null

    private val body = """
        {"incidents":[{"incident_id":"sos-1","status":"acknowledged","acknowledged_at":"2026-10-17T10:05:00Z","resolved_at":null}],
         "messages":[
           {"message_id":"p1","device_id":"d","sender":"parent","body":"hello","sent_at":"2026-10-17T10:00:00Z","received_at":"2026-10-17T10:00:01Z","status":"delivered","acknowledged_at":null},
           {"message_id":"own-1","device_id":"d","sender":"device","body":"x","sent_at":"2026-10-17T10:00:00Z","received_at":"2026-10-17T10:00:01Z","status":"acknowledged","acknowledged_at":"2026-10-17T10:06:00Z"}],
         "total_count":2,"has_more":false}
    """.trimIndent()

    @Before fun setUp() {
        graph.comms.clear()
        graph.vault.clearEnrollment()
    }

    @After fun tearDown() {
        server?.close()
        graph.comms.clear()
        graph.vault.clearEnrollment()
        graph.setParentMessages(CommsView())
    }

    private fun pair(base: String) = graph.vault.save(Enrollment("dev-1", "fam-1", base, "pkd_secret", "Test phone"))

    private fun deliveredSos(id: String) {
        graph.comms.enqueue(NewComm(id, CommKind.SOS, Instant.parse("2026-10-17T10:00:00Z"), "help"), 0)
        graph.comms.markSubmitted(id)
        graph.comms.markDelivered(id, "open", null, null, 1)
    }

    @Test fun aPushTriggersAnAuthoritativeSyncThatUpdatesLocalState() {
        server = MiniServer(200, body)
        pair(server!!.base)
        deliveredSos("sos-1")
        assertTrue(PushHandler.handle(context, PushEvent(PushType.SOS_UPDATE, ID)))
        assertEquals("acknowledged", graph.comms.items().first { it.id == "sos-1" }.remoteStatus) // from the server, not the push
        assertEquals(listOf("p1"), graph.parentMessages.value.messages.map { it.id })
        assertTrue(server!!.requestLine.contains("/api/v1/"))
    }

    @Test fun theSamePushTwiceChangesNothingTheSecondTime() {
        server = MiniServer(200, body)
        pair(server!!.base)
        deliveredSos("sos-1")
        PushHandler.handle(context, PushEvent(PushType.SOS_UPDATE, ID))
        val after = graph.comms.items()
        PushHandler.handle(context, PushEvent(PushType.SOS_UPDATE, ID))
        assertEquals(after, graph.comms.items())
        assertEquals(1, graph.comms.items().size) // a push can never create a second incident
    }

    @Test fun aPushCannotInventStateTheServerDoesNotHave() {
        server = MiniServer(200, """{"incidents":[],"messages":[],"total_count":0,"has_more":false}""")
        pair(server!!.base)
        deliveredSos("sos-1")
        PushHandler.handle(context, PushEvent(PushType.SOS_UPDATE, ID))
        assertEquals("open", graph.comms.items().single().remoteStatus) // still only what the server said
    }

    @Test fun whenTheServerCannotBeReachedThePushIsAFallbackNotAnError() {
        val dead = ServerSocket(0).use { it.localPort }
        pair("http://127.0.0.1:$dead")
        deliveredSos("sos-1")
        assertFalse(PushHandler.handle(context, PushEvent(PushType.MESSAGE, ID))) // reports "could not sync"
        assertEquals("open", graph.comms.items().single().remoteStatus)
    }

    @Test fun anUnpairedPhoneIgnoresPushes() {
        assertFalse(PushHandler.handle(context, PushEvent(PushType.MESSAGE, ID)))
        assertTrue(graph.comms.items().isEmpty())
    }

    @Test fun aRevokedPhoneIgnoresPushes() {
        server = MiniServer(200, body)
        pair(server!!.base)
        graph.vault.credentialRevoked = true
        assertFalse(PushHandler.handle(context, PushEvent(PushType.MESSAGE, ID)))
        assertEquals(0, server!!.requests)
    }

    // ---- the Firebase service entry point ----------------------------------------------------------------
    private fun service() = object : PikoMessagingService() {
        init {
            attachBaseContext(context)
        }
    }

    private fun remote(vararg data: Pair<String, String>) = RemoteMessage.Builder("piko-test@fcm").setData(mapOf(*data)).build()

    @Test fun theServiceRunsTheHandlerForAWellFormedMessage() {
        server = MiniServer(200, body)
        pair(server!!.base)
        deliveredSos("sos-1")
        service().onMessageReceived(remote("v" to "1", "type" to "sos_update", "id" to ID))
        assertEquals("acknowledged", graph.comms.items().single().remoteStatus)
    }

    @Test fun theServiceIgnoresMalformedForeignOrUnknownMessages() {
        server = MiniServer(200, body)
        pair(server!!.base)
        deliveredSos("sos-1")
        val s = service()
        s.onMessageReceived(remote())
        s.onMessageReceived(remote("v" to "9", "type" to "sos_update", "id" to ID))
        s.onMessageReceived(remote("v" to "1", "type" to "delete_everything", "id" to ID))
        s.onMessageReceived(remote("v" to "1", "type" to "message", "id" to "../../etc/passwd"))
        assertEquals(0, server!!.requests) // nothing contacted the server for any of them
        assertEquals("open", graph.comms.items().single().remoteStatus)
    }

    @Test fun aNewTokenIsStoredAndRegisteredWithTheServerWhenPaired() {
        server = MiniServer(204, "")
        pair(server!!.base)
        service().onNewToken("fcm-test-token-" + "A".repeat(40))
        assertEquals("fcm-test-token-" + "A".repeat(40), graph.vault.pushToken)
        assertEquals(graph.vault.pushToken, graph.vault.pushConfirmed)
        assertTrue(server!!.requestLine.startsWith("PUT /api/v1/push/device-token"))
        assertEquals("Bearer pkd_secret", server!!.requestHeaders["authorization"])
    }

    @Test fun aTokenIssuedWhileUnpairedIsKeptAndRegisteredLater() {
        service().onNewToken("fcm-early-token-" + "B".repeat(40))
        assertEquals("fcm-early-token-" + "B".repeat(40), graph.vault.pushToken)
        assertNull(graph.vault.pushConfirmed)
    }

    @Test fun anUnpairedPhoneForgetsTheServersConfirmation() {
        server = MiniServer(204, "")
        pair(server!!.base)
        service().onNewToken("fcm-test-token-" + "C".repeat(40))
        graph.vault.clearEnrollment()
        assertNull(graph.vault.pushConfirmed) // re-pairing registers again instead of assuming
    }
}
