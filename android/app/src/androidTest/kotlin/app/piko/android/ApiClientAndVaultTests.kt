package app.piko.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import app.piko.android.core.Batch
import app.piko.android.core.DeliveryState
import app.piko.android.core.EventData
import app.piko.android.core.EventPriority
import app.piko.android.core.EventType
import app.piko.android.core.QueuedEvent
import app.piko.android.core.SendResult
import app.piko.android.data.DeviceVault
import app.piko.android.data.Enrollment
import app.piko.android.net.ApiClient
import app.piko.android.net.PairResult
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.ServerSocket
import java.util.zip.GZIPInputStream
import kotlin.concurrent.thread

/** A one-connection-at-a-time HTTP server on loopback that replays a scripted response. */
private class MiniServer(private val status: Int, private val body: String, private val headers: Map<String, String> = emptyMap()) {
    private val socket = ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))
    val base = "http://127.0.0.1:${socket.localPort}"
    @Volatile var requestHeaders: Map<String, String> = emptyMap()
    @Volatile var requestBody: ByteArray = ByteArray(0)
    @Volatile var requests = 0

    init {
        thread(isDaemon = true) {
            while (!socket.isClosed) {
                try {
                    socket.accept().use { client ->
                        val input = client.getInputStream()
                        val head = readHead(input)
                        requestHeaders = head.lines().drop(1).filter { ":" in it }.associate { it.substringBefore(":").lowercase() to it.substringAfter(":").trim() }
                        val length = requestHeaders["content-length"]?.toInt() ?: 0
                        requestBody = ByteArray(length).also { buf -> var read = 0; while (read < length) read += input.read(buf, read, length - read) }
                        requests++
                        val payload = body.toByteArray()
                        val extra = headers.entries.joinToString("") { "${it.key}: ${it.value}\r\n" }
                        client.getOutputStream().apply {
                            write("HTTP/1.1 $status X\r\nContent-Type: application/json\r\nContent-Length: ${payload.size}\r\n${extra}Connection: close\r\n\r\n".toByteArray())
                            write(payload); flush()
                        }
                    }
                } catch (_: Exception) {
                    // socket closed by the test
                }
            }
        }
    }

    private fun readHead(input: InputStream): String {
        val out = ByteArrayOutputStream()
        while (!out.toString().endsWith("\r\n\r\n")) {
            val b = input.read()
            if (b < 0) break
            out.write(b)
        }
        return out.toString()
    }

    fun close() = socket.close()
}

class ApiClientTest {
    private var server: MiniServer? = null

    @After fun stop() { server?.close() }

    private fun batch(vararg ids: String) = Batch(
        "batch-1",
        ids.mapIndexed { i, id ->
            QueuedEvent(i + 1L, id, EventType.BATTERY, "2026-10-16T10:00:00Z", EventData.Battery(50, null).toJson(),
                EventPriority.NORMAL, DeliveryState.SUBMITTED, 0, "batch-1", null)
        },
    )

    private fun send(status: Int, body: String = "{}", headers: Map<String, String> = emptyMap(), batch: Batch = batch("a")): SendResult {
        val s = MiniServer(status, body, headers).also { server = it }
        return ApiClient(s.base, "dev-1", "secret-token").send(batch)
    }

    @Test fun acceptedBatchIsParsedAndCarriesOnlyTheBearerCredential() {
        val result = send(202, """{"batch_id":"batch-1","status":"accepted","accepted_event_ids":["a"],"duplicate_event_ids":[],"rejected_events":[]}""")
        assertEquals(SendResult.Ack(setOf("a"), emptySet(), emptyMap()), result)
        val headers = server!!.requestHeaders
        assertEquals("Bearer secret-token", headers["authorization"])
        assertEquals("application/json", headers["content-type"])
    }

    @Test fun statusCodesMapToTheRightRecoveryBehaviour() {
        assertEquals(SendResult.Unauthorized, send(401))
        assertEquals(SendResult.RateLimited(7), send(429, headers = mapOf("Retry-After" to "7")))
        assertEquals(SendResult.ServerError(503), send(503))
        assertEquals(SendResult.ServerError(413), send(413)) // too big: send less
        assertEquals(SendResult.ServerError(202), send(202, "garbage")) // unreadable success is not an ack
        assertEquals(SendResult.Refused(400, "VALIDATION_ERROR"), send(400, """{"error":{"code":"VALIDATION_ERROR"}}"""))
    }

