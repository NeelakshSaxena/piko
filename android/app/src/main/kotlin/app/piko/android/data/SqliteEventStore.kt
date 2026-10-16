package app.piko.android.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import app.piko.android.core.Batch
import app.piko.android.core.DeliveryState
import app.piko.android.core.EnqueueResult
import app.piko.android.core.EventPriority
import app.piko.android.core.EventStore
import app.piko.android.core.EventType
import app.piko.android.core.NewEvent
import app.piko.android.core.QueueCounts
import app.piko.android.core.QueuedEvent
import java.util.UUID

/**
 * The durable queue on the framework SQLite (no extra dependency). `synchronous=FULL` means a
 * committed event survives process death and power loss, and every mutation is one transaction.
 *
 * `sequence_number` sent to the server is the AUTOINCREMENT row id: strictly increasing and never
 * reused, even after deletes.
 */
class SqliteEventStore(
    context: Context,
    name: String? = DB_NAME,
    private val capacity: Int = DEFAULT_MAX_EVENTS,
) : SQLiteOpenHelper(context.applicationContext, name, null, VERSION), EventStore {

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
        db.rawQuery("PRAGMA synchronous=FULL", null).use { it.moveToFirst() }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE events(
                 seq INTEGER PRIMARY KEY AUTOINCREMENT,
                 event_id TEXT NOT NULL UNIQUE,
                 type TEXT NOT NULL,
                 occurred_at TEXT NOT NULL,
                 data TEXT NOT NULL,
                 priority INTEGER NOT NULL,
                 state INTEGER NOT NULL,
                 attempts INTEGER NOT NULL DEFAULT 0,
                 batch_id TEXT,
                 reject_reason TEXT)""",
        )
        db.execSQL("CREATE INDEX events_claim ON events(state, priority DESC, seq)")
        db.execSQL("CREATE INDEX events_batch ON events(batch_id) WHERE batch_id IS NOT NULL")
        db.execSQL("CREATE TABLE counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        error("no migrations exist yet (from $oldVersion to $newVersion)")
    }

    @Synchronized
    override fun enqueue(event: NewEvent, nowMs: Long): EnqueueResult = inTransaction { db ->
        val values = ContentValues().apply {
            put("event_id", event.eventId)
            put("type", event.data.type.wire)
            put("occurred_at", event.occurredAt.toString())
            put("data", event.data.toJson())
            put("priority", event.priority.value)
            put("state", DeliveryState.QUEUED.ordinal)
        }
        val seq = db.insertWithOnConflict("events", null, values, SQLiteDatabase.CONFLICT_IGNORE)
        if (seq == -1L) return@inTransaction EnqueueResult.AlreadyQueued
        val dropped = makeRoom(db)
        EnqueueResult.Stored(seq, dropped)
    }

    /** Bounds storage: oldest NORMAL queued events go first (counted); old REJECTED rows are pruned. */
    private fun makeRoom(db: SQLiteDatabase): Int {
        var dropped = 0
        val total = scalar(db, "SELECT COUNT(*) FROM events")
        if (total > capacity) {
            db.execSQL(
                """DELETE FROM events WHERE seq IN (
                     SELECT seq FROM events WHERE state = ? AND priority = ? ORDER BY seq LIMIT ?)""",
                arrayOf<Any?>(DeliveryState.QUEUED.ordinal, EventPriority.NORMAL.value, total - capacity),
            )
            dropped = scalar(db, "SELECT changes()").toInt()
            if (dropped > 0) addCounter(db, DROPPED, dropped.toLong())
        }
        db.execSQL(
            """DELETE FROM events WHERE seq IN (
                 SELECT seq FROM events WHERE state = ? ORDER BY seq DESC LIMIT -1 OFFSET ?)""",
            arrayOf(DeliveryState.REJECTED.ordinal, MAX_REJECTED_KEPT),
        )
        return dropped
    }

    @Synchronized
    override fun nextBatch(maxEvents: Int): Batch? = inTransaction { db ->
        val inDoubt = db.rawQuery(
            "SELECT batch_id FROM events WHERE state = ? ORDER BY seq LIMIT 1",
            arrayOf(DeliveryState.SUBMITTED.ordinal.toString()),
        ).use { if (it.moveToFirst()) it.getString(0) else null }
        if (inDoubt != null) {
            return@inTransaction Batch(inDoubt, rows(db, "batch_id = ? AND state = ${DeliveryState.SUBMITTED.ordinal}", inDoubt))
        }
        // Events that already failed several times go after fresh ones so one poison event
        // cannot block the queue.
        val seqs = db.rawQuery(
            """SELECT seq FROM events WHERE state = ?
               ORDER BY priority DESC, (attempts >= $POISON_AFTER) ASC, seq ASC LIMIT ?""",
            arrayOf(DeliveryState.QUEUED.ordinal.toString(), maxEvents.toString()),
        ).use { c -> buildList { while (c.moveToNext()) add(c.getLong(0)) } }
        if (seqs.isEmpty()) return@inTransaction null
        val batchId = UUID.randomUUID().toString()
        db.execSQL(
            "UPDATE events SET state = ?, batch_id = ? WHERE seq IN (${seqs.joinToString(",")})",
            arrayOf<Any?>(DeliveryState.SUBMITTED.ordinal, batchId),
        )
        Batch(batchId, rows(db, "batch_id = ?", batchId))
    }

    @Synchronized
    override fun applyAck(
        batchId: String,
        accepted: Set<String>,
        duplicates: Set<String>,
        rejected: Map<String, String>,
        nowMs: Long,
    ) = inTransaction { db ->
        var acknowledged = 0L
        for (event in rows(db, "batch_id = ? AND state = ${DeliveryState.SUBMITTED.ordinal}", batchId)) {
            when {
                event.eventId in accepted || event.eventId in duplicates -> {
                    db.delete("events", "seq = ?", arrayOf(event.seq.toString()))
                    acknowledged++
                }
                event.eventId in rejected -> db.execSQL(
                    "UPDATE events SET state = ?, batch_id = NULL, reject_reason = ? WHERE seq = ?",
                    arrayOf<Any?>(DeliveryState.REJECTED.ordinal, rejected.getValue(event.eventId).take(200), event.seq),
                )
                // Not mentioned by the server: not acknowledged, so it stays queued.
                else -> db.execSQL(
                    "UPDATE events SET state = ?, batch_id = NULL WHERE seq = ?",
                    arrayOf<Any?>(DeliveryState.QUEUED.ordinal, event.seq),
                )
            }
        }
        if (acknowledged > 0) {
            addCounter(db, ACKNOWLEDGED, acknowledged)
            setCounter(db, LAST_ACK_MS, nowMs)
        }
    }

    @Synchronized
    override fun releaseBatch(batchId: String, countAttempt: Boolean) = inTransaction { db ->
        db.execSQL(
            "UPDATE events SET state = ?, batch_id = NULL, attempts = attempts + ? WHERE batch_id = ? AND state = ?",
            arrayOf<Any?>(DeliveryState.QUEUED.ordinal, if (countAttempt) 1 else 0, batchId, DeliveryState.SUBMITTED.ordinal),
        )
    }

    @Synchronized
    override fun rejectBatch(batchId: String, reason: String) = inTransaction { db ->
        db.execSQL(
            "UPDATE events SET state = ?, batch_id = NULL, reject_reason = ? WHERE batch_id = ? AND state = ?",
            arrayOf<Any?>(DeliveryState.REJECTED.ordinal, reason.take(200), batchId, DeliveryState.SUBMITTED.ordinal),
        )
    }

    @Synchronized
    override fun counts(): QueueCounts {
        val db = readableDatabase
        fun count(state: DeliveryState) =
            scalar(db, "SELECT COUNT(*) FROM events WHERE state = ${state.ordinal}").toInt()
        val oldest = db.rawQuery(
            "SELECT occurred_at FROM events WHERE state IN (?, ?) ORDER BY seq LIMIT 1",
            arrayOf(DeliveryState.QUEUED.ordinal.toString(), DeliveryState.SUBMITTED.ordinal.toString()),
        ).use { if (it.moveToFirst()) it.getString(0) else null }
        return QueueCounts(
            queued = count(DeliveryState.QUEUED),
            submitted = count(DeliveryState.SUBMITTED),
            rejected = count(DeliveryState.REJECTED),
            droppedTotal = counter(db, DROPPED) ?: 0,
            acknowledgedTotal = counter(db, ACKNOWLEDGED) ?: 0,
            lastAcknowledgedAtMs = counter(db, LAST_ACK_MS),
            oldestPendingOccurredAt = oldest,
        )
    }

    @Synchronized
    override fun clear(): Int = inTransaction { db ->
        val n = scalar(db, "SELECT COUNT(*) FROM events").toInt()
        db.execSQL("DELETE FROM events")
        db.execSQL("DELETE FROM counters")
        n
    }

    private fun <T> inTransaction(block: (SQLiteDatabase) -> T): T {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val result = block(db)
            db.setTransactionSuccessful()
            return result
        } finally {
            db.endTransaction()
        }
    }

    private fun rows(db: SQLiteDatabase, where: String, vararg args: String): List<QueuedEvent> =
        db.query("events", null, where, args, null, null, "seq").use { c ->
            buildList { while (c.moveToNext()) add(c.toEvent()) }
        }

    private fun Cursor.toEvent() = QueuedEvent(
        seq = getLong(getColumnIndexOrThrow("seq")),
        eventId = getString(getColumnIndexOrThrow("event_id")),
        type = EventType.fromWire(getString(getColumnIndexOrThrow("type"))),
        occurredAtIso = getString(getColumnIndexOrThrow("occurred_at")),
        dataJson = getString(getColumnIndexOrThrow("data")),
        priority = EventPriority.entries.first { it.value == getInt(getColumnIndexOrThrow("priority")) },
        state = DeliveryState.entries[getInt(getColumnIndexOrThrow("state"))],
        attempts = getInt(getColumnIndexOrThrow("attempts")),
        batchId = getString(getColumnIndexOrThrow("batch_id")),
        rejectReason = getString(getColumnIndexOrThrow("reject_reason")),
    )

    private fun scalar(db: SQLiteDatabase, sql: String): Long =
        db.rawQuery(sql, null).use { if (it.moveToFirst()) it.getLong(0) else 0 }

    private fun counter(db: SQLiteDatabase, name: String): Long? =
        db.rawQuery("SELECT value FROM counters WHERE name = ?", arrayOf(name))
            .use { if (it.moveToFirst()) it.getLong(0) else null }

    private fun setCounter(db: SQLiteDatabase, name: String, value: Long) {
        db.execSQL("INSERT OR REPLACE INTO counters(name, value) VALUES (?, ?)", arrayOf<Any?>(name, value))
    }

    private fun addCounter(db: SQLiteDatabase, name: String, delta: Long) {
        setCounter(db, name, (counter(db, name) ?: 0) + delta)
    }

    companion object {
        const val DB_NAME = "piko-queue.db"
        const val DEFAULT_MAX_EVENTS = 20_000
        private const val VERSION = 1
        private const val MAX_REJECTED_KEPT = 200
        private const val POISON_AFTER = 3
        private const val DROPPED = "dropped"
        private const val ACKNOWLEDGED = "acknowledged"
        private const val LAST_ACK_MS = "last_ack_ms"
    }
}
