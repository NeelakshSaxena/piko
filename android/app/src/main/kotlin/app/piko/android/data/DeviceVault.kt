package app.piko.android.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import app.piko.android.core.SyncMode
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class Enrollment(
    val deviceId: String,
    val familyId: String,
    /** Normalised server base the user entered, e.g. https://piko.example.com (no path). */
    val serverBase: String,
    val credential: String,
    val deviceName: String,
)

/**
 * Pairing state and user choices. The device credential is encrypted with an AES-GCM key held in
 * the Android Keystore (never exported); it is never logged and never part of a backup
 * (the manifest disables backup and data extraction).
 */
class DeviceVault(context: Context, file: String = FILE) {
    private val prefs = context.applicationContext.getSharedPreferences(file, Context.MODE_PRIVATE)

    @Synchronized
    fun save(enrollment: Enrollment) {
        prefs.edit()
            .putString("device_id", enrollment.deviceId)
            .putString("family_id", enrollment.familyId)
            .putString("server_base", enrollment.serverBase)
            .putString("device_name", enrollment.deviceName)
            .putString("credential", encrypt(enrollment.credential))
            .putBoolean("revoked", false)
            .commit()
    }

    @Synchronized
    fun load(): Enrollment? {
        val id = prefs.getString("device_id", null) ?: return null
        val credential = prefs.getString("credential", null)?.let(::decrypt) ?: return null
        return Enrollment(
            deviceId = id,
            familyId = prefs.getString("family_id", "") ?: "",
            serverBase = prefs.getString("server_base", null) ?: return null,
            credential = credential,
            deviceName = prefs.getString("device_name", "") ?: "",
        )
    }

    @Synchronized
    fun clearEnrollment() {
        prefs.edit().remove("device_id").remove("family_id").remove("server_base")
            .remove("device_name").remove("credential").putBoolean("sharing", false)
            .putBoolean("revoked", false).commit()
    }

    /** The server answered 401: this device must be paired again. Remembered across restarts. */
    var credentialRevoked: Boolean
        get() = prefs.getBoolean("revoked", false)
        set(value) { prefs.edit().putBoolean("revoked", value).commit() }

    /** What the user last asked for. Whether sharing is *actually* running is the service's state. */
    var sharingRequested: Boolean
        get() = prefs.getBoolean("sharing", false)
        set(value) { prefs.edit().putBoolean("sharing", value).commit() }

    var mode: SyncMode
        get() = runCatching { SyncMode.valueOf(prefs.getString("mode", null) ?: "") }.getOrDefault(SyncMode.POLLING)
        set(value) { prefs.edit().putString("mode", value.name).commit() }

    var consentAccepted: Boolean
        get() = prefs.getBoolean("consent", false)
        set(value) { prefs.edit().putBoolean("consent", value).commit() }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORM).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(sealed, Base64.NO_WRAP)
    }

    /** Null if the key no longer opens the value (for example after a restore): the user re-pairs. */
    private fun decrypt(stored: String): String? = runCatching {
        val (iv, sealed) = stored.split(":", limit = 2)
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
        String(cipher.doFinal(Base64.decode(sealed, Base64.NO_WRAP)), Charsets.UTF_8)
    }.getOrNull()

    companion object {
        const val FILE = "piko-device"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val KEY_ALIAS = "piko-device-credential"
        private const val TRANSFORM = "AES/GCM/NoPadding"
    }
}
