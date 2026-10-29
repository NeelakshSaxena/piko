# Journeys hardening, migration re-drill, key impact (2026-10-29)

Supersedes the migration section of `journeys-providers.md` where they differ (migration `0007` was changed after that drill).
Nothing here was deployed. Migration `0007` is **not applied**; production is still at `0006`.

## 1. Audit Mediums closed (ADR-028)
| Finding | Fix | Regression proof |
|---|---|---|
| M1 lost upload reply, then delete | phone records an upload attempt before sending; delete of any attempted journey is queued in its database and retried until answered; a journey deleted after the pending list was read is never sent | JVM `JourneyBackupRegressionTest` (lost reply, repeated offline retries, fresh engine = restart, forgetSync, deleted-before-its-turn); emulator `aRevisionAnOwedDeleteAndTheAttemptNoteSurviveARestart`, contract tests, v3->v4 migration test |
| M2 backwards clock | per-journey revision (+1 per saved edit) and (timestamp, revision) acknowledgement read atomically; a higher server revision is `Stale`, never "backed up", rebases and retries; UI shows waiting (including owed deletes) and "could not be backed up" | JVM: same/earlier timestamp edits, save during upload, stale then success, answer interpretation; backend: stepped-back clock, lost counter |
| M3 tombstone growth | 30-day retention (per device + retention job + journeys of devices revoked > 30 days), cap 1000/device, partial index | backend: cap keeps real deletes working, expiry, retention job |
| M4 stale replay | server applies a write only with a strictly higher `revision`; `updated_at` display only, never backwards | backend: fast-clock late replay does not overwrite; revision required/strict/range |
| M6 provider budget | DB-backed daily 10 / monthly 90 per provider (advisory-locked, fails closed, `0` disables), single-flight, `UNUSABLE` pauses 60 s | backend: exhausted budget makes no call, cache/manual spend nothing, fail closed, 6 simultaneous lookups = 1 call, daily/monthly across two budget instances against the real database, API-level stop |

Independent re-audit (`journeys-independent-audit.md`): 0 Critical, 0 High, 1 Medium (N1, fixed), Lows accepted or fixed.

## 2. Test evidence (exact)
- Backend, targeted: `test_api_journeys.py` 19 passed; `test_live_data.py` 57 passed (mocked provider HTTP + real test database for the budget). ruff, ruff format and mypy clean.
- Backend, full suite on GitHub Actions: **passed** at commit `0340cfb` (workflow `ci`, job `backend`; see section 8). The local full serial run below was stopped.
- Backend, local **full serial suite: NOT completed.** It was stopped at about 28% (144 of 513 tests; one `F` at about test 129, not yet identified) at the user's instruction ("skip it, if it breaks we'll fix later"). An earlier full serial run (before these fixes) passed 499, 1 skipped. The real GitHub run is the full-suite evidence for these changes. A separate targeted run of `test_live_data.py` took 2h19m and showed 5 failures and 1 error that passed on immediate rerun: the remote test database pooler drops connections (known; see the environment note).
- Android JVM: 211 passed, 0 failed. Emulator (`connectedDebugAndroidTest`, AVD `Piko_Test_Device`): 98 passed, 0 failed. Lint: 0 errors; `assembleRelease` (minified, unsigned) builds, 3.66 MB.

## 3. Migration `0007` re-drill (changed: adds `journeys.revision`, `live_data_usage`, partial index `ix_journeys_device_deleted`)
- Target identity (no credentials): Supabase pooler `aws-0-ap-northeast-2.pooler.supabase.com:5432`, database `postgres`, role `postgres.<project ref>`, schema `piko`, `PIKO_ENV=development`. The project ref `wktsqtydgfmmmugngzxo` equals the ref in `SUPABASE_URL` and the ref recorded in `STATE.md` for the earlier production migrations and `piko_backup_0003`.
- Production: `alembic current` = `0006`, 17 tables (16 data tables + `alembic_version`); unchanged before and after every step.
- Backup taken with the **deployed** code (`git archive 953588f`, matching the live schema): `.data/backups/piko-pre-0007-20261029-0556.gz` (git-ignored), sha256 `1192b216a6a757506e7aa13bba0f6dbceee570c4ca2d85f18cea251e2fb0918a`, checksum file matches, `gzip -t` ok, revision 0006.
- Restore into new scratch schema `piko_drill_c011fb` (upgraded to `0006` first): 417 rows; per-table counts equal production for all 16 tables, 0 mismatches.
- `0007` on the scratch copy: up (new column `revision bigint NOT NULL DEFAULT 0`, table `live_data_usage(provider, day, calls)`, index `ix_journeys_device_deleted`), down to `0006` (the 16 data tables intact, counts equal), up again; `doctor`: database reachable, migrations at head.
- Earlier scratch schema `piko_drill_c90445` was dropped with approval after checking: name matched the drill pattern and differed from `piko`, 20 tables at `0007`, no other non-idle sessions; afterwards it was gone and production was `0006` with 17 tables. Other `piko_*` schemas were not touched (see section 6).
- **`piko_drill_c011fb` still exists** (holds a copy of family data). Dropping it needs approval.

