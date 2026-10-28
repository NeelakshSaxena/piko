package app.piko.android.journeys

import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.ArrivalPolicy
import app.piko.android.journeys.domain.ArrivalVerdict
import app.piko.android.journeys.domain.Fix
import app.piko.android.journeys.domain.GeoPoint
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.ReminderPlanner
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingResult
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.domain.TransportMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime

class TrackingControllerTest {
    private val store = InMemoryJourneyStore()
    private var counter = 0
    private val controller = TrackingController(store, store) { "ev${++counter}" }
    private val t0 = Instant.parse("2026-11-01T06:00:00Z")

    private fun planned(id: String = "j", legs: Int = 2) {
        store.save(journey(id, List(legs) { leg("$id-l${it + 1}") }, status = JourneyStatus.PLANNED))
    }

    private fun types(id: String = "j") = store.pendingEvents(id, 100).map { it.type }

    private fun refused(r: TrackingResult) = (r as TrackingResult.Refused).reason

    @Test fun onlyAPlannedJourneyCanBeFollowed() {
        store.save(journey("draft", listOf(leg("d1"))))
        assertEquals("Mark the journey as planned before following it.", refused(controller.start("draft", t0, false)))
        assertTrue(refused(controller.start("missing", t0, false)).contains("no longer exists"))
    }

    @Test fun startingIsRecordedAndOnlyOneJourneyIsFollowedAtATime() {
        planned("a")
        planned("b")
        val ok = controller.start("a", t0, locationDetection = true) as TrackingResult.Ok
        assertEquals(TrackingState.ACTIVE, ok.session.state)
        assertTrue(ok.session.locationDetection)
        assertEquals(listOf("tracking_started"), types("a"))
        assertEquals(true, store.pendingEvents("a", 1).single().data["location_detection"])
        assertTrue(refused(controller.start("b", t0, false)).contains("Another journey"))
        assertTrue(refused(controller.start("a", t0, false)).contains("already being followed"))
    }

    @Test fun pauseResumeAndStopFollowTheirPreconditions() {
        planned()
        assertTrue(refused(controller.pause("j", t0)).contains("not being followed"))
        controller.start("j", t0, false)
        assertTrue(refused(controller.resume("j", t0)).contains("not paused"))
        assertEquals(TrackingState.PAUSED, (controller.pause("j", t0.plusSeconds(60)) as TrackingResult.Ok).session.state)
        assertTrue(refused(controller.pause("j", t0)).contains("not being followed"))
        assertEquals(TrackingState.ACTIVE, (controller.resume("j", t0.plusSeconds(120)) as TrackingResult.Ok).session.state)
        assertEquals(TrackingState.STOPPED, (controller.stop("j", t0.plusSeconds(180)) as TrackingResult.Ok).session.state)
        assertTrue(refused(controller.stop("j", t0)).contains("not being followed"))
        assertEquals(listOf("tracking_started", "tracking_paused", "tracking_resumed", "tracking_stopped"), types())
        // Stopped means free again.
        assertTrue(controller.start("j", t0.plusSeconds(300), false) is TrackingResult.Ok)
    }

    @Test fun arrivalsMoveThroughTheLegsInOrderAndFinishTheJourney() {
        planned(legs = 3)
        controller.start("j", t0, false)
        assertEquals("j-l1", controller.progress(store.get("j")!!).current!!.id)
        // Skipping ahead is refused: a leg cannot be confirmed before the ones before it.
        assertEquals("That is not the leg you are on.", refused(controller.confirmArrival("j", "j-l2", t0, ArrivalBasis.MANUAL)))
        assertTrue(controller.confirmArrival("j", "j-l1", t0.plusSeconds(10), ArrivalBasis.MANUAL) is TrackingResult.Ok)
        assertEquals("That is not the leg you are on.", refused(controller.confirmArrival("j", "j-l1", t0.plusSeconds(20), ArrivalBasis.MANUAL)))
        controller.confirmArrival("j", "j-l2", t0.plusSeconds(30), ArrivalBasis.DETECTED)
        val last = controller.confirmArrival("j", "j-l3", t0.plusSeconds(40), ArrivalBasis.MANUAL) as TrackingResult.Ok
        assertTrue(last.completed)
        assertEquals(TrackingState.STOPPED, last.session.state)
        assertEquals(
            listOf("tracking_started", "arrival_confirmed", "arrival_detected", "arrival_confirmed", "journey_completed"),
            types(),
        )
        val progress = controller.progress(store.get("j")!!)
        assertTrue(progress.completed)
        assertEquals(3, progress.arrived.size)
        assertTrue(refused(controller.start("j", t0.plusSeconds(60), false)).contains("already finished"))
    }

