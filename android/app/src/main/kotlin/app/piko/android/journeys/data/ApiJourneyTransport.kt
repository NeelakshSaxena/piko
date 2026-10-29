package app.piko.android.journeys.data

import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyEvent
import app.piko.android.journeys.domain.JourneyTransport
import app.piko.android.journeys.domain.SyncCall
import app.piko.android.net.ApiClient
import java.io.IOException

class ApiJourneyTransport(private val client: ApiClient) : JourneyTransport {
    override fun put(journey: Journey, revision: Long): SyncCall = call(
        { client.putJourney(journey.id, JourneyCodec.put(journey, revision)) },
    ) { reply -> answerToPut(reply.body, revision) }

    override fun delete(id: String): SyncCall = call({ client.deleteJourney(id) })

    override fun events(journeyId: String, events: List<JourneyEvent>): SyncCall =
        call({ client.postJourneyEvents(journeyId, JourneyCodec.events(java.util.UUID.randomUUID().toString(), events)) })

    private fun call(request: () -> ApiClient.StatusReply, onSuccess: (ApiClient.StatusReply) -> SyncCall = { SyncCall.Ok }): SyncCall = try {
        val r = request()
        when {
            r.status in 200..204 -> onSuccess(r) // 202 for an events batch
            r.status == 401 -> SyncCall.Unauthorized
            r.status == 429 -> SyncCall.Retry(r.retryAfter)
            r.status == 408 || r.status == 413 || r.status >= 500 -> SyncCall.Retry()
            else -> SyncCall.Refused(r.status)
        }
    } catch (_: IOException) {
        SyncCall.Retry()
    }

    companion object {
        /**
         * A 200 can mean "stored" or "I already hold this revision or a newer one". Only the first two are success: a
         * newer server revision means the upload changed nothing, which must never be reported as backed up.
         */
        fun answerToPut(body: String, sent: Long): SyncCall {
            val (applied, held) = JourneyCodec.putAnswer(body) ?: return SyncCall.Refused(200)
            return when {
                applied || held == sent -> SyncCall.Ok
                held > sent -> SyncCall.Stale(held)
                else -> SyncCall.Refused(200) // the server claims an older revision than the one it just refused
            }
        }
    }
}
