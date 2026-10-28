package app.piko.android.journeys.tracking

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.piko.android.graph
import app.piko.android.journeys.domain.ReminderPlanner
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingState
import java.time.Instant

/**
 * Departure reminders are alarms set on the phone, so they work with no connection. They are inexact on purpose
 * (`setAndAllowWhileIdle` needs no special permission) and Android may deliver them a little late; the text
 * says when the leg is due, so a late alarm is not misleading. They are rebuilt after a reboot or an update.
 */
object JourneyReminders {
    private const val EXTRA_JOURNEY = "journey"
    private const val EXTRA_LEG = "leg"
    private const val EXTRA_KEY = "key"
    private const val EXTRA_TEXT = "text"

    /** Cancels this journey's alarms, then sets the ones that are still ahead if it is being followed. */
    fun replan(context: Context, journeyId: String) {
        val graph = context.graph
        val journey = graph.journeys.get(journeyId)
        val alarms = context.getSystemService(AlarmManager::class.java)
        journey?.legs?.forEach { leg -> KINDS.forEach { alarms.cancel(pending(context, journeyId, leg.id, it, "", "")) } }
        val session = graph.journeys.session(journeyId)
        if (journey == null || session == null || session.state != TrackingState.ACTIVE) return
        val progress = TrackingController(graph.journeys, graph.journeys).progress(journey)
        val now = Instant.ofEpochMilli(graph.clock.nowMs())
        for (reminder in ReminderPlanner.plan(journey, progress, now)) {
            val kind = reminder.key.substringBefore(':')
            val legId = reminder.key.substringAfterLast(':')
            alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, reminder.at.toEpochMilli(), pending(context, journeyId, legId, kind, reminder.key, reminder.text))
        }
    }

    private val KINDS = listOf("reminder", "arrival")

    private fun pending(context: Context, journeyId: String, legId: String, kind: String, key: String, text: String): PendingIntent =
        PendingIntent.getBroadcast(
            context,
            (kind + journeyId + legId).hashCode(),
            Intent(context, JourneyAlarmReceiver::class.java)
                .putExtra(EXTRA_JOURNEY, journeyId).putExtra(EXTRA_LEG, legId).putExtra(EXTRA_KEY, key).putExtra(EXTRA_TEXT, text),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    internal fun fire(context: Context, intent: Intent) {
        val journeyId = intent.getStringExtra(EXTRA_JOURNEY) ?: return
        val legId = intent.getStringExtra(EXTRA_LEG) ?: return
        val key = intent.getStringExtra(EXTRA_KEY)?.takeIf { it.isNotEmpty() } ?: return
        val text = intent.getStringExtra(EXTRA_TEXT) ?: return
        val graph = context.graph
        val journey = graph.journeys.get(journeyId) ?: return
        val session = graph.journeys.session(journeyId)
        // The user may have stopped following, deleted the journey or already reached this leg since the alarm was set.
        if (session == null || session.state != TrackingState.ACTIVE) return
        val progress = TrackingController(graph.journeys, graph.journeys).progress(journey)
        if (progress.arrived.any { it.id == legId }) return
        JourneyNotifier.notifyOnce(context, key, journey.title, text)
    }
}

class JourneyAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = JourneyReminders.fire(context, intent)
}

/** Alarms do not survive a reboot or an app update, so they are rebuilt. Nothing else happens at boot. */
class JourneyBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        // Only the two system broadcasts it asks for; anything else (it is not exported) is ignored.
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        context.graph.journeys.followed()?.let { JourneyReminders.replan(context, it.journeyId) }
    }
}