    @Test fun arrivalCannotBeConfirmedWithoutFollowing() {
        planned()
        assertTrue(refused(controller.confirmArrival("j", "j-l1", t0, ArrivalBasis.MANUAL)).contains("not being followed"))
        controller.start("j", t0, false)
        controller.stop("j", t0)
        assertTrue(refused(controller.confirmArrival("j", "j-l1", t0, ArrivalBasis.MANUAL)).contains("not being followed"))
    }

    @Test fun networkRestoredIsRecordedOnlyWhileAJourneyIsFollowed() {
        planned()
        controller.networkRestored(t0)
        assertTrue(types().isEmpty())
        controller.start("j", t0, false)
        controller.networkRestored(t0.plusSeconds(5))
        assertEquals(listOf("tracking_started", "network_restored"), types())
    }

    @Test fun eventsNeverCarryPlaceNamesOrCoordinates() {
        planned()
        controller.start("j", t0, true)
        controller.confirmArrival("j", "j-l1", t0, ArrivalBasis.DETECTED)
        store.pendingEvents("j", 100).forEach { e ->
            e.data.values.forEach { v -> assertTrue("only flat primitives: $v", v == null || v is Boolean || v is Number || v is String) }
            assertFalse(e.data.toString().contains("Katpadi"))
        }
    }
}

class ArrivalPolicyTest {
    private val station = GeoPoint(12.9716, 77.5946)
    private val near = GeoPoint(12.9720, 77.5950) // about 60 m away
    private val far = GeoPoint(13.0500, 77.7000)
    private val now = 10_000_000L

    private fun fix(point: GeoPoint, agoSeconds: Long, accuracy: Double? = 20.0) = Fix(point, accuracy, now - agoSeconds * 1000)

    @Test fun distanceIsRoughlyRight() {
        val d = ArrivalPolicy.distanceM(station, GeoPoint(12.9716, 77.6046)) // 0.01 degrees of longitude at this latitude
        assertEquals(1085.0, d, 15.0)
    }

    @Test fun aSingleReadingInsideIsNotArrival() {
        assertEquals(ArrivalVerdict.NotYet, ArrivalPolicy.evaluate(station, listOf(fix(near, 10)), now))
    }

    @Test fun readingsInsideForTheDwellTimeAreArrival() {
        assertEquals(ArrivalVerdict.Arrived, ArrivalPolicy.evaluate(station, listOf(fix(near, 150), fix(near, 10)), now))
    }

    @Test fun readingsTooCloseInTimeAreNotEnough() {
        assertEquals(ArrivalVerdict.NotYet, ArrivalPolicy.evaluate(station, listOf(fix(near, 40), fix(near, 10)), now))
    }

    @Test fun aGoodReadingElsewhereResetsTheWait() {
        val fixes = listOf(fix(near, 200), fix(far, 100), fix(near, 20))
        assertEquals(ArrivalVerdict.NotYet, ArrivalPolicy.evaluate(station, fixes, now))
    }

    @Test fun staleOrImpreciseReadingsNeverProveArrival() {
        val stale = listOf(fix(near, 900), fix(near, 800))
        assertTrue(ArrivalPolicy.evaluate(station, stale, now) is ArrivalVerdict.Uncertain)
        val vague = listOf(fix(near, 150, accuracy = 800.0), fix(near, 10, accuracy = 900.0))
        assertTrue(ArrivalPolicy.evaluate(station, vague, now) is ArrivalVerdict.Uncertain)
        val unknown = listOf(fix(near, 150, accuracy = null), fix(near, 10, accuracy = null))
        assertTrue(ArrivalPolicy.evaluate(station, unknown, now) is ArrivalVerdict.Uncertain)
        assertTrue(ArrivalPolicy.evaluate(station, emptyList(), now) is ArrivalVerdict.Uncertain)
    }

