# Journeys: provider setup, manual mode and verification (2026-10-29)

Scope: ADR-027 (optional Aviationstack / RailRadar lookups), regression of ADR-025/026. **No phase gate is claimed as passed.**
Provider tests are **mocked HTTP only**: `.env` held no provider key, so no live call was made and no live integration is claimed.

## Provider documentation read (2026-10-29)
- Aviationstack (docs.apilayer.com/aviationstack, aviationstack.com/product): base `https://api.aviationstack.com/v1/`, auth `access_key` query parameter, errors `invalid_access_key`, `missing_access_key`, `inactive_user`, `function_access_restricted`, `usage_limit_reached`, `rate_limit_reached`, `internal_error`. Free: 100 requests/month, non-commercial; historical `flight_date` and schedules are paid. Response shape taken from APILayer's own sample; the full field reference page was not retrievable, so unlisted fields are not used. Timestamp offsets in that sample could not be verified, so no timestamp is used.
- RailRadar (railradar.in/docs, /docs/live-train-status, /pricing): base `https://api.railradar.in/v1`, `Authorization: Bearer`, envelope `{success,data,meta}` / `{success:false,error}`, errors 400/401/404/429/503. Free: 100 requests/month, 10/min, non-commercial. Paid from INR 499 (first month, then 999), 30,000/month.

## Results
| Check | Command | Result |
|---|---|---|
| Backend lint/format/types | `ruff check backend`, `ruff format --check backend`, `mypy backend/app` | clean (81 files formatted, 43 source files) |
| Provider adapters, mocked (42 tests, no DB) | `pytest tests/test_live_data.py -k "not api_"` | 42 pass: success, 401/403, 429, 5xx, timeout, network error, malformed/non-JSON/wrong shape, wrong date/flight/train, codeshare, missing key, manual mode, cache, cooldown, key redaction (logs, repr, settings dump) |
| Live-data API (4 tests) + journeys + migrations | `pytest tests/test_live_data.py tests/test_api_journeys.py tests/test_migrations.py` | 66 pass: device-only access, input validation, 10/min limit, key never in a response, default manual calls nothing, lookup changes no journey |
| Full backend suite, serial | `pytest tests -q` (47 min) | **494 passed, 1 skipped** (POSIX file modes), 0 failed |
| Android JVM | `gradle :app:testDebugUnitTest --offline --no-daemon` | **199 run, 0 failed** (184 + 15 live-status: request shaping, window, suggestion, stale/cancelled/not-live, missing delay stays missing, wire parsing, all failure states) |
| Android emulator, full suite | `gradle :app:connectedDebugAndroidTest "-Ppiko.versionCode=99"` | **93 run, 0 failed** |
| Android lint | `gradle :app:lintDebug --offline` | **not run**: cannot resolve `lint-gradle:32.4.1` offline |
| Minified release build | `gradle :app:assembleRelease --offline` | **not run**: cannot resolve `compose-group-mapping:2.4.21` offline. R8 output is unverified |

Manual-mode coverage: create/edit/save/reload/delete, expected times, connection arithmetic, following, reminders, backup and offline recovery are covered by the existing JVM, contract, durability and migration tests (all passing above). They need no key. "Manual values survive provider errors and stale responses" holds by construction and by test: a lookup writes nothing (server stores nothing; the API test compares the journey list before and after) and the phone only pre-fills boxes on a tap.

## Remote database drops
Earlier parallel runs (three pytest processes) produced 6 `server closed the connection unexpectedly` / `503` failures; each passed alone. The serial full run above had **zero**. The database is a Supabase Supavisor session-mode pooler (port 5432). Likely cause: three processes each opening two engines (up to 10 connections each) exceeded the pooler's client cap. This is consistent with the evidence but **not proven** (no pooler limit was read). Run the suite serially.

