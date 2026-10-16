package app.piko.android.core

/** Human-readable ages. An unknown time is "never", not "0 seconds ago". */
object TimeText {
    /** Same threshold the server uses for "fresh" location (docs/API_CONTRACTS.md). */
    const val FRESH_MS = 5 * 60_000L

    fun ago(nowMs: Long, thenMs: Long?): String {
        if (thenMs == null) return "never"
        val seconds = ((nowMs - thenMs) / 1000).coerceAtLeast(0)
        return when {
            seconds < 5 -> "just now"
            seconds < 60 -> "${seconds}s ago"
            seconds < 3600 -> "${seconds / 60} min ago"
            seconds < 86_400 -> "${seconds / 3600} h ago"
            else -> "${seconds / 86_400} d ago"
        }
    }

    /** A location older than [FRESH_MS] is never called live. */
    fun isFresh(nowMs: Long, thenMs: Long?): Boolean = thenMs != null && nowMs - thenMs in 0..FRESH_MS
}
