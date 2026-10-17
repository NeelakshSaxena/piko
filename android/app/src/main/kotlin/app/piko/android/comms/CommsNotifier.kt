package app.piko.android.comms

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import app.piko.android.core.PushEvent
import app.piko.android.core.PushType
import app.piko.android.core.RefreshResult
import app.piko.android.graph
import app.piko.android.ui.MainActivity

/**
 * Tells the child about replies. Notification text never contains a message body (lock screens are
 * visible to others). If the notification permission is denied nothing is shown here and the app
 * says so on its screens: this is a convenience, never the only place the information lives.
 */
object CommsNotifier {
    private const val CHANNEL_ID = "family"
    private const val SOS_NOTIFICATION_ID = 20
    private const val MESSAGE_NOTIFICATION_ID = 21
    const val OPEN_MESSAGES = "messages"
    const val OPEN_HOME = "home"

    fun canNotify(context: Context): Boolean =
        context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED &&
            context.getSystemService(NotificationManager::class.java).areNotificationsEnabled()

    fun announce(context: Context, result: RefreshResult) {
        val graph = context.graph
        val unseen = result.parentMessages.filter { it.status == "delivered" && it.id !in graph.vault.announcedMessages() }
        // Mark first: if the permission is off the message is still not re-announced forever when it
        // is granted later; the in-app list keeps showing it as unread.
        if (unseen.isNotEmpty()) graph.vault.markAnnounced(unseen.map { it.id })
        if (!canNotify(context)) return
        if (unseen.isNotEmpty()) {
            post(context, MESSAGE_NOTIFICATION_ID, "New message from your family", "Open Piko to read it.", OPEN_MESSAGES)
        }
        val latest = result.sosAdvanced.lastOrNull()?.second ?: return
        val text = if (latest == "resolved") "A parent marked your SOS as resolved." else "A parent saw your SOS."
        post(context, SOS_NOTIFICATION_ID, "Update on your SOS", text, OPEN_HOME)
    }

    /**
     * Used when a push arrived but the server could not be read (offline, outage). It says only that
     * something changed, never what; one notification per event id, so a duplicate push replaces it.
     */
    fun showGeneric(context: Context, event: PushEvent) {
        if (!canNotify(context)) return
        val (title, text, open) = when (event.type) {
            PushType.MESSAGE -> Triple("New message from your family", "Open Piko to read it.", OPEN_MESSAGES)
            PushType.SOS_UPDATE, PushType.SOS_CREATED -> Triple("Update on your SOS", "Open Piko to see what changed.", OPEN_HOME)
        }
        post(context, 1000 + (event.type.wire + event.id).hashCode().and(0xFFFF), title, text, open)
    }

    private fun post(context: Context, id: Int, title: String, text: String, open: String) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "Family replies", NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Replies from your family and updates on an SOS" },
        )
        val intent = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_OPEN, open)
            .setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val tap = PendingIntent.getActivity(context, id, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        manager.notify(
            id,
            Notification.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(text)
                .setContentIntent(tap)
                .setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .build(),
        )
    }
}
