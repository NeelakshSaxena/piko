package app.piko.android.journeys

import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.ArrivalInference
import app.piko.android.journeys.domain.ConnectionPlanner
import app.piko.android.journeys.domain.Estimate
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.LegInput
import app.piko.android.journeys.domain.Risk
import app.piko.android.journeys.domain.TimeBasis
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TransportMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime

class ConnectionPlannerTest {
    private val ist = ZoneId.of("Asia/Kolkata")
    private fun at(h: Int, m: Int = 0) = ZonedDateTime.of(2026, 11, 1, h, m, 0, 0, ist)
    private val earlier = Instant.parse("2026-11-01T00:00:00Z") // 05:30 IST

    private fun trip(nextMode: TransportMode, nextDeparts: ZonedDateTime?, arrives: ZonedDateTime? = at(11, 30), estimate: Estimate? = null) =
        journey(
            "j",
            listOf(
                leg("a", TransportMode.TRAIN, "Katpadi", "Bengaluru", at(7, 45), arrives).copy(estimate = estimate),
                leg("b", nextMode, "Bengaluru", "Airport", nextDeparts, at(16, 30)),
            ),
            status = JourneyStatus.PLANNED,
        )

    private fun assess(j: app.piko.android.journeys.domain.Journey, now: Instant = earlier, arrived: List<String> = emptyList()): app.piko.android.journeys.domain.Connection {
        val store = InMemoryJourneyStore().also { it.save(j) }
        val controller = TrackingController(store, store)
        if (arrived.isNotEmpty()) {
            controller.start("j", earlier, false)
            arrived.forEach { controller.confirmArrival("j", it, earlier, ArrivalBasis.MANUAL) }
        }
        return ConnectionPlanner.assess(j, controller.progress(j), now).single()
    }

    @Test fun plentyOfTimeIsComfortableAndExplainsItsNumbers() {
        val c = assess(trip(TransportMode.FLIGHT, at(15)))
        assertEquals(Risk.COMFORTABLE, c.risk)
        assertEquals(Duration.ofMinutes(210), c.available)
        assertEquals(Duration.ofMinutes(90), c.required) // 75 min flight transfer + 15 min margin
        assertEquals(Duration.ofMinutes(120), c.slack)
        assertEquals(TimeBasis.SCHEDULE, c.basis)
        assertTrue(c.explanation.contains("the schedule you entered"))
        assertTrue(c.explanation.contains("3 h 30 min"))
    }

    @Test fun thresholdsAreExact() {
        // 11:30 arrival, a flight needs 90 min: 12:59 is short by a minute (at risk), 13:00 has no slack (tight),
        // 13:29 has 29 min (still tight), 13:30 has the 30 min that count as comfortable.
        assertEquals(Risk.AT_RISK, assess(trip(TransportMode.FLIGHT, at(12, 59))).risk)
        assertEquals(Risk.TIGHT, assess(trip(TransportMode.FLIGHT, at(13, 0))).risk)
        assertEquals(Risk.TIGHT, assess(trip(TransportMode.FLIGHT, at(13, 29))).risk)
        assertEquals(Risk.COMFORTABLE, assess(trip(TransportMode.FLIGHT, at(13, 30))).risk)
    }

    @Test fun aDelayUpdateChangesTheVerdictWithoutTouchingTheSchedule() {
        val delayed = Estimate(null, at(13, 20), Instant.parse("2026-11-01T04:00:00Z")) // arrival now expected 13:20
        assertEquals(Risk.COMFORTABLE, assess(trip(TransportMode.FLIGHT, at(14, 30))).risk) // on the schedule alone: 180 min, 90 needed
        val j = trip(TransportMode.FLIGHT, at(14, 30), estimate = delayed)
        val c = assess(j, now = Instant.parse("2026-11-01T04:30:00Z"))
        assertEquals(Risk.AT_RISK, c.risk) // after the delay: 70 min available, 90 needed
        assertEquals(at(11, 30), j.legs[0].arrival) // the schedule is still what was entered
        assertEquals(TimeBasis.YOUR_UPDATE, c.basis)
    }

    @Test fun anOldUpdateForALegNotYetReachedIsNotTrusted() {
        val old = Estimate(null, at(13, 20), Instant.parse("2026-11-01T00:00:00Z"))
        val c = assess(trip(TransportMode.FLIGHT, at(15), estimate = old), now = Instant.parse("2026-11-01T04:30:00Z")) // 4.5 h later, arrival still ahead
        assertEquals(Risk.UNKNOWN, c.risk)
        assertTrue(c.explanation.contains("not trusted"))
    }

    @Test fun aMissingTimeIsUnknownNotAGuess() {
        assertEquals(Risk.UNKNOWN, assess(trip(TransportMode.FLIGHT, null)).risk)
        assertEquals(Risk.UNKNOWN, assess(trip(TransportMode.FLIGHT, at(15), arrives = null)).risk)
    }

