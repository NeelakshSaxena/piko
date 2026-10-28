package app.piko.android.journeys.domain

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** One location reading. [atMs] is when it was measured, not when it was received. */
data class Fix(val point: GeoPoint, val accuracyM: Double?, val atMs: Long)

sealed interface ArrivalVerdict {
    /** Enough good readings stayed inside the area. */
    data object Arrived : ArrivalVerdict

    /** Readings are good and say the phone is somewhere else (or has only just reached the area). */
    data object NotYet : ArrivalVerdict

    /** Not enough trustworthy readings to say either way. The caller must not claim arrival. */
    data class Uncertain(val reason: String) : ArrivalVerdict
}

/**
 * Arrival is never one reading. It needs [MIN_FIXES] readings, each fresh and accurate enough, all inside the
 * radius, spanning at least [DWELL_MS]. A good reading outside the radius resets the wait. Airport interiors and
 * overlapping station areas make single readings unreliable, which is why the user can always confirm by hand.
 */
object ArrivalPolicy {
    const val RADIUS_M = 300.0
    const val MAX_ACCURACY_M = 150.0
    const val MAX_AGE_MS = 5 * 60_000L
    const val DWELL_MS = 2 * 60_000L
    const val MIN_FIXES = 2

    fun evaluate(target: GeoPoint, fixes: List<Fix>, nowMs: Long, radiusM: Double = RADIUS_M): ArrivalVerdict {
        val fresh = fixes.filter { nowMs - it.atMs in 0..MAX_AGE_MS }
        if (fresh.isEmpty()) return ArrivalVerdict.Uncertain("No recent location reading.")
        val usable = fresh.filter { it.accuracyM != null && it.accuracyM <= MAX_ACCURACY_M }.sortedBy { it.atMs }
        if (usable.isEmpty()) return ArrivalVerdict.Uncertain("Location readings are too imprecise.")
        // Walk back from the newest reading while they stay inside the area.
        val inside = usable.takeLastWhile { distanceM(target, it.point) <= radiusM + (it.accuracyM ?: 0.0).coerceAtMost(50.0) }
        if (inside.isEmpty()) return ArrivalVerdict.NotYet
        if (inside.size < MIN_FIXES || inside.last().atMs - inside.first().atMs < DWELL_MS) return ArrivalVerdict.NotYet
        return ArrivalVerdict.Arrived
    }

    /** Great-circle distance in metres. */
    fun distanceM(a: GeoPoint, b: GeoPoint): Double {
        val r = 6_371_000.0
        val dLat = Math.toRadians(b.latitude - a.latitude)
        val dLon = Math.toRadians(b.longitude - a.longitude)
        val h = sin(dLat / 2).pow(2) + cos(Math.toRadians(a.latitude)) * cos(Math.toRadians(b.latitude)) * sin(dLon / 2).pow(2)
        return 2 * r * asin(sqrt(h))
    }
}
