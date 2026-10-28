package app.piko.android.journeys.domain

import java.time.Instant
import java.util.UUID

/** ACTIVE and PAUSED are "a journey is being followed"; STOPPED is over (finished or ended by the user). */
enum class TrackingState { ACTIVE, PAUSED, STOPPED }

/**
 * [locationDetection] is the user's explicit choice to let Piko use this phone's location to notice arrival.
 * Without it nothing about location is read, and arrival is confirmed by the user.
 */
data class TrackingSession(
    val journeyId: String,
    val state: TrackingState,
    val startedAt: Instant,
    val updatedAt: Instant,
    val locationDetection: Boolean,
) {
    val following: Boolean get() = state != TrackingState.STOPPED
}

enum class ArrivalBasis { MANUAL, DETECTED }

data class Arrival(val legId: String, val at: Instant, val basis: ArrivalBasis)

/** Mirrors the server's list of event types (docs/API_CONTRACTS.md). [data] holds flat primitives only. */
data class JourneyEvent(
    val id: String,
    val journeyId: String,
    val type: String,
    val occurredAt: Instant,
    val data: Map<String, Any?> = emptyMap(),
)

/** Tracking bookkeeping that sits beside the journeys. Everything here is deleted with its journey. */
interface TrackingStore {
    fun session(journeyId: String): TrackingSession?

    /** The one journey being followed right now (ACTIVE or PAUSED), if any. */
    fun followed(): TrackingSession?

    fun saveSession(session: TrackingSession)

    fun arrivals(journeyId: String): List<Arrival>

    /** False if the leg already has an arrival; the first one stands. */
    fun recordArrival(journeyId: String, arrival: Arrival): Boolean

    fun appendEvent(event: JourneyEvent)

    /** Events not yet delivered to the server, oldest first. */
    fun pendingEvents(journeyId: String, limit: Int): List<JourneyEvent>

    fun journeysWithPendingEvents(): List<String>

    fun markEventsSent(ids: List<String>)

    /** Deletes delivered events, and undelivered ones too once they are older than [cutoff]. Returns how many. */
    fun pruneEvents(cutoff: Instant): Int

    /** True the first time a key is claimed. A notification is shown only when this returns true. */
    fun claimAlert(key: String, at: Instant): Boolean

    fun pruneAlerts(cutoff: Instant): Int
}

sealed interface TrackingResult {
    data class Ok(val session: TrackingSession, val completed: Boolean = false) : TrackingResult
    data class Refused(val reason: String) : TrackingResult
}

/** Where a journey stands, derived only from what was confirmed. Nothing here is a prediction. */
data class Progress(val arrived: List<Leg>, val current: Leg?, val upcoming: List<Leg>) {
    val completed: Boolean get() = current == null && arrived.isNotEmpty()
}

/** The tracking lifecycle. It decides what is allowed and what happened; showing it is someone else's job. */
class TrackingController(
    private val journeys: JourneyStore,
    private val tracking: TrackingStore,
    /** Events exist only to be backed up. With backup off nothing is recorded, so nothing piles up on the phone. */
    private val recordEvents: () -> Boolean = { true },
    private val newId: () -> String = { UUID.randomUUID().toString() },
) {
    fun progress(journey: Journey): Progress {
        val done = tracking.arrivals(journey.id).map { it.legId }.toSet()
        val current = journey.legs.firstOrNull { it.id !in done }
        val arrived = journey.legs.filter { it.id in done }
        val upcoming = if (current == null) emptyList() else journey.legs.dropWhile { it.id != current.id }.drop(1)
        return Progress(arrived, current, upcoming)
    }

    fun start(journeyId: String, now: Instant, locationDetection: Boolean): TrackingResult {
        val journey = journeys.get(journeyId) ?: return TrackingResult.Refused("That journey no longer exists.")
        if (journey.status != JourneyStatus.PLANNED) return TrackingResult.Refused("Mark the journey as planned before following it.")
        tracking.followed()?.let {
            return TrackingResult.Refused(
                if (it.journeyId == journeyId) "This journey is already being followed." else "Another journey is being followed. Stop it first.",
            )
        }
        if (progress(journey).completed) return TrackingResult.Refused("This journey is already finished.")
        val session = TrackingSession(journeyId, TrackingState.ACTIVE, now, now, locationDetection)
        tracking.saveSession(session)
        record(journeyId, "tracking_started", now, mapOf("location_detection" to locationDetection))
        return TrackingResult.Ok(session)
    }

    fun pause(journeyId: String, now: Instant): TrackingResult = change(journeyId, TrackingState.ACTIVE, TrackingState.PAUSED, "tracking_paused", now)

    fun resume(journeyId: String, now: Instant): TrackingResult = change(journeyId, TrackingState.PAUSED, TrackingState.ACTIVE, "tracking_resumed", now)

    fun stop(journeyId: String, now: Instant): TrackingResult {
        val s = tracking.session(journeyId)?.takeIf { it.following } ?: return TrackingResult.Refused("This journey is not being followed.")
        val stopped = s.copy(state = TrackingState.STOPPED, updatedAt = now)
        tracking.saveSession(stopped)
        record(journeyId, "tracking_stopped", now)
        return TrackingResult.Ok(stopped)
    }

    /** Confirms arrival at the end of the current leg. Only the current leg can be confirmed, so legs are never skipped. */
    fun confirmArrival(journeyId: String, legId: String, now: Instant, basis: ArrivalBasis): TrackingResult {
        val s = tracking.session(journeyId)?.takeIf { it.following } ?: return TrackingResult.Refused("This journey is not being followed.")
        val journey = journeys.get(journeyId) ?: return TrackingResult.Refused("That journey no longer exists.")
        val current = progress(journey).current ?: return TrackingResult.Refused("This journey is already finished.")
        if (current.id != legId) return TrackingResult.Refused("That is not the leg you are on.")
        if (!tracking.recordArrival(journeyId, Arrival(legId, now, basis))) return TrackingResult.Refused("Arrival was already recorded.")
        val sequence = journey.legs.indexOfFirst { it.id == legId } + 1
        record(journeyId, if (basis == ArrivalBasis.MANUAL) "arrival_confirmed" else "arrival_detected", now, mapOf("leg" to sequence))
        if (progress(journey).completed) {
            record(journeyId, "journey_completed", now)
            val finished = s.copy(state = TrackingState.STOPPED, updatedAt = now)
            tracking.saveSession(finished)
            return TrackingResult.Ok(finished, completed = true)
        }
        return TrackingResult.Ok(s)
    }

    /** The phone regained a connection while a journey is being followed. */
    fun networkRestored(now: Instant) {
        val s = tracking.followed() ?: return
        record(s.journeyId, "network_restored", now)
    }

    fun record(journeyId: String, type: String, at: Instant, data: Map<String, Any?> = emptyMap()) {
        if (!recordEvents()) return
        tracking.appendEvent(JourneyEvent(newId(), journeyId, type, at, data))
    }

    private fun change(journeyId: String, from: TrackingState, to: TrackingState, event: String, now: Instant): TrackingResult {
        val s = tracking.session(journeyId)
        if (s == null || s.state != from) {
            return TrackingResult.Refused(if (from == TrackingState.ACTIVE) "This journey is not being followed." else "This journey is not paused.")
        }
        val next = s.copy(state = to, updatedAt = now)
        tracking.saveSession(next)
        record(journeyId, event, now)
        return TrackingResult.Ok(next)
    }
}
