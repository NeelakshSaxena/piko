package app.piko.android.journeys.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import app.piko.android.journeys.domain.GeoPoint
import app.piko.android.journeys.providers.PlaceFinder
import app.piko.android.journeys.providers.PlaceMatch
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyRules
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.Leg
import app.piko.android.journeys.domain.LegInput
import app.piko.android.journeys.domain.TransportMode
import app.piko.android.ui.Clay
import app.piko.android.ui.ClayButton
import java.time.Instant
import java.time.ZoneId
import java.util.UUID

/** Edits a copy; nothing is stored until a save button is pressed. [existing] null starts a new journey. */
@Composable
internal fun JourneyEditorScreen(existing: Journey?, nowMs: () -> Long, onCancel: () -> Unit, onSave: (Journey) -> Unit) {
    var title by remember { mutableStateOf(existing?.title.orEmpty()) }
    var legs by remember { mutableStateOf(existing?.legs.orEmpty()) }
    // -1: dialog closed; legs.size: a new leg; otherwise the leg being edited.
    var editing by remember { mutableIntStateOf(-1) }

    fun build(status: JourneyStatus): Journey {
        val now = Instant.ofEpochMilli(nowMs())
        return Journey(
            id = existing?.id ?: UUID.randomUUID().toString(),
            title = title.trim(),
            status = status,
            legs = legs,
            createdAt = existing?.createdAt ?: now,
            updatedAt = now,
        )
    }

    val draft = build(JourneyStatus.DRAFT)
    val saveProblems = JourneyRules.problemsForSaving(draft)
    val planProblems = JourneyRules.problemsForPlanning(draft)

    Text(
        if (existing == null) "New journey" else "Edit journey",
        style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
    )
    OutlinedTextField(
        value = title,
        onValueChange = { title = it },
        label = { Text("Title") },
        singleLine = true,
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        modifier = Modifier.fillMaxWidth(),
    )

    Timeline(legs) { index, leg ->
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            TextButton(
                onClick = { legs = JourneyRules.move(legs, index, index - 1) },
                enabled = index > 0,
                modifier = Modifier.semantics { contentDescription = "Move leg ${index + 1} earlier" },
            ) { Text("Earlier") }
            TextButton(
                onClick = { legs = JourneyRules.move(legs, index, index + 1) },
                enabled = index < legs.size - 1,
                modifier = Modifier.semantics { contentDescription = "Move leg ${index + 1} later" },
            ) { Text("Later") }
            TextButton(
                onClick = { editing = index },
                modifier = Modifier.semantics { contentDescription = "Edit leg ${index + 1}" },
            ) { Text("Edit") }
            TextButton(
                onClick = { legs = legs.filterNot { it.id == leg.id } },
                modifier = Modifier.semantics { contentDescription = "Remove leg ${index + 1}" },
            ) { Text("Remove", color = Clay.Critical) }
        }
    }
    ClayButton(
        "Add a leg",
        onClick = { editing = legs.size },
        soft = true,
        enabled = legs.size < JourneyRules.MAX_LEGS,
    )

    if (planProblems.isNotEmpty()) {
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("To mark this journey as planned:", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
            planProblems.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary) }
        }
    }
    ClayButton("Save as planned", { onSave(build(JourneyStatus.PLANNED)) }, enabled = planProblems.isEmpty())
    ClayButton("Save as draft", { onSave(draft) }, soft = true, enabled = saveProblems.isEmpty())
    TextButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text("Cancel") }

    if (editing >= 0) {
        val index = editing
        val previous = if (index == legs.size) legs.lastOrNull() else legs.getOrNull(index - 1)
        // A new leg gets a fresh id; an edited one keeps its own.
        val legId = remember(index) { legs.getOrNull(index)?.id ?: UUID.randomUUID().toString() }
        LegDialog(
            legId = legId,
            previous = legs.getOrNull(index),
            initial = legs.getOrNull(index)?.let { LegInput.of(it, defaultZone()) } ?: blankLeg(previous),
            onDismiss = { editing = -1 },
            onDone = { leg ->
                legs = if (index < legs.size) legs.toMutableList().also { it[index] = leg } else legs + leg
                editing = -1
            },
        )
    }
}

private fun defaultZone(): String = ZoneId.systemDefault().id