### Proposed production sequence (not run)
From `backend/` with the **deployed** code for the backup, and the working tree for the migration:
1. `python -m alembic current` -> expect `0006`; confirm schema `piko`, project ref above.
2. `python -m app.cli backup --out ..\.data\backups\piko-pre-0007-<date>.gz` (writes `.sha256`; expect revision 0006); compare checksum; `gzip -t`.
3. `python -m alembic upgrade 0007`; `python -m alembic current` -> `0007`; `python -m app.cli doctor`; `GET /api/v1/health/ready`.
4. Deploy the backend that knows `revision` **only after** step 3 (the old backend ignores the new tables; the new backend needs them). Phones on old builds cannot back up (the server requires `revision`), which is acceptable because backup is off by default and the endpoint did not exist before.

### Rollback / recovery
- Schema-only rollback: `python -m alembic downgrade 0006` (drops `live_data_usage` and the journey tables, so **any journeys backed up since are lost**; the other 16 tables are unaffected, as drilled).
- Full recovery from the backup: the restore tool requires an empty schema at the same revision, so restore into a **new** schema (`alembic upgrade 0006` then `python -m app.cli restore --file <backup>`), run `doctor`, compare counts, and repoint `PIKO_DB_SCHEMA` on the host. Production's own schema is never overwritten in place.

## 4. Live provider checks (real, one call each)
Keys were found in the git-ignored `.env` under the names `AVIATION_STACK` and `RAIL_RADAR` (the server reads `PIKO_AVIATIONSTACK_API_KEY` / `PIKO_RAILRADAR_API_KEY`; the `.env` was not changed). A throwaway script read them in memory and called the real providers once each; no key, URL or raw body was printed or stored.
- Aviationstack (AI101, today): state `ok`, status `scheduled`, departure delay 21 min, terminals 3/4. The request went to `https://api.aviationstack.com`.
- RailRadar (12919): state `ok`, status `running`, running delay 62 min.
- **Not live-tested:** the server's HTTP route end to end against a real provider, not-found / auth-failed / rate-limited answers (only mocked), the budget against a real provider, and the phone "Check live status" button against a real answer. Those paths remain covered by mocked tests only.

