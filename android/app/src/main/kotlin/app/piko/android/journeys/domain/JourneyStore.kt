package app.piko.android.journeys.domain

import java.time.Instant

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
    fun dirty(): List<Journey>

    /** Records that the server holds the version saved at [updatedAt]. False if the journey no longer exists. */
    fun markSynced(id: String, updatedAt: Instant): Boolean

    /** Ids deleted here that the server may still hold. Only journeys the server acknowledged are queued. */
    fun pendingDeletes(): List<String>

    fun queueDelete(id: String)

    fun markDeleteSynced(id: String)

    /** The phone now talks to a different server identity: nothing is known to be backed up any more. */
    fun forgetSync()
}
