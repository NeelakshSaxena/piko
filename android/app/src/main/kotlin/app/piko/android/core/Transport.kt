package app.piko.android.core

sealed interface SendResult {
    /** 202: the server durably accepted the listed ids; everything else is NOT acknowledged. */
    data class Ack(
        val accepted: Set<String>,
        val duplicates: Set<String>,
        val rejected: Map<String, String>,
    ) : SendResult

    /** No usable response (timeout, reset, offline). The server may or may not have stored it. */
    data class Network(val cause: String) : SendResult

    data class RateLimited(val retryAfterSeconds: Long?) : SendResult

    /** 5xx or an unreadable success body: the batch is not acknowledged. */
    data class ServerError(val status: Int) : SendResult

    /** 401: the credential was revoked or the device unenrolled. Sending must stop. */
    data object Unauthorized : SendResult

    /** Other 4xx: retrying the same request cannot succeed. */
    data class Refused(val status: Int, val code: String?) : SendResult
}

fun interface Transport {
    fun send(batch: Batch): SendResult
}
