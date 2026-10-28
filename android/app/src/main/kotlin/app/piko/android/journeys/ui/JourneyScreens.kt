package app.piko.android.journeys.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.piko.android.journeys.data.JourneyPrefs
import app.piko.android.journeys.data.SqliteJourneyStore
import app.piko.android.journeys.domain.Arrival
import app.piko.android.journeys.data.JourneyLive
import app.piko.android.journeys.domain.Connection
import app.piko.android.journeys.domain.ConnectionPlanner
import app.piko.android.journeys.domain.LiveLookup
import app.piko.android.journeys.domain.LiveRequest
import app.piko.android.journeys.domain.Estimate
import app.piko.android.journeys.domain.Risk
import app.piko.android.journeys.domain.TimeBasis
import app.piko.android.journeys.domain.TrackingController
import app.piko.android.journeys.domain.TrackingResult
import app.piko.android.journeys.domain.TrackingSession
import app.piko.android.journeys.tracking.JourneyActions
import app.piko.android.journeys.tracking.JourneyRuntime
import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyRules
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.Leg
import app.piko.android.ui.Chip
import app.piko.android.ui.Clay
import app.piko.android.ui.ClayButton
import app.piko.android.ui.ClayCard
import app.piko.android.ui.Label
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.format.DateTimeFormatter
import java.util.Locale

private sealed interface Route {
    data object List : Route
    data class Detail(val id: String) : Route
    data class Edit(val id: String?) : Route
}

/**
 * The Journeys feature: list, detail and editor, kept apart from the rest of the app's screens.
 * Everything is stored on this phone; nothing is sent anywhere.
 */
