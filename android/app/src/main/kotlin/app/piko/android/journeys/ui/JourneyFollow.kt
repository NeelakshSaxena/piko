package app.piko.android.journeys.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.piko.android.collect.hasPreciseLocation
import app.piko.android.core.TimeText
import app.piko.android.journeys.domain.Arrival
import app.piko.android.journeys.domain.ArrivalInference
import app.piko.android.journeys.domain.Estimate
import app.piko.android.journeys.domain.LegInput
import app.piko.android.journeys.domain.LiveLookup
import app.piko.android.journeys.domain.LiveRequest
import app.piko.android.journeys.domain.LiveRules
import app.piko.android.journeys.domain.LiveSuggestion
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.ZoneId
import app.piko.android.journeys.domain.TransportMode
import androidx.compose.material3.OutlinedTextField
import java.time.Instant
import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.Leg
import app.piko.android.journeys.domain.Progress
import app.piko.android.journeys.domain.TrackingSession
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.tracking.TrackerStatus
import app.piko.android.ui.Chip
import app.piko.android.ui.Clay
import app.piko.android.ui.ClayButton
import app.piko.android.ui.ClayCard

/** What the detail screen needs to know about following; all of it comes from stored facts, not guesses. */
internal data class FollowView(
    val session: TrackingSession?,
    val progress: Progress,
    val arrivals: List<Arrival>,
    val status: TrackerStatus,
    val nowMs: Long,
)

internal class FollowActions(
    val start: (detect: Boolean) -> Unit,
    val pause: () -> Unit,
    val resume: () -> Unit,
    val stop: () -> Unit,
    val arrived: (Leg) -> Unit,
    val restartDetection: () -> Unit,
)

/** Per-leg wording for the timeline: arrived (and how we know), where the user is, or still ahead. */
internal fun legNotes(view: FollowView): Map<String, String> {
    if (view.session == null) return emptyMap()
    val notes = HashMap<String, String>()
    view.arrivals.forEach {
        notes[it.legId] = when (it.basis) {
            ArrivalBasis.MANUAL -> "Arrived · confirmed by you"
            ArrivalBasis.DETECTED -> "Arrived · noticed by location (not confirmed by you)"
        }
    }
    view.progress.current?.let {
        notes[it.id] = when {
            !view.session.following -> "Not reached"
            // A clock guess, never a fact: it says so, and only the user (or a checked location reading) records an arrival.
            ArrivalInference.possiblyArrived(it, false, Instant.ofEpochMilli(view.nowMs)) -> "You are on this leg · ${ArrivalInference.WORDING}"
            else -> "You are on this leg"
        }
    }
    return notes
}

@Composable
internal fun FollowSection(journey: Journey, view: FollowView, actions: FollowActions) {
    if (journey.status != JourneyStatus.PLANNED) {
        Text("Mark this journey as planned to follow it.", color = Clay.TextSecondary)
        return
    }
    val session = view.session
    when {
        session != null && session.following -> Following(journey, session, view, actions)
        view.progress.completed -> ClayCard(tint = Clay.Mint) {
            Text("You reached the end of this journey.", fontWeight = FontWeight.Bold)
        }
        else -> StartCard(actions)
    }
}

