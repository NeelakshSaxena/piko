package app.piko.android.core

import java.time.Instant
import java.util.UUID

/**
 * Turns collector readings into durable queue entries. Occurrence time is the time the reading was
 * captured (never later than "now"); it is never touched again after this point.
 */
class Recorder(
    private val store: EventStore,
    private val clock: Clock,
    private val newId: () -> String = { UUID.randomUUID().toString() },
) {
    @Volatile
    private var lastRecordedMs: Long = clock.nowMs()

    fun record(
        data: EventData,
        capturedAtMs: Long = clock.nowMs(),
        priority: EventPriority = EventPriority.NORMAL,
    ): EnqueueResult {
        val now = clock.nowMs()
        val occurred = Instant.ofEpochMilli(if (capturedAtMs in 1..now) capturedAtMs else now)
        val result = store.enqueue(NewEvent(newId(), occurred, data, priority), now)
        lastRecordedMs = now
        return result
    }

    /** True when nothing has been recorded for [HEARTBEAT_AFTER_MS], so the parent would see "offline". */
    fun heartbeatDue(): Boolean = clock.nowMs() - lastRecordedMs >= HEARTBEAT_AFTER_MS
}

/** Battery changes constantly; only a meaningful change (or a slow refresh) becomes an event. */
class BatteryThrottle(
    private val minDeltaPercent: Int = 2,
    private val refreshMs: Long = 15 * 60_000,
) {
    private var lastPercent: Int? = null
    private var lastCharging: Boolean? = null
    private var lastEmitMs = 0L

    fun shouldEmit(percent: Int, charging: Boolean, nowMs: Long): Boolean {
        val last = lastPercent
        val emit = last == null ||
            kotlin.math.abs(percent - last) >= minDeltaPercent ||
            charging != lastCharging ||
            nowMs - lastEmitMs >= refreshMs
        if (emit) {
            lastPercent = percent
            lastCharging = charging
            lastEmitMs = nowMs
        }
        return emit
    }
}

/** One connectivity event per change of network type, not per capability callback. */
class ConnectivityThrottle {
    private var last: String? = null

    fun shouldEmit(networkType: String): Boolean {
        if (networkType == last) return false
        last = networkType
        return true
    }
}
