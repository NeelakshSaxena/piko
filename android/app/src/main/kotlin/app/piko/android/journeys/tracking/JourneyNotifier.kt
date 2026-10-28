package app.piko.android.journeys.tracking

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import app.piko.android.comms.CommsNotifier
import app.piko.android.graph
import app.piko.android.ui.MainActivity
import java.time.Instant

/**
 * One place that decides whether a journey notification is shown. A key is claimed in the database first, so a
 * reminder that fires twice (a restart, a repeated alarm) is shown once. Nothing here puts a place name or a
 * position on the lock screen: the visibility is private.
 */
object JourneyNotifier {
    const val CHANNEL = "journey_updates"
    const val OPEN = "journeys"
    private const val KEEP_KEYS_DAYS = 14L

    /** Shows the notification unless [key] was already shown or notifications are off. */
    fun notifyOnce(context: Context, key: String, title: String, text: String): Boolean {
        val graph = context.graph
        val now = Instant.ofEpochMilli(graph.clock.nowMs())
        graph.journeys.pruneAlerts(now.minusSeconds(KEEP_KEYS_DAYS * 86_400))
        if (!CommsNotifier.canNotify(context)) return false // not claimed: nothing was shown
        if (!graph.journeys.claimAlert(key, now)) return false
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Journey updates", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "Reminders and arrivals for a journey you chose to follow" },
        )
        val id = key.hashCode()
        val open = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_OPEN, OPEN)
            .setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        manager.notify(
            id,
            Notification.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(Notification.BigTextStyle().bigText(text))
                .setContentIntent(PendingIntent.getActivity(context, id, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
                .setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .build(),
        )
        return true
    }
}