    @Test fun aReadingFromTheFutureIsIgnored() {
        assertTrue(ArrivalPolicy.evaluate(station, listOf(fix(near, -30), fix(near, -10)), now) is ArrivalVerdict.Uncertain)
    }
}

class ReminderPlannerTest {
    private val ist = ZoneId.of("Asia/Kolkata")
    private fun at(h: Int, m: Int = 0) = ZonedDateTime.of(2026, 11, 1, h, m, 0, 0, ist)
    private val trip = journey(
        "j",
        listOf(
            leg("train", TransportMode.TRAIN, "Katpadi", "Bengaluru", at(7, 45), at(11, 30), number = "12607"),
            leg("taxi", TransportMode.TAXI, "Bengaluru", "Airport", at(11, 50), at(12, 40)),
            leg("flight", TransportMode.FLIGHT, "Airport", "Lucknow", at(14), at(16, 30), number = "6E 123"),
            leg("none", TransportMode.BUS, "A", "B", null, null),
        ),
        status = JourneyStatus.PLANNED,
    )
    private val store = InMemoryJourneyStore().also { it.save(trip) }
    private val controller = TrackingController(store, store)

    @Test fun remindersUseModeLeadTimesAndSkipLegsWithoutATime() {
        val reminders = ReminderPlanner.plan(trip, controller.progress(trip), Instant.parse("2026-10-31T00:00:00Z"))
        assertEquals(4, reminders.size)
        assertEquals(at(7, 15).toInstant(), reminders[0].at)
        assertEquals(at(11, 40).toInstant(), reminders[1].at)
        assertEquals(at(12, 0).toInstant(), reminders[2].at)
        assertTrue(reminders[2].text.contains("flight 6E 123"))
        assertEquals("reminder:j:train", reminders[0].key)
        // A flight also gets a check at its expected arrival, worded as a question, not as a landing.
        assertEquals("arrival:j:flight", reminders[3].key)
        assertEquals(at(16, 30).toInstant(), reminders[3].at)
        assertTrue(reminders[3].text.contains("Piko cannot tell that it landed"))
    }

    @Test fun pastRemindersAndArrivedLegsAreDropped() {
        controller.start("j", Instant.parse("2026-11-01T01:00:00Z"), false)
        controller.confirmArrival("j", "train", Instant.parse("2026-11-01T06:05:00Z"), ArrivalBasis.MANUAL)
        val now = at(11, 45).toInstant()
        val reminders = ReminderPlanner.plan(trip, controller.progress(trip), now)
        assertEquals(listOf("reminder:j:flight", "arrival:j:flight"), reminders.map { it.key })
    }
}

class BatteryPolicyTest {
    @Test fun lowBatteryStopsLocationAndItComesBackWithAMargin() {
        assertTrue(app.piko.android.journeys.domain.BatteryPolicy.allowsLocation(50, false, true))
        assertFalse(app.piko.android.journeys.domain.BatteryPolicy.allowsLocation(9, false, true))
        // Back at 12%: still off, because resuming needs 15% (no flapping around one value).
        assertFalse(app.piko.android.journeys.domain.BatteryPolicy.allowsLocation(12, false, false))
        assertTrue(app.piko.android.journeys.domain.BatteryPolicy.allowsLocation(15, false, false))
    }

    @Test fun chargingOrAnUnknownLevelNeverBlocks() {
        assertTrue(app.piko.android.journeys.domain.BatteryPolicy.allowsLocation(3, true, false))
        assertTrue(app.piko.android.journeys.domain.BatteryPolicy.allowsLocation(null, null, false))
    }
}

class EventRecordingTest {
    @Test fun nothingIsRecordedWhileBackupIsOffButProgressStillWorks() {
        val store = InMemoryJourneyStore()
        store.save(journey("j", listOf(leg("l1")), status = JourneyStatus.PLANNED))
        val controller = TrackingController(store, store, { false })
        val t0 = Instant.parse("2026-11-01T06:00:00Z")
        assertTrue(controller.start("j", t0, false) is TrackingResult.Ok)
        val done = controller.confirmArrival("j", "l1", t0.plusSeconds(5), ArrivalBasis.MANUAL) as TrackingResult.Ok
        assertTrue(done.completed)
        assertTrue(store.pendingEvents("j", 10).isEmpty())
        assertEquals(1, store.arrivals("j").size)
    }
}
