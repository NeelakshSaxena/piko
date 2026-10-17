package app.piko.android.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import app.piko.android.core.CommItem
import app.piko.android.core.CommKind
import app.piko.android.core.CommState
import app.piko.android.core.CommStore
import app.piko.android.core.NewComm
import app.piko.android.core.POISON_AFTER
import app.piko.android.core.SosPoint
import app.piko.android.core.remoteRank

/**
 * Durable outbox for SOS and messages, in its own database file so the telemetry queue's schema is
 * untouched. `synchronous=FULL`: a committed SOS survives process death and power loss, and it is
 * committed before the first network attempt.
 */
class SqliteCommStore(
    context: Context,
    name: String? = DB_NAME,
) : SQLiteOpenHelper(context.applicationContext, name, null, VERSION), CommStore {

    override fun onConfigure(db: SQLiteDatabase) {
        db.rawQuery("PRAGMA synchronous=FULL", null).use { it.moveToFirst() }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE comms(
                 seq INTEGER PRIMARY KEY AUTOINCREMENT,
                 id TEXT NOT NULL UNIQUE,
                 kind INTEGER NOT NULL,
                 created_at TEXT NOT NULL,
                 text TEXT,
                 lat REAL, lon REAL, accuracy REAL,
                 state INTEGER NOT NULL,
                 attempts INTEGER NOT NULL DEFAULT 0,
                 fail_reason TEXT,
                 delivered_at_ms INTEGER,
                 remote_status TEXT,
                 acknowledged_at TEXT,
                 resolved_at TEXT)""",
        )
        db.execSQL("CREATE INDEX comms_pending ON comms(state, kind, seq)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        error("no migrations exist yet (from $oldVersion to $newVersion)")
    }

    @Synchronized
    override fun enqueue(comm: NewComm, nowMs: Long): Boolean = inTransaction { db ->
        val values = ContentValues().apply {
            put("id", comm.id)
            put("kind", comm.kind.ordinal)
            put("created_at", comm.createdAt.toString())
            put("text", comm.text)
            comm.location?.let {
                put("lat", it.latitude)
                put("lon", it.longitude)
                it.accuracyMeters?.let { a -> put("accuracy", a) }
            }
            put("state", CommState.QUEUED.ordinal)
        }
        db.insertWithOnConflict("comms", null, values, SQLiteDatabase.CONFLICT_IGNORE) != -1L
    }

    @Synchronized
    override fun next(): CommItem? {
        val db = readableDatabase
        return db.rawQuery(
            "SELECT * FROM comms WHERE state IN (?, ?) ORDER BY (attempts >= $POISON_AFTER) ASC, kind ASC, seq ASC LIMIT 1",
            arrayOf(CommState.QUEUED.ordinal.toString(), CommState.SUBMITTED.ordinal.toString()),
        ).use { if (it.moveToFirst()) it.toItem() else null }
    }

    @Synchronized
    override fun markSubmitted(id: String) = inTransaction { db ->
        db.execSQL(
            "UPDATE comms SET state = ? WHERE id = ? AND state IN (?, ?)",
            arrayOf<Any?>(CommState.SUBMITTED.ordinal, id, CommState.QUEUED.ordinal, CommState.SUBMITTED.ordinal),
        )
    }

    @Synchronized
    override fun markDelivered(id: String, remoteStatus: String, acknowledgedAtIso: String?, resolvedAtIso: String?, nowMs: Long) =
        inTransaction { db ->
            db.execSQL(
                """UPDATE comms SET state = ?, remote_status = ?, acknowledged_at = ?, resolved_at = ?, delivered_at_ms = ?
                   WHERE id = ? AND state IN (?, ?)""",
                arrayOf<Any?>(
                    CommState.DELIVERED.ordinal, remoteStatus, acknowledgedAtIso, resolvedAtIso, nowMs,
                    id, CommState.QUEUED.ordinal, CommState.SUBMITTED.ordinal,
                ),
            )
        }

    @Synchronized
    override fun release(id: String, countAttempt: Boolean) = inTransaction { db ->
        db.execSQL(
            "UPDATE comms SET state = ?, attempts = attempts + ? WHERE id = ? AND state = ?",
            arrayOf<Any?>(CommState.QUEUED.ordinal, if (countAttempt) 1 else 0, id, CommState.SUBMITTED.ordinal),
        )
    }

    @Synchronized
    override fun markFailed(id: String, reason: String) = inTransaction { db ->
        db.execSQL(
            "UPDATE comms SET state = ?, fail_reason = ? WHERE id = ? AND state IN (?, ?)",
            arrayOf<Any?>(CommState.FAILED.ordinal, reason.take(200), id, CommState.QUEUED.ordinal, CommState.SUBMITTED.ordinal),
        )
    }

    @Synchronized
    override fun applyRemote(id: String, remoteStatus: String, acknowledgedAtIso: String?, resolvedAtIso: String?): Boolean =
        inTransaction { db ->
            val current = db.rawQuery(
                "SELECT * FROM comms WHERE id = ? AND state = ?",
                arrayOf(id, CommState.DELIVERED.ordinal.toString()),
            ).use { if (it.moveToFirst()) it.toItem() else null } ?: return@inTransaction false
            if (remoteRank(current.kind, remoteStatus) <= remoteRank(current.kind, current.remoteStatus)) {
                return@inTransaction false
            }
            db.execSQL(
                "UPDATE comms SET remote_status = ?, acknowledged_at = ?, resolved_at = ? WHERE id = ?",
                arrayOf<Any?>(remoteStatus, acknowledgedAtIso ?: current.acknowledgedAtIso, resolvedAtIso ?: current.resolvedAtIso, id),
            )
            true
        }

    @Synchronized
    override fun items(limit: Int): List<CommItem> =
        readableDatabase.rawQuery("SELECT * FROM comms ORDER BY seq DESC LIMIT ?", arrayOf(limit.toString()))
            .use { c -> buildList { while (c.moveToNext()) add(c.toItem()) } }

    @Synchronized
    override fun pendingCount(): Int =
        readableDatabase.rawQuery(
            "SELECT COUNT(*) FROM comms WHERE state IN (?, ?)",
            arrayOf(CommState.QUEUED.ordinal.toString(), CommState.SUBMITTED.ordinal.toString()),
        ).use { if (it.moveToFirst()) it.getInt(0) else 0 }

    @Synchronized
    override fun clear(): Int = inTransaction { db ->
        val n = db.rawQuery("SELECT COUNT(*) FROM comms", null).use { if (it.moveToFirst()) it.getInt(0) else 0 }
        db.execSQL("DELETE FROM comms")
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

    private fun Cursor.toItem(): CommItem {
        fun str(col: String) = getString(getColumnIndexOrThrow(col))
        fun isNull(col: String) = isNull(getColumnIndexOrThrow(col))
        val location = if (isNull("lat") || isNull("lon")) {
            null
        } else {
            SosPoint(
                getDouble(getColumnIndexOrThrow("lat")),
                getDouble(getColumnIndexOrThrow("lon")),
                if (isNull("accuracy")) null else getDouble(getColumnIndexOrThrow("accuracy")),
            )
        }
        return CommItem(
            id = str("id"),
            kind = CommKind.entries[getInt(getColumnIndexOrThrow("kind"))],
            createdAtIso = str("created_at"),
            text = str("text"),
            location = location,
            state = CommState.entries[getInt(getColumnIndexOrThrow("state"))],
            attempts = getInt(getColumnIndexOrThrow("attempts")),
            failReason = str("fail_reason"),
            deliveredAtMs = if (isNull("delivered_at_ms")) null else getLong(getColumnIndexOrThrow("delivered_at_ms")),
            remoteStatus = str("remote_status"),
            acknowledgedAtIso = str("acknowledged_at"),
            resolvedAtIso = str("resolved_at"),
        )
    }

    companion object {
        const val DB_NAME = "piko-comms.db"
        private const val VERSION = 1
    }
}
