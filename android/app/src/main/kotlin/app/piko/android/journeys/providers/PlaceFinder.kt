package app.piko.android.journeys.providers

import android.content.Context
import android.location.Address
import android.location.Geocoder
import android.os.Build
import android.os.Handler
import android.os.Looper
import app.piko.android.journeys.domain.GeoPoint
import java.io.IOException

data class PlaceMatch(val label: String, val point: GeoPoint)

/**
 * Turns a place name into candidate map positions using the phone's own geocoder (no key, no Piko server).
 * It is used only when the user taps "Find on map", it sends the name they typed to the phone's map service,
 * and nothing is chosen for them: the user picks one of the matches or none.
 */
object PlaceFinder {
    fun available(): Boolean = Geocoder.isPresent()

    /** [onResult] runs on the main thread; null means the lookup failed (usually no connection). */
    fun find(context: Context, name: String, onResult: (List<PlaceMatch>?) -> Unit) {
        val main = Handler(Looper.getMainLooper())
        val geocoder = Geocoder(context.applicationContext)
        if (Build.VERSION.SDK_INT >= 33) {
            geocoder.getFromLocationName(
                name, MAX_MATCHES,
                object : Geocoder.GeocodeListener {
                    override fun onGeocode(addresses: MutableList<Address>) {
                        val matches = matches(addresses)
                        main.post { onResult(matches) }
                    }

                    override fun onError(errorMessage: String?) {
                        main.post { onResult(null) }
                    }
                },
            )
        } else {
            Thread {
                @Suppress("DEPRECATION")
                val found = try {
                    matches(geocoder.getFromLocationName(name, MAX_MATCHES).orEmpty())
                } catch (_: IOException) {
                    null
                }
                main.post { onResult(found) }
            }.start()
        }
    }

    private fun matches(addresses: List<Address>): List<PlaceMatch> = addresses.mapNotNull { a ->
        if (!a.hasLatitude() || !a.hasLongitude()) return@mapNotNull null
        val label = (0..a.maxAddressLineIndex).mapNotNull { a.getAddressLine(it) }.joinToString(", ").ifBlank { a.featureName ?: return@mapNotNull null }
        PlaceMatch(label.take(120), GeoPoint(a.latitude, a.longitude))
    }

    private const val MAX_MATCHES = 4
}
