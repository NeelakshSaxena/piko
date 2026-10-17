package app.piko.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RuntimeSnapshotTest {
    @Test fun linkingAPhoneClearsTheStateAPreviousRevocationLeftBehind() {
        val stale = RuntimeSnapshot(
            sharing = SharingState.CredentialRevoked,
            sync = SyncStatus.WaitingForNetwork,
            message = "This phone was unlinked.",
            batteryPercent = 40,
        )
        val after = stale.afterLinking()
        assertEquals(SharingState.Stopped, after.sharing) // the SOS button is gated on this
        assertEquals(SyncStatus.Idle, after.sync)
        assertNull(after.message)
        assertEquals(40, after.batteryPercent) // unrelated readings are kept
    }
}
