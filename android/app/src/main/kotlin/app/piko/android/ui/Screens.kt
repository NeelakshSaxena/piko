package app.piko.android.ui

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import app.piko.android.BuildConfig
import app.piko.android.RuntimeSnapshot
import app.piko.android.SharingState
import app.piko.android.SyncStatus
import app.piko.android.core.CommItem
import app.piko.android.core.QueueCounts
import app.piko.android.core.ServerUrl
import app.piko.android.core.SyncMode
import app.piko.android.core.TimeText
import app.piko.android.data.Enrollment
import app.piko.android.net.ApiClient
import app.piko.android.net.PairResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
private fun Page(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) { content() }
}

/** screens/drishti_choose_your_role, reduced to what is true in this app. */
@Composable
fun RoleScreen(onChild: () -> Unit) = Page {
    Chip("Connected by care", Clay.SoftLavender, modifier = Modifier.align(Alignment.CenterHorizontally))
    Text("How will you use Piko today?", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(
        "This app runs on the phone that shares its location. Parents and guardians use the Piko web dashboard.",
        color = Clay.TextSecondary,
    )
    ClayCard(tint = Clay.Surface) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip("Parent or Guardian", Clay.PrimaryDeep, androidx.compose.ui.graphics.Color.White)
            Text("Use the web dashboard", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "Sign in on the Piko website to see your family, device status and alerts, and to create a pairing code for a child's phone.",
                color = Clay.TextSecondary,
            )
        }
    }
    ClayCard(tint = Clay.Mint) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Chip("Child or Family Member", Clay.Mint, Clay.ForestMint)
            Text("Share this phone's location", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "Location sharing is always visible to you: a notification stays on while sharing is on, and you can stop it any time.",
                color = Clay.TextSecondary,
            )
            ClayButton("Continue as Child", onChild, soft = true)
        }
    }
    Text(
        "A phone is only linked when a parent gives you a one-time pairing code from their dashboard.",
        style = MaterialTheme.typography.bodySmall,
        color = Clay.TextSecondary,
    )
}

@Composable
fun PairScreen(onBack: () -> Unit, onPaired: (Enrollment, discardedEvents: Int) -> Unit, pair: suspend (String, String, String) -> PairOutcome) = Page {
    var server by rememberSaveable { mutableStateOf(BuildConfig.DEFAULT_SERVER) }
    var code by rememberSaveable { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf(Build.MODEL ?: "My phone") }
    var consent by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    TextButton(onClick = onBack) { Text("Back") }
    Text("Link this phone", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(
        if (BuildConfig.DEFAULT_SERVER.isNotEmpty()) "Ask a parent for a pairing code (Family Members page on the dashboard). Codes work once and expire after 15 minutes. Change the server address only if your family runs its own."
        else "Ask a parent for the server address and a pairing code. Codes work once and expire after 15 minutes.",
        color = Clay.TextSecondary,
    )
    OutlinedTextField(
        server, { server = it; error = null }, Modifier.fillMaxWidth(), label = { Text("Server address") },
        placeholder = { Text(if (BuildConfig.DEBUG) "http://10.0.2.2:8000" else "https://piko.example.com") },
        singleLine = true, shape = RoundedCornerShape(20.dp),
    )
    OutlinedTextField(
        code, { code = it.uppercase().take(12); error = null }, Modifier.fillMaxWidth(), label = { Text("Pairing code") },
        placeholder = { Text("ABC-DEF-GHI") }, singleLine = true, shape = RoundedCornerShape(20.dp),
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
    )
    OutlinedTextField(
        name, { name = it.take(100) }, Modifier.fillMaxWidth(), label = { Text("Name shown to your family") },
        singleLine = true, shape = RoundedCornerShape(20.dp),
    )
    ClayCard(tint = Clay.Sky) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("What your family will see", fontWeight = FontWeight.SemiBold)
            Text(SHARED_SUMMARY, style = MaterialTheme.typography.bodySmall)
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Checkbox(consent, { consent = it }, modifier = Modifier.semantics { contentDescription = "I understand and agree" })
        Text("I understand this phone will share this information, and a notification will show while it does.", style = MaterialTheme.typography.bodyMedium)
    }
    error?.let { Text(it, color = Clay.Critical, fontWeight = FontWeight.SemiBold) }
    ClayButton(if (busy) "Linking…" else "Link this phone", onClick = {
        val base = ServerUrl.parse(server, BuildConfig.DEBUG)
        when {
            base == null -> error = if (BuildConfig.DEBUG) "Enter an https:// address (or http://10.0.2.2:PORT for the emulator)." else "Enter an https:// server address."
            code.length < 9 -> error = "Enter the full pairing code."
            name.isBlank() -> error = "Enter a name for this phone."
            else -> {
                busy = true
                scope.launch {
                    when (val r = pair(base, code, name.trim())) {
                        is PairOutcome.Linked -> onPaired(r.enrollment, r.discardedEvents)
                        is PairOutcome.Error -> { error = r.message; busy = false }
                    }
                }
            }
        }
    }, enabled = consent && !busy)
}

