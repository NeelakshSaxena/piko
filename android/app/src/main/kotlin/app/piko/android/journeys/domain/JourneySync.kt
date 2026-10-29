package app.piko.android.journeys.domain

sealed interface SyncCall {
    data object Ok : SyncCall
    data object Unauthorized : SyncCall

    /** No connection, a server error or a rate limit: nothing is lost, try again later. */
    data class Retry(val afterSeconds: Long? = null) : SyncCall

    /** The server will never accept this as sent (bad request, deleted there, id in use). */
    data class Refused(val status: Int) : SyncCall

    /** The server already holds revision [serverRevision], newer than the one sent. Nothing was changed there. */
    data class Stale(val serverRevision: Long) : SyncCall
}

interface JourneyTransport {
    /** Uploads one whole journey at [revision]. [SyncCall.Ok] covers "stored" and "the server already had exactly this revision". */
    fun put(journey: Journey, revision: Long): SyncCall

    /** Idempotent on the server. */
    fun delete(id: String): SyncCall

    /** Delivers a batch of events for a journey the server holds. The server ignores ids it already has. */
    fun events(journeyId: String, events: List<JourneyEvent>): SyncCall
}

sealed interface JourneySyncOutcome {
    data class Done(val uploaded: Int, val deleted: Int, val refused: Int, val events: Int = 0) : JourneySyncOutcome
    data object RetryLater : JourneySyncOutcome
    data object CredentialRevoked : JourneySyncOutcome
}

/**
 * Backs journeys up to the user's Piko server. The phone stays the source of truth: nothing is ever pulled
 * into the local store, so a failed or refused upload never changes what the user sees.
 *
 * Deletes owed to the server are always delivered (they remove data). Uploads happen only while
 * [backupEnabled] says the user turned backup on.
 */
class JourneySyncEngine(
    private val store: JourneyStore,
    private val tracking: TrackingStore,
    private val transport: JourneyTransport,
    private val backupEnabled: () -> Boolean,
) {
    fun drain(): JourneySyncOutcome {
        var deleted = 0
        var uploaded = 0
        var refused = 0
        when (val r = deliverDeletes { deleted++ }) {
            null -> Unit
            else -> return r
        }
        if (backupEnabled()) {
            var raced = false
            var rebased = false
            for (pending in store.dirtyUploads()) {
                val journey = pending.journey
                // Recorded before the request: if its reply is lost the server may still have stored it.
                // False: it was deleted since this list was read, so it must not be sent at all.
                if (!store.markUploadAttempted(journey.id)) continue
                when (val call = transport.put(journey, pending.revision)) {
                    SyncCall.Ok -> {
                        uploaded++
                        // Deleted on the phone while the upload was in flight: the server now holds a copy that must go.
                        if (!store.markSynced(journey.id, journey.updatedAt, pending.revision)) {
                            store.queueDelete(journey.id)
                            raced = true
                        }
                    }
                    SyncCall.Unauthorized -> return JourneySyncOutcome.CredentialRevoked
                    is SyncCall.Retry -> return JourneySyncOutcome.RetryLater
                    is SyncCall.Refused -> refused++ // stays dirty; the next run tries again
                    is SyncCall.Stale -> {
                        // The server keeps a newer revision (this phone lost its counter, or an old copy arrived late).
                        // It stays dirty and visibly unsent; the next run reads it afresh with a revision above the server's.
                        store.rebase(journey.id, call.serverRevision)
                        refused++
                        rebased = true
                    }
                }
            }
            if (raced) deliverDeletes { deleted++ }?.let { return it }
            if (rebased) return JourneySyncOutcome.RetryLater
        }
        var events = 0
        if (backupEnabled()) {
            // Events describe what the user did on a trip, so they go only with a journey the server holds and
            // whose latest version it has acknowledged.
            val unsynced = store.dirty().map { it.id }.toSet()
            for (journeyId in tracking.journeysWithPendingEvents()) {
                if (journeyId in unsynced || store.get(journeyId) == null) continue
                while (true) {
                    val batch = tracking.pendingEvents(journeyId, EVENT_BATCH)
                    if (batch.isEmpty()) break
                    when (transport.events(journeyId, batch)) {
                        // Refused: the server will never take these (unknown or deleted there), so they are not retried forever.
                        SyncCall.Ok, is SyncCall.Refused, is SyncCall.Stale -> {
                            tracking.markEventsSent(batch.map { it.id })
                            events += batch.size
                        }
                        SyncCall.Unauthorized -> return JourneySyncOutcome.CredentialRevoked
                        is SyncCall.Retry -> return JourneySyncOutcome.RetryLater
                    }
                }
            }
        }
        return JourneySyncOutcome.Done(uploaded, deleted, refused, events)
    }

    private companion object {
        const val EVENT_BATCH = 100
    }

    /** Null when every owed delete was delivered; otherwise the outcome that stops the run. */
    private inline fun deliverDeletes(onDeleted: () -> Unit): JourneySyncOutcome? {
        for (id in store.pendingDeletes()) {
            when (transport.delete(id)) {
                // Refused: the server will never act on it (for example it never knew the id), so the debt is void.
                SyncCall.Ok, is SyncCall.Refused, is SyncCall.Stale -> {
                    store.markDeleteSynced(id)
                    onDeleted()
                }
                SyncCall.Unauthorized -> return JourneySyncOutcome.CredentialRevoked
                is SyncCall.Retry -> return JourneySyncOutcome.RetryLater
            }
        }
        return null
    }
}
