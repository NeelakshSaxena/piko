package app.piko.android

import android.app.Application
import android.content.Context
import app.piko.android.core.Clock
import app.piko.android.core.Recorder
import app.piko.android.core.RemoteMessage
import app.piko.android.core.SosPoint
import app.piko.android.core.SyncMode
import app.piko.android.data.DeviceVault
import app.piko.android.data.SqliteCommStore
import app.piko.android.data.SqliteEventStore
import app.piko.android.net.PayloadSize
import app.piko.android.push.PushSupport
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What the foreground service is really doing right now. Initial value after a process start is Stopped. */
sealed interface SharingState {
    data object Stopped : SharingState
    data class Running(val mode: SyncMode) : SharingState
    data class PermissionMissing(val detail: String) : SharingState

    /** The server stopped accepting this device (401). The device must be paired again. */
    data object CredentialRevoked : SharingState
}

sealed interface SyncStatus {
    data object Idle : SyncStatus
    data object Syncing : SyncStatus
    data object WaitingForNetwork : SyncStatus
    data class BackingOff(val untilMs: Long, val reason: String) : SyncStatus
}

data class RuntimeSnapshot(
    val sharing: SharingState = SharingState.Stopped,
    val sync: SyncStatus = SyncStatus.Idle,
    val networkType: String? = null,
    val lastLocationAtMs: Long? = null,
    val lastLocationAccuracyM: Double? = null,
    /** Kept in memory only, to attach a position to an SOS when it is still fresh. */
    val lastFix: SosPoint? = null,
    val batteryPercent: Int? = null,
    val batteryCharging: Boolean? = null,
    val lastPayload: PayloadSize? = null,
    val message: String? = null,
)

/**
 * A phone that has just been linked is not "unlinked" any more. A previous revocation leaves
 * [SharingState.CredentialRevoked] in memory; without this the SOS button would stay disabled until the
 * process restarted.
 */
fun RuntimeSnapshot.afterLinking(): RuntimeSnapshot =
    copy(sharing = SharingState.Stopped, sync = SyncStatus.Idle, message = null)

/** [loadedAtMs] null: the list has not been fetched in this process, so it must not read as "empty". */
data class CommsView(val messages: List<RemoteMessage> = emptyList(), val loadedAtMs: Long? = null)

/** Hand-wired dependencies; one process-wide instance, no DI framework. */
class AppGraph(context: Context) {
    val clock = Clock { System.currentTimeMillis() }
    val vault = DeviceVault(context)
    val store = SqliteEventStore(context)
    val recorder = Recorder(store, clock)
    val comms = SqliteCommStore(context)

    private val _runtime = MutableStateFlow(RuntimeSnapshot())
    val runtime: StateFlow<RuntimeSnapshot> = _runtime.asStateFlow()

    /** Parents' messages as last fetched. Empty means "not loaded", never "no messages" (see [CommsView]). */
    private val _parentMessages = MutableStateFlow(CommsView())
    val parentMessages: StateFlow<CommsView> = _parentMessages.asStateFlow()

    fun setParentMessages(view: CommsView) {
        _parentMessages.value = view
    }

    fun update(change: (RuntimeSnapshot) -> RuntimeSnapshot) {
        _runtime.value = change(_runtime.value)
    }
}

class PikoApp : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        PushSupport.start(this) // no-op unless this build has Firebase settings
    }
}

val Context.graph: AppGraph get() = (applicationContext as PikoApp).graph
