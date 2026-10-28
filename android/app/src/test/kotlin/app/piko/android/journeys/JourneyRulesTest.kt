package app.piko.android.journeys

import app.piko.android.journeys.domain.JourneyRules
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.LegInput
import app.piko.android.journeys.domain.TransportMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Duration
import java.time.ZoneId
import java.time.ZonedDateTime

class JourneyRulesTest {
    private val ist = ZoneId.of("Asia/Kolkata")
    private fun at(h: Int, m: Int = 0, day: Int = 1) = ZonedDateTime.of(2026, 11, day, h, m, 0, 0, ist)

    @Test fun aDraftOnlyNeedsATitle() {
        assertTrue(JourneyRules.problemsForSaving(journey("j", emptyList())).isEmpty())
        assertEquals(listOf("Give the journey a title."), JourneyRules.problemsForSaving(journey("j", emptyList()).copy(title = "  ")))
    }

    @Test fun planningNeedsLegsAndTimes() {
        assertEquals(listOf("Add at least one leg."), JourneyRules.problemsForPlanning(journey("j", emptyList())))
        val missing = JourneyRules.problemsForPlanning(journey("j", listOf(leg("a", departure = null, arrival = null))))
        assertEquals(listOf("Leg 1 needs a departure time.", "Leg 1 needs an arrival time."), missing)
    }

    @Test fun planningRejectsArrivingBeforeDepartingAndOverlappingLegs() {
        val backwards = journey("j", listOf(leg("a", departure = at(10), arrival = at(9))))
        assertEquals(listOf("Leg 1 arrives before it departs."), JourneyRules.problemsForPlanning(backwards))

        val overlap = journey("j", listOf(leg("a", departure = at(7), arrival = at(11)), leg("b", departure = at(10), arrival = at(12))))
        assertEquals(listOf("Leg 2 departs before leg 1 arrives."), JourneyRules.problemsForPlanning(overlap))
    }

    @Test fun legsAreComparedByInstantAcrossTimeZones() {
        // 23:00 IST departure, arriving 05:30 in London the next day (= 11:00 IST): later than departure, so valid.
        val flight = leg(
            "f", TransportMode.FLIGHT,
            departure = at(23),
            arrival = ZonedDateTime.of(2026, 11, 2, 5, 30, 0, 0, ZoneId.of("Europe/London")),
        )
        assertTrue(JourneyRules.problemsForPlanning(journey("j", listOf(flight))).isEmpty())
    }

    @Test fun aCompleteTrainTaxiFlightTaxiTripCanBePlanned() {
        val trip = journey(
            "j",
            listOf(
                leg("1", TransportMode.TRAIN, departure = at(7, 45), arrival = at(11, 30)),
                leg("2", TransportMode.TAXI, departure = at(11, 50), arrival = at(12, 40)),
                leg("3", TransportMode.FLIGHT, departure = at(14), arrival = at(16, 30)),
                leg("4", TransportMode.TAXI, departure = at(16, 50), arrival = at(17, 40)),
            ),
            status = JourneyStatus.PLANNED,
        )
        assertTrue(JourneyRules.problemsForPlanning(trip).isEmpty())
        assertEquals(Duration.ofMinutes(20), JourneyRules.gapBetween(trip.legs[0], trip.legs[1]))
    }

    @Test fun gapIsUnknownWhenATimeIsMissing() {
        assertNull(JourneyRules.gapBetween(leg("a", arrival = null), leg("b")))
    }

    @Test fun moveReordersAndIgnoresBadIndexes() {
        val legs = listOf(leg("a"), leg("b"), leg("c"))
        assertEquals(listOf("b", "c", "a"), JourneyRules.move(legs, 0, 2).map { it.id })
        assertEquals(listOf("c", "a", "b"), JourneyRules.move(legs, 2, 0).map { it.id })
        assertEquals(legs, JourneyRules.move(legs, 0, 3))
        assertEquals(legs, JourneyRules.move(legs, -1, 1))
        assertEquals(legs, JourneyRules.move(legs, 1, 1))
    }

    @Test fun tooManyLegsCannotBeSaved() {
        val many = journey("j", List(JourneyRules.MAX_LEGS + 1) { leg("l$it") })
        assertEquals(1, JourneyRules.problemsForSaving(many).size)
    }
}

class LegInputTest {
    private fun input(
        mode: TransportMode = TransportMode.FLIGHT,
        number: String = " 6E 123 ",
        from: String = " Bengaluru ",
        to: String = "Lucknow",
        dep: String = "2026-11-01 07:45",
        depZone: String = "Asia/Kolkata",
        arr: String = "2026-11-01 10:05",
        arrZone: String = "Asia/Kolkata",
    ) = LegInput(mode, number, from, to, dep, depZone, arr, arrZone)

    private fun ok(i: LegInput) = (i.parse("id") as LegInput.Parsed.Ok).leg
    private fun error(i: LegInput) = (i.parse("id") as LegInput.Parsed.Error).message

    @Test fun validInputIsTrimmedAndKeepsItsZones() {
        val leg = ok(input(arrZone = "Europe/London"))
        assertEquals("Bengaluru", leg.origin)
        assertEquals("6E 123", leg.serviceNumber)
        assertEquals(ZoneId.of("Asia/Kolkata"), leg.departure!!.zone)
        assertEquals(ZoneId.of("Europe/London"), leg.arrival!!.zone)
        assertEquals(7, leg.departure!!.hour)
    }

    @Test fun timesMayBeBlankInADraft() {
        val leg = ok(input(dep = "", arr = "  "))
        assertNull(leg.departure)
        assertNull(leg.arrival)
    }

    @Test fun aNumberIsDroppedForModesThatHaveNone() {
        assertNull(ok(input(mode = TransportMode.TAXI)).serviceNumber)
    }

    @Test fun missingPlacesAreRejected() {
        assertEquals("Enter where this leg starts.", error(input(from = " ")))
        assertEquals("Enter where this leg ends.", error(input(to = "")))
    }

    @Test fun nonsenseDatesAndZonesAreRejectedWithAReadableMessage() {
        assertTrue(error(input(dep = "tomorrow")).contains("departure"))
        assertTrue(error(input(arr = "2026-02-30 10:00")).contains("arrival")) // not a real date: strict parsing
        assertTrue(error(input(depZone = "Mars/Olympus")).contains("departure time zone"))
        assertTrue(error(input(arrZone = "")).contains("arrival time zone"))
    }

    @Test fun aZoneIsNotRequiredWhenTheTimeIsBlank() {
        assertNull(ok(input(arr = "", arrZone = "nonsense")).arrival)
    }

    @Test fun editingARoundTripsWhatWasEntered() {
        val leg = ok(input())
        assertEquals(leg, ok(LegInput.of(leg, "UTC")))
    }
}
