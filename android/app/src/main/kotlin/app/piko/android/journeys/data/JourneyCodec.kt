package app.piko.android.journeys.data

import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyEvent
import org.json.JSONArray
import org.json.JSONObject
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** The wire form of a journey for `PUT /api/v1/journeys/{id}` (see docs/API_CONTRACTS.md). */
object JourneyCodec {
    fun put(journey: Journey, revision: Long): String {
        val legs = JSONArray()
        journey.legs.forEach { leg ->
            legs.put(
                JSONObject()
                    .put("id", leg.id)
                    .put("mode", leg.mode.name)
                    .put("service_number", leg.serviceNumber ?: JSONObject.NULL)
                    .put("origin", leg.origin)
                    .put("destination", leg.destination)
                    .put("departure_at", leg.departure.offsetText())
                    .put("departure_zone", leg.departure?.zone?.id ?: JSONObject.NULL)
                    .put("arrival_at", leg.arrival.offsetText())
                    .put("arrival_zone", leg.arrival?.zone?.id ?: JSONObject.NULL),
            )
        }
        return JSONObject()
            .put("title", journey.title)
            .put("status", journey.status.name)
            .put("created_at", journey.createdAt.toString())
            .put("updated_at", journey.updatedAt.toString())
            .put("revision", revision)
            .put("legs", legs)
            .toString()
    }

    /** What the server said about a PUT: whether it applied the upload and the revision it now holds. Null if unreadable. */
    fun putAnswer(body: String): Pair<Boolean, Long>? = try {
        val json = JSONObject(body)
        json.getBoolean("applied") to json.getJSONObject("journey").getLong("revision")
    } catch (_: org.json.JSONException) {
        null
    }

    /** The body of `POST /api/v1/journeys/{id}/events`. [batchId] only labels the request; event ids make it idempotent. */
    fun events(batchId: String, events: List<JourneyEvent>): String {
        val array = JSONArray()
        events.forEach { e ->
            array.put(
                JSONObject()
                    .put("event_id", e.id)
                    .put("event_type", e.type)
                    .put("occurred_at", e.occurredAt.toString())
                    .put("data", JSONObject(e.data.mapValues { it.value ?: JSONObject.NULL })),
            )
        }
        return JSONObject().put("batch_id", batchId).put("events", array).toString()
    }

    private fun ZonedDateTime?.offsetText(): Any = this?.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME) ?: JSONObject.NULL
}
