package app.piko.android.journeys.domain

import java.time.Duration
import java.time.Instant

data class Reminder(val key: String, val at: Instant, val text: String)

/**
 * Departure reminders for the legs still ahead, based on the times the user entered (or last updated).
 * They are planned on the phone so they work without a connection. The lead times are plain defaults, not
 * airline or railway rules: an airport check-in cut-off is not known here.
 */
object ReminderPlanner {
    fun lead(mode: TransportMode): Duration = when (mode) {
        TransportMode.FLIGHT -> Duration.ofMinutes(120)
        TransportMode.TRAIN -> Duration.ofMinutes(30)
        TransportMode.BUS, TransportMode.METRO -> Duration.ofMinutes(15)
        TransportMode.TAXI, TransportMode.BIKE_TAXI, TransportMode.WALKING, TransportMode.OTHER -> Duration.ofMinutes(10)
    }

    /** Reminders that are still in the future at [now], earliest first. Legs already arrived are skipped. */
    fun plan(journey: Journey, progress: Progress, now: Instant): List<Reminder> {
        val ahead = listOfNotNull(progress.current) + progress.upcoming
        return ahead.flatMap { leg ->
            val name = leg.mode.label.lowercase() + (leg.serviceNumber?.let { " $it" } ?: "")
            val reminders = ArrayList<Reminder>()
            leg.departure?.let { departure ->
                val at = departure.toInstant().minus(lead(leg.mode))
                reminders += Reminder(
                    key = "reminder:${journey.id}:${leg.id}",
                    at = at,
                    text = "Your $name from ${leg.origin} is due to leave at ${departure.toLocalTime().withSecond(0).withNano(0)} " +
                        "(${departure.zone.id}), as you entered it.",
                )
            }
            // A flight can end with no connection and no way to know it landed, so at the expected time Piko asks.
            if (leg.mode == TransportMode.FLIGHT) {
                val expected = leg.estimate?.arrival ?: leg.arrival
                if (expected != null) {
                    reminders += Reminder(
                        key = "arrival:${journey.id}:${leg.id}",
                        at = expected.toInstant(),
                        text = "Your $name was due to arrive at ${expected.toLocalTime().withSecond(0).withNano(0)} (${expected.zone.id}), " +
                            "going by the time you entered. Piko cannot tell that it landed: open Piko and confirm when you have.",
                    )
                }
            }
            reminders
        }.filter { it.at.isAfter(now) }.sortedBy { it.at }
    }
}
