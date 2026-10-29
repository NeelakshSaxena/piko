package app.piko.android.journeys.domain

import java.time.Instant

/** A journey and the revision the phone assigned to this saved version. They are read together, never apart. */
data class PendingUpload(val journey: Journey, val revision: Long)

/** Where journeys live on the phone. Nothing here needs the network; see JourneyStoreContract for the rules. */
interface JourneyStore {
    /** Inserts or replaces the journey and its legs in one transaction; leg order is the sequence. */
    fun save(journey: Journey)

    fun get(id: String): Journey?

    /** Most recently updated first. */
    fun list(): List<Journey>

    /** True if a journey was removed. Its legs go with it. */
    fun delete(id: String): Boolean

    /** Sets or clears the user's expected times for one leg. The schedule and the journey's edit time do not change, so nothing is re-uploaded. */
    fun setEstimate(journeyId: String, legId: String, estimate: Estimate?)

    // ---- backup bookkeeping (ADR-026). The phone stays the source of truth; the server copy is a backup. ----

    /** Journeys whose latest saved version the server has not acknowledged. */
    fun dirty(): List<Journey> = dirtyUploads().map { it.journey }

    /**
     * Like [dirty], with each journey's revision read in the same step. Every [save] raises a journey's revision by
     * one, whatever the clock says; the server applies an upload only if its revision is higher than the one it holds.
     */
    fun dirtyUploads(): List<PendingUpload>

    /**
     * Records that the server holds the version saved at [updatedAt] with [revision] (null: the current revision,
     * for callers that cannot have raced a save). False if the journey no longer exists. A save made while the
     * upload was in flight leaves the journey dirty, even if the clock gave both saves the same time.
     */
    fun markSynced(id: String, updatedAt: Instant, revision: Long? = null): Boolean

    /**
     * Call before sending a journey: from then on the server may hold it, so deleting it here owes the server a delete.
     * False if the journey no longer exists (deleted since the list of pending uploads was read): do not send it.
     */
    fun markUploadAttempted(id: String): Boolean

    /** The server holds revision [serverRevision] (or newer): the next upload of [id] must use a higher one. */
    fun rebase(id: String, serverRevision: Long)

    /** Ids deleted here that the server may still hold. Only journeys the server acknowledged are queued. */
    fun pendingDeletes(): List<String>

    fun queueDelete(id: String)

    fun markDeleteSynced(id: String)

    /** The phone now talks to a different server identity: nothing is known to be backed up any more. */
    fun forgetSync()
}
