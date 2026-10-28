package app.piko.android.journeys.domain

import java.time.DateTimeException
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.format.ResolverStyle

enum class TransportMode(val label: String) {
    FLIGHT("Flight"),
    TRAIN("Train"),
    TAXI("Taxi"),
    BIKE_TAXI("Bike taxi"),
    METRO("Metro"),
    BUS("Bus"),
    WALKING("Walking"),
    OTHER("Other"),
    ;

    /** Modes that have a number worth writing down (flight, train, bus or route number). */
    val hasServiceNumber: Boolean get() = this == FLIGHT || this == TRAIN || this == BUS || this == METRO
}

/** DRAFT may be incomplete; PLANNED has passed [JourneyRules.problemsForPlanning]. Nothing tracks yet. */
enum class JourneyStatus { DRAFT, PLANNED }

/** A place on the map. Kept on the phone only: it is never uploaded in a backup. */
data class GeoPoint(val latitude: Double, val longitude: Double)

/**
 * What the user last said to expect for a leg (for example a delay they heard about). It sits beside the schedule and
 * never replaces it. Kept on the phone only. [enteredAt] is when they said it, so its age can be shown and trusted accordingly.
 */
data class Estimate(val departure: ZonedDateTime?, val arrival: ZonedDateTime?, val enteredAt: Instant)

/**
 * One segment of a trip. Times are what the user entered, kept with the zone they were entered in
 * (a flight departs in one zone and lands in another), and are never overwritten by estimates.
 */
data class Leg(
    val id: String,
    val mode: TransportMode,
    val serviceNumber: String?,
    val origin: String,
    val destination: String,
    val departure: ZonedDateTime?,
    val arrival: ZonedDateTime?,
    /** Where the leg ends, if the user picked a match for the name. Needed only for arrival detection by location. */
    val destinationPoint: GeoPoint? = null,
    val estimate: Estimate? = null,
)

/** [legs] list order is the trip order; the position is the leg's sequence. */
data class Journey(
    val id: String,
    val title: String,
    val status: JourneyStatus,
    val legs: List<Leg>,
    val createdAt: Instant,
    val updatedAt: Instant,
)

object JourneyRules {
    const val MAX_LEGS = 20
    const val MAX_TEXT = 80

    /** Problems that stop even a draft from being saved. */
    fun problemsForSaving(journey: Journey): List<String> = buildList {
        if (journey.title.isBlank()) add("Give the journey a title.")
        if (journey.title.length > MAX_TEXT) add("The title is longer than $MAX_TEXT characters.")
        if (journey.legs.size > MAX_LEGS) add("A journey can have at most $MAX_LEGS legs.")
    }

    /** What must be fixed before a draft can be marked planned. Every message names the leg it is about. */
    fun problemsForPlanning(journey: Journey): List<String> = buildList {
        addAll(problemsForSaving(journey))
        if (journey.legs.isEmpty()) add("Add at least one leg.")
        journey.legs.forEachIndexed { i, leg ->
            val n = i + 1
            val dep = leg.departure
            val arr = leg.arrival
            if (dep == null) add("Leg $n needs a departure time.")
            if (arr == null) add("Leg $n needs an arrival time.")
            if (dep != null && arr != null && !arr.toInstant().isAfter(dep.toInstant())) {
                add("Leg $n arrives before it departs.")
            }
            val previousArrival = journey.legs.getOrNull(i - 1)?.arrival
            if (dep != null && previousArrival != null && dep.toInstant().isBefore(previousArrival.toInstant())) {
                add("Leg $n departs before leg $i arrives.")
            }
        }
    }

    /** Moves one leg; an out-of-range index leaves the order unchanged. */
    fun move(legs: List<Leg>, from: Int, to: Int): List<Leg> {
        if (from !in legs.indices || to !in legs.indices || from == to) return legs
        return legs.toMutableList().also { it.add(to, it.removeAt(from)) }
    }

    /** Time between one leg's arrival and the next one's departure; null when either time is missing. */
    fun gapBetween(previous: Leg, next: Leg): Duration? {
        val arrival = previous.arrival ?: return null
        val departure = next.departure ?: return null
        return Duration.between(arrival.toInstant(), departure.toInstant())
    }
}

