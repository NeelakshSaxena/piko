package app.piko.android.journeys

import app.piko.android.journeys.data.LiveCodec
import app.piko.android.journeys.domain.LiveLookup
import app.piko.android.journeys.domain.LiveReading
import app.piko.android.journeys.domain.LiveRequest
import app.piko.android.journeys.domain.LiveRules
import app.piko.android.journeys.domain.LiveState
import app.piko.android.journeys.domain.TransportMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

/** Live data is optional and advisory (ADR-027). These checks use answers shaped like the server's; no network is involved. */
class LiveStatusTest {
    private val ist = ZoneId.of("Asia/Kolkata")
    private fun at(h: Int, m: Int = 0) = ZonedDateTime.of(2026, 11, 1, h, m, 0, 0, ist)
    private val flight = leg("f", TransportMode.FLIGHT, "Delhi", "Mumbai", at(7, 45), at(11, 30), "ai 101")
    private val train = leg("t", TransportMode.TRAIN, "Indore", "Katra", at(7, 45), at(11, 30), "12919")
    private val duringFlight = Instant.parse("2026-11-01T03:00:00Z") // 08:30 IST, in the air
    private val checked = Instant.parse("2026-11-01T03:00:00Z")

    private fun reading(
        dep: Int? = null,
        arr: Int? = null,
        running: Int? = null,
        status: String? = "active",
        updated: Instant? = null,
        notices: List<String> = emptyList(),
        at: Instant = checked,
    ) = LiveReading("aviationstack", at, status, dep, arr, running, null, null, null, null, updated, notices)

    // ---- what is asked, and when ----
    @Test fun aFlightNumberIsNormalizedAndCarriesTheScheduledLocalDate() {
        assertEquals(LiveRequest.Flight("AI101", LocalDate.of(2026, 11, 1)), LiveRules.request(flight))
    }

    @Test fun aTrainNeedsExactlyFiveDigits() {
        assertEquals(LiveRequest.Train("12919"), LiveRules.request(train))
        assertNull(LiveRules.request(train.copy(serviceNumber = "1291")))
        assertNull(LiveRules.request(train.copy(serviceNumber = "12919A")))
    }

    @Test fun nothingIsAskedForOtherModesBadNumbersOrMissingSchedules() {
        assertNull(LiveRules.request(flight.copy(mode = TransportMode.BUS)))
        assertNull(LiveRules.request(flight.copy(serviceNumber = null)))
        assertNull(LiveRules.request(flight.copy(serviceNumber = "AI-101; drop")))
        assertNull(LiveRules.request(flight.copy(departure = null)))
        assertNull(LiveRules.request(flight.copy(arrival = null)))
    }

    @Test fun theWindowOpensSixHoursBeforeDepartureAndClosesThreeHoursAfterArrival() {
        val dep = flight.departure!!.toInstant()
        val arr = flight.arrival!!.toInstant()
        assertFalse(LiveRules.inWindow(flight, dep.minusSeconds(6 * 3600 + 1)))
        assertTrue(LiveRules.inWindow(flight, dep.minusSeconds(6 * 3600)))
        assertTrue(LiveRules.inWindow(flight, arr.plusSeconds(3 * 3600)))
        assertFalse(LiveRules.inWindow(flight, arr.plusSeconds(3 * 3600 + 1)))
    }

    // ---- what is believed ----
    @Test fun aFlightReadingSuggestsTheScheduleMovedByTheReportedDelays() {
        val s = LiveRules.suggest(flight, reading(dep = 10, arr = 25), duringFlight)
        assertEquals(at(7, 55), s?.departure)
        assertEquals(at(11, 55), s?.arrival)
    }

    @Test fun aTrainDelayMovesOnlyTheArrival() {
        val s = LiveRules.suggest(train, reading(running = 12), duringFlight)
        assertNull(s?.departure)
        assertEquals(at(11, 42), s?.arrival)
    }

    @Test fun aDelayThatWasNotGivenIsNotSuggestedAsZero() {
        assertNull(LiveRules.suggest(flight, reading(), duringFlight))
        assertNull(LiveRules.suggest(flight, reading(status = null), duringFlight))
    }

    @Test fun anEarlyReportIsOfferedAsReportedNotClampedOrInvented() {
        assertEquals(at(11, 20), LiveRules.suggest(train, reading(running = -10), duringFlight)?.arrival)
    }

    @Test fun cancelledNotLiveAndStaleReadingsAreShownButNeverOffered() {
        assertNull(LiveRules.suggest(flight, reading(arr = 25, status = "cancelled"), duringFlight))
        assertNull(LiveRules.suggest(train, reading(running = 5, notices = listOf("CANCELLED")), duringFlight))
        assertNull(LiveRules.suggest(train, reading(running = 5, notices = listOf("NOT_LIVE")), duringFlight))
        val old = duringFlight.minusSeconds(3 * 3600 + 60)
        assertNull(LiveRules.suggest(train, reading(running = 5, updated = old), duringFlight)) // the provider's data is old
        assertNull(LiveRules.suggest(train, reading(running = 5, at = old), duringFlight)) // we asked long ago
        assertNotNull(LiveRules.suggest(train, reading(running = 5, updated = duringFlight.minusSeconds(3 * 3600)), duringFlight))
    }

