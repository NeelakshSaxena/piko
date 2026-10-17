package app.piko.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.piko.android.CommsView
import app.piko.android.core.CommItem
import app.piko.android.core.CommKind
import app.piko.android.core.CommLabels
import app.piko.android.core.NewComm
import app.piko.android.core.RemoteMessage
import app.piko.android.core.TimeText
import app.piko.android.core.Tone
import java.time.OffsetDateTime

internal fun isoToMs(iso: String): Long? = runCatching { OffsetDateTime.parse(iso).toInstant().toEpochMilli() }.getOrNull()

private fun toneColor(tone: Tone): Color = when (tone) {
    Tone.PENDING -> Clay.TextSecondary
    Tone.OK -> Clay.ForestMint
    Tone.WARN -> Clay.Caution
    Tone.BAD -> Clay.Critical
}

/** What an SOS is and is not, shown wherever the button is. There is no emergency-service integration. */
const val SOS_DISCLAIMER =
    "This sends an SOS to your family through Piko. It does NOT call the police, an ambulance or any " +
        "emergency service. In an emergency, call your local emergency number."

@Composable
fun SosCard(items: List<CommItem>, nowMs: Long, canSend: Boolean, onSend: (String?) -> Unit) {
    var confirm by rememberSaveable { mutableStateOf(false) }
    var note by rememberSaveable { mutableStateOf("") }
    ClayCard(tint = Clay.CriticalSoft) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Label("Need help?")
            Text("Send an SOS to your family", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(SOS_DISCLAIMER, style = MaterialTheme.typography.bodySmall)
            if (!canSend) {
                Text(
                    "This phone is not linked to the server right now, so an SOS cannot be sent. Contact your family another way.",
                    color = Clay.Critical, fontWeight = FontWeight.SemiBold,
                )
            }
            ClayButton("Send SOS", { confirm = true }, enabled = canSend)
            val sos = items.filter { it.kind == CommKind.SOS }.take(3)
            if (sos.isNotEmpty()) {
                Label("Your recent SOS")
                sos.forEach { CommRow("SOS", it, nowMs) }
            }
        }
    }
    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Send SOS to your family?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(SOS_DISCLAIMER)
                    OutlinedTextField(
                        note, { note = it.take(NewComm.MAX_SOS_TEXT) }, Modifier.fillMaxWidth(),
                        label = { Text("Optional note") }, shape = RoundedCornerShape(20.dp),
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { confirm = false; onSend(note.ifBlank { null }); note = "" }) { Text("Send SOS") }
            },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun CommRow(title: String, item: CommItem, nowMs: Long) {
    val label = CommLabels.of(item)
    val whenText = isoToMs(item.createdAtIso)?.let { TimeText.ago(nowMs, it) } ?: "unknown time"
    Column(Modifier.fillMaxWidth().semantics { contentDescription = "$title, $whenText, ${label.text}" }) {
        Text("$title · $whenText", style = MaterialTheme.typography.labelMedium, color = Clay.TextSecondary)
        item.text?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        Text(label.text, style = MaterialTheme.typography.bodySmall, color = toneColor(label.tone), fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun MessagesScreen(
    items: List<CommItem>,
    parent: CommsView,
    nowMs: Long,
    canSend: Boolean,
    notificationsAllowed: Boolean,
    onBack: () -> Unit,
    onSend: (String) -> String?,
    onGotIt: (String) -> Unit,
    onRefresh: () -> Unit,
    onAllowAlerts: () -> Unit,
    error: String?,
    backgroundAlerts: String,
) {
    var draft by rememberSaveable { mutableStateOf("") }
    var problem by remember { mutableStateOf<String?>(null) }
    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        TextButton(onClick = onBack) { Text("Back") }
        Text("Family messages", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(
            "Messages go to the parents and guardians in your family. They are not end-to-end encrypted and " +
                "are not an emergency channel.",
            color = Clay.TextSecondary,
        )
        if (!notificationsAllowed) {
            ClayCard(tint = Clay.Peach) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Reply alerts are off", fontWeight = FontWeight.Bold)
                    Text(
                        "Piko cannot alert you when a parent replies. You will only see replies when you open this " +
                            "screen. Replies are checked while this app is open or while sharing is on.",
                    )
                    ClayButton("Allow alerts", onAllowAlerts, soft = true)
                }
            }
        }
        Text(backgroundAlerts, style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary)
        if (!canSend) {
            Text("This phone is not linked to the server, so messages cannot be sent.", color = Clay.Critical, fontWeight = FontWeight.SemiBold)
        }
        OutlinedTextField(
            draft, { draft = it.take(NewComm.MAX_MESSAGE_TEXT); problem = null }, Modifier.fillMaxWidth(),
            label = { Text("Message to your family") }, shape = RoundedCornerShape(20.dp),
        )
        (problem ?: error)?.let { Text(it, color = Clay.Critical, fontWeight = FontWeight.SemiBold) }
        ClayButton("Send message", {
            val err = onSend(draft)
            problem = err
            if (err == null) draft = ""
        }, enabled = canSend)

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Label("Conversation")
            TextButton(onClick = onRefresh) { Text("Refresh") }
        }
        if (parent.loadedAtMs == null) {
            Text(
                "Messages from your family have not been loaded yet. Connect and tap Refresh. Until then, replies you " +
                    "may have received are not shown.",
                color = Clay.Caution, style = MaterialTheme.typography.bodySmall,
            )
        } else {
            Text("Checked ${TimeText.ago(nowMs, parent.loadedAtMs)}", style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary)
        }

        val mine = items.filter { it.kind == CommKind.MESSAGE }
        val timeline = (mine.map { Entry.Mine(it, isoToMs(it.createdAtIso) ?: 0) } +
            parent.messages.map { Entry.Theirs(it, isoToMs(it.sentAtIso) ?: 0) }).sortedByDescending { it.at }
        if (timeline.isEmpty() && parent.loadedAtMs != null) {
            Text("No messages yet.", color = Clay.TextSecondary)
        }
        timeline.forEach { entry ->
            ClayCard(tint = if (entry is Entry.Theirs) Clay.Sky else Clay.Surface) {
                when (entry) {
                    is Entry.Mine -> CommRow("You", entry.item, nowMs)
                    is Entry.Theirs -> ParentRow(entry.message, nowMs, onGotIt)
                }
            }
        }
    }
}

private sealed interface Entry {
    val at: Long
    data class Mine(val item: CommItem, override val at: Long) : Entry
    data class Theirs(val message: RemoteMessage, override val at: Long) : Entry
}

@Composable
private fun ParentRow(message: RemoteMessage, nowMs: Long, onGotIt: (String) -> Unit) {
    val whenText = isoToMs(message.sentAtIso)?.let { TimeText.ago(nowMs, it) } ?: "unknown time"
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Family · $whenText", style = MaterialTheme.typography.labelMedium, color = Clay.TextSecondary)
        Text(message.body, style = MaterialTheme.typography.bodyMedium)
        if (message.status == "acknowledged") {
            Text("You confirmed you saw this", style = MaterialTheme.typography.bodySmall, color = Clay.ForestMint, fontWeight = FontWeight.SemiBold)
        } else {
            TextButton(onClick = { onGotIt(message.id) }) { Text("Got it") }
        }
    }
}
