package app.piko.android.core

import java.net.URI

/**
 * The only place a server address is accepted. HTTPS is required; plain HTTP is allowed only when
 * [allowLoopbackHttp] is set (debug builds) and only for the emulator's host loopback and
 * localhost. Credentials in the URL, query strings, fragments and other paths are rejected.
 */
object ServerUrl {
    private val LOOPBACK_HOSTS = setOf("10.0.2.2", "localhost", "127.0.0.1")

    /** Returns the normalised base (no trailing slash), or null if it is not acceptable. */
    fun parse(raw: String, allowLoopbackHttp: Boolean): String? {
        val text = raw.trim()
        if (text.isEmpty() || text.length > 200) return null
        val uri = try {
            URI(text)
        } catch (_: Exception) {
            return null
        }
        val host = uri.host?.lowercase() ?: return null
        if (uri.userInfo != null || uri.rawQuery != null || uri.rawFragment != null) return null
        if (!uri.rawPath.isNullOrEmpty() && uri.rawPath != "/") return null
        val scheme = uri.scheme?.lowercase()
        val ok = scheme == "https" || (scheme == "http" && allowLoopbackHttp && host in LOOPBACK_HOSTS)
        if (!ok) return null
        if (uri.port != -1 && uri.port !in 1..65535) return null
        val port = if (uri.port == -1) "" else ":${uri.port}"
        return "$scheme://$host$port"
    }

    fun apiBase(base: String): String = "$base/api/v1"
}
