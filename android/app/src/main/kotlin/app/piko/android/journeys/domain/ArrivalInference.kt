package app.piko.android.journeys.domain

import java.time.Instant

/**
 * "Possible arrival" is a guess from the clock, never a fact. It exists so that after a long flight with no
 * connection the screen can say "this may have landed, please confirm" instead of either staying silent or
 * announcing a landing nobody confirmed. Only the user (or a location reading that passed [ArrivalPolicy]) records
 * an arrival; no live flight data source is used in this build.
 */
object ArrivalInference {
    /** True once the leg's expected arrival time (your update if any, else the schedule) has passed and it is not confirmed. */
    fun possiblyArrived(leg: Leg, confirmed: Boolean, now: Instant): Boolean {
        if (confirmed) return false
        val expected = (leg.estimate?.arrival ?: leg.arrival)?.toInstant() ?: return false
        return !now.isBefore(expected)
    }

    const val WORDING = "Possible arrival, awaiting confirmation"
}
