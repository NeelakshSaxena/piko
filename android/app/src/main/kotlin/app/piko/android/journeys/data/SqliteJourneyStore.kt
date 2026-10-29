package app.piko.android.journeys.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import app.piko.android.journeys.domain.Arrival
import app.piko.android.journeys.domain.ArrivalBasis
import app.piko.android.journeys.domain.Estimate
import app.piko.android.journeys.domain.GeoPoint
import app.piko.android.journeys.domain.Journey
import app.piko.android.journeys.domain.JourneyEvent
import app.piko.android.journeys.domain.JourneyStatus
import app.piko.android.journeys.domain.JourneyStore
import app.piko.android.journeys.domain.Leg
import app.piko.android.journeys.domain.PendingUpload
import app.piko.android.journeys.domain.TrackingSession
import app.piko.android.journeys.domain.TrackingState
import app.piko.android.journeys.domain.TrackingStore
import app.piko.android.journeys.domain.TransportMode
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * Journeys in their own database file, so the telemetry and outbox schemas are untouched. Times are stored
 * as UTC instants plus the IANA zone they were entered in. `synchronous=FULL`: a saved trip survives
 * process death and power loss.
 */
class SqliteJourneyStore(
    context: Context,
    name: String? = DB_NAME,
) : SQLiteOpenHelper(context.applicationContext, name, null, VERSION), JourneyStore, TrackingStore {

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
        db.rawQuery("PRAGMA synchronous=FULL", null).use { it.moveToFirst() }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE journeys(
                 id TEXT PRIMARY KEY,
                 title TEXT NOT NULL,
                 status TEXT NOT NULL,
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL,
                 synced_updated_at TEXT,
                 revision INTEGER NOT NULL DEFAULT 1,
                 synced_revision INTEGER,
                 upload_attempted INTEGER NOT NULL DEFAULT 0)""",
        )
        db.execSQL(
            """CREATE TABLE journey_legs(
                 id TEXT PRIMARY KEY,
                 journey_id TEXT NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                 sequence INTEGER NOT NULL,
                 mode TEXT NOT NULL,
                 service_number TEXT,
                 origin TEXT NOT NULL,
                 destination TEXT NOT NULL,
                 departure_at TEXT, departure_zone TEXT,
                 arrival_at TEXT, arrival_zone TEXT,
                 dest_lat REAL, dest_lon REAL,
                 est_departure_at TEXT, est_arrival_at TEXT, est_entered_at TEXT,
                 UNIQUE(journey_id, sequence))""",
        )
        db.execSQL("CREATE TABLE journey_deletions(id TEXT PRIMARY KEY)")
        createTrackingTables(db)
    }

    // Tracking state hangs off the journey (not its legs: saving a journey rewrites its legs), so deleting a
    // journey removes its sessions, arrivals and unsent events with it.
    private fun createTrackingTables(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE journey_tracking(
                 journey_id TEXT PRIMARY KEY REFERENCES journeys(id) ON DELETE CASCADE,
                 state TEXT NOT NULL,
                 started_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL,
                 location_detection INTEGER NOT NULL)""",
        )
        db.execSQL(
            """CREATE TABLE journey_arrivals(
                 leg_id TEXT PRIMARY KEY,
                 journey_id TEXT NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                 at TEXT NOT NULL,
                 basis TEXT NOT NULL)""",
        )
        db.execSQL(
            """CREATE TABLE journey_events(
                 seq INTEGER PRIMARY KEY AUTOINCREMENT,
                 id TEXT NOT NULL UNIQUE,
                 journey_id TEXT NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                 type TEXT NOT NULL,
                 occurred_at TEXT NOT NULL,
                 data TEXT NOT NULL,
                 sent INTEGER NOT NULL DEFAULT 0)""",
        )
        db.execSQL("CREATE INDEX journey_events_pending ON journey_events(journey_id, sent, seq)")
        db.execSQL("CREATE TABLE journey_alerts(key TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        check(oldVersion in 1..3 && newVersion == 4) { "no migration from $oldVersion to $newVersion" }
        if (oldVersion < 2) {
            // 1 -> 2: backup bookkeeping, destination coordinates and tracking. Existing journeys are kept and are
            // all "not yet backed up", which is true.
            db.execSQL("ALTER TABLE journeys ADD COLUMN synced_updated_at TEXT")
            db.execSQL("ALTER TABLE journey_legs ADD COLUMN dest_lat REAL")
            db.execSQL("ALTER TABLE journey_legs ADD COLUMN dest_lon REAL")
            db.execSQL("CREATE TABLE journey_deletions(id TEXT PRIMARY KEY)")
            createTrackingTables(db)
        }
        if (oldVersion < 3) {
            // 2 -> 3: the user's expected times, beside the schedule.
            db.execSQL("ALTER TABLE journey_legs ADD COLUMN est_departure_at TEXT")
            db.execSQL("ALTER TABLE journey_legs ADD COLUMN est_arrival_at TEXT")
            db.execSQL("ALTER TABLE journey_legs ADD COLUMN est_entered_at TEXT")
        }
        // 3 -> 4: a revision per saved edit, and a note of whether an upload was ever attempted. A journey the
        // server acknowledged was attempted, and is clean if nothing changed since; all others stay dirty.
        db.execSQL("ALTER TABLE journeys ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
        db.execSQL("ALTER TABLE journeys ADD COLUMN synced_revision INTEGER")
        db.execSQL("ALTER TABLE journeys ADD COLUMN upload_attempted INTEGER NOT NULL DEFAULT 0")
        db.execSQL("UPDATE journeys SET upload_attempted = 1 WHERE synced_updated_at IS NOT NULL")
        db.execSQL("UPDATE journeys SET synced_revision = 1 WHERE synced_updated_at = updated_at")
    }

    @Synchronized
    override fun save(journey: Journey) = inTransaction { db ->
        val row = ContentValues().apply {
            put("id", journey.id)
            put("title", journey.title)
            put("status", journey.status.name)
            put("created_at", journey.createdAt.toString())
            put("updated_at", journey.updatedAt.toString())
        }
        // Every saved edit gets the next revision, whatever the clock says; the server orders writes by it.
        val previous = db.rawQuery("SELECT revision FROM journeys WHERE id = ?", arrayOf(journey.id))
            .use { if (it.moveToFirst()) it.getLong(0) else 0L }
        row.put("revision", previous + 1)
        // Not CONFLICT_REPLACE: that would delete the row first and cascade away the legs of a journey being edited.
        if (db.update("journeys", row, "id = ?", arrayOf(journey.id)) == 0) db.insertOrThrow("journeys", null, row)
        db.delete("journey_legs", "journey_id = ?", arrayOf(journey.id))
        journey.legs.forEachIndexed { sequence, leg ->
            db.insertOrThrow(
                "journey_legs", null,
                ContentValues().apply {
                    put("id", leg.id)
                    put("journey_id", journey.id)
                    put("sequence", sequence)
                    put("mode", leg.mode.name)
                    put("service_number", leg.serviceNumber)
                    put("origin", leg.origin)
                    put("destination", leg.destination)
                    put("departure_at", leg.departure?.toInstant()?.toString())
                    put("departure_zone", leg.departure?.zone?.id)
                    put("arrival_at", leg.arrival?.toInstant()?.toString())
                    put("arrival_zone", leg.arrival?.zone?.id)
                    put("dest_lat", leg.destinationPoint?.latitude)
                    put("dest_lon", leg.destinationPoint?.longitude)
                    put("est_departure_at", leg.estimate?.departure?.toInstant()?.toString())
                    put("est_arrival_at", leg.estimate?.arrival?.toInstant()?.toString())
                    put("est_entered_at", leg.estimate?.enteredAt?.toString())
                },
            )
        }
    }

    @Synchronized
    override fun get(id: String): Journey? = readableDatabase.rawQuery(
        "SELECT * FROM journeys WHERE id = ?", arrayOf(id),
    ).use { if (it.moveToFirst()) it.toJourney(readableDatabase) else null }

    @Synchronized
    override fun list(): List<Journey> = readableDatabase.rawQuery(
        "SELECT * FROM journeys ORDER BY updated_at DESC, id", null,
    ).use { c -> buildList { while (c.moveToNext()) add(c.toJourney(readableDatabase)) } }

    @Synchronized
    override fun delete(id: String): Boolean = inTransaction { db ->
        // A journey the server acknowledged, or one whose upload was at least attempted (the reply may have been
        // lost after the server stored it), may be on the server, so only then is a delete owed to it.
        val onServer = db.rawQuery(
            "SELECT 1 FROM journeys WHERE id = ? AND (synced_updated_at IS NOT NULL OR upload_attempted = 1)", arrayOf(id),
        )
            .use { it.moveToFirst() }
        if (onServer) db.execSQL("INSERT OR IGNORE INTO journey_deletions(id) VALUES (?)", arrayOf(id))
        db.delete("journeys", "id = ?", arrayOf(id)) > 0
    }

    @Synchronized
    override fun setEstimate(journeyId: String, legId: String, estimate: Estimate?) = inTransaction { db ->
        db.update(
            "journey_legs",
            ContentValues().apply {
                put("est_departure_at", estimate?.departure?.toInstant()?.toString())
                put("est_arrival_at", estimate?.arrival?.toInstant()?.toString())
                put("est_entered_at", estimate?.enteredAt?.toString())
            },
            "id = ? AND journey_id = ?", arrayOf(legId, journeyId),
        )
        Unit
    }

    @Synchronized
    override fun dirtyUploads(): List<PendingUpload> = readableDatabase.rawQuery(
        """SELECT * FROM journeys WHERE synced_updated_at IS NULL OR synced_updated_at != updated_at
             OR synced_revision IS NULL OR synced_revision != revision ORDER BY updated_at, id""",
        null,
    ).use { c -> buildList { while (c.moveToNext()) add(PendingUpload(c.toJourney(readableDatabase), c.getLong(c.getColumnIndexOrThrow("revision")))) } }

    @Synchronized
    override fun markSynced(id: String, updatedAt: Instant, revision: Long?): Boolean = inTransaction { db ->
        if (revision == null) {
            db.execSQL("UPDATE journeys SET synced_updated_at = ?, synced_revision = revision WHERE id = ?", arrayOf(updatedAt.toString(), id))
        } else {
            db.execSQL("UPDATE journeys SET synced_updated_at = ?, synced_revision = ? WHERE id = ?", arrayOf<Any>(updatedAt.toString(), revision, id))
        }
        db.rawQuery("SELECT changes()", null).use { it.moveToFirst() && it.getInt(0) > 0 }
    }

    @Synchronized
    override fun markUploadAttempted(id: String): Boolean = inTransaction { db ->
        db.execSQL("UPDATE journeys SET upload_attempted = 1 WHERE id = ?", arrayOf(id))
        db.rawQuery("SELECT changes()", null).use { it.moveToFirst() && it.getInt(0) > 0 }
    }

    @Synchronized
    override fun rebase(id: String, serverRevision: Long) = inTransaction { db ->
        db.execSQL("UPDATE journeys SET revision = MAX(revision, ?) WHERE id = ?", arrayOf<Any>(serverRevision + 1, id))
    }

    @Synchronized
    override fun pendingDeletes(): List<String> = readableDatabase.rawQuery("SELECT id FROM journey_deletions ORDER BY id", null)
        .use { c -> buildList { while (c.moveToNext()) add(c.getString(0)) } }

    @Synchronized
    override fun queueDelete(id: String) = inTransaction { db ->
        db.execSQL("INSERT OR IGNORE INTO journey_deletions(id) VALUES (?)", arrayOf(id))
    }

    @Synchronized
    override fun markDeleteSynced(id: String) = inTransaction { db -> db.execSQL("DELETE FROM journey_deletions WHERE id = ?", arrayOf(id)) }

    @Synchronized
    override fun forgetSync() = inTransaction { db ->
        db.execSQL("UPDATE journeys SET synced_updated_at = NULL, synced_revision = NULL, upload_attempted = 0")
        db.execSQL("DELETE FROM journey_deletions")
    }

    // ---- tracking ----

    @Synchronized
    override fun session(journeyId: String): TrackingSession? = readableDatabase.rawQuery(
        "SELECT * FROM journey_tracking WHERE journey_id = ?", arrayOf(journeyId),
    ).use { if (it.moveToFirst()) it.toSession() else null }

    @Synchronized
    override fun followed(): TrackingSession? = readableDatabase.rawQuery(
        "SELECT * FROM journey_tracking WHERE state != ? ORDER BY updated_at DESC LIMIT 1", arrayOf(TrackingState.STOPPED.name),
    ).use { if (it.moveToFirst()) it.toSession() else null }

    @Synchronized
    override fun saveSession(session: TrackingSession) = inTransaction { db ->
        db.execSQL(
            "INSERT OR REPLACE INTO journey_tracking(journey_id, state, started_at, updated_at, location_detection) VALUES (?, ?, ?, ?, ?)",
            arrayOf<Any>(
                session.journeyId, session.state.name, session.startedAt.toString(), session.updatedAt.toString(),
                if (session.locationDetection) 1 else 0,
            ),
        )
    }

    @Synchronized
    override fun arrivals(journeyId: String): List<Arrival> = readableDatabase.rawQuery(
        "SELECT leg_id, at, basis FROM journey_arrivals WHERE journey_id = ? ORDER BY at", arrayOf(journeyId),
    ).use { c -> buildList { while (c.moveToNext()) add(Arrival(c.getString(0), Instant.parse(c.getString(1)), ArrivalBasis.valueOf(c.getString(2)))) } }

    @Synchronized
    override fun recordArrival(journeyId: String, arrival: Arrival): Boolean = inTransaction { db ->
        db.insertWithOnConflict(
            "journey_arrivals", null,
            ContentValues().apply {
                put("leg_id", arrival.legId)
                put("journey_id", journeyId)
                put("at", arrival.at.toString())
                put("basis", arrival.basis.name)
            },
            SQLiteDatabase.CONFLICT_IGNORE,
        ) != -1L
    }

    @Synchronized
    override fun appendEvent(event: JourneyEvent) = inTransaction { db ->
        db.insertWithOnConflict(
            "journey_events", null,
            ContentValues().apply {
                put("id", event.id)
                put("journey_id", event.journeyId)
                put("type", event.type)
                put("occurred_at", event.occurredAt.toString())
                put("data", JSONObject(event.data.mapValues { it.value ?: JSONObject.NULL }).toString())
            },
            SQLiteDatabase.CONFLICT_IGNORE,
        )
        Unit
    }

    @Synchronized
    override fun pendingEvents(journeyId: String, limit: Int): List<JourneyEvent> = readableDatabase.rawQuery(
        "SELECT id, journey_id, type, occurred_at, data FROM journey_events WHERE journey_id = ? AND sent = 0 ORDER BY seq LIMIT ?",
        arrayOf(journeyId, limit.toString()),
    ).use { c ->
        buildList {
            while (c.moveToNext()) {
                val json = JSONObject(c.getString(4))
                add(
                    JourneyEvent(
                        c.getString(0), c.getString(1), c.getString(2), Instant.parse(c.getString(3)),
                        json.keys().asSequence().associateWith { k -> json.get(k).takeIf { it != JSONObject.NULL } },
                    ),
                )
            }
        }
    }

    @Synchronized
    override fun journeysWithPendingEvents(): List<String> = readableDatabase.rawQuery(
        "SELECT DISTINCT journey_id FROM journey_events WHERE sent = 0 ORDER BY journey_id", null,
    ).use { c -> buildList { while (c.moveToNext()) add(c.getString(0)) } }

    @Synchronized
    override fun markEventsSent(ids: List<String>) = inTransaction { db ->
        ids.forEach { db.execSQL("UPDATE journey_events SET sent = 1 WHERE id = ?", arrayOf(it)) }
    }

    @Synchronized
    override fun pruneEvents(cutoff: Instant): Int = inTransaction { db ->
        db.delete("journey_events", "sent = 1 OR occurred_at < ?", arrayOf(cutoff.toString()))
    }

    @Synchronized
    override fun claimAlert(key: String, at: Instant): Boolean = inTransaction { db ->
        db.insertWithOnConflict(
            "journey_alerts", null,
            ContentValues().apply {
                put("key", key)
                put("created_at", at.toString())
            },
            SQLiteDatabase.CONFLICT_IGNORE,
        ) != -1L
    }

    @Synchronized
    override fun pruneAlerts(cutoff: Instant): Int = inTransaction { db -> db.delete("journey_alerts", "created_at < ?", arrayOf(cutoff.toString())) }

    private fun Cursor.toSession() = TrackingSession(
        journeyId = getString(getColumnIndexOrThrow("journey_id")),
        state = TrackingState.valueOf(getString(getColumnIndexOrThrow("state"))),
        startedAt = Instant.parse(getString(getColumnIndexOrThrow("started_at"))),
        updatedAt = Instant.parse(getString(getColumnIndexOrThrow("updated_at"))),
        locationDetection = getInt(getColumnIndexOrThrow("location_detection")) == 1,
    )

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

    private fun Cursor.toJourney(db: SQLiteDatabase): Journey {
        val id = getString(getColumnIndexOrThrow("id"))
        val legs = db.rawQuery("SELECT * FROM journey_legs WHERE journey_id = ? ORDER BY sequence", arrayOf(id))
            .use { c -> buildList { while (c.moveToNext()) add(c.toLeg()) } }
        return Journey(
            id = id,
            title = getString(getColumnIndexOrThrow("title")),
            status = JourneyStatus.valueOf(getString(getColumnIndexOrThrow("status"))),
            legs = legs,
            createdAt = Instant.parse(getString(getColumnIndexOrThrow("created_at"))),
            updatedAt = Instant.parse(getString(getColumnIndexOrThrow("updated_at"))),
        )
    }

    private fun Cursor.toLeg(): Leg {
        fun str(col: String): String? = getString(getColumnIndexOrThrow(col))
        fun time(at: String, zone: String): ZonedDateTime? =
            str(at)?.let { ZonedDateTime.ofInstant(Instant.parse(it), ZoneId.of(str(zone))) }
        // An estimate is shown in the zone of the schedule it refers to.
        fun estimate(): Estimate? {
            val entered = str("est_entered_at") ?: return null
            fun at(col: String, zoneCol: String): ZonedDateTime? =
                str(col)?.let { ZonedDateTime.ofInstant(Instant.parse(it), ZoneId.of(str(zoneCol) ?: "UTC")) }
            return Estimate(at("est_departure_at", "departure_zone"), at("est_arrival_at", "arrival_zone"), Instant.parse(entered))
        }
        return Leg(
            id = str("id")!!,
            mode = TransportMode.valueOf(str("mode")!!),
            serviceNumber = str("service_number"),
            origin = str("origin")!!,
            destination = str("destination")!!,
            departure = time("departure_at", "departure_zone"),
            arrival = time("arrival_at", "arrival_zone"),
            destinationPoint = if (isNull(getColumnIndexOrThrow("dest_lat"))) null else
                GeoPoint(getDouble(getColumnIndexOrThrow("dest_lat")), getDouble(getColumnIndexOrThrow("dest_lon"))),
            estimate = estimate(),
        )
    }

    companion object {
        const val DB_NAME = "piko-journeys.db"
        private const val VERSION = 4
    }
}