sealed interface PairOutcome {
    data class Linked(val enrollment: Enrollment, val discardedEvents: Int) : PairOutcome
    data class Error(val message: String) : PairOutcome
}

suspend fun runPair(base: String, code: String, name: String, appVersion: String, discard: () -> Int, save: (Enrollment) -> Unit): PairOutcome =
    withContext(Dispatchers.IO) {
        val result = ApiClient(base).pair(code, name, Build.MODEL ?: "unknown", Build.VERSION.RELEASE ?: "unknown", appVersion)
        when (result) {
            is PairResult.Success -> {
                // Anything queued for a previous pairing must never be uploaded to a new family.
                val discarded = discard()
                val enrollment = Enrollment(result.device.deviceId, result.device.familyId, base, result.device.credential, name)
                save(enrollment)
                PairOutcome.Linked(enrollment, discarded)
            }
            PairResult.InvalidCode -> PairOutcome.Error("That code is not valid. It may have expired or been used. Ask for a new one.")
            PairResult.RateLimited -> PairOutcome.Error("Too many attempts. Wait a minute and try again.")
            is PairResult.Failed -> PairOutcome.Error(result.message)
        }
    }

private const val SHARED_SUMMARY =
    "Your location (with how accurate it is and when it was taken), battery level and whether you are charging, " +
        "and whether you are on Wi-Fi or mobile data. Not shared: your contacts, your phone's own text messages, photos, apps or microphone. Messages you send through Piko go to your parents."

