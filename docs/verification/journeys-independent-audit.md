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
| M1 | Med | A journey deleted on the phone after a PUT whose reply was lost (never marked synced) queues no server delete, so the server copy stays (`SqliteJourneyStore.kt` delete / `forgetSync`) | **OPEN.** Needs an "upload attempted" flag (Android DB v4). Delete wording in the UI is therefore "when connected and backed up". Fix before relying on backup |
| M2 | Med | Server `applied=false` (equal/newer copy kept) is treated as success; a phone clock stepped backwards makes later edits silently not back up while the UI says "Everything is backed up" | **OPEN.** Parse `applied`, re-stamp above the server's value, count pending deletes/events in the status line |
| M3 | Med | Tombstones are never purged and `DELETE` of an unseen id inserts one: about 5k rows/hour/device is reachable; revoked devices' journeys are never purged | **OPEN.** Add a per-device tombstone cap and a retention rule (suggest 30 days); define a purge for revoked devices |
| M4 | Med | `updated_at` is clamped to server time rather than rejected, so with a fast client clock a late replay of an older edit can overwrite a newer one | **OPEN.** Reject (409) future-dated `updated_at` beyond the allowance, or add a per-journey revision. Low exposure today (the client re-sends its current state) |
| M5 | Med | Aviationstack's free plan may not serve HTTPS (unverified); the tempting workaround, `http://`, would send the key in clear | **PARTLY FIXED.** Test now asserts both provider URLs are `https://`; docs say never to switch to `http` and to use a paid plan if HTTPS is refused. An HTTPS-refused answer shows as "unusable" |
| M6 | Med | Any enrolled device can spend a 100/month provider quota (distinct numbers/dates, shared across families) and trigger a provider-wide cooldown | **PARTLY FIXED.** `day` is now limited to within 2 days of today. **OPEN:** a global per-provider budget and single-flight coalescing |
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