    @Test fun redirectsAreNotFollowed() {
        val result = send(302, "", mapOf("Location" to "http://127.0.0.1:1/elsewhere"))
        assertEquals(SendResult.Refused(302, null), result)
    }

    @Test fun nothingListeningIsANetworkFailureNotACrash() {
        val dead = ServerSocket(0).use { it.localPort } // a port that was just released
        val result = ApiClient("http://127.0.0.1:$dead", "d", "t").send(batch("a"))
        assertTrue(result is SendResult.Network)
    }

    @Test fun largeBatchesAreGzippedAndTheSizesAreReported() {
        var size: app.piko.android.net.PayloadSize? = null
        val s = MiniServer(202, """{"accepted_event_ids":[],"duplicate_event_ids":[],"rejected_events":[]}""").also { server = it }
        val big = batch(*Array(60) { "event-id-$it-" + "x".repeat(20) })
        ApiClient(s.base, "dev-1", "t") { size = it }.send(big)
        assertEquals("gzip", s.requestHeaders["content-encoding"])
        val decoded = GZIPInputStream(s.requestBody.inputStream()).readBytes().decodeToString()
        assertTrue(decoded.contains("\"batch_id\":\"batch-1\""))
        assertEquals(60, size!!.events)
        assertTrue(size!!.wireBytes < size!!.rawBytes)
    }

    @Test fun pairingMapsTheServersAnswers() {
        val ok = MiniServer(201, """{"device_id":"d1","device_credential":"pkd_x","api_endpoint":"https://evil.example/api/v1","polling_interval_seconds":60,"family_id":"f1"}""").also { server = it }
        val paired = ApiClient(ok.base).pair("ABC-DEF-GHI", "Phone", "Pixel", "16", "0.4.0")
        assertEquals(PairResult.Success(app.piko.android.net.PairedDevice("d1", "f1", "pkd_x")), paired)
        assertFalse(String(ok.requestBody).contains("pkd_")) // the request carries no credential
        ok.close()
        assertEquals(PairResult.InvalidCode, MiniServer(401, "{}").also { server = it }.let { ApiClient(it.base).pair("A", "n", "m", "v", "a") })
        server!!.close()
        assertEquals(PairResult.InvalidCode, MiniServer(409, "{}").also { server = it }.let { ApiClient(it.base).pair("A", "n", "m", "v", "a") })
        server!!.close()
        assertEquals(PairResult.RateLimited, MiniServer(429, "{}").also { server = it }.let { ApiClient(it.base).pair("A", "n", "m", "v", "a") })
    }
}

/** Uses its own preferences file: these tests must never read or wipe the real app's pairing. */
class DeviceVaultTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val file = "vault-test-${java.util.UUID.randomUUID()}"
    private val vault get() = DeviceVault(context, file)

    @After fun cleanUp() {
        context.deleteSharedPreferences(file)
    }

    @Test fun enrollmentRoundTripsAndTheCredentialIsNotStoredInPlaintext() {
        val enrollment = Enrollment("dev-1", "fam-1", "https://piko.example.com", "pkd_super-secret-credential", "Aarav's phone")
        vault.save(enrollment)
        assertEquals(enrollment, DeviceVault(context, file).load())
        val raw = context.getSharedPreferences(file, Context.MODE_PRIVATE).all.values.joinToString("|")
        assertFalse("credential must be encrypted at rest", raw.contains("pkd_super-secret-credential"))
    }

    @Test fun clearingForgetsTheEnrollmentAndStopsSharing() {
        vault.save(Enrollment("d", "f", "https://x.example.com", "pkd_c", "n"))
        vault.sharingRequested = true
        vault.clearEnrollment()
        assertNull(vault.load())
        assertFalse(vault.sharingRequested)
    }

    @Test fun defaultsAreTheConservativeOnes() {
        val fresh = vault
        fresh.clearEnrollment()
        assertEquals(app.piko.android.core.SyncMode.POLLING, fresh.mode)
        assertFalse(fresh.sharingRequested)
        assertFalse(fresh.credentialRevoked)
    }
}
