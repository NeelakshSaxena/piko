package app.piko.android.push

import android.content.Context
import app.piko.android.comms.CommsNotifier
import app.piko.android.comms.CommsRunner
import app.piko.android.core.PushEvent
import app.piko.android.core.PushPayload
import app.piko.android.graph
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/**
 * Receives pushes while the app is in the background or its process was not running (FCM starts it).
 *
 * The push is only a trigger. It carries a type and an id, which are validated and then ignored except
 * to decide what to say if the server cannot be reached: the phone asks the authoritative API what
 * changed, applies it through the same idempotent code the open app uses, and only then shows a
 * notification (see [CommsNotifier]). A duplicate, delayed or reordered push therefore cannot show a
 * second alert or change any state.
 */
open class PikoMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        PushSupport.onNewToken(applicationContext, token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val event = PushPayload.parse(message.data) ?: return // not ours, malformed or a newer format
        PushHandler.handle(applicationContext, event)
    }
}

object PushHandler {
    /**
     * Runs on a background thread (FCM gives a service about 20 seconds). Returns true if the server was
     * read, false if it could not be and the generic fallback notification was used instead.
     */
    fun handle(context: Context, event: PushEvent): Boolean {
        val graph = context.graph
        if (graph.vault.load() == null || graph.vault.credentialRevoked) return false // not paired: ignore
        val before = CommsRunner.lastRefreshMs
        try {
            CommsRunner.runOnce(context, forceRefresh = true)
        } catch (_: Exception) {
            // fall through: the fallback below tells the child that something changed
        }
        val synced = CommsRunner.lastRefreshMs > before
        if (!synced) CommsNotifier.showGeneric(context, event)
        return synced
    }
}