@Composable
private fun StartCard(actions: FollowActions) {
    val context = LocalContext.current
    var detect by remember { mutableStateOf(false) }
    var denied by remember { mutableStateOf(false) }
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { actions.start(detect) }
    val begin = {
        // Notifications are asked for last and are optional: following works without them, reminders just stay silent.
        if (Build.VERSION.SDK_INT >= 33 &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            actions.start(detect)
        }
    }
    val location = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (context.hasPreciseLocation()) begin() else { denied = true; detect = false }
    }
    ClayCard(tint = Clay.LavenderSoft) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Follow this journey", fontWeight = FontWeight.Bold)
            Text(
                "Piko will remind you before each leg and keep track of which leg you are on. You confirm each arrival, or " +
                    "you can let Piko notice it with your phone's location. Nothing is shared with your family.",
                style = MaterialTheme.typography.bodySmall,
            )
            Row(
                Modifier.toggleable(value = detect, role = Role.Checkbox, onValueChange = { detect = it; denied = false }),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Checkbox(checked = detect, onCheckedChange = null)
                Text(
                    "Use this phone's location to notice arrival (only while following; needs a position picked for the destination)",
                    style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f),
                )
            }
            if (denied) {
                Text(
                    "Precise location was not allowed, so location detection is off. You can still follow the journey and confirm arrivals yourself.",
                    style = MaterialTheme.typography.bodySmall, color = Clay.Caution,
                )
            }
            ClayButton(
                "Start following",
                onClick = {
                    if (detect && !context.hasPreciseLocation()) {
                        location.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
                    } else {
                        begin()
                    }
                },
            )
        }
    }
}

@Composable
private fun Following(journey: Journey, session: TrackingSession, view: FollowView, actions: FollowActions) {
    var confirming by remember { mutableStateOf<Leg?>(null) }
    val paused = session.state == TrackingState.PAUSED
    ClayCard(tint = if (paused) Clay.PeachSoft else Clay.Mint) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip(if (paused) "Paused" else "Following", if (paused) Clay.Peach else Clay.SoftLavender)
            Text(
                view.progress.current?.let { "On the way to ${it.destination}" } ?: "Finished",
                style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
            )
            Text(locationLine(session, view), style = MaterialTheme.typography.bodySmall)
            if (view.progress.current?.mode == TransportMode.FLIGHT) {
                Text(
                    "Flight: everything on this screen is stored on this phone, so it works without a connection. " +
                        "Piko cannot tell that you have landed. Tap \"I've arrived\" when you have; until then the leg stays open.",
                    style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
                )
            }
            if (session.locationDetection && !paused && !view.status.detecting) {
                TextButton(onClick = actions.restartDetection) { Text("Restart location detection") }
            }
        }
    }
    view.progress.current?.let { leg ->
        ClayButton("I've arrived at ${leg.destination}", { confirming = leg })
    }
    if (paused) ClayButton("Resume following", actions.resume, soft = true) else ClayButton("Pause following", actions.pause, soft = true)
    TextButton(onClick = actions.stop, modifier = Modifier.fillMaxWidth().semantics { contentDescription = "Stop following ${journey.title}" }) {
        Text("Stop following", color = Clay.Critical)
    }
    confirming?.let { leg ->
        AlertDialog(
            onDismissRequest = { confirming = null },
            title = { Text("Confirm arrival") },
            text = { Text("Mark that you have arrived at ${leg.destination}? This moves you on to the next leg.") },
            confirmButton = { TextButton(onClick = { confirming = null; actions.arrived(leg) }) { Text("Yes, I've arrived") } },
            dismissButton = { TextButton(onClick = { confirming = null }) { Text("Not yet") } },
        )
    }
}

private fun locationLine(session: TrackingSession, view: FollowView): String = when {
    !session.locationDetection -> "Location is not used. Confirm each arrival yourself."
    session.state == TrackingState.PAUSED -> "Paused: your location is not being read."
    view.status.detecting -> {
        val age = view.status.lastFixAtMs?.let { "last reading ${TimeText.ago(view.nowMs, it)}" } ?: "waiting for a reading"
        "Using your location to notice arrival ($age). It can be wrong; confirm if it is."
    }
    else -> (view.status.note ?: "Location detection is not running.") + " Confirm each arrival yourself."
}