/** screens/drishti_child_safety_home, limited to features that exist (no check-ins yet). */
@Composable
fun HomeScreen(
    enrollment: Enrollment,
    runtime: RuntimeSnapshot,
    counts: QueueCounts,
    nowMs: Long,
    mode: SyncMode,
    revoked: Boolean,
    interrupted: Boolean,
    onToggleSharing: () -> Unit,
    onMode: (SyncMode) -> Unit,
    onTransparency: () -> Unit,
    onRelink: () -> Unit,
    onOpenSettings: () -> Unit,
    comms: List<CommItem>,
    unreadMessages: Int,
    canSend: Boolean,
    onSos: (String?) -> Unit,
    onMessages: () -> Unit,
    onJourneys: () -> Unit,
) = Page {
    val running = runtime.sharing is SharingState.Running
    Text("Child Home", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    Text("Hello, ${enrollment.deviceName}", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)

    SosCard(comms, nowMs, canSend && !(revoked || runtime.sharing is SharingState.CredentialRevoked), onSos)
    ClayCard(tint = Clay.Sky) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Family messages", fontWeight = FontWeight.Bold)
                Text(
                    if (unreadMessages > 0) "$unreadMessages message(s) from your family to confirm" else "Write to your parents",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            TextButton(onClick = onMessages) { Text("Open") }
        }
    }

    if (revoked || runtime.sharing is SharingState.CredentialRevoked) {
        ClayCard(tint = Clay.CriticalSoft) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("This phone was unlinked", fontWeight = FontWeight.Bold, color = Clay.Critical)
                Text("The server no longer accepts this phone, so nothing is being shared. Ask a parent for a new pairing code.")
                ClayButton("Link again", onRelink)
            }
        }
    }
    (runtime.sharing as? SharingState.PermissionMissing)?.let {
        ClayCard(tint = Clay.Peach) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Location permission is off", fontWeight = FontWeight.Bold)
                Text("Sharing cannot start without it. Nothing is being shared.")
                ClayButton("Open settings", onOpenSettings, soft = true)
            }
        }
    }
    runtime.message?.let { Text(it, color = Clay.Caution, fontWeight = FontWeight.SemiBold) }
    if (interrupted && !running) Text("Sharing was interrupted and is not running.", color = Clay.Caution, fontWeight = FontWeight.SemiBold)

    ClayCard(tint = if (running) Clay.Mint else Clay.Surface) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Label(if (running) "Sharing is on" else "Sharing is off")
            Text(
                if (running) "Your family can see your location" else "Your family cannot see your location right now",
                style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
            )
            StatRow("Mode", mode.name)
            StatRow("Last location", locationLine(runtime, nowMs))
            StatRow("Last confirmed by server", TimeText.ago(nowMs, counts.lastAcknowledgedAtMs))
            StatRow("Battery", runtime.batteryPercent?.let { "$it%" + if (runtime.batteryCharging == true) " (charging)" else "" } ?: "unknown")
            StatRow("Connection", syncLine(runtime, nowMs))
        }
    }

    ClayButton(if (running) "Stop sharing" else "Start sharing", onToggleSharing, soft = running,
        enabled = !(revoked || runtime.sharing is SharingState.CredentialRevoked))

    ClayCard {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Update mode", fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ModeChip("Polling", mode == SyncMode.POLLING) { onMode(SyncMode.POLLING) }
                ModeChip("Realtime", mode == SyncMode.REALTIME) { onMode(SyncMode.REALTIME) }
            }
            Text(
                if (mode == SyncMode.REALTIME) "Realtime sends updates within seconds while there is a connection. It uses more battery."
                else "Polling checks about once a minute and saves battery. It does not wake the GPS every minute.",
                style = MaterialTheme.typography.bodySmall, color = Clay.TextSecondary,
            )
        }
    }

    ClayCard(tint = Clay.PeachSoft) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Offline Shield", fontWeight = FontWeight.Bold)
            Text(offlineLine(counts, runtime), style = MaterialTheme.typography.bodyMedium)
            StatRow("Waiting to send", counts.pending.toString())
            StatRow("Confirmed by server (total)", counts.acknowledgedTotal.toString())
            if (counts.rejected > 0) StatRow("Rejected by server", counts.rejected.toString())
            if (counts.droppedTotal > 0) StatRow("Discarded (phone storage full)", counts.droppedTotal.toString())
            counts.oldestPendingOccurredAt?.let { StatRow("Oldest waiting reading", "taken " + agoIso(nowMs, it)) }
            runtime.lastPayload?.let { StatRow("Last upload", "${it.events} events, ${it.wireBytes} bytes") }
        }
    }

    ClayCard(tint = Clay.LavenderSoft) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Open transparency", fontWeight = FontWeight.Bold)
                Text("See exactly what your family can view", style = MaterialTheme.typography.bodySmall)
            }
            TextButton(onClick = onTransparency) { Text("Review") }
        }
    }

    ClayCard(tint = Clay.Mint) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Journeys", fontWeight = FontWeight.Bold)
                Text("Plan a trip leg by leg. Saved on this phone only.", style = MaterialTheme.typography.bodySmall)
            }
            TextButton(onClick = onJourneys) { Text("Open") }
        }
    }
}

