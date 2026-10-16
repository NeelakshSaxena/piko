package app.piko.android.core

import app.piko.android.net.ApiClient
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class EventDataTest {
    @Test fun locationRangesAreEnforcedBeforeAnythingIsQueued() {
        assertThrows(InvalidEvent::class.java) { EventData.Location(91.0, 0.0, null) }
        assertThrows(InvalidEvent::class.java) { EventData.Location(0.0, -180.5, null) }
        assertThrows(InvalidEvent::class.java) { EventData.Location(0.0, 0.0, 10_000.5) }
        assertThrows(InvalidEvent::class.java) { EventData.Location(0.0, 0.0, -1.0) }
        assertThrows(InvalidEvent::class.java) { EventData.Location(Double.NaN, 0.0, null) }
        assertThrows(InvalidEvent::class.java) { EventData.Location(0.0, Double.POSITIVE_INFINITY, null) }
        EventData.Location(90.0, -180.0, 0.0)
    }

    @Test fun batteryAndNetworkValidation() {
        assertThrows(InvalidEvent::class.java) { EventData.Battery(101, null) }
        assertThrows(InvalidEvent::class.java) { EventData.Battery(-1, null) }
        assertThrows(InvalidEvent::class.java) { EventData.Connectivity("Wi-Fi") }
        assertThrows(InvalidEvent::class.java) { EventData.Connectivity("a".repeat(33)) }
        EventData.Connectivity("wifi")
    }

    @Test fun jsonIsValidLocaleIndependentAndMatchesTheServerContract() {
        val json = JSONObject(EventData.Location(40.7128, -74.006, 15.0).toJson())
        assertEquals(40.7128, json.getDouble("latitude"), 1e-9)
        assertEquals(-74.006, json.getDouble("longitude"), 1e-9)
        assertEquals(15.0, json.getDouble("accuracy_meters"), 1e-9)
        assertFalse(JSONObject(EventData.Location(1.0, 2.0, null).toJson()).has("accuracy_meters"))
        val battery = JSONObject(EventData.Battery(85, true).toJson())
        assertEquals(85, battery.getInt("percent"))
        assertTrue(battery.getBoolean("is_charging"))
        assertEquals("wifi", JSONObject(EventData.Connectivity("wifi").toJson()).getString("network_type"))
    }
}

class BatchCodecTest {
    @Test fun requestBodyMatchesTheTelemetryContract() {
        val event = QueuedEvent(
            seq = 42, eventId = "11111111-1111-1111-1111-111111111111", type = EventType.LOCATION,
            occurredAtIso = "2026-10-16T09:59:58.123Z", dataJson = EventData.Location(1.5, 2.5, 3.0).toJson(),
            priority = EventPriority.NORMAL, state = DeliveryState.SUBMITTED, attempts = 0, batchId = "b", rejectReason = null,
        )
        val body = JSONObject(BatchCodec.encode("dev-1", Batch("batch-1", listOf(event))))
        assertEquals("batch-1", body.getString("batch_id"))
        assertEquals(1, body.getInt("schema_version"))
        assertEquals("dev-1", body.getString("device_id"))
        val sent = body.getJSONArray("events").getJSONObject(0)
        assertEquals("location", sent.getString("event_type"))
        assertEquals(42, sent.getInt("sequence_number"))
        assertEquals("2026-10-16T09:59:58.123Z", sent.getString("occurred_at")) // untouched capture time
        assertEquals(1.5, sent.getJSONObject("data").getDouble("latitude"), 1e-9)
    }

    @Test fun identifiersAreEscapedDefensively() {
        val event = QueuedEvent(1, "a\"b\\c", EventType.BATTERY, "t", EventData.Battery(1, null).toJson(),
            EventPriority.NORMAL, DeliveryState.SUBMITTED, 0, "b", null)
        assertEquals("a\"b\\c", JSONObject(BatchCodec.encode("d", Batch("x", listOf(event)))).getJSONArray("events").getJSONObject(0).getString("event_id"))
    }
}

class AckParsingTest {
    @Test fun parsesTheServersAcknowledgement() {
        val ack = ApiClient.parseAck(
            """{"batch_id":"b","status":"partial","accepted_event_ids":["a","b"],"duplicate_event_ids":["c"],
                "rejected_events":[{"event_id":"d","error_code":"VALIDATION_ERROR","reason":"latitude out of range"}]}""",
        )!!
        assertEquals(setOf("a", "b"), ack.accepted)
        assertEquals(setOf("c"), ack.duplicates)
        assertEquals(mapOf("d" to "latitude out of range"), ack.rejected)
    }

    @Test fun anythingMalformedIsNotAnAcknowledgement() {
        assertNull(ApiClient.parseAck("not json"))
        assertNull(ApiClient.parseAck("""{"accepted_event_ids":["a"]}"""))
        assertNull(ApiClient.parseAck("""{"accepted_event_ids":[{}],"duplicate_event_ids":[],"rejected_events":[]}"""))
    }
}

