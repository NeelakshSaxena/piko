package app.piko.android.net

import app.piko.android.core.Batch
import app.piko.android.core.CommCodec
import app.piko.android.core.CommItem
import app.piko.android.core.CommKind
import app.piko.android.core.CommResult
import app.piko.android.core.CommTransport
import app.piko.android.core.Fetch
import app.piko.android.core.PushCall
import app.piko.android.core.RemoteMessage
import app.piko.android.core.RemoteMessageStatus
import app.piko.android.core.RemoteSos
import app.piko.android.core.BatchCodec
import app.piko.android.core.SendResult
import app.piko.android.core.ServerUrl
import app.piko.android.core.Transport
import org.json.JSONException
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.zip.GZIPOutputStream

data class PairedDevice(val deviceId: String, val familyId: String, val credential: String)

sealed interface PairResult {
    data class Success(val device: PairedDevice) : PairResult

    /** The code is wrong, expired or already used. The server deliberately does not say which. */
    data object InvalidCode : PairResult

    data object RateLimited : PairResult
    data class Failed(val message: String) : PairResult
}

/** Sizes of the last upload, kept so payload size can be measured instead of assumed. */
data class PayloadSize(val events: Int, val rawBytes: Int, val wireBytes: Int)

/**
 * Plain `HttpURLConnection` (no extra dependency). No redirects are followed, responses are size
 * capped, the credential only ever goes into the Authorization header of the enrolled server, and
 * nothing here logs request or response bodies.
 */
