package app.piko.android

import android.Manifest
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import app.piko.android.journeys.domain.GeoPoint
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.TrackingResult
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.journey
import app.piko.android.journeys.leg
import app.piko.android.journeys.domain.TransportMode
import app.piko.android.journeys.tracking.JourneyActions
import app.piko.android.journeys.tracking.JourneyObservations
import app.piko.android.journeys.tracking.JourneyRuntime
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.ZonedDateTime
import java.util.UUID

/**
 * Runs the real service, alarms and store in the app process. It proves the foreground-service type,
 * permissions and lifecycle work on a device image; it does NOT prove arrival detection with real movement.
 */
class JourneyTrackingSmokeTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val id = "smoke-" + UUID.randomUUID()
    private val legId = "leg-" + UUID.randomUUID()

    private var backupBefore = false

    @Before fun setUp() {
        backupBefore = context.graph.journeyPrefs.backupEnabled
        context.graph.journeyPrefs.backupEnabled = true // events are recorded only for backup
        val ui = InstrumentationRegistry.getInstrumentation().uiAutomation
        listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.POST_NOTIFICATIONS)
            .forEach { ui.grantRuntimePermission(context.packageName, it) }
        context.graph.journeys.followed()?.let { JourneyActions.stop(context, it.journeyId) }
        val later = ZonedDateTime.now().plusDays(1)
        context.graph.journeys.save(
            journey(id, listOf(leg(legId, departure = later, arrival = later.plusHours(2)).copy(destinationPoint = GeoPoint(12.9941, 77.7066))), status = JourneyStatus.PLANNED),
        )
    }

    @After fun tearDown() {
        context.graph.journeyPrefs.backupEnabled = backupBefore
        context.graph.journeys.followed()?.let { JourneyActions.stop(context, it.journeyId) }
        context.graph.journeys.delete(id)
    }

    @Test fun followingWithLocationStartsTheServiceAndStoppingEndsIt() {
        val started = JourneyActions.start(context, id, locationDetection = true)
        assertTrue(started.toString(), started is TrackingResult.Ok)
        assertEquals(id, context.graph.journeys.followed()!!.journeyId)
        // The service reports honestly that it is reading location (or why it is not).
        val deadline = System.currentTimeMillis() + 15_000
        while (!JourneyRuntime.status.value.detecting && System.currentTimeMillis() < deadline) Thread.sleep(250)
        val status = JourneyRuntime.status.value
        assertTrue("detecting=${status.detecting} note=${status.note}", status.detecting)

        assertTrue(JourneyActions.pause(context, id) is TrackingResult.Ok)
        assertEquals(TrackingState.PAUSED, context.graph.journeys.session(id)!!.state)
        waitUntil { !JourneyRuntime.status.value.detecting }
        assertTrue(!JourneyRuntime.status.value.detecting)

        assertTrue(JourneyActions.resume(context, id) is TrackingResult.Ok)
        waitUntil { JourneyRuntime.status.value.detecting }
        assertTrue(JourneyRuntime.status.value.detecting)

        assertTrue(JourneyActions.stop(context, id) is TrackingResult.Ok)
        assertNull(context.graph.journeys.followed())
        waitUntil { !JourneyRuntime.status.value.detecting }
        assertTrue(!JourneyRuntime.status.value.detecting)
        // The lifecycle was recorded as events, in order, and none of them carries a place name.
        val types = context.graph.journeys.pendingEvents(id, 50).map { it.type }
        assertEquals(listOf("tracking_started", "tracking_paused", "tracking_resumed", "tracking_stopped"), types)
        assertNotNull(context.graph.journeys.session(id))
    }

    @Test fun followingWithoutLocationNeverStartsTheLocationService() {
        assertTrue(JourneyActions.start(context, id, locationDetection = false) is TrackingResult.Ok)
        Thread.sleep(1_500)
        assertTrue(!JourneyRuntime.status.value.detecting)
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 10_000
        while (!condition() && System.currentTimeMillis() < deadline) Thread.sleep(250)
    }

    @Test fun aFlightLegGetsABatteryAndConnectionReadingWithoutLocation() {
        val flightId = "smoke-flight-" + UUID.randomUUID()
        val later = ZonedDateTime.now().plusDays(1)
        context.graph.journeys.save(
            journey(flightId, listOf(leg("f-" + UUID.randomUUID(), TransportMode.FLIGHT, departure = later, arrival = later.plusHours(2))), status = JourneyStatus.PLANNED),
        )
        try {
            context.graph.journeys.followed()?.let { JourneyActions.stop(context, it.journeyId) }
            assertTrue(JourneyActions.start(context, flightId, locationDetection = false) is TrackingResult.Ok)
            assertTrue(JourneyObservations.record(context))
            // The scheduled job may have taken its own reading meanwhile; every reading must look the same.
            val readings = context.graph.journeys.pendingEvents(flightId, 10).filter { it.type == "observation" }
            assertTrue(readings.isNotEmpty())
            readings.forEach { reading ->
                assertTrue(reading.data.keys.containsAll(listOf("charging", "connected", "airplane_mode")))
                assertTrue("no position in a reading", reading.data.keys.none { it.contains("lat") || it.contains("lon") })
            }
            // A non-flight journey is not sampled.
            JourneyActions.stop(context, flightId)
            assertTrue(!JourneyObservations.record(context))
        } finally {
            context.graph.journeys.followed()?.let { JourneyActions.stop(context, it.journeyId) }
            context.graph.journeys.delete(flightId)
        }
    }
}
