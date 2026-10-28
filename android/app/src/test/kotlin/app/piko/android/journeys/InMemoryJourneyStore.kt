package app.piko.android.journeys

import app.piko.android.journeys.domain.Arrival
import app.piko.android.journeys.domain.Estimate
import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyEvent
import app.piko.android.journeys.domain.JourneyStore
import app.piko.android.journeys.domain.TrackingSession
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.domain.TrackingStore
import java.time.Instant

/** Test fake with the same observable behaviour as SqliteJourneyStore (see JourneyStoreContract). */
class InMemoryJourneyStore : JourneyStore, TrackingStore {
    private val rows = LinkedHashMap<String, Journey>()
    private val synced = HashMap<String, Instant>()
    private val deletions = sortedSetOf<String>()
    private val sessions = HashMap<String, TrackingSession>()
    private val arrivalRows = LinkedHashMap<String, Pair<String, Arrival>>() // leg id -> (journey id, arrival)
    private class Stored(val event: JourneyEvent, var sent: Boolean = false)
    private val eventRows = LinkedHashMap<String, Stored>()
    private val alerts = HashMap<String, Instant>()

    @Synchronized override fun save(journey: Journey) {
        rows[journey.id] = journey
    }

    @Synchronized override fun get(id: String): Journey? = rows[id]

    @Synchronized override fun list(): List<Journey> =
        rows.values.sortedWith(compareByDescending<Journey> { it.updatedAt }.thenBy { it.id })

    @Synchronized override fun delete(id: String): Boolean {
        if (id in rows && id in synced) deletions += id
        synced.remove(id)
        sessions.remove(id)
        arrivalRows.values.removeAll { it.first == id }
        eventRows.values.removeAll { it.event.journeyId == id }
        return rows.remove(id) != null
    }

    @Synchronized override fun setEstimate(journeyId: String, legId: String, estimate: Estimate?) {
        val j = rows[journeyId] ?: return
        rows[journeyId] = j.copy(legs = j.legs.map { if (it.id == legId) it.copy(estimate = estimate) else it })
    }

    @Synchronized override fun dirty(): List<Journey> =
        rows.values.filter { synced[it.id] != it.updatedAt }.sortedWith(compareBy<Journey> { it.updatedAt }.thenBy { it.id })

    @Synchronized override fun markSynced(id: String, updatedAt: Instant): Boolean {
        if (id !in rows) return false
        synced[id] = updatedAt
        return true
    }

    @Synchronized override fun pendingDeletes(): List<String> = deletions.toList()

    @Synchronized override fun queueDelete(id: String) {
        deletions += id
    }

    @Synchronized override fun markDeleteSynced(id: String) {
        deletions -= id
    }

    @Synchronized override fun forgetSync() {
        synced.clear()
        deletions.clear()
    }

    // ---- tracking ----
    @Synchronized override fun session(journeyId: String): TrackingSession? = sessions[journeyId]

    @Synchronized override fun followed(): TrackingSession? =
        sessions.values.filter { it.state != TrackingState.STOPPED }.maxByOrNull { it.updatedAt }

    @Synchronized override fun saveSession(session: TrackingSession) {
        check(session.journeyId in rows) { "foreign key" }
        sessions[session.journeyId] = session
    }

    @Synchronized override fun arrivals(journeyId: String): List<Arrival> =
        arrivalRows.values.filter { it.first == journeyId }.map { it.second }.sortedBy { it.at }

    @Synchronized override fun recordArrival(journeyId: String, arrival: Arrival): Boolean {
        if (arrival.legId in arrivalRows) return false
        arrivalRows[arrival.legId] = journeyId to arrival
        return true
    }

    @Synchronized override fun appendEvent(event: JourneyEvent) {
        eventRows.putIfAbsent(event.id, Stored(event))
    }

    @Synchronized override fun pendingEvents(journeyId: String, limit: Int): List<JourneyEvent> =
        eventRows.values.filter { it.event.journeyId == journeyId && !it.sent }.map { it.event }.take(limit)

    @Synchronized override fun journeysWithPendingEvents(): List<String> =
        eventRows.values.filter { !it.sent }.map { it.event.journeyId }.distinct().sorted()

    @Synchronized override fun markEventsSent(ids: List<String>) {
        ids.forEach { eventRows[it]?.sent = true }
    }

    @Synchronized override fun pruneEvents(cutoff: Instant): Int {
        val doomed = eventRows.values.filter { it.sent || it.event.occurredAt < cutoff }.map { it.event.id }
        doomed.forEach { eventRows.remove(it) }
        return doomed.size
    }

    @Synchronized override fun claimAlert(key: String, at: Instant): Boolean = alerts.putIfAbsent(key, at) == null

    @Synchronized override fun pruneAlerts(cutoff: Instant): Int {
        val doomed = alerts.filterValues { it < cutoff }.keys.toList()
        doomed.forEach { alerts.remove(it) }
        return doomed.size
    }

}

class InMemoryJourneyStoreContractTest : JourneyStoreContract() {
    override fun newStore() = InMemoryJourneyStore()
}

class InMemoryTrackingStoreContractTest : TrackingStoreContract() {
    override fun newStores() = InMemoryJourneyStore().let { it to it }
}
