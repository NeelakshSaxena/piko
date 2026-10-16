package app.piko.android.core

import java.time.Instant
import java.util.Locale

/** Pure Kotlin (no Android types) so the whole delivery pipeline is unit-testable on the JVM. */

fun interface Clock {
    fun nowMs(): Long
}

enum class EventType(val wire: String) {
    LOCATION("location"),
    BATTERY("battery"),
    CONNECTIVITY("connectivity");

    companion object {
        fun fromWire(value: String): EventType = entries.first { it.wire == value }
    }
}

/** CRITICAL is delivered first after reconnecting. Nothing emits it until the SOS phase. */
enum class EventPriority(val value: Int) { NORMAL(0), CRITICAL(1) }

/**
 * Local delivery state. An acknowledged event is deleted (and counted), so there is no
 * "delivered" row: delivered means the server acknowledged durable acceptance.
 *
 * QUEUED -> SUBMITTED (claimed into a batch) -> deleted on ack
 * SUBMITTED -> QUEUED on partial ack or a retryable server failure
 * SUBMITTED -> REJECTED on a permanent rejection (kept so the user can see it failed)
 */
enum class DeliveryState { QUEUED, SUBMITTED, REJECTED }

class InvalidEvent(message: String) : IllegalArgumentException(message)

/** Validated payloads mirroring the server contract; invalid values never reach the queue. */
sealed interface EventData {
    val type: EventType
    fun toJson(): String

    data class Location(
        val latitude: Double,
        val longitude: Double,
        val accuracyMeters: Double?,
    ) : EventData {
        init {
            if (!latitude.isFinite() || latitude !in -90.0..90.0) throw InvalidEvent("latitude")
            if (!longitude.isFinite() || longitude !in -180.0..180.0) throw InvalidEvent("longitude")
            if (accuracyMeters != null && (!accuracyMeters.isFinite() || accuracyMeters !in 0.0..10000.0)) {
                throw InvalidEvent("accuracy")
            }
        }

        override val type get() = EventType.LOCATION
        override fun toJson(): String {
            val acc = accuracyMeters?.let { "," + "\"accuracy_meters\":" + fmt(it, 2) } ?: ""
            return "{\"latitude\":${fmt(latitude, 7)},\"longitude\":${fmt(longitude, 7)}$acc}"
        }
    }

    data class Battery(val percent: Int, val isCharging: Boolean?) : EventData {
        init {
            if (percent !in 0..100) throw InvalidEvent("percent")
        }

        override val type get() = EventType.BATTERY
        override fun toJson(): String {
            val charging = isCharging?.let { ",\"is_charging\":$it" } ?: ""
            return "{\"percent\":$percent$charging}"
        }
    }

    data class Connectivity(val networkType: String) : EventData {
        init {
            if (!NETWORK_TYPE.matches(networkType)) throw InvalidEvent("network_type")
        }

        override val type get() = EventType.CONNECTIVITY
        override fun toJson(): String = "{\"network_type\":\"$networkType\"}"
    }

    private companion object {
        val NETWORK_TYPE = Regex("^[a-z0-9_]{1,32}$")
    }
}

internal fun fmt(value: Double, places: Int): String = String.format(Locale.ROOT, "%.${places}f", value)

/** `occurredAt` is when the reading was captured. It is stored and sent unchanged, always. */
data class NewEvent(
    val eventId: String,
    val occurredAt: Instant,
    val data: EventData,
    val priority: EventPriority = EventPriority.NORMAL,
)

data class QueuedEvent(
    val seq: Long,
    val eventId: String,
    val type: EventType,
    val occurredAtIso: String,
    val dataJson: String,
    val priority: EventPriority,
    val state: DeliveryState,
    val attempts: Int,
    val batchId: String?,
    val rejectReason: String?,
)

data class Batch(val batchId: String, val events: List<QueuedEvent>)

data class QueueCounts(
    val queued: Int,
    val submitted: Int,
    val rejected: Int,
    /** Events discarded because the queue was full (oldest normal-priority first). Never silent. */
    val droppedTotal: Long,
    val acknowledgedTotal: Long,
    val lastAcknowledgedAtMs: Long?,
    val oldestPendingOccurredAt: String?,
) {
    val pending: Int get() = queued + submitted
}

enum class SyncMode { REALTIME, POLLING }

/**
 * How each mode behaves. POLLING checks the queue every 60 s but does NOT sample the GPS every
 * minute; it asks the platform for balanced-power updates and only a movement of at least
 * [minDistanceMeters] (or the interval, whichever the system serves) produces an event.
 */
data class ModePlan(
    val syncIntervalMs: Long,
    val locationIntervalMs: Long,
    val minDistanceMeters: Float,
    val highAccuracy: Boolean,
    val flushOnEvent: Boolean,
)

fun SyncMode.plan(): ModePlan = when (this) {
    SyncMode.REALTIME -> ModePlan(60_000, 10_000, 5f, highAccuracy = true, flushOnEvent = true)
    SyncMode.POLLING -> ModePlan(60_000, 60_000, 20f, highAccuracy = false, flushOnEvent = false)
}

/** A silent device is judged offline by the server after 5 minutes; send liveness well before. */
const val HEARTBEAT_AFTER_MS = 4 * 60_000L
