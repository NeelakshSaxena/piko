package app.piko.android.core

/**
 * Push (ADR-023), pure Kotlin so it is testable on the JVM.
 *
 * A push is a trigger, never the source of truth: it carries a type and an id and nothing else. The phone
 * treats it as "go and ask the server", so a forged, duplicated, delayed or reordered push can at worst cause
 * an extra refresh; it cannot create an incident, a message or a status.
 */
enum class PushType(val wire: String) {
    SOS_CREATED("sos_created"),
    SOS_UPDATE("sos_update"),
    MESSAGE("message"),
}

data class PushEvent(val type: PushType, val id: String)

object PushPayload {
    private val UUID = Regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    /** Strict: unknown versions or types, and anything that is not a UUID id, are ignored (null). */
    fun parse(data: Map<String, String>): PushEvent? {
        if (data["v"] != "1") return null
        val type = PushType.entries.firstOrNull { it.wire == data["type"] } ?: return null
        val id = data["id"]?.takeIf { UUID.matches(it) } ?: return null
        return PushEvent(type, id.lowercase())
    }
}

/** The FCM token as the phone and the server know it. */
interface TokenStore {
    /** The latest token Firebase gave this install, or null before the first one. */
    var current: String?

    /** The token the server last confirmed it stored for this device. */
    var confirmed: String?
}

sealed interface PushCall {
    data object Ok : PushCall

    /** Network failure, 429 or 5xx: try again later. */
    data object Retry : PushCall

    /** 401: the credential is no longer accepted (revoked device). Never retried. */
    data object Unauthorized : PushCall

    /** Any other refusal: this token will not be accepted. */
    data class Refused(val status: Int) : PushCall
}

interface TokenServer {
    fun put(token: String): PushCall
    fun delete(): PushCall
}

enum class TokenSyncResult { NOTHING_TO_DO, UP_TO_DATE, REGISTERED, RETRY_LATER, REJECTED, CREDENTIAL_REVOKED }

/**
 * Keeps the server's copy of the token equal to the phone's. Rotation is just a new `current`: the next
 * [sync] replaces the server's value. Nothing here ever blocks the app: a failure leaves the token pending.
 */
class TokenSync(private val store: TokenStore, private val server: TokenServer) {
    fun onNewToken(token: String) {
        if (token != store.current) store.current = token
    }

    fun sync(): TokenSyncResult {
        val token = store.current ?: return TokenSyncResult.NOTHING_TO_DO
        if (token == store.confirmed) return TokenSyncResult.UP_TO_DATE
        return when (server.put(token)) {
            PushCall.Ok -> { store.confirmed = token; TokenSyncResult.REGISTERED }
            PushCall.Retry -> TokenSyncResult.RETRY_LATER
            PushCall.Unauthorized -> TokenSyncResult.CREDENTIAL_REVOKED
            is PushCall.Refused -> TokenSyncResult.REJECTED
        }
    }

    /** Logout, unlink or revocation: tell the server to stop (best effort) and forget the confirmation. */
    fun unregister(): PushCall {
        val result = server.delete()
        store.confirmed = null
        return result
    }
}
