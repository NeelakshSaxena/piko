package app.piko.android.journeys.data

import android.content.Context
import app.piko.android.graph
import app.piko.android.journeys.domain.LiveLookup
import app.piko.android.journeys.domain.LiveRequest
import app.piko.android.journeys.domain.LiveState
import app.piko.android.net.ApiClient
import java.io.IOException

/**
 * One on-demand live check, asked for by the user. The phone talks only to the user's own Piko server; the
 * provider key lives there and never reaches the phone. Nothing is stored and no journey is changed. Blocking:
 * call off the main thread.
 */
object JourneyLive {
    fun check(context: Context, request: LiveRequest): LiveLookup {
        val graph = context.graph
        val enrollment = graph.vault.load() ?: return LiveLookup.Failed(LiveState.NOT_PAIRED)
        if (graph.vault.credentialRevoked) return LiveLookup.Failed(LiveState.NOT_PAIRED)
        val client = ApiClient(enrollment.serverBase, enrollment.deviceId, enrollment.credential)
        return try {
            val reply = when (request) {
                is LiveRequest.Flight -> client.liveFlight(request.code, request.day.toString())
                is LiveRequest.Train -> client.liveTrain(request.number)
            }
            LiveCodec.parse(reply.status, reply.body)
        } catch (_: IOException) {
            LiveLookup.Failed(LiveState.OFFLINE)
        }
    }
}