    @Test fun suggestingNeverChangesTheSchedule() {
        val before = flight.copy()
        LiveRules.suggest(flight, reading(dep = 90, arr = 90), duringFlight)
        assertEquals(before, flight)
    }

    @Test fun theCardSaysWhoSaidItAndLeavesOutWhatWasNotSaid() {
        val text = LiveRules.describe(reading(arr = 25), ist).joinToString("\n")
        assertTrue(text.contains("Aviationstack"))
        assertTrue(text.contains("Arrival delay according to Aviationstack: 25 min late"))
        assertFalse(text.contains("Departure delay")) // not reported: not shown, not "0"
        assertTrue(text.contains("Not saved"))
        assertTrue(text.contains("Checked at 08:30"))
    }

    @Test fun everyFailureHasPlainWordingThatKeepsTheUsersTimes() {
        LiveState.values().filter { it != LiveState.OK }.forEach {
            val words = LiveRules.explain(it)
            assertTrue("$it", words.isNotBlank())
        }
        assertTrue(LiveRules.explain(LiveState.OFFLINE).contains("unchanged"))
        assertTrue(LiveRules.explain(LiveState.DISABLED).contains("only the times you enter"))
    }

    // ---- the server's answer ----
    private val ok = """
        {"state":"ok","provider":"railradar","checked_at":"2026-11-01T08:30:00.123456+05:30","status":"running",
         "departure_delay_minutes":null,"arrival_delay_minutes":null,"running_delay_minutes":12,
         "departure_gate":null,"departure_terminal":null,"arrival_gate":null,"arrival_terminal":null,
         "provider_updated_at":"2026-11-01T08:14:00+05:30","notices":["DIVERTED"]}
    """.trimIndent()

    @Test fun anOkAnswerBecomesAReadingAndAMissingNumberStaysMissing() {
        val got = LiveCodec.parse(200, ok) as LiveLookup.Got
        val r = got.reading
        assertEquals("railradar", r.provider)
        assertEquals(12, r.runningDelayMinutes)
        assertNull(r.departureDelayMinutes)
        assertNull(r.arrivalDelayMinutes)
        assertEquals(Instant.parse("2026-11-01T03:00:00.123456Z"), r.checkedAt)
        assertEquals(Instant.parse("2026-11-01T02:44:00Z"), r.providerUpdatedAt)
        assertEquals(listOf("DIVERTED"), r.notices)
    }

    @Test fun everyNonOkStateMapsToAFailureWithNoReading() {
        mapOf(
            "disabled" to LiveState.DISABLED, "not_configured" to LiveState.NOT_CONFIGURED, "not_found" to LiveState.NOT_FOUND,
            "auth_failed" to LiveState.AUTH_FAILED, "rate_limited" to LiveState.RATE_LIMITED, "unavailable" to LiveState.UNAVAILABLE,
            "unusable" to LiveState.UNUSABLE, "something_new" to LiveState.UNUSABLE,
        ).forEach { (word, expected) ->
            val body = """{"state":"$word","provider":null,"checked_at":"2026-11-01T08:30:00+05:30"}"""
            assertEquals(word, LiveLookup.Failed(expected), LiveCodec.parse(200, body))
        }
    }

    @Test fun httpFailuresAndGarbageNeverProduceAReading() {
        assertEquals(LiveLookup.Failed(LiveState.NOT_PAIRED), LiveCodec.parse(401, "{}"))
        assertEquals(LiveLookup.Failed(LiveState.RATE_LIMITED), LiveCodec.parse(429, "{}"))
        assertEquals(LiveLookup.Failed(LiveState.UNAVAILABLE), LiveCodec.parse(503, ""))
        assertEquals(LiveLookup.Failed(LiveState.REFUSED), LiveCodec.parse(400, "{}"))
        assertEquals(LiveLookup.Failed(LiveState.UNUSABLE), LiveCodec.parse(200, "not json"))
        assertEquals(LiveLookup.Failed(LiveState.UNUSABLE), LiveCodec.parse(200, """{"state":"ok"}"""))
        assertEquals(LiveLookup.Failed(LiveState.UNUSABLE), LiveCodec.parse(200, ok.replace("2026-11-01T08:30:00.123456+05:30", "yesterday")))
        assertEquals(LiveLookup.Failed(LiveState.UNUSABLE), LiveCodec.parse(200, ok.replace("\"running_delay_minutes\":12", "\"running_delay_minutes\":\"late\"")))
    }
}
