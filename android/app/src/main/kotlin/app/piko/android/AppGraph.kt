package app.piko.android

import android.app.Application
import android.content.Context
import app.piko.android.core.Clock
import app.piko.android.core.Recorder
import app.piko.android.core.SyncMode
import app.piko.android.data.DeviceVault
import app.piko.android.data.SqliteEventStore
import app.piko.android.net.PayloadSize
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
    val batteryPercent: Int? = null,
    val batteryCharging: Boolean? = null,
    val lastPayload: PayloadSize? = null,
    val message: String? = null,
)

/** Hand-wired dependencies; one process-wide instance, no DI framework. */
class AppGraph(context: Context) {
    val clock = Clock { System.currentTimeMillis() }
    val vault = DeviceVault(context)
    val store = SqliteEventStore(context)
    val recorder = Recorder(store, clock)

    private val _runtime = MutableStateFlow(RuntimeSnapshot())
    val runtime: StateFlow<RuntimeSnapshot> = _runtime.asStateFlow()

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
    }
}

val Context.graph: AppGraph get() = (applicationContext as PikoApp).graph