class ApiClient(
    private val serverBase: String,
    private val deviceId: String? = null,
    private val credential: String? = null,
    private val onPayload: (PayloadSize) -> Unit = {},
) : Transport, CommTransport {

    override fun send(batch: Batch): SendResult {
        val id = requireNotNull(deviceId) { "device id required" }
        val token = requireNotNull(credential) { "credential required" }
        val raw = BatchCodec.encode(id, batch).toByteArray(Charsets.UTF_8)
        val gzip = raw.size > GZIP_THRESHOLD
        val wire = if (gzip) gzip(raw) else raw
        onPayload(PayloadSize(batch.events.size, raw.size, wire.size))
        return try {
            val response = post("/telemetry/batches", wire, gzip, token)
            when {
                response.status == 202 -> parseAck(response.body) ?: SendResult.ServerError(202)
                response.status == 401 -> SendResult.Unauthorized
                response.status == 429 -> SendResult.RateLimited(response.retryAfter)
                // A body that is too large or a request timeout is fixed by sending less.
                response.status == 408 || response.status == 413 || response.status >= 500 ->
                    SendResult.ServerError(response.status)
                else -> SendResult.Refused(response.status, errorCode(response.body))
            }
        } catch (e: IOException) {
            SendResult.Network(e.javaClass.simpleName)
        }
    }

    fun pair(code: String, deviceName: String, model: String, androidVersion: String, appVersion: String): PairResult {
        val body = JSONObject()
            .put("pairing_code", code)
            .put("device_name", deviceName)
            .put("device_model", model)
            .put("android_version", androidVersion)
            .put("app_version", appVersion)
            .toString().toByteArray(Charsets.UTF_8)
        return try {
            val response = post("/devices/pair", body, gzip = false, bearer = null)
            when (response.status) {
                201 -> parsePair(response.body)
                401, 409 -> PairResult.InvalidCode
                429 -> PairResult.RateLimited
                else -> PairResult.Failed("The server answered HTTP ${response.status}.")
            }
        } catch (e: IOException) {
            PairResult.Failed("Could not reach the server (${e.javaClass.simpleName}).")
        }
    }

    // ---- journeys (ADR-026): the caller maps the status ----

    class StatusReply(val status: Int, val retryAfter: Long?)

    fun putJourney(id: String, json: String): StatusReply =
        reply(call("PUT", "/journeys/$id", json.toByteArray(Charsets.UTF_8), gzip = false, bearer = requireNotNull(credential)))

    fun postJourneyEvents(id: String, json: String): StatusReply =
        reply(post("/journeys/$id/events", json.toByteArray(Charsets.UTF_8), gzip = false, bearer = requireNotNull(credential)))

    fun deleteJourney(id: String): StatusReply =
        reply(call("DELETE", "/journeys/$id", null, gzip = false, bearer = requireNotNull(credential)))

    // ---- live flight/train lookup (ADR-027): read-only, the server holds the provider key ----

    class LiveReply(val status: Int, val body: String)

    fun liveFlight(flight: String, day: String): LiveReply =
        live("/journeys/live/flight?flight=${URLEncoder.encode(flight, "UTF-8")}&day=${URLEncoder.encode(day, "UTF-8")}")

    fun liveTrain(number: String): LiveReply = live("/journeys/live/train?number=${URLEncoder.encode(number, "UTF-8")}")

    private fun live(path: String): LiveReply =
        call("GET", path, null, gzip = false, bearer = requireNotNull(credential)).let { LiveReply(it.status, it.body) }

    private fun reply(response: Response) = StatusReply(response.status, response.retryAfter)

    // ---- push registration (ADR-023) ----

    fun putPushToken(token: String): PushCall {
        // The server accepts only this alphabet; refusing here also keeps the JSON trivially safe.
        if (!PUSH_TOKEN.matches(token)) return PushCall.Refused(0)
        val body = """{"token":"$token","platform":"fcm"}""".toByteArray(Charsets.UTF_8)
        return pushCall("PUT", body)
    }

    fun deletePushToken(): PushCall = pushCall("DELETE", null)

    private fun pushCall(method: String, body: ByteArray?): PushCall = try {
        val r = call(method, "/push/device-token", body, gzip = false, bearer = requireNotNull(credential))
        when {
            r.status == 204 || r.status == 200 -> PushCall.Ok
            r.status == 401 -> PushCall.Unauthorized
            r.status == 408 || r.status == 429 || r.status >= 500 -> PushCall.Retry
            else -> PushCall.Refused(r.status)
        }
    } catch (_: IOException) {
        PushCall.Retry
    }

    // ---- SOS and messages (Phase 6) ----

    override fun deliver(item: CommItem): CommResult {
        val id = requireNotNull(deviceId) { "device id required" }
        val token = requireNotNull(credential) { "credential required" }
        val (path, json) = when (item.kind) {
            CommKind.SOS -> "/sos/incidents" to CommCodec.sos(id, item)
            CommKind.MESSAGE -> "/messages" to CommCodec.message(item)
        }
        return try {
            toResult(post(path, json.toByteArray(Charsets.UTF_8), gzip = false, bearer = token))
        } catch (e: IOException) {
            CommResult.Network(e.javaClass.simpleName)
        }
    }

    override fun acknowledgeMessage(id: String): CommResult = try {
        toResult(post("/messages/$id/ack", ByteArray(0), gzip = false, bearer = requireNotNull(credential)))
    } catch (e: IOException) {
        CommResult.Network(e.javaClass.simpleName)
    }

    override fun fetchSos(): Fetch<List<RemoteSos>> = fetch("/sos/incidents?limit=50") { json ->
        val array = json.getJSONArray("incidents")
        List(array.length()) { i ->
            val o = array.getJSONObject(i)
            RemoteSos(o.getString("incident_id"), o.getString("status"), o.optStringOrNull("acknowledged_at"), o.optStringOrNull("resolved_at"))
        }
    }

    override fun fetchParentMessages(): Fetch<List<RemoteMessage>> = fetch("/messages?sender=parent&limit=50") { json ->
        val array = json.getJSONArray("messages")
        buildList {
            for (i in 0 until array.length()) {
                val o = array.getJSONObject(i)
                if (o.getString("sender") != "parent") continue
                add(RemoteMessage(o.getString("message_id"), o.getString("body"), o.getString("sent_at"), o.getString("received_at"), o.getString("status")))
            }
        }
    }

    override fun fetchOwnMessages(): Fetch<List<RemoteMessageStatus>> = fetch("/messages?sender=device&limit=50") { json ->
        val array = json.getJSONArray("messages")
        List(array.length()) { i ->
            val o = array.getJSONObject(i)
            RemoteMessageStatus(o.getString("message_id"), o.getString("status"), o.optStringOrNull("acknowledged_at"))
        }
    }

    private fun <T> fetch(path: String, parse: (JSONObject) -> T): Fetch<T> = try {
        val response = call("GET", path, null, gzip = false, bearer = requireNotNull(credential))
        when {
            response.status == 401 -> Fetch.Unauthorized
            response.status == 200 -> try {
                Fetch.Ok(parse(JSONObject(response.body)))
            } catch (_: JSONException) {
                Fetch.Unavailable
            }
            else -> Fetch.Unavailable
        }
    } catch (_: IOException) {
        Fetch.Unavailable
    }

    private fun toResult(response: Response): CommResult = when {
        response.status == 200 || response.status == 201 -> try {
            val json = JSONObject(response.body)
            CommResult.Delivered(json.getString("status"), json.optStringOrNull("acknowledged_at"), json.optStringOrNull("resolved_at"))
        } catch (_: JSONException) {
            CommResult.ServerError(response.status) // stored or not, we cannot tell: it is re-sent by id
        }
        response.status == 401 -> CommResult.Unauthorized
        response.status == 429 -> CommResult.RateLimited(response.retryAfter)
        response.status == 408 || response.status == 413 || response.status >= 500 -> CommResult.ServerError(response.status)
        else -> CommResult.Refused(response.status, errorCode(response.body))
    }

    private fun JSONObject.optStringOrNull(name: String): String? = if (isNull(name)) null else optString(name).takeIf { it.isNotEmpty() }

    private class Response(val status: Int, val body: String, val retryAfter: Long?)

    private fun post(path: String, body: ByteArray, gzip: Boolean, bearer: String?): Response =
        call("POST", path, body, gzip, bearer)

    private fun call(method: String, path: String, body: ByteArray?, gzip: Boolean, bearer: String?): Response {
        val connection = URL(ServerUrl.apiBase(serverBase) + path).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/json")
            if (bearer != null) connection.setRequestProperty("Authorization", "Bearer $bearer")
            if (body != null) {
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(body.size)
                connection.setRequestProperty("Content-Type", "application/json")
                if (gzip) connection.setRequestProperty("Content-Encoding", "gzip")
                connection.outputStream.use { it.write(body) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..399) connection.inputStream else connection.errorStream
            return Response(status, stream?.use { readCapped(it) }.orEmpty(), connection.getHeaderField("Retry-After")?.toLongOrNull())
        } finally {
            connection.disconnect()
        }
    }

    private fun readCapped(stream: java.io.InputStream): String {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            val n = stream.read(buffer)
            if (n < 0) break
            out.write(buffer, 0, n)
            if (out.size() > MAX_RESPONSE_BYTES) throw IOException("response too large")
        }
        return out.toString(Charsets.UTF_8.name())
    }

    private fun gzip(raw: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(raw) }
        return out.toByteArray()
    }

    private fun errorCode(body: String): String? = try {
        JSONObject(body).optJSONObject("error")?.optString("code")?.takeIf { it.isNotEmpty() }
    } catch (_: JSONException) {
        null
    }

    private fun parsePair(body: String): PairResult = try {
        val json = JSONObject(body)
        PairResult.Success(
            PairedDevice(json.getString("device_id"), json.getString("family_id"), json.getString("device_credential")),
        )
    } catch (_: JSONException) {
        PairResult.Failed("The server's reply was not understood.")
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 10_000
        private const val READ_TIMEOUT_MS = 20_000
        private const val MAX_RESPONSE_BYTES = 256 * 1024
        private const val GZIP_THRESHOLD = 1024
        private val PUSH_TOKEN = Regex("^[A-Za-z0-9_:.-]{20,4096}$")

        /** Only ids the server explicitly lists count; anything malformed means "not acknowledged". */
        fun parseAck(body: String): SendResult.Ack? = try {
            val json = JSONObject(body)
            val rejected = HashMap<String, String>()
            json.getJSONArray("rejected_events").let { array ->
                for (i in 0 until array.length()) {
                    val item = array.getJSONObject(i)
                    rejected[item.getString("event_id")] = item.optString("reason", item.optString("error_code", "rejected"))
                }
            }
            SendResult.Ack(ids(json.getJSONArray("accepted_event_ids")), ids(json.getJSONArray("duplicate_event_ids")), rejected)
        } catch (_: JSONException) {
            null
        }

        private fun ids(array: org.json.JSONArray): Set<String> =
            buildSet { for (i in 0 until array.length()) add(array.getString(i)) }
    }
}