## 5. Local HMAC key (`.data/keys/hmac.key`) impact
- **What it is:** `PIKO_HMAC_KEY_FILE`, used only by the local server, CLI and MCP adapter. It keys: lookup digests of the login email, pairing codes, invitation codes, FCM tokens and Web Push endpoints (`keyed_digest`), and it is the source (HKDF) of the AES-256-GCM key that seals push tokens and Web Push secrets. It does **not** sign JWTs (separate `jwt_private.pem`, untouched) and does not hash session or refresh tokens (plain SHA-256).
- **Local sessions and tokens:** no invalidation needed. JWT signing key and refresh-token hashing do not depend on it; the emulator and tests used throwaway test schemas.
- **Records that depend on it (schema `piko`, read-only check, counts only):** `device_push_tokens` 0 rows; `web_push_subscriptions` 1 row (created 2026-10-28 13:05 UTC, before the overwrite) which **cannot be opened with the current local key**; no pairing, invitation or push rows were created since the overwrite. Nothing in `piko` was written with the replacement key.
- **Production:** per `docs/DEPLOYMENT.md` the deployed API reads `PIKO_HMAC_KEY_B64` from the host's environment, not this file, so it is unaffected by this overwrite. Whether the *old* local key was ever the source of that value cannot be determined from the repository, and I did not read host secrets. If it was, the host still holds it; if not, nothing is lost.
- **Practical impact / hazard:** `.env` points the local tools at the **production schema `piko`** (same database). With the replacement key, running the local server, CLI or MCP adapter against `piko` would fail to find users, pairing codes and push data (a safe failure), and would write *new* digests/ciphertexts that production cannot read. Do not do that.
- **Required local recovery (user action):** (1) point local development at a non-production schema, e.g. set `PIKO_DB_SCHEMA=piko_dev` in `.env` and run `alembic upgrade head` there; (2) if the one production Web Push subscription must keep working, nothing needs doing (it belongs to the host's key); (3) treat the replacement key as a new, unrelated key and never as the original; neither key was printed or committed. No unrelated production secret was rotated and none is indicated by this evidence.

## 6. Schemas present that are not part of this work (not touched)
`piko_backup_0003`, `piko_test_0ea72a0c`, `piko_test_73d473c6`, `piko_test_814638b9`, `piko_test_e2e_9dff60` (leftover test fixtures; the last one is my earlier emulator fixture) and the new `piko_drill_c011fb`. Cleanup needs approval.

## 7. Still not verified
Physical-device battery, Doze, OEM behaviour and movement-based arrival; TalkBack and large text on the Journeys screens; the "I've arrived" tap and reminders firing on the emulator; a dependency vulnerability scan; a local full serial backend run after these changes (GitHub's run covers it).

## 8. Real GitHub Actions runs (branch `deployment`, pushed without force; commits `4164f77`, `ac4f2e7`, `16e20e1`, `95f6106`, `dbb93ad`, `0340cfb`)
Three earlier runs failed and each exposed a real defect that my partial local runs had not reached; all were fixed and pushed:
1. `test_migrations` expected-table list lacked `live_data_usage` (test fixed).
2. The `Journey` model did not declare the partial index that `0007` creates, so the models-vs-migrations drift check failed (model fixed).
3. The backup tool could not JSON-encode a `date` column (`live_data_usage.day`): **a backup taken after `0007` would have failed** once that table had rows (tool fixed, round-trip test added).

Final runs for commit `0340cfb3930f8f19389f411cd22b9e42157966f9`:
- Workflow "Android APK & CI": https://github.com/NeelakshSaxena/piko/actions/runs/40923511420 - completed **success** (Backend Tests & Lint, Web Dashboard Build & Tests, Test/Lint/Build Android APKs: success; "Publish rolling debug APK" skipped by design).
- Workflow "ci": https://github.com/NeelakshSaxena/piko/actions/runs/40923511112 - completed **success** (backend, android-jvm, web).
- Artifact `piko-android-0340cfb3930f8f19389f411cd22b9e42157966f9` (16,721,635 bytes, expires 2026-11-28; zip sha256 `12411c227e411378cd69fb94c594f11abb8bb393723b89672f0a670a3f795d10` as reported by the GitHub API). It contains the debug-signed APK, the **unsigned** minified release APK, `SHA256SUMS.txt`, the R8 mapping and `build-metadata.json`. Downloading the artifact needs a GitHub login; I could not download it here, so the per-APK checksums inside it and installability of the CI-built APK are **not independently verified** (a locally built unsigned release APK signed with a throwaway key was installed on the emulator earlier).
- No secrets were required by the workflow, nothing was published as a Release, and no backend deploy ran.

## 9. Tester build and the production migration attempt (2026-10-30)
- **Tester APK:** `.data/tester-builds/piko-test-v1001-66169a130788.apk` (git-ignored), minified release, versionCode 1001, signed with the new long-lived test key (`docs/TESTER_BUILDS.md`; certificate SHA-256 `30:E8:85:9A:...:BC:C7:FC`). apksigner verified it (v3); it installed on the emulator, started and showed no crashes. APK sha256 `3cd700991558765499363484210fea3ed770b3a73714a4e901642c7c94261d02`. Physical-device install and the pairing flow against production were not tested.
- **Migration `0007`: NOT APPLIED.** With the user's go-ahead I verified the target (schema `piko`, project `wktsqtydgfmmmugngzxo`, revision `0006`, no other active sessions) and took a final backup with the deployed code: `.data/backups/piko-pre-0007-final-20261030-0050.gz`, revision 0006, 417 rows in 16 tables, sha256 `0f73fbf7416e42df5e7476b3727c5a77d4c6aac5e84aaaee526e7fd6da2d103f`, checksum sidecar matches, gzip intact. The `alembic upgrade 0007` command was then **denied by Claude Code's permission check** (no reason given) and was not retried or worked around. `alembic current` afterwards: `0006`.
- **Next step (user):** run `python -m alembic upgrade 0007` from `backend/`, or allow it in the Claude Code permission settings and ask for a retry; then `alembic current` (expect `0007`), `python -m app.cli doctor`, `GET /api/v1/health/ready`; then deploy the matching backend from the Vercel project. Rollback: `alembic downgrade 0006`.
- Production (`piko-api-ten.vercel.app`) still runs the old backend: `/api/v1/journeys` answers 404 there.
- Open schemas that need approval to drop: `piko_drill_c011fb` (copy of family data), `piko_backup_0003`, `piko_test_0ea72a0c`, `piko_test_73d473c6`, `piko_test_814638b9`, `piko_test_e2e_9dff60`.
- Parent mode for Android is deliberately not started (user decision, 2026-10-30).

