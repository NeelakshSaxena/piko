package app.piko.android.core

/** Builds the request body for `POST /api/v1/telemetry/batches` (schema_version 1). */
object BatchCodec {
    const val SCHEMA_VERSION = 1

    fun encode(deviceId: String, batch: Batch): String = buildString {
        append("{\"batch_id\":").append(str(batch.batchId))
        append(",\"schema_version\":").append(SCHEMA_VERSION)
        append(",\"device_id\":").append(str(deviceId))
        append(",\"events\":[")
        batch.events.forEachIndexed { i, e ->
            if (i > 0) append(',')
            append("{\"event_id\":").append(str(e.eventId))
            append(",\"event_type\":").append(str(e.type.wire))
            // The row id is strictly increasing per install, which is what `sequence_number` is for.
            append(",\"sequence_number\":").append(e.seq)
            append(",\"occurred_at\":").append(str(e.occurredAtIso))
            append(",\"data\":").append(e.dataJson).append('}')
        }
        append("]}")
    }

    /** Every value written here is a UUID, an enum or an ISO instant; escaping is defensive only. */
    private fun str(value: String): String = buildString {
        append('"')
        for (c in value) {
            when {
                c == '"' || c == '\\' -> append('\\').append(c)
                c < ' ' -> append(String.format("\\u%04x", c.code))
                else -> append(c)
            }
        }
        append('"')
    }
}