class ServerUrlTest {
    @Test fun httpsIsRequiredInReleaseBuilds() {
        assertEquals("https://piko.example.com", ServerUrl.parse("https://piko.example.com/", false))
        assertEquals("https://piko.example.com:8443", ServerUrl.parse(" https://Piko.Example.com:8443 ", false))
        assertNull(ServerUrl.parse("http://piko.example.com", false))
        assertNull(ServerUrl.parse("http://10.0.2.2:8000", false))
    }

    @Test fun debugBuildsMayUseCleartextOnlyToTheHostLoopback() {
        assertEquals("http://10.0.2.2:8000", ServerUrl.parse("http://10.0.2.2:8000", true))
        assertEquals("http://localhost:8000", ServerUrl.parse("http://localhost:8000", true))
        assertNull(ServerUrl.parse("http://piko.example.com", true))
        assertNull(ServerUrl.parse("http://192.168.1.5:8000", true))
    }

    @Test fun credentialsPathsQueriesAndGarbageAreRejected() {
        for (bad in listOf("", "piko.example.com", "ftp://x.com", "https://user:pw@x.com", "https://x.com/api",
            "https://x.com?x=1", "https://x.com#f", "https://", "https://x.com:99999", "javascript:alert(1)")) {
            assertNull(bad, ServerUrl.parse(bad, true))
        }
        assertEquals("https://piko.example.com/api/v1", ServerUrl.apiBase("https://piko.example.com"))
    }
}

class ThrottleAndModeTest {
    @Test fun batteryEventsOnlyOnMeaningfulChange() {
        val t = BatteryThrottle(minDeltaPercent = 2, refreshMs = 900_000)
        assertTrue(t.shouldEmit(80, false, 0))
        assertFalse(t.shouldEmit(79, false, 1_000))
        assertTrue(t.shouldEmit(78, false, 2_000))
        assertTrue(t.shouldEmit(78, true, 3_000)) // plugged in
        assertFalse(t.shouldEmit(78, true, 4_000))
        assertTrue(t.shouldEmit(78, true, 3_000 + 900_000)) // slow refresh
    }

    @Test fun connectivityEventsOnlyWhenTheTypeChanges() {
        val t = ConnectivityThrottle()
        assertTrue(t.shouldEmit("wifi"))
        assertFalse(t.shouldEmit("wifi"))
        assertTrue(t.shouldEmit("none"))
        assertTrue(t.shouldEmit("cellular"))
    }

    @Test fun pollingDoesNotSampleTheGpsEveryMinuteAsARule() {
        val polling = SyncMode.POLLING.plan()
        val realtime = SyncMode.REALTIME.plan()
        assertEquals(60_000, polling.syncIntervalMs) // 60 s upload/check cadence
        assertFalse(polling.highAccuracy)
        assertTrue(polling.minDistanceMeters >= 10f) // movement-gated, balanced power
        assertTrue(realtime.highAccuracy && realtime.flushOnEvent && !polling.flushOnEvent)
        assertTrue(realtime.locationIntervalMs < polling.locationIntervalMs)
        assertTrue(HEARTBEAT_AFTER_MS < 5 * 60_000) // before the server calls a silent device offline
    }

    @Test fun timeTextNeverCallsOldDataLiveOrUnknownDataZero() {
        assertEquals("never", TimeText.ago(10_000, null))
        assertEquals("just now", TimeText.ago(10_000, 9_000))
        assertEquals("30s ago", TimeText.ago(40_000, 10_000))
        assertEquals("3 min ago", TimeText.ago(190_000, 10_000))
        assertTrue(TimeText.isFresh(100_000, 100_000 - TimeText.FRESH_MS))
        assertFalse(TimeText.isFresh(100_000 + 1, 100_000 - TimeText.FRESH_MS))
        assertFalse(TimeText.isFresh(100_000, null))
        assertFalse(TimeText.isFresh(100_000, 200_000)) // a time in the future is not "fresh"
    }
}

class RecorderTest {
    private var now = 10_000_000L
    private val store = InMemoryEventStore()
    private val ids = generateSequence(1) { it + 1 }.map { "id$it" }.iterator()
    private val recorder = Recorder(store, { now }, { ids.next() })

    @Test fun capturedTimeIsKeptNotReplacedByReceiptTime() {
        recorder.record(EventData.Battery(50, null), capturedAtMs = now - 90_000)
        val sent = store.nextBatch(1)!!.events.single()
        assertEquals(Instant.ofEpochMilli(now - 90_000).toString(), sent.occurredAtIso)
    }

    @Test fun aCaptureTimeInTheFutureIsClampedToNow() {
        recorder.record(EventData.Battery(50, null), capturedAtMs = now + 3_600_000)
        assertEquals(Instant.ofEpochMilli(now).toString(), store.nextBatch(1)!!.events.single().occurredAtIso)
    }

    @Test fun heartbeatIsDueOnlyAfterTheQuietPeriodAndRecordingResetsIt() {
        assertFalse(recorder.heartbeatDue())
        now += HEARTBEAT_AFTER_MS
        assertTrue(recorder.heartbeatDue())
        recorder.record(EventData.Connectivity("wifi"))
        assertFalse(recorder.heartbeatDue())
    }
}
