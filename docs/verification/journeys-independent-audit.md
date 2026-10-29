# Journeys: independent audit (2026-10-29)

Reviewer: a separate, fresh, read-only reviewer (a subagent given no knowledge of the tests' intent), reading the uncommitted
tree. It ran no tests, touched no database or network and did not read `.env`, `.data/` or key files. Its tool caveats:
`mypy` crashed in its own invocation (the implementing session's `mypy backend/app` is clean), `bandit` is not installed, and
`pip-audit` needs the network, so no dependency-vulnerability scan was run. **This is a model-assisted review, not a
third-party penetration test.**

Result: **0 Critical, 0 High, 6 Medium, 9 Low, 4 Info.** No cross-device, cross-family or parent-account access path and no
provider-key exposure path was found. Everything the reviewer verified as sound is listed at the end.

## Findings and disposition
| ID | Sev | Finding | Disposition |
|---|---|---|---|
| M1 | Med | A journey deleted on the phone after a PUT whose reply was lost (never marked synced) queued no server delete | **FIXED** (ADR-028): the phone records an upload attempt before sending; a delete of any attempted journey is queued durably (DB v4) and retried until the server answers; a journey deleted after the pending list was read is never sent. Re-audit N1 fixed. Tests: JVM `JourneyBackupRegressionTest`, emulator durability/contract/migration tests |
| M2 | Med | `applied=false` was treated as success; a phone clock stepped backwards made edits silently not back up | **FIXED**: ordering and "synced" use a per-journey revision, not the clock; a server revision above the one sent is `Stale` (never "backed up"), the phone rebases above it, retries, and the UI shows it as waiting / could not be backed up; owed deletes count as waiting |
| M3 | Med | Tombstones never purged; deleting an unseen id inserts one | **FIXED**: 30-day retention (per-device purge + retention job, plus journeys of devices revoked > 30 days), cap of 1000 per device, partial index. Documented in ADR-028 / API_CONTRACTS. Deleting a real journey always works |
| M4 | Med | Server clamped `updated_at` instead of rejecting; a late replay of an older edit could overwrite a newer one | **FIXED**: server applies a write only if its `revision` is strictly higher; `updated_at` is display order and never moves backwards. Tests include a fast-clock replay |
| M5 | Med | Aviationstack's free plan may not serve HTTPS (unverified); the tempting workaround, `http://`, would send the key in clear | **PARTLY FIXED.** Test now asserts both provider URLs are `https://`; docs say never to switch to `http` and to use a paid plan if HTTPS is refused. An HTTPS-refused answer shows as "unusable" |
| M6 | Med | Any enrolled device could spend the shared provider quota | **FIXED** (bounded, not eliminated): DB-backed daily (10) and monthly (90) budget per provider, advisory-locked, fails closed; single-flight; `UNUSABLE` answers pause the provider 60 s. A paired device can still use up the shared budget (re-audit N3, accepted: it is the point of a budget, and resets daily/monthly) |
| L1 | Low | `$` in the number regexes accepted a trailing newline (distinct cache key, wasted call) | **FIXED** (`fullmatch`; tested) |
| L2 | Low | NaN/inf: event values (poison batch blocks a device's sync) and provider delays (`int()` raised, 60 s provider cooldown) | **FIXED** (`allow_inf_nan=False`; finite check; tested) |
| L3 | Low | `add_events` racing `delete` can leave orphan events until the 90-day rule; 5000-event cap not atomic | **OPEN**, low impact |
| L4 | Low | RailRadar: a missing `isLive` was treated as live | **FIXED** (a delay is "current" only if `isLive` is true; `LIVE_UNCONFIRMED` notice; tested) |
| L5 | Low | Arrival detection: the 12-fix buffer is not cleared on a manual arrival, so a short next leg could be "arrived" at once; slow traffic near a destination for 2 min can trigger it; mock locations not rejected | **OPEN.** Clear fixes on leg change; reject mock locations. Arrival is always labelled "noticed by location (not confirmed by you)" |
| L6 | Low | `JourneyAlarmReceiver` and `PikoApp.onCreate` do SQLite work on the main thread; notification-id hash collisions | **OPEN** |
| L7 | Low | Wording too strong: "Off. Nothing leaves this phone" (a live check sends one number; a pending delete is sent), "Your family cannot see them" (the server operator and logical backups hold journeys in plaintext) | **FIXED** (backup-switch text now says live check sends one number; `docs/JOURNEYS.md` states operator/backup visibility). Delete wording tied to M1 |
| L8 | Low | Manual dispatch from any branch could publish a debug APK as `android-latest`; CI debug key differs per run so builds cannot update each other | **FIXED** (publish job limited to `main`/`deployment`; comment corrected) |
| L9 | Low | `vars.PIKO_API_URL` interpolated into a shell command | **FIXED** (passed through `env:`) |
| I1-I4 | Info | Existence oracle only for guessed 122-bit ids; refused events are discarded (documented); event `data` keys not allow-listed server-side; downgrade drops tables with no guard, FKs without `ON DELETE`/indexes | Noted; no action now |

## Verified sound (reviewer's list)
Ownership checked on every journey route (`device_id`, never family or parent); user tokens refused; other-device and
missing rows give the same error; tombstoned rows leak nothing; `/journeys/live/*` routed before `/{journey_id}`; strict
request schemas and caps; the provider key is a `SecretStr`, read in one place, never logged or returned, no
provider text kept; httpx logging muted; hard-coded provider hosts, parameters passed through httpx; in-memory cache holds
only public data and is bounded; all new Android components not exported, immutable PendingIntents, boot receiver checks its
action, `allowBackup=false`, tracking service not sticky with visible notification, positions kept in memory only; a user tap
is required for each live lookup; CI permissions are read-only except the opt-in publish job, actions SHA-pinned (the
implementing session verified `download-artifact` v4.1.9 and `upload-artifact` v4.6.1 against the upstream tags).

## Could not verify
`mypy` under the reviewer; the request-body size cap (none found in `main.py`/`core`, may live at the host); HTTP mapping of
`NOT_FOUND_OR_NOT_VISIBLE`; real provider behaviour; whether `dataExtractionRules` covers `piko-journeys.db`; battery,
OEM and foreground-service behaviour on hardware; dependency vulnerabilities (no offline scanner).

## Release view
No Critical or High finding remains, so none blocks a release by the stated rule. **M1-M4 and M6 are open data-integrity and
abuse-resistance gaps in the optional backup and lookup paths.** Backup is off by default and cannot work in production until
migration `0007` is applied, so they do not affect existing users today; they should be fixed (or consciously accepted)
before backup is encouraged or the lookup is exposed beyond a trusted family.

## Re-audit of the M1-M4 and M6 fixes (2026-10-29)
Reviewer: a second fresh, read-only model-assisted reviewer (not a penetration test; it ran no code, touched no database or
network and read no `.env`, `.data` or key files). Result: **0 Critical, 0 High, 1 Medium, 4 Low, 4 Info.** No new device-isolation
or key-exposure path. Verdicts: M2, M3, M4 closed; M6 closed with caveats; M1 partly closed until N1 (below) was fixed.

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| N1 | Med (narrow) | `drain` read the pending list once; a journey deleted before its turn was still sent (and, if the reply was lost, orphaned on the server) | **FIXED** (`markUploadAttempted` returns false for a missing row and the engine skips it; test added) |
| N2 | Low | `UNUSABLE` answers were neither cached nor cooled down, so a broken provider response could drain the budget | **FIXED** (60 s pause; test added) |
| N3 | Low | One paired device can spend the day's shared budget with made-up flight numbers | Accepted trade-off: bounded by 10/day and 90/month; each device is limited to 10 requests/minute. A per-family sub-budget is possible later |
| N4 | Low | Single-flight lock is dropped after each call, so a late arrival can start a second identical fetch for uncached results | Accepted: the budget still bounds the calls |
| N5 | Low | A delete of an unseen id while a device is at the 1000-tombstone cap leaves no tombstone | Accepted: needs > 1000 deletions in 30 days plus a lost reply |
| N6 | Low/Info | Re-pairing the same server: an id still owned by the old revoked device answers 404, shown as "could not be backed up" until the 30-day revoked-device purge | Accepted and honest in the UI. Note: backups of a revoked device are deleted 30 days after revocation (documented in the retention rules) |
| N7 | Info | `0007` was edited in place | Safe: no persistent database applied the old 0007 (production is at `0006`; only throwaway test/scratch schemas did) |
| N8/N9 | Info | Count-then-insert caps can overshoot by a few under concurrency; rows upgraded from DB v3 with a lost reply before upgrade have no attempt note | Accepted |

Not verified by the reviewer: `hashtext(:p)` through the psycopg driver and the Supabase pooler (**verified by tests that ran
the budget against the real database**, see the verification note), the SQLite upgrade at runtime (**verified by the emulator
migration test**), and whether two sync runs can overlap.

Still open from the first review (unchanged, Low): L3 (`add_events` racing `delete`), L5 (arrival-detection buffer and mock
locations), L6 (main-thread SQLite in the alarm receiver). M5 remains partly fixed (HTTPS asserted; plan support unverified).
