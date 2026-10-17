# Migration 0004 and remote test-schema status (2026-10-17)

Method: a read-only Python script (`SET TRANSACTION READ ONLY`, `default_transaction_read_only=on`) listed
schemas matching `piko%`, read `alembic_version`, table names and **row counts only**. No row contents were
read, nothing was written or dropped. The database URL was not printed.

## Findings
| Schema | Alembic version | Tables | Notes |
|---|---|---|---|
| `piko` (configured persistent schema, `PIKO_DB_SCHEMA=piko`) | **0003** | 12 | 1 family, 4 users, 2 devices, 100 telemetry events, 103 audit rows. This is the operator's development data. **Migration 0004 is NOT applied.** |
| `piko_test_e2e_1fc14f` | 0004 | 14 | Created by this work for the emulator run (5 SOS, 4 messages, 6 telemetry events). Disposable. |
| `piko_test_a39da344` | 0003 | 12 | **Not created by Phase 6 work** (version 0003 predates 0004; 52 users, 38 families). Looks like a test run that was interrupted before cleanup. |
| `piko_test_4aa04b19` | 0003 | 12 | Same: interrupted test run (16 users, 15 families). |
`anon` and `authenticated` (Supabase API roles) have no USAGE on any of these schemas.

## Is 0004 the right next migration?
- Chain: `0001 -> 0002 -> 0003 -> 0004` (`down_revision = "0003"`). The persistent schema is at 0003, so 0004 is the next and only pending revision.
- Content: creates `sos_incidents` and `messages` (+3 indexes) and replaces one CHECK constraint (`audit_events_action_check`) by a **superset** (adds `sos_acknowledged`). No existing row can violate it; no column of an existing table changes; no data is rewritten.
- Evidence it works: `test_migrations.py` (head creates all 14 tables; models and migrations agree via `compare_metadata`; upgrade from 0001 preserves data; idempotent upgrade; downgrade 0004->0003->0002->0001->base->head; see the upgrade-with-data test added for 0003 -> 0004). Run against throwaway schemas on the same database server.
- Rollback: `alembic downgrade 0003` **drops `sos_incidents` and `messages` with their contents** (safety records) after deleting `sos_acknowledged` audit rows. Back up before any downgrade once real incidents exist.

## Plan to apply 0004 to `piko` (needs your explicit approval; NOT executed)
1. Confirm `piko` is the intended development database (it is the schema named in `.env.example` and used by earlier phases) and that the 1 family in it is test data (the earlier report calls it "TEST FAMILY (safe to delete)").
2. Back up first. Options: Supabase dashboard backup/point-in-time snapshot, or `pg_dump --schema=piko` from a machine that has it (not installed in the project toolchain; installing it needs your approval).
3. Apply: `cd backend; ..\.venv\Scripts\python -m alembic upgrade head` (runs with the `.env` settings, `PIKO_DB_SCHEMA=piko`). Each migration runs in its own transaction.
4. Verify: `alembic_version` = `0004`; 14 tables; run the inspection script again; start the server and call `GET /api/v1/health/ready`.
5. If it fails: nothing is half-applied (transactional DDL in PostgreSQL); restore from the backup only if needed.

## Cleanup plan for leftover schemas (NOT executed; destructive)
Each statement drops one schema and everything in it. The schema name was verified above and carries the
`piko_test_` prefix that the test harness uses and refuses to drop anything without.
```sql
DROP SCHEMA "piko_test_e2e_1fc14f" CASCADE;   -- created by this work, disposable
DROP SCHEMA "piko_test_a39da344" CASCADE;     -- interrupted earlier test run (verify with the operator)
DROP SCHEMA "piko_test_4aa04b19" CASCADE;     -- interrupted earlier test run (verify with the operator)
```
Please approve the exact schemas you want dropped. I will not run any of them without that approval.
Never run a `DROP` against `piko`.
