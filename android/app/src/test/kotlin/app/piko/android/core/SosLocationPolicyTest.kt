package app.piko.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SosLocationPolicyTest {
    private val fix = SosPoint(40.7, -74.0, 12.0)
    private val now = 10_000_000L

    @Test fun aFixMeasuredMomentsAgoIsAttached() {
        assertEquals(fix, SosLocationPolicy.attachable(fix, now - 5_000, now))
        assertEquals(fix, SosLocationPolicy.attachable(fix, now, now))
    }

    @Test fun theBoundaryIsInclusiveAtTwoMinutes() {
        assertEquals(fix, SosLocationPolicy.attachable(fix, now - 120_000, now))
        assertNull(SosLocationPolicy.attachable(fix, now - 120_001, now))
    }

    @Test fun aStaleFixIsNeverAttachedAsIfItWereCurrent() {
        assertNull(SosLocationPolicy.attachable(fix, now - 5 * 60_000, now))
        assertNull(SosLocationPolicy.attachable(fix, now - 24 * 3_600_000, now))
    }

    @Test fun noFixOrNoTimestampMeansNoLocation() {
        assertNull(SosLocationPolicy.attachable(null, now, now))
        assertNull(SosLocationPolicy.attachable(fix, null, now))
    }

    @Test fun aFixDatedInTheFutureIsNotTrusted() {
        assertNull(SosLocationPolicy.attachable(fix, now + 1, now))
        assertNull(SosLocationPolicy.attachable(fix, now + 3_600_000, now))
    }
}
