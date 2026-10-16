package app.piko.android.collect

import android.Manifest
import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.location.LocationRequest
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.BatteryManager
import androidx.core.content.ContextCompat
import app.piko.android.core.ModePlan

fun Context.hasLocationPermission(): Boolean =
    ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

fun Context.hasPreciseLocation(): Boolean =
    ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

/**
 * Location through the platform's fused provider (Android 12+, no Play Services dependency).
 * The system decides when to power the GPS: POLLING asks for balanced power with a minimum
 * movement, so the GPS is not woken every minute merely because uploads are checked every minute.
 */
class LocationCollector(private val context: Context, private val onFix: (Location) -> Unit) {
    private val manager = context.getSystemService(LocationManager::class.java)
    private val listener = LocationListener { onFix(it) }
    private var active = false

    @SuppressLint("MissingPermission") // checked by hasLocationPermission() before every call
    fun start(plan: ModePlan): Boolean {
        stop()
        if (!context.hasLocationPermission()) return false
        val provider = if (manager.hasProvider(LocationManager.FUSED_PROVIDER)) {
            LocationManager.FUSED_PROVIDER
        } else {
            listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER).firstOrNull(manager::hasProvider)
                ?: return false
        }
        val request = LocationRequest.Builder(plan.locationIntervalMs)
            .setMinUpdateDistanceMeters(plan.minDistanceMeters)
            .setQuality(
                if (plan.highAccuracy) LocationRequest.QUALITY_HIGH_ACCURACY else LocationRequest.QUALITY_BALANCED_POWER_ACCURACY,
            )
            .build()
        manager.requestLocationUpdates(provider, request, ContextCompat.getMainExecutor(context), listener)
        active = true
        // A recent cached fix is valid evidence; it keeps its own capture time (shown honestly as older).
        manager.getLastKnownLocation(provider)?.let(onFix)
        return true
    }

    fun stop() {
        if (active) manager.removeUpdates(listener)
        active = false
    }
}

class BatteryCollector(private val context: Context, private val onReading: (percent: Int, charging: Boolean) -> Unit) {
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) = read(intent)
    }

    fun start() {
        // The sticky broadcast gives the current value immediately; later changes arrive as pushes
        // (no polling of the battery).
        context.registerReceiver(receiver, IntentFilter(Intent.ACTION_BATTERY_CHANGED))?.let(::read)
    }

    fun stop() {
        runCatching { context.unregisterReceiver(receiver) }
    }

    private fun read(intent: Intent) {
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
        onReading((level * 100f / scale).toInt().coerceIn(0, 100), charging)
    }
}

/** Reports the default network's type and whether it is validated (really has internet). */
class ConnectivityMonitor(
    context: Context,
    private val onChange: (networkType: String, online: Boolean) -> Unit,
) {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
            onChange(typeOf(caps), caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
        }

        override fun onLost(network: Network) = onChange("none", false)
    }

    fun start() {
        manager.registerDefaultNetworkCallback(callback)
        // A device with no network at start never receives a callback; say so explicitly.
        if (manager.activeNetwork == null) onChange("none", false)
    }

    fun stop() {
        runCatching { manager.unregisterNetworkCallback(callback) }
    }

    private fun typeOf(caps: NetworkCapabilities): String = when {
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
        else -> "other"
    }
}