@Composable
private fun ModeChip(text: String, selected: Boolean, onClick: () -> Unit) {
    TextButton(onClick = onClick, modifier = Modifier.semantics { contentDescription = "$text mode" + if (selected) ", selected" else "" }) {
        Chip(text + if (selected) " ✓" else "", if (selected) Clay.SoftLavender else Clay.Canvas)
    }
}

private fun locationLine(runtime: RuntimeSnapshot, nowMs: Long): String {
    val at = runtime.lastLocationAtMs ?: return "none yet"
    val age = TimeText.ago(nowMs, at)
    val accuracy = runtime.lastLocationAccuracyM?.let { " (±${it.toInt()} m)" } ?: ""
    // Never "live" for an old fix.
    return if (TimeText.isFresh(nowMs, at)) "$age$accuracy" else "last seen $age$accuracy"
}

private fun syncLine(runtime: RuntimeSnapshot, nowMs: Long): String = when (val s = runtime.sync) {
    SyncStatus.Idle -> if (runtime.sharing is SharingState.Running) "ready" else "not sharing"
    SyncStatus.Syncing -> "sending…"
    SyncStatus.WaitingForNetwork -> "offline, saving on this phone"
    is SyncStatus.BackingOff -> "retrying in ${((s.untilMs - nowMs) / 1000).coerceAtLeast(0)} s (${s.reason.replace('_', ' ')})"
}

private fun readings(n: Int): String = if (n == 1) "1 reading is" else "$n readings are"

private fun offlineLine(counts: QueueCounts, runtime: RuntimeSnapshot): String = when {
    runtime.sync == SyncStatus.WaitingForNetwork && counts.pending > 0 ->
        "No connection. ${readings(counts.pending)} saved on this phone and will be sent when you reconnect."
    counts.pending > 0 -> "${readings(counts.pending)} waiting to be confirmed by the server."
    else -> "Nothing is waiting. With no signal, readings are saved on this phone and sent when you reconnect."
}

private fun agoIso(nowMs: Long, iso: String): String =
    runCatching { TimeText.ago(nowMs, java.time.Instant.parse(iso).toEpochMilli()) }.getOrDefault("unknown time")

@Composable
fun TransparencyScreen(enrollment: Enrollment, onBack: () -> Unit, onUnlink: () -> Unit) = Page {
    var confirm by remember { mutableStateOf(false) }
    TextButton(onClick = onBack) { Text("Back") }
    Text("What your family can see", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    ClayCard {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Label("Shared while sharing is on")
            Text(SHARED_SUMMARY)
            VGap(4)
            Label("Who can see it")
            Text("Parents and guardians in your family, through the Piko dashboard. Each time one of them looks at your location, it is recorded.")
            VGap(4)
            Label("How long it is kept")
            Text("The family's retention setting (30 days unless a parent changed it).")
            VGap(4)
            Label("Your controls")
            Text("Stop sharing any time from the home screen or the notification. When sharing is off, nothing new is collected.")
            VGap(4)
            Label("SOS and messages")
            Text(
                "An SOS or a message goes to the parents and guardians in your family through the Piko server. " +
                    "It does not call emergency services. If you have no connection, it is saved on this phone and " +
                    "sent when you reconnect; the app tells you whether it was only saved, delivered, or seen.",
            )
        }
    }
    ClayCard(tint = Clay.Sky) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Label("This phone")
            StatRow("Name", enrollment.deviceName)
            StatRow("Server", enrollment.serverBase)
        }
    }
    ClayButton("Unlink this phone", { confirm = true }, soft = true)
    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Unlink this phone?") },
            text = { Text("Sharing stops and anything still waiting on this phone (readings, and any SOS or message not yet delivered) is deleted. A parent must create a new pairing code to link it again.") },
            confirmButton = { TextButton(onClick = { confirm = false; onUnlink() }) { Text("Unlink") } },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        )
    }
}
