package app.piko.android.journeys.data

import app.piko.android.journeys.domain.LiveLookup
import app.piko.android.journeys.domain.LiveReading
import app.piko.android.journeys.domain.LiveState
import org.json.JSONException
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

/** Reads the answer of `GET /api/v1/journeys/live/{flight,train}` (docs/API_CONTRACTS.md). Anything unexpected is a failure, never a guess. */
object LiveCodec {
    fun parse(status: Int, body: String): LiveLookup = when {
        status == 200 -> parseBody(body)
        status == 401 -> LiveLookup.Failed(LiveState.NOT_PAIRED)
        status == 429 -> LiveLookup.Failed(LiveState.RATE_LIMITED)
        status == 408 || status >= 500 -> LiveLookup.Failed(LiveState.UNAVAILABLE)
        else -> LiveLookup.Failed(LiveState.REFUSED)
    }

    private fun parseBody(body: String): LiveLookup = try {
        val json = JSONObject(body)
        when (val state = json.getString("state")) {
            "ok" -> LiveLookup.Got(reading(json))
            else -> LiveLookup.Failed(failure(state))
        }
    } catch (_: JSONException) {
        LiveLookup.Failed(LiveState.UNUSABLE)
    } catch (_: DateTimeParseException) {
        LiveLookup.Failed(LiveState.UNUSABLE)
    }

    private fun failure(state: String): LiveState = when (state) {
        "disabled" -> LiveState.DISABLED
        "not_configured" -> LiveState.NOT_CONFIGURED
        "not_found" -> LiveState.NOT_FOUND
        "auth_failed" -> LiveState.AUTH_FAILED
        "rate_limited" -> LiveState.RATE_LIMITED
        "unavailable" -> LiveState.UNAVAILABLE
        else -> LiveState.UNUSABLE
    }

    private fun reading(json: JSONObject): LiveReading {
        val notices = json.optJSONArray("notices")
        return LiveReading(
            provider = json.getString("provider"),
            checkedAt = instant(json.getString("checked_at")),
            status = json.text("status"),
            departureDelayMinutes = json.minutes("departure_delay_minutes"),
            arrivalDelayMinutes = json.minutes("arrival_delay_minutes"),
            runningDelayMinutes = json.minutes("running_delay_minutes"),
            departureGate = json.text("departure_gate"),
            departureTerminal = json.text("departure_terminal"),
            arrivalGate = json.text("arrival_gate"),
            arrivalTerminal = json.text("arrival_terminal"),
            providerUpdatedAt = json.text("provider_updated_at")?.let(::instant),
            notices = (0 until (notices?.length() ?: 0)).mapNotNull { notices?.optString(it)?.takeIf { s -> s.isNotEmpty() } },
        )
    }

    private fun instant(text: String): Instant = OffsetDateTime.parse(text).toInstant()

    private fun JSONObject.text(name: String): String? = if (isNull(name)) null else optString(name).takeIf { it.isNotEmpty() }

    // A missing value stays missing: it is never read as 0 minutes.
    private fun JSONObject.minutes(name: String): Int? = if (isNull(name) || !has(name)) null else getInt(name)
}