/** A new leg starts where the previous one ended, in the zone it ended in. */
private fun blankLeg(previous: Leg?): LegInput = LegInput(
    mode = TransportMode.TRAIN,
    serviceNumber = "",
    origin = previous?.destination.orEmpty(),
    destination = "",
    departure = "",
    departureZone = previous?.arrival?.zone?.id ?: defaultZone(),
    arrival = "",
    arrivalZone = previous?.arrival?.zone?.id ?: defaultZone(),
)

@Composable
private fun LegDialog(legId: String, previous: Leg?, initial: LegInput, onDismiss: () -> Unit, onDone: (Leg) -> Unit) {
    var form by remember { mutableStateOf(initial) }
    var error by remember { mutableStateOf<String?>(null) }
    var modeMenu by remember { mutableStateOf(false) }
    val context = LocalContext.current
    var matches by remember { mutableStateOf<List<PlaceMatch>?>(null) }
    var searching by remember { mutableStateOf(false) }
    var pickedLabel by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Leg details") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { modeMenu = true }, modifier = Modifier.semantics { contentDescription = "Transport: ${form.mode.label}. Tap to change." }) {
                    Text("Transport: ${form.mode.label}")
                }
                DropdownMenu(expanded = modeMenu, onDismissRequest = { modeMenu = false }) {
                    TransportMode.entries.forEach { mode ->
                        DropdownMenuItem(text = { Text(mode.label) }, onClick = { form = form.copy(mode = mode); modeMenu = false })
                    }
                }
                if (form.mode.hasServiceNumber) {
                    Field("${form.mode.label} number (optional)", form.serviceNumber) { form = form.copy(serviceNumber = it) }
                }
                Field("From", form.origin) { form = form.copy(origin = it) }
                // Editing the name drops a position picked for the old one: it would point somewhere else.
                Field("To", form.destination) { form = form.copy(destination = it, destinationPoint = null); pickedLabel = null; matches = null }
                DestinationPosition(
                    point = form.destinationPoint,
                    pickedLabel = pickedLabel,
                    searching = searching,
                    matches = matches,
                    canSearch = form.destination.isNotBlank() && PlaceFinder.available(),
                    onSearch = {
                        searching = true
                        PlaceFinder.find(context, form.destination.trim()) { found -> searching = false; matches = found ?: emptyList() }
                    },
                    onPick = { m -> form = form.copy(destinationPoint = m.point); pickedLabel = m.label; matches = null },
                    onClear = { form = form.copy(destinationPoint = null); pickedLabel = null },
                )
                Field("Departs (${LegInput.EXAMPLE})", form.departure) { form = form.copy(departure = it) }
                Field("Departure time zone", form.departureZone) { form = form.copy(departureZone = it) }
                Field("Arrives (${LegInput.EXAMPLE})", form.arrival) { form = form.copy(arrival = it) }
                Field("Arrival time zone", form.arrivalZone) { form = form.copy(arrivalZone = it) }
                Text(
                    "Times can stay empty while this is a draft. Use the zone of the place, for example Asia/Kolkata.",
                    style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
                )
                error?.let { Text(it, color = Clay.Critical, fontWeight = FontWeight.SemiBold) }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                when (val parsed = form.parse(legId, previous)) {
                    is LegInput.Parsed.Error -> error = parsed.message
                    is LegInput.Parsed.Ok -> onDone(parsed.leg)
                }
            }) { Text("Done") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun DestinationPosition(
    point: GeoPoint?,
    pickedLabel: String?,
    searching: Boolean,
    matches: List<PlaceMatch>?,
    canSearch: Boolean,
    onSearch: () -> Unit,
    onPick: (PlaceMatch) -> Unit,
    onClear: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        if (point != null) {
            Text(
                "Arrival can be noticed near: ${pickedLabel ?: "the position you picked"}",
                style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold,
            )
            TextButton(onClick = onClear) { Text("Clear position") }
        } else {
            TextButton(onClick = onSearch, enabled = canSearch && !searching) {
                Text(if (searching) "Searching…" else "Find this place on the map (optional)")
            }
            Text(
                "Only needed if you want Piko to notice arrival by location. This sends the name above to your phone's map service. " +
                    "Without a position you confirm arrival yourself.",
                style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
            )
        }
        when {
            matches == null -> Unit
            matches.isEmpty() -> Text("No match found, or no connection. You can still confirm arrival yourself.", style = MaterialTheme.typography.bodySmall, color = Clay.Caution)
            else -> {
                Text("Pick the right one:", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
                matches.forEach { m -> TextButton(onClick = { onPick(m) }) { Text(m.label, style = MaterialTheme.typography.bodySmall) } }
            }
        }
    }
}