/** Lets the user say what to expect now (for example a delay they heard about). The schedule stays as entered. */
@Composable
internal fun EstimateDialog(
    leg: Leg,
    nowMs: () -> Long,
    lookup: ((LiveRequest) -> LiveLookup)?,
    onDismiss: () -> Unit,
    onSave: (Estimate?) -> Unit,
) {
    var departure by remember { mutableStateOf(LegInput.estimateText(leg.estimate?.departure)) }
    var arrival by remember { mutableStateOf(LegInput.estimateText(leg.estimate?.arrival)) }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Expected time") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "Say what you now expect, for example after hearing about a delay. Piko keeps your schedule as entered and uses this " +
                        "only to judge connections. It does not check any timetable, and it is only as good as what you tell it.",
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    value = departure, onValueChange = { departure = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    label = { Text("Expected departure (${LegInput.EXAMPLE})") }, enabled = leg.departure != null,
                )
                OutlinedTextField(
                    value = arrival, onValueChange = { arrival = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    label = { Text("Expected arrival (${LegInput.EXAMPLE})") }, enabled = leg.arrival != null,
                )
                Text("Times are in each place's own time zone, like the schedule. Leave both empty to remove an update.", style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary)
                if (lookup != null) {
                    LiveCheck(leg, nowMs, lookup) { s ->
                        s.departure?.let { departure = LegInput.estimateText(it) }
                        s.arrival?.let { arrival = LegInput.estimateText(it) }
                        error = null
                    }
                }
                error?.let { Text(it, color = Clay.Critical, fontWeight = FontWeight.SemiBold) }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                when (val r = LegInput.parseEstimate(leg, departure, arrival, Instant.ofEpochMilli(nowMs()))) {
                    is LegInput.EstimateParsed.Error -> error = r.message
                    is LegInput.EstimateParsed.Ok -> onSave(r.estimate)
                }
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/**
 * Optional, on request: asks the user's own server what its flight/train data source says. The answer is shown with
 * its source and is never saved. At most it fills the boxes above, and only when the user taps for it; what they then
 * save is their own expected time.
 */
@Composable
private fun LiveCheck(leg: Leg, nowMs: () -> Long, lookup: (LiveRequest) -> LiveLookup, onUse: (LiveSuggestion) -> Unit) {
    val request = remember(leg) { LiveRules.request(leg) } ?: return
    val scope = rememberCoroutineScope()
    var checking by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<LiveLookup?>(null) }
    val subject = if (request is LiveRequest.Flight) "flight number and date" else "train number"
    if (!LiveRules.inWindow(leg, Instant.ofEpochMilli(nowMs()))) {
        Text(
            "A live check is available from 6 hours before departure until 3 hours after arrival.",
            style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
        )
        return
    }
    Text(
        "Optional: \"Check live status\" sends this $subject to your Piko server, which asks its data source if one was set up. " +
            "Nothing else is sent. The answer is shown below, not saved, and never changes your schedule.",
        style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
    )
    TextButton(
        enabled = !checking,
        onClick = {
            checking = true
            scope.launch {
                result = withContext(Dispatchers.IO) { lookup(request) }
                checking = false
            }
        },
    ) { Text(if (checking) "Checking…" else "Check live status") }
    when (val r = result) {
        null -> Unit
        is LiveLookup.Failed -> Text(LiveRules.explain(r.state), style = MaterialTheme.typography.bodySmall, color = Clay.Caution)
        is LiveLookup.Got -> {
            val suggestion = LiveRules.suggest(leg, r.reading, Instant.ofEpochMilli(nowMs()))
            Column(
                Modifier.semantics { contentDescription = "Live data from ${LiveRules.providerName(r.reading.provider)}, not your own entry" },
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text("From ${LiveRules.providerName(r.reading.provider)} (not your entry)", fontWeight = FontWeight.SemiBold)
                LiveRules.describe(r.reading, ZoneId.systemDefault()).forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                if (suggestion != null) {
                    TextButton(onClick = { onUse(suggestion) }) { Text("Put these times in the boxes above") }
                    Text(
                        "Your schedule plus the reported delay. Review them, then Save to keep them as your own expected time.",
                        style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
                    )
                } else {
                    Text(
                        "This reading is not offered as an expected time (cancelled, not live, out of date, or no delay given). Your own times are unchanged.",
                        style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
                    )
                }
            }
        }
    }
}
