package app.piko.android.journeys.domain

import java.time.Duration
import java.time.Instant

enum class Risk { COMFORTABLE, TIGHT, AT_RISK, UNKNOWN }

/** How [Connection.predictedArrival] and the next departure were obtained. Never "confirmed": no live data source is used. */
enum class TimeBasis { SCHEDULE, YOUR_UPDATE }

/**
 * @property slack available minus required; negative means the next leg is expected to leave before the trip
 *  can reasonably get there. Null when it cannot be worked out.
 */
data class Connection(
    val fromLegId: String,
    val toLegId: String,
    val risk: Risk,
    val slack: Duration?,
    val available: Duration?,
    val required: Duration,
    val basis: TimeBasis,
    val estimateEnteredAt: Instant?,
    val explanation: String,
)

/** Plain defaults, not airline or railway rules. [transfer] is time to get from one leg to the next; [margin] is extra safety. */
data class ConnectionAssumptions(
    val transfer: Map<TransportMode, Duration> = mapOf(
        TransportMode.FLIGHT to Duration.ofMinutes(75), // check-in, security, boarding cut-off
        TransportMode.TRAIN to Duration.ofMinutes(20),
        TransportMode.BUS to Duration.ofMinutes(10),
        TransportMode.METRO to Duration.ofMinutes(5),
        TransportMode.TAXI to Duration.ofMinutes(5),
        TransportMode.BIKE_TAXI to Duration.ofMinutes(5),
        TransportMode.WALKING to Duration.ZERO,
        TransportMode.OTHER to Duration.ofMinutes(10),
    ),
    val margin: Duration = Duration.ofMinutes(15),
    val comfortableSlack: Duration = Duration.ofMinutes(30),
    /** An update older than this, for a leg that has not arrived, is not trusted. */
    val staleAfter: Duration = Duration.ofHours(3),
) {
    fun required(next: TransportMode): Duration = (transfer[next] ?: Duration.ofMinutes(10)).plus(margin)
}

/**
 * Looks at the connection after every leg that has not been reached yet:
 * `available = next departure - predicted arrival`, `required = transfer + margin`, `slack = available - required`.
 * The prediction is the schedule the user entered, or their latest update; it says so in words and goes UNKNOWN
 * when a time is missing or the update is stale, rather than guessing.
 */
object ConnectionPlanner {
    fun assess(
        journey: Journey,
        progress: Progress,
        now: Instant,
        assumptions: ConnectionAssumptions = ConnectionAssumptions(),
    ): List<Connection> {
        val reached = progress.arrived.map { it.id }.toSet()
        return journey.legs.zipWithNext().filter { (from, _) -> from.id !in reached }.map { (from, to) -> one(from, to, now, assumptions) }
    }

    private fun one(from: Leg, to: Leg, now: Instant, a: ConnectionAssumptions): Connection {
        val required = a.required(to.mode)
        val arrivalUpdate = from.estimate?.arrival
        val departureUpdate = to.estimate?.departure
        val arrival = (arrivalUpdate ?: from.arrival)?.toInstant()
        val departure = (departureUpdate ?: to.departure)?.toInstant()
        val usedUpdate = arrivalUpdate != null || departureUpdate != null
        val basis = if (usedUpdate) TimeBasis.YOUR_UPDATE else TimeBasis.SCHEDULE
        val enteredAt = listOfNotNull(from.estimate?.takeIf { arrivalUpdate != null }?.enteredAt, to.estimate?.takeIf { departureUpdate != null }?.enteredAt).minOrNull()

        fun result(risk: Risk, slack: Duration?, available: Duration?, why: String) =
            Connection(from.id, to.id, risk, slack, available, required, basis, enteredAt, why)

        if (arrival == null || departure == null) {
            return result(Risk.UNKNOWN, null, null, "A time is missing, so this connection cannot be worked out.")
        }
        if (enteredAt != null && Duration.between(enteredAt, now) > a.staleAfter && arrival.isAfter(now)) {
            return result(Risk.UNKNOWN, null, null, "Your last update is more than ${a.staleAfter.toHours()} hours old, so it is not trusted. Update the expected time.")
        }
        val available = Duration.between(arrival, departure)
        val slack = available.minus(required)
        val source = if (usedUpdate) "your update" else "the schedule you entered"
        val numbers = "${minutes(available)} between arriving and the next leg leaving, and about ${minutes(required)} needed " +
            "(${minutes(a.transfer[to.mode] ?: Duration.ZERO)} to transfer plus ${minutes(a.margin)} margin), going by $source."
        return when {
            slack.isNegative -> result(Risk.AT_RISK, slack, available, "At risk: $numbers")
            slack < a.comfortableSlack -> result(Risk.TIGHT, slack, available, "Tight: $numbers")
            else -> result(Risk.COMFORTABLE, slack, available, "Comfortable: $numbers")
        }
    }

    private fun minutes(d: Duration): String {
        val m = d.toMinutes()
        return if (m >= 60) "${m / 60} h ${m % 60} min" else "$m min"
    }
}