## Migration 0007 review (not applied)
- Upgrade only creates `journeys`, `journey_legs`, `journey_events` and two indexes; no existing table or row is touched. Downgrade drops those three tables (destroying any backed-up journeys).
- The schema is at `0006` (read-only `alembic current`). The only backup on disk, `.data/backups/piko-pre-0006-20261027.gz`, has a matching checksum but is revision **0005**, so it is **not** a restore point for this change (restore requires the same revision). **No verified backup at 0006 exists.**
- Safe sequence, from the repo root (nothing here has been run):
  1. `cd backend; ..\.venv\Scripts\python -m alembic current` (expect `0006`), `..\.venv\Scripts\python -m alembic heads` (expect `0007`).
  2. `..\.venv\Scripts\python -m app.cli backup --out ..\.data\backups\piko-pre-0007-<date>.gz` (writes `.sha256`; prints the revision, which must be `0006`).
  3. Verify: compare the checksum, then restore into a throwaway schema (`PIKO_DB_SCHEMA=piko_drill`, `alembic upgrade 0006`, `restore --file ...`, `doctor`). Drop the drill schema only with your approval.
  4. `..\.venv\Scripts\python -m alembic upgrade 0007`, then `alembic current`, `python -m app.cli doctor`, and `GET /api/v1/health/ready`.
  5. Rollback if needed: `alembic downgrade 0006` (only after confirming no one needs the journeys backed up since).

## Not verified / outstanding
- **Live provider calls**: none (no keys). Aviationstack's full response reference, timestamp semantics, and Indian airline/airport coverage are unverified; RailRadar's accuracy, licence for non-personal use, and cancellation vocabulary are unverified.
- **Physical device**: none attached. Battery, Doze, OEM battery managers, background tracking, arrival detection while moving, and offline reminders remain unmeasured (`docs/BATTERY_TEST_PROTOCOL.md`).
- **Screens**: never viewed running (needs a paired phone and a live backend); no screenshot, TalkBack or large-text pass. The new live-check card is compiled and its logic unit-tested only.
- **Lint and release build**: blocked offline (above).
- **No independent audit** of the live-data path.

## Gate
Not passed for any phase. Phases 0-1 storage criterion unchanged; phase 2 migration unapplied; phases 3-6 hardware, UI and audit checks outstanding.

---

# Second pass (2026-10-29, later): drill, lint, release build, CI workflow, emulator, audit

## Live provider checks: BLOCKED
No provider key exists in `.env` (checked by name only; values never read). `PIKO_AVIATIONSTACK_API_KEY` and `PIKO_RAILRADAR_API_KEY` are empty, so **no live call was made and no live integration is claimed.** All provider results are mocked HTTP. To run them: put the keys in `.env` yourself (never in chat), set the two `*_DATA_PROVIDER` variables, then run one lookup per provider from the Journeys dialog; both free plans allow only 100 requests a month and are non-commercial.

## Results (serial wherever a database is involved)
| Check | Command | Result |
|---|---|---|
| Backend full suite, serial | `pytest tests -q` (53 min) | **499 passed, 1 skipped** (POSIX file modes), 0 failed |
| Backend lint/format/types | `ruff check`, `ruff format --check`, `mypy backend/app` | clean |
| Provider adapters + API, **mocked** | `pytest tests/test_live_data.py` | 50 pass |
| Android JVM | `gradle :app:testDebugUnitTest` | **199 run, 0 failed** |
| Android emulator (API 36, AVD `Piko_Test_Device`) | `gradle :app:connectedDebugAndroidTest -Ppiko.versionCode=99` | **93 run, 0 failed** (journey stores, v1->v3 migration, tracking lifecycle, durability) |
| Android lint | `gradle :app:lintDebug` (artifacts downloaded into the project-local `.gradle-home`) | **0 errors**, 35 warnings/infos (39 before fixes); remaining Journeys ones: an intentional `commit()` and two KTX style hints |
| Minified release build | `gradle :app:assembleRelease` | built: `app-release-unsigned.apk`, 3,658,465 bytes, R8 mapping produced. It is **unsigned** (no signing config exists) |
| Release installability | signed a copy with a **throwaway local key** (`apksigner`, v3 verifies), `adb install`, cold start | installed, started in about 4 s, no `AndroidRuntime` errors, not debuggable, minSdk 31. The throwaway key is for this test only; it is **not** a release signature |
| Workflow | YAML parsed; the collect/checksum/metadata step run locally against real outputs (checksums verify, JSON valid); action SHAs checked against upstream tags | **a real GitHub Actions run has NOT happened** (nothing pushed); no artifact URL exists |

