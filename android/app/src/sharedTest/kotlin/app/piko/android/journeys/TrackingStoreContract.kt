package app.piko.android.journeys

import app.piko.android.journeys.domain.Arrival
import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.GeoPoint
import app.piko.android.journeys.domain.JourneyEvent
import app.piko.android.journeys.domain.JourneyStore
import app.piko.android.journeys.domain.TrackingSession
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.domain.TrackingStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/** Journey and tracking state share one database; both views must be the same object. */
abstract class TrackingStoreContract {
    abstract fun newStores(): Pair<JourneyStore, TrackingStore>

    private val t0 = Instant.parse("2026-11-01T06:00:00Z")

    private fun session(id: String, state: TrackingState = TrackingState.ACTIVE, detect: Boolean = false) =
        TrackingSession(id, state, t0, t0, detect)

    private fun event(id: String, journey: String, type: String = "observation", at: Instant = t0, data: Map<String, Any?> = emptyMap()) =
        JourneyEvent(id, journey, type, at, data)

    @Test fun aSessionRoundTripsAndOnlyOneIsFollowed() {
        val (journeys, tracking) = newStores()
        journeys.save(journey("a", listOf(leg("l1"))))
        journeys.save(journey("b", listOf(leg("l2"))))
        assertNull(tracking.followed())
        tracking.saveSession(session("a", detect = true))
        assertEquals(session("a", detect = true), tracking.session("a"))
        assertEquals("a", tracking.followed()!!.journeyId)
        tracking.saveSession(session("a").copy(state = TrackingState.PAUSED))
        assertEquals("a", tracking.followed()!!.journeyId) // paused is still followed
        tracking.saveSession(session("a").copy(state = TrackingState.STOPPED))
        assertNull(tracking.followed())
        assertEquals(TrackingState.STOPPED, tracking.session("a")!!.state)
    }

    @Test fun anArrivalIsRecordedOnceAndTheFirstOneStands() {
        val (journeys, tracking) = newStores()
        journeys.save(journey("a", listOf(leg("l1"))))
        assertTrue(tracking.recordArrival("a", Arrival("l1", t0, ArrivalBasis.DETECTED)))
        assertFalse(tracking.recordArrival("a", Arrival("l1", t0.plusSeconds(60), ArrivalBasis.MANUAL)))
        assertEquals(listOf(Arrival("l1", t0, ArrivalBasis.DETECTED)), tracking.arrivals("a"))
    }

    @Test fun arrivalsSurviveSavingTheJourneyAgain() {
        // Saving rewrites the legs; progress must not disappear with them.
        val (journeys, tracking) = newStores()
        journeys.save(journey("a", listOf(leg("l1"), leg("l2"))))
        tracking.recordArrival("a", Arrival("l1", t0, ArrivalBasis.MANUAL))
        journeys.save(journey("a", listOf(leg("l1"), leg("l2")), updated = "2026-10-29T10:00:00Z"))
        assertEquals(1, tracking.arrivals("a").size)
    }

    @Test fun eventsAreDeliveredInOrderThenMarkedSentAndDeduplicatedById() {
        val (journeys, tracking) = newStores()
        journeys.save(journey("a", listOf(leg("l1"))))
        tracking.appendEvent(event("e1", "a", "tracking_started", data = mapOf("location_detection" to true)))
        tracking.appendEvent(event("e2", "a", "observation", data = mapOf("battery_percent" to 41, "connected" to false, "network" to null)))
        tracking.appendEvent(event("e1", "a", "tracking_started")) // same id again: ignored
        val pending = tracking.pendingEvents("a", 10)
        assertEquals(listOf("e1", "e2"), pending.map { it.id })
        assertEquals(true, pending[0].data["location_detection"])
        assertEquals(41, pending[1].data["battery_percent"])
        assertEquals(false, pending[1].data["connected"])
        assertEquals(listOf("a"), tracking.journeysWithPendingEvents())
        assertEquals(listOf("e1"), tracking.pendingEvents("a", 1).map { it.id }) // bounded batches
        tracking.markEventsSent(listOf("e1", "e2"))
        assertTrue(tracking.pendingEvents("a", 10).isEmpty())
        assertTrue(tracking.journeysWithPendingEvents().isEmpty())
    }

    @Test fun pruningDropsDeliveredEventsAndOverdueOnesOnly() {
        val (journeys, tracking) = newStores()
        journeys.save(journey("a", listOf(leg("l1"))))
        tracking.appendEvent(event("old", "a", at = t0.minusSeconds(40L * 86_400)))
        tracking.appendEvent(event("sent", "a", at = t0))
        tracking.appendEvent(event("fresh", "a", at = t0))
        tracking.markEventsSent(listOf("sent"))
        assertEquals(2, tracking.pruneEvents(t0.minusSeconds(30L * 86_400)))
        assertEquals(listOf("fresh"), tracking.pendingEvents("a", 10).map { it.id })
    }

    @Test fun deletingAJourneyRemovesItsTrackingData() {
        val (journeys, tracking) = newStores()
        journeys.save(journey("a", listOf(leg("l1"))))
        tracking.saveSession(session("a"))
        tracking.recordArrival("a", Arrival("l1", t0, ArrivalBasis.MANUAL))
        tracking.appendEvent(event("e1", "a"))
        journeys.delete("a")
        assertNull(tracking.session("a"))
        assertNull(tracking.followed())
        assertTrue(tracking.arrivals("a").isEmpty())
        assertTrue(tracking.pendingEvents("a", 10).isEmpty())
    }

    @Test fun anAlertIsClaimedOnlyOnce() {
        val (_, tracking) = newStores()
        assertTrue(tracking.claimAlert("reminder:a:l1", t0))
        assertFalse(tracking.claimAlert("reminder:a:l1", t0.plusSeconds(5)))
        assertTrue(tracking.claimAlert("reminder:a:l2", t0))
        assertEquals(0, tracking.pruneAlerts(t0.minusSeconds(1)))
        assertEquals(2, tracking.pruneAlerts(t0.plusSeconds(1)))
        assertTrue(tracking.claimAlert("reminder:a:l1", t0.plusSeconds(10))) // a forgotten key can be claimed again
    }

    @Test fun destinationCoordinatesRoundTripAndMayBeAbsent() {
        val (journeys, _) = newStores()
        journeys.save(
            journey(
                "a",
                listOf(leg("l1").copy(destinationPoint = GeoPoint(12.9941, 77.7066)), leg("l2")),
            ),
        )
        val loaded = journeys.get("a")!!
        assertEquals(GeoPoint(12.9941, 77.7066), loaded.legs[0].destinationPoint)
        assertNull(loaded.legs[1].destinationPoint)
    }
}