    @Test fun aWalkingLegNeedsOnlyTheMargin() {
        assertEquals(Duration.ofMinutes(15), assess(trip(TransportMode.WALKING, at(12, 0))).required)
    }

    @Test fun legsAlreadyReachedHaveNoConnectionToAssess() {
        val j = trip(TransportMode.FLIGHT, at(15))
        val store = InMemoryJourneyStore().also { it.save(j) }
        val controller = TrackingController(store, store)
        controller.start("j", earlier, false)
        controller.confirmArrival("j", "a", earlier, ArrivalBasis.MANUAL)
        assertTrue(ConnectionPlanner.assess(j, controller.progress(j), earlier).isEmpty())
    }
}

class EstimateAndInferenceTest {
    private val ist = ZoneId.of("Asia/Kolkata")
    private fun at(h: Int, m: Int = 0) = ZonedDateTime.of(2026, 11, 1, h, m, 0, 0, ist)

    private fun input(dep: String = "2026-11-01 07:45", arr: String = "2026-11-01 11:30") =
        LegInput(TransportMode.TRAIN, "", "A", "B", dep, "Asia/Kolkata", arr, "Asia/Kolkata")

    @Test fun anUpdateSurvivesEditingTheNameButNotChangingTheSchedule() {
        val updated = leg("a", departure = at(7, 45), arrival = at(11, 30)).copy(estimate = Estimate(null, at(12, 15), Instant.EPOCH))
        val sameSchedule = (input().parse("a", updated) as LegInput.Parsed.Ok).leg
        assertEquals(updated.estimate, sameSchedule.estimate)
        val newSchedule = (input(arr = "2026-11-01 12:00").parse("a", updated) as LegInput.Parsed.Ok).leg
        assertNull(newSchedule.estimate)
        assertNull((input().parse("a", null) as LegInput.Parsed.Ok).leg.estimate)
    }

    @Test fun possibleArrivalIsAClockGuessThatNeverCountsAsConfirmed() {
        val flight = leg("f", TransportMode.FLIGHT, departure = at(14), arrival = at(16, 30))
        assertFalse(ArrivalInference.possiblyArrived(flight, false, at(16, 29).toInstant()))
        assertTrue(ArrivalInference.possiblyArrived(flight, false, at(16, 30).toInstant()))
        assertFalse(ArrivalInference.possiblyArrived(flight, true, at(18).toInstant())) // already confirmed: nothing to infer
        // A delay update moves the guess later.
        val delayed = flight.copy(estimate = Estimate(null, at(17, 45), Instant.EPOCH))
        assertFalse(ArrivalInference.possiblyArrived(delayed, false, at(17, 0).toInstant()))
        assertTrue(ArrivalInference.possiblyArrived(delayed, false, at(17, 45).toInstant()))
        assertFalse(ArrivalInference.possiblyArrived(leg("n", arrival = null), false, at(23).toInstant()))
    }
}

class ExpectedTimeFormTest {
    private val ist = ZoneId.of("Asia/Kolkata")
    private fun at(h: Int, m: Int = 0) = ZonedDateTime.of(2026, 11, 1, h, m, 0, 0, ist)
    private val leg = leg("a", TransportMode.FLIGHT, departure = at(14), arrival = at(16, 30))
    private val now = Instant.parse("2026-11-01T05:00:00Z")

    private fun parse(dep: String = "", arr: String = "") = LegInput.parseEstimate(leg, dep, arr, now)

    @Test fun anUpdateIsReadInTheLegsOwnZoneAndStampedWithWhenItWasEntered() {
        val ok = parse(arr = "2026-11-01 17:45") as LegInput.EstimateParsed.Ok
        assertEquals(at(17, 45), ok.estimate!!.arrival)
        assertNull(ok.estimate!!.departure)
        assertEquals(now, ok.estimate!!.enteredAt)
    }

    @Test fun bothBlankClearsTheUpdate() {
        assertNull((parse() as LegInput.EstimateParsed.Ok).estimate)
    }

    @Test fun badInputIsRefusedInWords() {
        assertTrue((parse(arr = "soon") as LegInput.EstimateParsed.Error).message.contains("arrival"))
        assertTrue((parse(dep = "2026-02-30 10:00") as LegInput.EstimateParsed.Error).message.contains("departure"))
        // Arriving before the (scheduled) departure makes no sense.
        assertEquals("The expected arrival is not after the departure.", (parse(arr = "2026-11-01 13:00") as LegInput.EstimateParsed.Error).message)
        // A leg with no scheduled arrival has nothing to update.
        val noTimes = LegInput.parseEstimate(leg("n", departure = null, arrival = null), "", "2026-11-01 10:00", now)
        assertTrue((noTimes as LegInput.EstimateParsed.Error).message.contains("no scheduled arrival"))
    }
}
