package app.piko.android.journeys.data

import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyEvent
import app.piko.android.journeys.domain.JourneyTransport
import app.piko.android.journeys.domain.SyncCall
import app.piko.android.net.ApiClient
import java.io.IOException

class ApiJourneyTransport(private val client: ApiClient) : JourneyTransport {
    override fun put(journey: Journey): SyncCall = call { client.putJourney(journey.id, JourneyCodec.put(journey)) }

    override fun delete(id: String): SyncCall = call { client.deleteJourney(id) }

    override fun events(journeyId: String, events: List<JourneyEvent>): SyncCall =
        call { client.postJourneyEvents(journeyId, JourneyCodec.events(java.util.UUID.randomUUID().toString(), events)) }

    private fun call(request: () -> ApiClient.StatusReply): SyncCall = try {
        val r = request()
        when {
            r.status in 200..204 -> SyncCall.Ok // 202 for an events batch
            r.status == 401 -> SyncCall.Unauthorized
            r.status == 429 -> SyncCall.Retry(r.retryAfter)
            r.status == 408 || r.status == 413 || r.status >= 500 -> SyncCall.Retry()
            else -> SyncCall.Refused(r.status)
        }
    } catch (_: IOException) {
        SyncCall.Retry()
    }
}