/** The leg form as typed: text in, a [Leg] or one readable error out. */
data class LegInput(
    val mode: TransportMode,
    val serviceNumber: String,
    val origin: String,
    val destination: String,
    val departure: String,
    val departureZone: String,
    val arrival: String,
    val arrivalZone: String,
    val destinationPoint: GeoPoint? = null,
) {
    sealed interface Parsed {
        data class Ok(val leg: Leg) : Parsed
        data class Error(val message: String) : Parsed
    }

    /** Times may stay blank in a draft; a time that is typed must be a real date and the zone a real IANA id. */
    fun parse(id: String, previous: Leg? = null): Parsed {
        val from = origin.trim()
        val to = destination.trim()
        val number = serviceNumber.trim()
        if (from.isEmpty()) return Parsed.Error("Enter where this leg starts.")
        if (to.isEmpty()) return Parsed.Error("Enter where this leg ends.")
        if (from.length > JourneyRules.MAX_TEXT || to.length > JourneyRules.MAX_TEXT || number.length > JourneyRules.MAX_TEXT) {
            return Parsed.Error("Names and numbers can be at most ${JourneyRules.MAX_TEXT} characters.")
        }
        val dep = zoned(departure, departureZone, "departure")
        if (dep is Zoned.Bad) return Parsed.Error(dep.message)
        val arr = zoned(arrival, arrivalZone, "arrival")
        if (arr is Zoned.Bad) return Parsed.Error(arr.message)
        val departureTime = (dep as Zoned.Value).time
        val arrivalTime = (arr as Zoned.Value).time
        // An update about the old schedule says nothing about a changed one, so it is kept only while the schedule is unchanged.
        val keptEstimate = previous?.estimate?.takeIf {
            previous.departure?.toInstant() == departureTime?.toInstant() && previous.arrival?.toInstant() == arrivalTime?.toInstant()
        }
        return Parsed.Ok(
            Leg(
                id = id,
                mode = mode,
                serviceNumber = number.ifEmpty { null }?.takeIf { mode.hasServiceNumber },
                origin = from,
                destination = to,
                departure = departureTime,
                arrival = arrivalTime,
                destinationPoint = destinationPoint,
                estimate = keptEstimate,
            ),
        )
    }

    private sealed interface Zoned {
        data class Value(val time: ZonedDateTime?) : Zoned
        data class Bad(val message: String) : Zoned
    }

    private fun zoned(text: String, zone: String, what: String): Zoned {
        val t = text.trim()
        if (t.isEmpty()) return Zoned.Value(null)
        val id = try {
            ZoneId.of(zone.trim())
        } catch (_: DateTimeException) {
            return Zoned.Bad("The $what time zone must be a place such as Asia/Kolkata.")
        }
        return try {
            Zoned.Value(ZonedDateTime.of(LocalDateTime.parse(t, TIME_FORMAT), id))
        } catch (_: DateTimeParseException) {
            Zoned.Bad("Write the $what as year-month-day hour:minute, for example $EXAMPLE.")
        }
    }

    sealed interface EstimateParsed {
        data class Ok(val estimate: Estimate?) : EstimateParsed
        data class Error(val message: String) : EstimateParsed
    }

    companion object {
        const val EXAMPLE = "2026-11-01 07:45"

        /**
         * The "expected time" form for one leg. Times are read in the zones of the leg's own schedule. Both blank
         * clears the update. A leg without a scheduled time has nothing to compare an update to, so it cannot take one.
         */
        fun parseEstimate(leg: Leg, departure: String, arrival: String, now: Instant): EstimateParsed {
            fun read(text: String, scheduled: ZonedDateTime?, what: String): Pair<ZonedDateTime?, String?> {
                val t = text.trim()
                if (t.isEmpty()) return null to null
                if (scheduled == null) return null to "This leg has no scheduled $what time to update."
                return try {
                    ZonedDateTime.of(LocalDateTime.parse(t, TIME_FORMAT), scheduled.zone) to null
                } catch (_: DateTimeParseException) {
                    null to "Write the expected $what as year-month-day hour:minute, for example $EXAMPLE."
                }
            }
            val (dep, depError) = read(departure, leg.departure, "departure")
            if (depError != null) return EstimateParsed.Error(depError)
            val (arr, arrError) = read(arrival, leg.arrival, "arrival")
            if (arrError != null) return EstimateParsed.Error(arrError)
            if (dep == null && arr == null) return EstimateParsed.Ok(null)
            val effectiveDeparture = (dep ?: leg.departure)?.toInstant()
            val effectiveArrival = (arr ?: leg.arrival)?.toInstant()
            if (effectiveDeparture != null && effectiveArrival != null && !effectiveArrival.isAfter(effectiveDeparture)) {
                return EstimateParsed.Error("The expected arrival is not after the departure.")
            }
            return EstimateParsed.Ok(Estimate(dep, arr, now))
        }

        /** The form text for an expected time, in the leg's own zone. */
        fun estimateText(time: ZonedDateTime?): String = time?.format(TIME_FORMAT).orEmpty()
        private val TIME_FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm").withResolverStyle(ResolverStyle.STRICT)

        /** The form text for a stored leg, so editing shows exactly what was entered. */
        fun of(leg: Leg, defaultZone: String): LegInput = LegInput(
            mode = leg.mode,
            serviceNumber = leg.serviceNumber.orEmpty(),
            origin = leg.origin,
            destination = leg.destination,
            departure = leg.departure?.format(TIME_FORMAT).orEmpty(),
            departureZone = leg.departure?.zone?.id ?: defaultZone,
            arrival = leg.arrival?.format(TIME_FORMAT).orEmpty(),
            arrivalZone = leg.arrival?.zone?.id ?: defaultZone,
            destinationPoint = leg.destinationPoint,
        )
    }
}
