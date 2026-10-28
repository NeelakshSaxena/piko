package app.piko.android.journeys.tracking

import android.content.Context
import app.piko.android.graph
import app.piko.android.journeys.data.JourneySync
import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.ConnectionPlanner
import app.piko.android.journeys.domain.Estimate
import app.piko.android.journeys.domain.Risk
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingResult
import java.time.Instant

/**
 * The user-facing and service-facing operations on a followed journey: the controller decides, then the
 * side effects follow (reminders, the location service, observers, backup). Blocking: call off the main thread.
 */
object JourneyActions {
    private fun controller(context: Context) = context.graph.let { g -> TrackingController(g.journeys, g.journeys, { g.journeyPrefs.backupEnabled }) }

    private fun now(context: Context): Instant = Instant.ofEpochMilli(context.graph.clock.nowMs())

    fun start(context: Context, journeyId: String, locationDetection: Boolean): TrackingResult =
        controller(context).start(journeyId, now(context), locationDetection).also { afterChange(context, journeyId, it) }

    fun pause(context: Context, journeyId: String): TrackingResult =
        controller(context).pause(journeyId, now(context)).also { afterChange(context, journeyId, it) }

    fun resume(context: Context, journeyId: String): TrackingResult =
        controller(context).resume(journeyId, now(context)).also { afterChange(context, journeyId, it) }

    fun stop(context: Context, journeyId: String): TrackingResult =
        controller(context).stop(journeyId, now(context)).also { afterChange(context, journeyId, it) }

    fun confirmArrival(context: Context, journeyId: String, legId: String, basis: ArrivalBasis): TrackingResult =
        controller(context).confirmArrival(journeyId, legId, now(context), basis).also { afterChange(context, journeyId, it) }

    /** Saves or clears the user's expected times for a leg, then tells them if a connection now looks tight or at risk. */
    fun setEstimate(context: Context, journeyId: String, legId: String, estimate: Estimate?) {
        context.graph.journeys.setEstimate(journeyId, legId, estimate)
        JourneyReminders.replan(context, journeyId) // an arrival check moves with the expected arrival
        warnAboutConnections(context, journeyId)
    }

    private fun warnAboutConnections(context: Context, journeyId: String) {
        val graph = context.graph
        val journey = graph.journeys.get(journeyId) ?: return
        if (graph.journeys.session(journeyId)?.following != true) return // alerts only for a journey being followed
        val progress = TrackingController(graph.journeys, graph.journeys).progress(journey)
        for (c in ConnectionPlanner.assess(journey, progress, now(context))) {
            if (c.risk != Risk.TIGHT && c.risk != Risk.AT_RISK) continue
            val place = journey.legs.firstOrNull { it.id == c.fromLegId }?.destination ?: continue
            val text = if (c.risk == Risk.AT_RISK) {
                "Your connection after $place may not work out, going by the times you gave. Review your next leg."
            } else {
                "Your connection after $place may be tight, going by the times you gave. Review your next leg."
            }
            JourneyNotifier.notifyOnce(context, "risk:$journeyId:${c.fromLegId}:${c.toLegId}:${c.risk}", journey.title, text)
        }
    }

    /** Re-applies the stored state (after a process start, or a restart the user asked for). */
    fun reapply(context: Context) {
        val s = context.graph.journeys.followed()
        if (s != null) JourneyReminders.replan(context, s.journeyId)
        JourneyTrackingService.sync(context)
        JourneyRuntime.ensure(context)
        JourneyObservations.reconcile(context)
    }

    private fun afterChange(context: Context, journeyId: String, result: TrackingResult) {
        if (result !is TrackingResult.Ok) return
        JourneyReminders.replan(context, journeyId)
        JourneyTrackingService.sync(context)
        JourneyRuntime.ensure(context)
        JourneyObservations.reconcile(context)
        JourneySync.request(context)
    }
}