Notes: offline, `assembleRelease` and `lintDebug` failed only because two artifacts were missing; online they resolve. One
`compose-group-mapping` download failed once with a transient network error and passed on retry. A first release build was
killed by memory pressure on this PC (other programs were using most of the RAM) and passed with a smaller heap.

## Migration 0007: backup and restore drill (NOT applied)
- Target confirmed: schema `piko`, revision `0006`, `PIKO_ENV=development`. The scratch schema `piko_drill_c90445` differs by name.
- Finding: backing up with the working-tree code failed (`relation "journeys" does not exist`) because the code is ahead of the schema. The backup tool now says so clearly and leaves no file (new test); the drill used an export of the deployed commit `953588f`.
- Backup `.data/backups/piko-pre-0007-20261029-0115.gz` (git-ignored): revision 0006, 16 tables, 417 rows, sha256 `b2a8f2d3ef9c639af39bc7763b4528a9d81edb5ee9c4f989e7aa3cd7dcbd474a`, checksum file matches, gzip intact.
- Restore into the scratch schema: 417 rows; per-table counts equal production for all 16 tables.
- `0007` on the scratch copy: up to `0007` (tables `journeys`, `journey_legs`, `journey_events`; indexes `ix_journeys_device_updated`, `ix_journey_events_journey`; check constraints on status, mode and event type; cascade only from journeys to legs and events), down to `0006` (journey tables gone, the other 16 tables unchanged), up again.
- Production stayed at `0006` throughout. **The scratch schema still exists** (it holds a full copy of family data); dropping it needs your approval.
- Exact production sequence, from `backend/` with the **deployed** code, after you approve:
  1. `python -m alembic current` (expect `0006`)
  2. a fresh `python -m app.cli backup --out ..\.data\backups\piko-pre-0007-<date>.gz` (the 20261029-0115 file is acceptable if nothing has changed since)
  3. `python -m alembic upgrade 0007`, then `python -m alembic current`, `python -m app.cli doctor`, and `GET /api/v1/health/ready`
  4. rollback if needed: `python -m alembic downgrade 0006` (destroys any journeys backed up since)

## Emulator UI evidence (debug build, local backend on a throwaway schema, since dropped)
Screenshots are under `.tmp/shots/` (not committed). Verified on the AVD: the first screen of the minified release build; the Journeys list with the backup switch off; creating a train leg and saving it as planned; the expected-time dialog; "Check live status" in manual mode ("Live data is switched off on your server"), with the server stopped ("No connection to your server... unchanged") and with a provider selected but no key ("Your server has no key..."); start following, pause, resume and stop. Pairing needed the emulator host `10.0.2.2` added to the local server's allowed hosts (local setup only).
**Not verified:** a TalkBack pass (an automated check found touch targets of at least 48 dp, and clickable containers take their labels from child text, which TalkBack merges, but nothing was read aloud); large text on the Journeys screens (changing the font scale restarted the app on Home, so only Home was seen at 1.5x); arrival by location while moving; the "I've arrived" tap; reminders firing; any provider-sourced reading.

## Audit
`docs/verification/journeys-independent-audit.md`: 0 Critical, 0 High, 6 Medium, 9 Low, 4 Info. Fixed: L1, L2, L4, L7, L8, L9; partly: M5, M6. Open: M1-M4, L3, L5, L6, and M6's global budget. No dependency scan was possible offline.

## Mistake made during this pass (disclosed)
A throwaway fixture script passed `.data/keys` to the test helper `build_settings`, which writes a fresh `hmac.key` when `jwt.pem` is missing. **The local dev `.data/keys/hmac.key` was overwritten** (a stray `jwt.pem` was also created, then removed). The previous key could not be recovered here. Production uses its own host secret and was not touched, but if that secret was ever copied from this local file, only the deployed copy still exists. Check this before relying on the local file.

## Physical device
Still none. Battery cost, Doze, OEM battery managers, background tracking and movement-based arrival detection are **unmeasured**; the emulator proves lifecycle only.

## Phase gates
Unchanged and **not passed**: phases 0-1 storage criterion met earlier; phase 2 blocked on the unapplied migration and open audit Mediums M1-M4; phases 3-6 blocked on hardware, TalkBack and live-provider checks.
