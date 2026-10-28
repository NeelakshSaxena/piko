package app.piko.android.journeys.data

import android.content.Context

/** The user's journey choices. Backup is OFF until the user turns it on; nothing is uploaded before that. */
class JourneyPrefs(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    var backupEnabled: Boolean
        get() = prefs.getBoolean("backup", false)
        set(value) {
            prefs.edit().putBoolean("backup", value).commit()
        }

    private companion object {
        const val FILE = "piko-journey-prefs"
    }
}
