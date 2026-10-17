package app.piko.android.push

import android.content.Context
import app.piko.android.BuildConfig
import app.piko.android.core.PushCall
import app.piko.android.core.TokenServer
import app.piko.android.core.TokenStore
import app.piko.android.core.TokenSync
import app.piko.android.core.TokenSyncResult
import app.piko.android.data.DeviceVault
import app.piko.android.graph
import app.piko.android.net.ApiClient
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging

/**
 * Firebase Cloud Messaging glue (ADR-023). Everything here is optional at build time: with no Firebase
 * settings in `local.properties` the app still builds and works, push is simply "not configured on this
 * build" and the app falls back to fetching when it is open or sharing. No secret lives in the app:
 * the settings below identify a Firebase project and are not credentials; the server's service-account
 * key never leaves the server.
 */
object PushSupport {
    enum class Status { NOT_CONFIGURED, WAITING_FOR_TOKEN, REGISTRATION_PENDING, REGISTERED }

    fun configured(): Boolean =
        BuildConfig.FIREBASE_PROJECT_ID.isNotBlank() && BuildConfig.FIREBASE_APP_ID.isNotBlank() &&
            BuildConfig.FIREBASE_API_KEY.isNotBlank() && BuildConfig.FIREBASE_SENDER_ID.isNotBlank()

    /** Initialises Firebase from the build settings (no google-services plugin, no JSON file in the repo). */
    private fun ready(context: Context): Boolean {
        if (!configured()) return false
        if (FirebaseApp.getApps(context).isEmpty()) {
            FirebaseApp.initializeApp(
                context,
                FirebaseOptions.Builder()
                    .setProjectId(BuildConfig.FIREBASE_PROJECT_ID)
                    .setApplicationId(BuildConfig.FIREBASE_APP_ID)
                    .setApiKey(BuildConfig.FIREBASE_API_KEY)
                    .setGcmSenderId(BuildConfig.FIREBASE_SENDER_ID)
                    .build(),
            )
        }
        return true
    }

    /** Called on every start: asks Firebase for the current token and makes sure the server has it. */
    fun start(context: Context) {
        val app = context.applicationContext
        if (!ready(app)) return
        FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
            app.graph.vault.pushToken = token
            Thread { syncToken(app) }.start()
        }
    }

    fun onNewToken(context: Context, token: String) {
        val app = context.applicationContext
        app.graph.vault.pushToken = token
        syncToken(app)
    }

    /** Makes the server's token equal the phone's. Safe to call often: it does nothing when up to date. */
    fun syncToken(context: Context): TokenSyncResult {
        val vault = context.applicationContext.graph.vault
        val enrollment = vault.load() ?: return TokenSyncResult.NOTHING_TO_DO
        if (vault.credentialRevoked) return TokenSyncResult.NOTHING_TO_DO
        val result = TokenSync(VaultTokens(vault), ServerTokens(ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential))).sync()
        if (result == TokenSyncResult.CREDENTIAL_REVOKED) vault.credentialRevoked = true
        return result
    }

    /** Unlink: stop the server notifying this phone, then drop the token locally so it cannot be reused. */
    fun unregister(context: Context) {
        val app = context.applicationContext
        val vault = app.graph.vault
        val enrollment = vault.load()
        if (enrollment != null && !vault.credentialRevoked) {
            TokenSync(VaultTokens(vault), ServerTokens(ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential))).unregister()
        }
        if (ready(app)) runCatching { FirebaseMessaging.getInstance().deleteToken() }
        vault.pushToken = null
        vault.pushConfirmed = null
    }

    fun status(context: Context): Status {
        if (!configured()) return Status.NOT_CONFIGURED
        val vault = context.applicationContext.graph.vault
        val token = vault.pushToken ?: return Status.WAITING_FOR_TOKEN
        return if (vault.pushConfirmed == token) Status.REGISTERED else Status.REGISTRATION_PENDING
    }
}

private class VaultTokens(private val vault: DeviceVault) : TokenStore {
    override var current: String?
        get() = vault.pushToken
        set(value) { vault.pushToken = value }
    override var confirmed: String?
        get() = vault.pushConfirmed
        set(value) { vault.pushConfirmed = value }
}

private class ServerTokens(private val client: ApiClient) : TokenServer {
    override fun put(token: String): PushCall = client.putPushToken(token)
    override fun delete(): PushCall = client.deletePushToken()
}
