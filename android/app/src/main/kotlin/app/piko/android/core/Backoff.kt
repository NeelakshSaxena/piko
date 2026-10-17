package app.piko.android.core

import kotlin.random.Random

/** Exponential backoff with equal jitter (half fixed, half random), shared by telemetry and comms. */
internal object Backoff {
    fun delayMs(consecutiveFailures: Int, config: SyncConfig, random: Random, retryAfterSeconds: Long?): Long {
        val exponent = minOf(consecutiveFailures - 1, 30)
        val ceiling = minOf(config.maxBackoffMs, config.baseBackoffMs shl exponent)
        val jittered = ceiling / 2 + random.nextLong(ceiling / 2 + 1)
        val server = retryAfterSeconds?.let { (it * 1000).coerceIn(1_000, config.maxBackoffMs) } ?: 0
        return maxOf(jittered, server)
    }
}
