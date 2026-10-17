package app.piko.android.debug

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.piko.android.core.PushPayload
import app.piko.android.push.PushHandler
import app.piko.android.push.PushSupport

/**
 * DEBUG BUILDS ONLY (this file lives in the debug source set). Stands in for Firebase's two callbacks so the
 * push-handling code can be driven from `adb shell am broadcast` on an emulator without a Firebase project:
 *
 *   SIMULATE_PUSH  --es v 1 --es type message --es id <uuid>   ->  the code path of onMessageReceived
 *   SIMULATE_TOKEN --es token <fcm-like token>                  ->  the code path of onNewToken
 *
 * It exercises validation, the authoritative sync and the notification logic. It proves nothing about FCM,
 * Google Play services or the network leg between them.
 */
class SimulatePushReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        Thread {
            try {
                when (intent.action) {
                    ACTION_PUSH -> {
                        val data = listOf("v", "type", "id").mapNotNull { key -> intent.getStringExtra(key)?.let { key to it } }.toMap()
                        PushPayload.parse(data)?.let { PushHandler.handle(context.applicationContext, it) }
                    }
                    ACTION_TOKEN -> intent.getStringExtra("token")?.let { PushSupport.onNewToken(context.applicationContext, it) }
                }
            } finally {
                pending.finish()
            }
        }.start()
    }

    companion object {
        const val ACTION_PUSH = "app.piko.android.debug.SIMULATE_PUSH"
        const val ACTION_TOKEN = "app.piko.android.debug.SIMULATE_TOKEN"
    }
}
