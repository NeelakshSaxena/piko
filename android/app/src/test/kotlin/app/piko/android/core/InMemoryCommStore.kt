package app.piko.android.core

/** Test fake with the same observable behaviour as SqliteCommStore (see CommStoreContract). */
class InMemoryCommStore : CommStore {
    private val rows = ArrayList<CommItem>()

    @Synchronized override fun enqueue(comm: NewComm, nowMs: Long): Boolean {
        if (rows.any { it.id == comm.id }) return false
        rows += CommItem(
            comm.id, comm.kind, comm.createdAt.toString(), comm.text, comm.location, CommState.QUEUED,
            0, null, null, null, null, null,
        )
        return true
    }

    @Synchronized override fun next(): CommItem? =
        rows.filter { it.pending }
            .sortedWith(compareBy({ it.attempts >= POISON_AFTER }, { it.kind.ordinal }, { rows.indexOf(it) }))
            .firstOrNull()

    private fun update(id: String, change: (CommItem) -> CommItem) {
        val i = rows.indexOfFirst { it.id == id }
        if (i >= 0) rows[i] = change(rows[i])
    }

    @Synchronized override fun markSubmitted(id: String) = update(id) {
        if (it.pending) it.copy(state = CommState.SUBMITTED) else it
    }

    @Synchronized override fun markDelivered(id: String, remoteStatus: String, acknowledgedAtIso: String?, resolvedAtIso: String?, nowMs: Long) =
        update(id) {
            if (it.pending) it.copy(state = CommState.DELIVERED, remoteStatus = remoteStatus, acknowledgedAtIso = acknowledgedAtIso, resolvedAtIso = resolvedAtIso, deliveredAtMs = nowMs) else it
        }

    @Synchronized override fun release(id: String, countAttempt: Boolean) = update(id) {
        if (it.state == CommState.SUBMITTED) it.copy(state = CommState.QUEUED, attempts = it.attempts + if (countAttempt) 1 else 0) else it
    }

    @Synchronized override fun markFailed(id: String, reason: String) = update(id) {
        if (it.pending) it.copy(state = CommState.FAILED, failReason = reason.take(200)) else it
    }

    @Synchronized override fun applyRemote(id: String, remoteStatus: String, acknowledgedAtIso: String?, resolvedAtIso: String?): Boolean {
        val current = rows.firstOrNull { it.id == id && it.state == CommState.DELIVERED } ?: return false
        if (remoteRank(current.kind, remoteStatus) <= remoteRank(current.kind, current.remoteStatus)) return false
        update(id) {
            it.copy(
                remoteStatus = remoteStatus,
                acknowledgedAtIso = acknowledgedAtIso ?: it.acknowledgedAtIso,
                resolvedAtIso = resolvedAtIso ?: it.resolvedAtIso,
            )
        }
        return true
    }

    @Synchronized override fun items(limit: Int): List<CommItem> = rows.reversed().take(limit)

    @Synchronized override fun pendingCount(): Int = rows.count { it.pending }

    @Synchronized override fun clear(): Int = rows.size.also { rows.clear() }
}