@Composable
fun JourneysHost(store: SqliteJourneyStore, prefs: JourneyPrefs, nowMs: () -> Long, onChanged: () -> Unit, onExit: () -> Unit) {
    val context = LocalContext.current
    var journeys by remember { mutableStateOf<List<Journey>?>(null) }
    var sessions by remember { mutableStateOf<Map<String, TrackingSession>>(emptyMap()) }
    var arrivals by remember { mutableStateOf<Map<String, List<Arrival>>>(emptyMap()) }
    val trackerStatus by JourneyRuntime.status.collectAsState()
    var route by remember { mutableStateOf<Route>(Route.List) }
    var failure by remember { mutableStateOf<String?>(null) }
    var backup by remember { mutableStateOf(prefs.backupEnabled) }
    var waiting by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    suspend fun reload() {
        withContext(Dispatchers.IO) {
            val all = store.list()
            journeys = all
            sessions = all.mapNotNull { j -> store.session(j.id) }.associateBy { it.journeyId }
            arrivals = all.associate { it.id to store.arrivals(it.id) }
            waiting = store.dirty().size
        }
    }
    LaunchedEffect(Unit) { reload() }
    // While a journey is followed the location service or the user may change it elsewhere; keep the screen true to the store.
    val following = sessions.values.any { it.following }
    LaunchedEffect(following) {
        while (following) {
            kotlinx.coroutines.delay(3_000)
            reload()
        }
    }

    /** Runs a tracking action off the main thread, shows a refusal in plain words, and refreshes. */
    fun act(block: () -> TrackingResult) {
        scope.launch {
            val result = withContext(Dispatchers.IO) { block() }
            failure = (result as? TrackingResult.Refused)?.reason
            reload()
        }
    }

    BackHandler {
        route = when (val r = route) {
            Route.List -> { onExit(); Route.List }
            is Route.Detail -> Route.List
            is Route.Edit -> if (r.id != null) Route.Detail(r.id) else Route.List
        }
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        failure?.let { Text(it, color = Clay.Critical, fontWeight = FontWeight.SemiBold) }
        when (val r = route) {
            Route.List -> JourneyListScreen(
                journeys = journeys,
                onBack = onExit,
                onOpen = { route = Route.Detail(it) },
                onNew = { route = Route.Edit(null) },
                backup = backup,
                waiting = waiting,
                onBackup = { on ->
                    backup = on
                    prefs.backupEnabled = on
                    // Events exist only to be backed up: turning backup off discards the ones still waiting.
                    if (!on) scope.launch(Dispatchers.IO) { store.pruneEvents(java.time.Instant.ofEpochMilli(nowMs()).plusSeconds(86_400)) }
                    onChanged()
                },
            )
            is Route.Detail -> {
                val journey = journeys?.firstOrNull { it.id == r.id }
                if (journey == null) {
                    // Deleted, or the list is still loading: go back to the list rather than render a blank page.
                    if (journeys != null) LaunchedEffect(Unit) { route = Route.List }
                } else {
                    JourneyDetailScreen(
                        journey = journey,
                        connections = if (journey.status == JourneyStatus.PLANNED) {
                            ConnectionPlanner.assess(journey, TrackingController(store, store).progress(journey), java.time.Instant.ofEpochMilli(nowMs()))
                                .associateBy { it.toLegId }
                        } else {
                            emptyMap()
                        },
                        nowMs = nowMs,
                        onEstimate = { leg, estimate ->
                            scope.launch {
                                withContext(Dispatchers.IO) { JourneyActions.setEstimate(context, journey.id, leg.id, estimate) }
                                reload()
                            }
                        },
                        lookup = { request -> JourneyLive.check(context, request) },
                        follow = FollowView(
                            session = sessions[journey.id],
                            progress = TrackingController(store, store).progress(journey),
                            arrivals = arrivals[journey.id].orEmpty(),
                            status = trackerStatus,
                            nowMs = nowMs(),
                        ),
                        actions = FollowActions(
                            start = { detect -> act { JourneyActions.start(context, journey.id, detect) } },
                            pause = { act { JourneyActions.pause(context, journey.id) } },
                            resume = { act { JourneyActions.resume(context, journey.id) } },
                            stop = { act { JourneyActions.stop(context, journey.id) } },
                            arrived = { leg -> act { JourneyActions.confirmArrival(context, journey.id, leg.id, ArrivalBasis.MANUAL) } },
                            restartDetection = { scope.launch(Dispatchers.IO) { JourneyActions.reapply(context) } },
                        ),
                        onBack = { route = Route.List },
                        onEdit = { route = Route.Edit(journey.id) },
                        onDelete = {
                            scope.launch {
                                failure = runCatching { withContext(Dispatchers.IO) { store.delete(journey.id) } }
                                    .exceptionOrNull()?.let { "The journey could not be deleted." }
                                onChanged()
                                reload()
                                route = Route.List
                            }
                        },
                    )
                }
            }
            is Route.Edit -> {
                val existing = r.id?.let { id -> journeys?.firstOrNull { it.id == id } }
                JourneyEditorScreen(
                    existing = existing,
                    nowMs = nowMs,
                    onCancel = { route = if (existing != null) Route.Detail(existing.id) else Route.List },
                    onSave = { saved ->
                        scope.launch {
                            val error = runCatching { withContext(Dispatchers.IO) { store.save(saved) } }.exceptionOrNull()
                            failure = error?.let { "The journey could not be saved on this phone." }
                            if (error == null) {
                                onChanged()
                                reload()
                                route = Route.Detail(saved.id)
                            }
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun JourneyListScreen(
    journeys: List<Journey>?,
    onBack: () -> Unit,
    onOpen: (String) -> Unit,
    onNew: () -> Unit,
    backup: Boolean,
    waiting: Int,
    onBackup: (Boolean) -> Unit,
) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text("Journeys", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        TextButton(onClick = onBack) { Text("Back") }
    }
    Text(
        "Plan a trip leg by leg. Journeys are saved on this phone and work without a connection. Your family cannot see them.",
        color = Clay.TextSecondary,
    )
    ClayButton("New journey", onNew)
    ClayCard(tint = Clay.Sky) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            // The whole row is the switch, so a screen reader announces the label with the state.
            Row(
                Modifier.fillMaxWidth().toggleable(value = backup, role = Role.Switch, onValueChange = onBackup),
                horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Back up to my Piko server", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Switch(checked = backup, onCheckedChange = null)
            }
            Text(
                if (backup) {
                    "On. Your journeys (places, times, flight and train numbers) are copied to the server this phone is linked to. " +
                        "Only this phone can read them back; your family cannot. Deleting a journey here also deletes its copy."
                } else {
                    "Off. Your journeys stay on this phone, except that tapping \"Check live status\" sends one flight or train number to your server. Turn this on to keep a copy on your own Piko server."
                },
                style = MaterialTheme.typography.bodySmall,
            )
            if (backup) {
                Text(
                    if (waiting == 0) "Everything is backed up." else "$waiting waiting to be backed up (needs a connection).",
                    style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
                )
            }
        }
    }
    when {
        journeys == null -> Text("Loading…", color = Clay.TextSecondary)
        journeys.isEmpty() -> ClayCard(tint = Clay.LavenderSoft) {
            Text("No journeys yet. Add one to see its legs in order.")
        }
        else -> journeys.forEach { journey ->
            ClayCard(modifier = Modifier.clickable(onClickLabel = "Open ${journey.title}") { onOpen(journey.id) }) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text(journey.title, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        StatusChip(journey.status)
                    }
                    Text(routeSummary(journey), style = MaterialTheme.typography.bodyMedium, color = Clay.TextSecondary)
                    journey.legs.firstOrNull()?.departure?.let {
                        Text("Starts ${formatTime(it)}", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun JourneyDetailScreen(
    journey: Journey,
    connections: Map<String, Connection>,
    nowMs: () -> Long,
    onEstimate: (Leg, Estimate?) -> Unit,
    lookup: ((LiveRequest) -> LiveLookup)?,
    follow: FollowView,
    actions: FollowActions,
    onBack: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    val busy = follow.session?.following == true
    var confirmDelete by remember { mutableStateOf(false) }
    var updating by remember { mutableStateOf<Leg?>(null) }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(journey.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        TextButton(onClick = onBack) { Text("Back") }
    }
    StatusChip(journey.status)
    if (journey.status == JourneyStatus.DRAFT) {
        Text("This is a draft. Times may be missing or inconsistent.", color = Clay.Caution)
    }
    if (journey.legs.isEmpty()) {
        ClayCard(tint = Clay.LavenderSoft) { Text("This journey has no legs yet.") }
    } else {
        Timeline(journey.legs, legNotes(follow), connections) { _, leg ->
            val reached = follow.arrivals.any { it.legId == leg.id }
            if (journey.status == JourneyStatus.PLANNED && !reached) {
                TextButton(onClick = { updating = leg }, modifier = Modifier.semantics { contentDescription = "Update the expected time of ${leg.origin} to ${leg.destination}" }) {
                    Text(if (leg.estimate == null) "Update expected time" else "Change expected time")
                }
            }
        }
    }
    FollowSection(journey, follow, actions)
    if (busy) {
        Text("Stop following to edit or delete this journey.", style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary)
    } else {
        ClayButton("Edit journey", onEdit)
        ClayButton("Delete journey", { confirmDelete = true }, soft = true)
    }
    Text(
        "Times are the ones you entered, shown in the time zone you chose for each leg. Piko does not check them against any timetable unless you ask for a live check.",
        style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
    )
    updating?.let { leg -> EstimateDialog(leg, nowMs, lookup, onDismiss = { updating = null }, onSave = { updating = null; onEstimate(leg, it) }) }
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete this journey?") },
            text = { Text("“${journey.title}” and its ${journey.legs.size} leg(s) will be removed from this phone.") },
            confirmButton = { TextButton(onClick = { confirmDelete = false; onDelete() }) { Text("Delete") } },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Keep") } },
        )
    }
}

/** Legs in trip order with the gap between them. [actions] adds per-leg controls (the editor uses it). */
@Composable
internal fun Timeline(
    legs: List<Leg>,
    notes: Map<String, String> = emptyMap(),
    connections: Map<String, Connection> = emptyMap(),
    actions: @Composable ColumnScope.(Int, Leg) -> Unit,
) {
    legs.forEachIndexed { index, leg ->
        if (index > 0) {
            val gap = JourneyRules.gapBetween(legs[index - 1], leg)
            Text(
                when {
                    gap == null -> "Gap unknown (a time is missing)"
                    gap.isNegative -> "Leg ${index + 1} departs before leg $index arrives"
                    else -> "${durationText(gap)} between legs"
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (gap != null && gap.isNegative) Clay.Critical else Clay.TextSecondary,
                modifier = Modifier.padding(start = 12.dp),
            )
            connections[leg.id]?.let { ConnectionNote(it) }
        }
        ClayCard(tint = Clay.Surface) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Label("Leg ${index + 1} · ${leg.mode.label}" + (leg.serviceNumber?.let { " $it" } ?: ""))
                notes[leg.id]?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = Clay.PrimaryDeep, fontWeight = FontWeight.SemiBold) }
                Text("${leg.origin} → ${leg.destination}", fontWeight = FontWeight.Bold)
                Text("Departs ${leg.departure?.let(::formatTime) ?: "time not set"}", style = MaterialTheme.typography.bodyMedium)
                Text("Arrives ${leg.arrival?.let(::formatTime) ?: "time not set"}", style = MaterialTheme.typography.bodyMedium)
                leg.estimate?.let { e ->
                    val parts = listOfNotNull(e.departure?.let { "leave ${formatTime(it)}" }, e.arrival?.let { "arrive ${formatTime(it)}" })
                    Text(
                        "Your update: ${parts.joinToString(", ")} (you said so ${durationText(Duration.between(e.enteredAt, java.time.Instant.now()).coerceAtLeast(Duration.ZERO))} ago)",
                        style = MaterialTheme.typography.bodySmall, color = Clay.Caution,
                    )
                }
                val dep = leg.departure
                val arr = leg.arrival
                if (dep != null && arr != null && arr.toInstant().isAfter(dep.toInstant())) {
                    Text(
                        "Takes ${durationText(Duration.between(dep.toInstant(), arr.toInstant()))}",
                        style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
                    )
                }
                actions(index, leg)
            }
        }
    }
}

@Composable
internal fun StatusChip(status: JourneyStatus) {
    when (status) {
        JourneyStatus.DRAFT -> Chip("Draft", Clay.PeachSoft)
        JourneyStatus.PLANNED -> Chip("Planned", Clay.Mint)
    }
}

private fun routeSummary(journey: Journey): String {
    val first = journey.legs.firstOrNull() ?: return "No legs yet"
    val last = journey.legs.last()
    val n = journey.legs.size
    return "${first.origin} → ${last.destination} · $n ${if (n == 1) "leg" else "legs"}"
}

// Built per call so a language change while the app is open is honoured (a static formatter would keep the old one).
private fun formatTime(time: java.time.ZonedDateTime): String =
    time.format(DateTimeFormatter.ofPattern("EEE d MMM, HH:mm z", Locale.getDefault()))

internal fun durationText(d: Duration): String {
    val hours = d.toHours()
    val minutes = d.toMinutes() % 60
    return when {
        hours == 0L -> "${minutes}m"
        minutes == 0L -> "${hours}h"
        else -> "${hours}h ${minutes}m"
    }
}

/** The verdict is written out, not just coloured, and always says what it is based on. */
@Composable
private fun ConnectionNote(c: Connection) {
    val (label, tint) = when (c.risk) {
        Risk.COMFORTABLE -> "Comfortable" to Clay.Mint
        Risk.TIGHT -> "Tight" to Clay.Peach
        Risk.AT_RISK -> "At risk" to Clay.CriticalSoft
        Risk.UNKNOWN -> "Unknown" to Clay.Well
    }
    Column(Modifier.padding(start = 12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Chip("Connection: $label", tint)
        Text(c.explanation, style = MaterialTheme.typography.bodySmall)
        if (c.basis == TimeBasis.SCHEDULE) {
            Text("No live flight or train data is used; this is only your entered schedule.", style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary)
        }
    }
}
