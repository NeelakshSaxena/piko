package app.piko.android.journeys.domain

import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** Why a live check gave no reading. The wording for each is in [LiveRules.explain]; none of them touches the journey. */
enum class LiveState { OK, DISABLED, NOT_CONFIGURED, NOT_FOUND, AUTH_FAILED, RATE_LIMITED, UNAVAILABLE, UNUSABLE, OFFLINE, NOT_PAIRED, REFUSED }

/** What a provider said when the user asked, nothing more. Never stored with the journey; not a schedule. */
data class LiveReading(
    val provider: String,
    val checkedAt: Instant,
    val status: String?,
    val departureDelayMinutes: Int?,
    val arrivalDelayMinutes: Int?,
    val runningDelayMinutes: Int?,
    val departureGate: String?,
    val departureTerminal: String?,
    val arrivalGate: String?,
    val arrivalTerminal: String?,
    val providerUpdatedAt: Instant?,
    val notices: List<String>,
)

sealed interface LiveLookup {
    data class Got(val reading: LiveReading) : LiveLookup
    data class Failed(val state: LiveState) : LiveLookup
}

sealed interface LiveRequest {
    data class Flight(val code: String, val day: LocalDate) : LiveRequest
    data class Train(val number: String) : LiveRequest
}

/** Expected times a reading would suggest. Offered to the user to review; never applied by itself. */
data class LiveSuggestion(val departure: ZonedDateTime?, val arrival: ZonedDateTime?)

/**
 * Rules for using live data without letting it overrule the user. The schedule and the user's own expected
 * times stay the source of truth: a reading is shown, labelled with its provider, and at most pre-fills the
 * "expected time" boxes, which the user then saves (or not) as their own entry.
 */
object LiveRules {
    /** A provider update older than this is shown but not offered, as with the user's own expected times. */
    val STALE: Duration = Duration.ofHours(3)
    val OPENS_BEFORE: Duration = Duration.ofHours(6)
    val CLOSES_AFTER: Duration = Duration.ofHours(3)

    private val FLIGHT = Regex("^[A-Z0-9]{2}[0-9]{1,4}[A-Z]?$")
    private val TRAIN = Regex("^[0-9]{5}$")

    /** What to ask the server for this leg, or null when it is not a flight/train with a usable number and schedule. */
    fun request(leg: Leg): LiveRequest? {
        val number = leg.serviceNumber?.filterNot { it.isWhitespace() }?.uppercase().orEmpty()
        val departure = leg.departure ?: return null
        if (leg.arrival == null) return null
        return when {
            leg.mode == TransportMode.FLIGHT && FLIGHT.matches(number) -> LiveRequest.Flight(number, departure.toLocalDate())
            leg.mode == TransportMode.TRAIN && TRAIN.matches(number) -> LiveRequest.Train(number)
            else -> null
        }
    }

    /** Asking outside this window would report a different day's run (trains take no date) or waste a small quota. */
    fun inWindow(leg: Leg, now: Instant): Boolean {
        val departure = leg.departure ?: return false
        val arrival = leg.arrival ?: return false
        return now >= departure.toInstant().minus(OPENS_BEFORE) && now <= arrival.toInstant().plus(CLOSES_AFTER)
    }

    fun providerName(id: String): String = when (id) {
        "aviationstack" -> "Aviationstack"
        "railradar" -> "RailRadar"
        else -> id
    }

    fun explain(state: LiveState): String = when (state) {
        LiveState.OK -> ""
        LiveState.DISABLED -> "Live data is switched off on your server, so only the times you enter are used."
        LiveState.NOT_CONFIGURED -> "Your server has no key for this data source yet, so only the times you enter are used."
        LiveState.NOT_FOUND -> "The data source has no record of this number on this date. Your own times are unchanged."
        LiveState.AUTH_FAILED -> "Your server's key for this data source was refused. Ask whoever runs your server. Your own times are unchanged."
        LiveState.RATE_LIMITED -> "The data source's request limit was reached for now. Try again later; your own times are unchanged."
        LiveState.UNAVAILABLE -> "The data source could not be reached. Try again later; your own times are unchanged."
        LiveState.UNUSABLE -> "The data source answered in a way Piko could not read, so nothing was used. Your own times are unchanged."
        LiveState.OFFLINE -> "No connection to your server. Your own times are unchanged and still work offline."
        LiveState.NOT_PAIRED -> "This phone is not linked to a server, so live data is not available."
        LiveState.REFUSED -> "Your server refused the request. Your own times are unchanged."
    }

    /**
     * Lines for the result card, each saying who said it. Delays are the provider's numbers, shown as such. A missing
     * number is left out: never shown as zero or "on time".
     */
    fun describe(reading: LiveReading, zone: ZoneId): List<String> {
        val who = providerName(reading.provider)
        val lines = ArrayList<String>()
        reading.status?.let { lines += "Status according to $who: $it" }
        reading.departureDelayMinutes?.let { lines += "Departure delay according to $who: ${minutesText(it)}" }
        reading.arrivalDelayMinutes?.let { lines += "Arrival delay according to $who: ${minutesText(it)}" }
        reading.runningDelayMinutes?.let { lines += "Current delay according to $who: ${minutesText(it)}" }
        listOfNotNull(
            reading.departureTerminal?.let { "terminal $it" },
            reading.departureGate?.let { "gate $it" },
        ).takeIf { it.isNotEmpty() }?.let { lines += "Departure ${it.joinToString(", ")} (per $who)" }
        listOfNotNull(
            reading.arrivalTerminal?.let { "terminal $it" },
            reading.arrivalGate?.let { "gate $it" },
        ).takeIf { it.isNotEmpty() }?.let { lines += "Arrival ${it.joinToString(", ")} (per $who)" }
        reading.notices.forEach { lines += noticeText(it, who) }
        val checked = DateTimeFormatter.ofPattern("HH:mm").withZone(zone).format(reading.checkedAt)
        val updated = reading.providerUpdatedAt?.let { ", data updated ${DateTimeFormatter.ofPattern("HH:mm").withZone(zone).format(it)}" }.orEmpty()
        lines += "Checked at $checked$updated. Not saved; this is not your schedule."
        return lines
    }

    private fun minutesText(minutes: Int): String = when {
        minutes == 0 -> "none (0 min)"
        minutes < 0 -> "${-minutes} min early"
        else -> "$minutes min late"
    }

    private fun noticeText(code: String, who: String): String = when (code) {
        "NOT_LIVE" -> "$who says this is not live tracking, so no current delay is shown."
        else -> "Notice from $who: ${code.lowercase().replace('_', ' ')}"
    }

    /**
     * The expected times this reading supports, built from the user's own schedule plus the provider's delay, or
     * null when it supports none: a stale or undated update, a cancellation notice, or no delay in the answer.
     */
    fun suggest(leg: Leg, reading: LiveReading, now: Instant): LiveSuggestion? {
        if (reading.notices.any { it == "CANCELLED" || it == "NOT_LIVE" }) return null
        if (reading.status == "cancelled") return null
        val updated = reading.providerUpdatedAt
        if (updated != null && Duration.between(updated, now) > STALE) return null
        if (Duration.between(reading.checkedAt, now) > STALE) return null
        val departure = leg.departure?.let { d -> reading.departureDelayMinutes?.let { d.plusMinutes(it.toLong()) } }
        val arrivalDelay = reading.arrivalDelayMinutes ?: reading.runningDelayMinutes
        val arrival = leg.arrival?.let { a -> arrivalDelay?.let { a.plusMinutes(it.toLong()) } }
        return if (departure == null && arrival == null) null else LiveSuggestion(departure, arrival)
    }
}
