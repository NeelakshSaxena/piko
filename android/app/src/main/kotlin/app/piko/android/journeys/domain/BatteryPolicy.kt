package app.piko.android.journeys.domain

/**
 * Location is the expensive sensor, so detection by location backs off on a low battery and comes back with a
 * margin (so it does not flap around one value). Charging, or an unknown level, never blocks it. The journey
 * itself, reminders and manual confirmation do not depend on this.
 */
object BatteryPolicy {
    const val PAUSE_BELOW = 10
    const val RESUME_AT = 15

    fun allowsLocation(percent: Int?, charging: Boolean?, currentlyAllowed: Boolean): Boolean {
        if (percent == null || charging == true) return true
        return if (currentlyAllowed) percent >= PAUSE_BELOW else percent >= RESUME_AT
    }
}
