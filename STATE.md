# Piko Project State

Status: **Phases 2-5 IMPLEMENTED and tested; NO formal gate passed (see `docs/PHASE_02_03_GATE_BACKLOG.md` and `docs/verification/phase-04-05-android-and-web.md`)**
Current phase owner: human operator (decisions below) + independent auditor
Implementation status: backend (Phases 2-3 plus history endpoint, invitations/guardian, refresh rotation), Android node (Phase 4) and parent dashboard (Phase 5) exist and were run end to end on the project-local emulator. No gate is passed. Phase 6 is built and verified on an emulator (2026-10-17) but its gate is NOT passed (see `docs/verification/phase-06-gate-report.md`); Phases 7 and 8 were built 2026-10-27 (see the update at the end); gates not passed.
Last verified commit: none (working tree not committed)
Open blockers: see "Gate blockers"

## Phase ledger

| Phase | Name | Status | Evidence |
|---|---|---|---|
| 0 | Inventory and project-local environment | ✅ PASS | `artifacts/initialization/` |
| 1 | Contracts and threat model | ✅ PASS (human operator approved the contracts in-session, 2026-10-16) | `docs/API_CONTRACTS.md`, `docs/DATA_MODEL.md`, `docs/verification/phase-01-contracts.md` |
| 2 | Backend foundation and auth | 🟡 IMPLEMENTED, GATE PENDING | `docs/verification/phase-02-03-backend.md`, `docs/verification/phase-02-03-security-findings.md` |
| 3 | Telemetry ingestion and offline reconciliation | 🟡 IMPLEMENTED, GATE PENDING | same as Phase 2 |
| 4 | Android durable node and modes | 🟡 IMPLEMENTED, GATE PENDING, **development paused by the operator 2026-10-16** | `docs/verification/phase-04-05-android-and-web.md` (48 JVM + 30 emulator tests pass; no physical device) |
| 5 | Parent web dashboard | 🟡 IMPLEMENTED (all four web designs; SOS/Messages/Alerts are honest "not available" pages), GATE PENDING | `docs/verification/phase-05-web.md` (72 tests pass; production CSP checked in a browser; no screen-reader pass) |
| 6 | SOS and messaging | 🟠 BUILT AND VERIFIED, GATE NOT PASSED: backend (297 tests), Android (90 JVM + 56 emulator), web (116) and a live emulator+browser run pass; independent audit run (3 Medium fixed, 3 Low/Info open); **waiting for operator approvals, physical-device run and an independent re-review** | `docs/verification/phase-06-gate-report.md` |
| 7 | Read-only MCP integration | 🟠 BUILT AND TESTED, GATE NOT PASSED (no independent audit; migration 0006 unapplied) | `docs/verification/phase-07-08-report.md`, ADR-024 |
| 8 | Self-hosting and operations | 🟠 BUILT AND TESTED, GATE NOT PASSED (no clean-checkout test) | `docs/verification/phase-07-08-report.md`, `docs/SELF_HOSTING.md` |
| 9 | Security, privacy, reliability, battery validation | ⏳ BLOCKED | Gates on Phase 4–7 |
| 10 | Release candidate and independent audit | ⏳ BLOCKED | Gates on all prior phases |

## Gate blockers for Phases 2-3 (why they are not marked PASS)

AGENTS.md section 10 requires, in addition to passing tests: no unresolved critical/high finding, documentation updated, evidence saved, and **an independent audit run for security-critical phases**.

1. **Independent audit RUN (2026-10-16)**: `docs/verification/phase-02-03-independent-audit.md` (0 Critical, 1 High, 4 Medium, 6 Low). H-1, M-1, M-2, M-4 are fixed with regression tests (`docs/verification/phase-02-03-fixes.md`, ADR-018). **Not yet re-reviewed independently.** M-3 (refresh-token rotation) awaits an operator decision; Low items are open.
2. ADR-008 and ADR-011 **approved** by the operator (2026-10-16).
3. Invite endpoint and `guardian` role **implemented** (ADR-017, migration 0003). Multi-family is out of scope.
4. **Not exercised**: nothing on a physical device; no persistent (non-test) schema has been migrated on the remote database; the retention/cleanup job is not included in Phase 3 (the Phase 3 prompt marks it optional).
5. **Dev/build tooling advisories** (`pytest 8.4.2`, venv `setuptools 65.5.0`): bumps need operator approval (ADR-016).

**Update 2026-10-17:** `docs/verification/phase-02-03-backlog-closure.md` records per-item results (L-1, L-2, L-3 done; the rest needs a decision or approval). The gate stays open.

**Deferred by the operator (2026-10-16):** the Phase 2-3 gate is intentionally left open and tracked in `docs/PHASE_02_03_GATE_BACKLOG.md` (no re-audit of the fixes; Low findings; migration on the persistent schema; final clean suite run). M-3 is resolved by ADR-019 (rotation with reuse detection). Phases 4-5 proceed on the operator's explicit instruction and are NOT gated-complete while that backlog is open.

## Rules

- Change a status only when the relevant phase gate has evidence.
- Do not mark a phase PASS based only on code review or a successful build.
- Never auto-advance.
- Record blockers and failed tests without hiding them.

## Update 2026-10-17: push, security closure, deployment prep (gate OPEN)
Implemented and tested: durable notification outbox, FCM + Web Push, Android messaging service, F-04/F-06/F-10/L-4/L-5, retention job, serverless entrypoint, CI/scheduler workflows (not run). Final suites: backend 378 passed, web 135 passed, Android JVM 102 / instrumented 67 (0 failures). NOT done: live FCM, live browser push, DB backup, migrations 0004/0005 on the persistent schema, schema drops, MCP auth, any deployment. See `docs/verification/push-deployment-gate-report.md`, `docs/PUSH_NOTIFICATIONS.md`, `docs/DEPLOYMENT.md`, ADR-023. Phases 7-8 not started.

## Update 2026-10-17: Deployment, Database Migration, and APK Release Automation (gate OPEN)
- **Branch Scope**: All deployment work executed on branch `deployment` (`abdf669`). Pushed to `origin/deployment`.
- **Database Backup Snapshot**: Verified pre-migration snapshot schema `piko_backup_0003` created in Supabase project `wktsqtydgfmmmugngzxo` with all 12 tables and rows preserved.
- **Database Migrations**: Operator-approved Alembic migrations 0004 & 0005 applied to persistent schema `piko` (now at head `0005`). Hard schema separation maintained (`public` contains 0 tables).
- **Vercel Backend (`piko-api`)**: Deployed to `https://piko-api-ten.vercel.app`. Live health check verified: `GET /api/v1/health/ready` -> `{"status":"ready","database":"ok"}`.
- **Vercel Frontend (`piko-web`)**: Deployed to `https://piko-web-jade.vercel.app`. Strict CSP verified with connect-src to `piko-api-ten.vercel.app`.
- **CI / CD Pipelines**:
  - `.github/workflows/ci.yml`: Backend (378 tests), Web (135 tests), Android JVM (102 tests) 100% green.
  - `.github/workflows/android-apk.yml`: Automated debug APK assembly and test report upload.
- **Documentation**: Root deliverable `initial_deployment.md` created with architecture Mermaid diagram, API table, database details, Vercel config, APK automation, and DR runbook.
- **Phase Gate**: Remains OPEN per Piko constitution (awaiting physical device baseline, live FCM credentials, and independent audit re-review). Next phase not started.


## Update 2026-10-27: Phases 7-8 built, parent onboarding, launch review (gates OPEN, nothing deployed)
- Phase 6 re-verified (378 backend, 136 web, 102 Android JVM pass). Gate still open for the operator items.
- Phase 7 (read-only MCP, local stdio, ADR-024) and Phase 8 (doctor/backup/restore, unsafe-default refusal, SELF_HOSTING.md) are implemented and tested; **neither gate is passed** (no independent audit, migration 0006 unapplied, no clean-checkout test). See `docs/verification/phase-07-08-report.md`.
- Also built: web parent onboarding, alert sounds (web + Android), landing SEO fixes and "Deploy yourself", CI APK on every push. Launch blockers still needing a decision (signup/billing path, privacy policy and contact): `docs/verification/launch-review-2026-10-27.md`.
- Working tree is uncommitted. Live deployments (API, web) are unchanged and healthy at the 2026-10-17 state.

## Update 2026-10-27 (later): production deploys and CI (gates still OPEN)
- Migration 0006 applied to the persistent `piko` schema (operator-approved; pre-migration backup `.data/backups/piko-pre-0006-20261027.gz`, not restore-tested). `doctor`: migrations at head (0006).
- `piko-web` and `piko-api` deployed to production with the Vercel CLI (project-local install in `.tools/vercel`; Vercel is NOT connected to Git, so pushes do not deploy). Live checks: API health/ready 200 with database ok, CORS preflight 200, bad login 401; web serves the new landing, `/signup`, `robots.txt`, `sitemap.xml`, WebP mascot, no console errors. Mobile LCP on the throttled profile is about 4.2 s (needs landing prerender/code splitting).
- CI on `deployment` (commit b0d4a0e): backend, web, android-jvm and APK build all green. Backend CI had failed twice: MCP SDK missing from `requirements.lock`, then a doctor test that used group-readable key files on Linux (test fixed, code was right).
- Still open: independent audit of the MCP adapter, physical-device checks, throwaway test schemas in the database (drops need approval), signup/billing and legal pages (see launch review).

## Update 2026-10-28: Journeys phases 0-1 built (gate OPEN, uncommitted)
- Local-first journey builder added on Android (list, detail, editor; own SQLite file; Home card). ADR-025, `docs/verification/journeys-phase-0-1.md`: JVM 123 pass, SQLite contract + durability 8 pass on the emulator. UI not exercised on screen. No backend, sync, tracking or providers (phases 2+ not started).

## Update 2026-10-28 (later): Journeys phases 2-6 built on the operator's instruction (gates OPEN, uncommitted, nothing deployed)
- Backend: journeys API (device-owned, idempotent upsert, tombstones, event batches), migration `0007` (**unapplied** to the persistent schema), retention rule for journey events. Android: opt-in backup sync, following with reminders, optional arrival detection by location, expected-time updates, connection-risk checks, flight-mode readings; database v3. ADR-026, `docs/JOURNEYS.md`, `docs/verification/journeys-phases-0-6.md`.
- Evidence: Android JVM 184 pass; instrumented 93 pass on the emulator (incl. v1->v3 migration and a service lifecycle smoke test); backend journeys/migration/retention pass; the full backend suite showed 6 transient remote-database connection failures under parallel load, all passing on rerun.
- **Not done:** any flight/rail/routing/taxi provider (no vendor chosen), physical-device battery and detection runs, on-screen UI check and screen-reader pass, Android lint and the minified release build (tool jars not cached offline), independent audit, family dashboard view. No phase of this feature is marked passed.


## Update 2026-10-29: optional live flight/train data (ADR-027; gates OPEN, uncommitted, nothing deployed)
- Server-side Aviationstack and RailRadar lookups, default `manual`, keys from `.env` only; phone "Check live status" in the expected-time dialog shows a labelled reading and never saves or applies it. Migration `0007` still **unapplied**; no verified backup at revision 0006 exists.
- Evidence (`docs/verification/journeys-providers.md`): backend full serial suite 494 passed, 1 skipped; Android JVM 199 pass; emulator 93 pass; ruff/mypy clean. Provider tests are mocked only (no key available): no live integration is claimed.
- Not done: live provider calls, physical-device checks, on-screen/TalkBack check, lint and release build (blocked offline), independent audit.

## Update 2026-10-29 (later): verification pass, CI workflow, audit (gates OPEN, nothing deployed)
- Backend serial full suite 499 passed/1 skipped; Android JVM 199, emulator 93; lint 0 errors; the minified release APK builds (unsigned) and a throwaway-signed copy installs and starts on the AVD. Live provider checks BLOCKED (no keys); all provider tests are mocked. `android-apk.yml` now tests, lints and builds debug + unsigned minified release with checksums and metadata; a Release is published only by an opt-in manual run on main/deployment. No GitHub run has happened yet.
- Migration `0007`: fresh backup and scratch restore drill passed (`docs/verification/journeys-providers.md`); production still `0006`; scratch schema `piko_drill_c90445` still exists (dropping it needs approval).
- Independent audit: 0 Critical/High; Mediums M1-M4 and M6 open (`docs/verification/journeys-independent-audit.md`).
- Incident: the local `.data/keys/hmac.key` was overwritten by my own helper script and is unrecoverable here; see the verification note.

## Update 2026-10-29 (hardening): audit Mediums closed, migration re-drilled, key impact assessed (gates OPEN, nothing deployed)
- M1-M4 and M6 fixed (ADR-028): per-journey revision, durable owed deletes, tombstone retention/cap, DB-backed provider budget. Re-audit: 0 Critical/High; its one Medium (N1) fixed. Evidence: `docs/verification/journeys-hardening-and-key-impact.md`, `journeys-independent-audit.md`.
- Migration `0007` changed (adds `revision`, `live_data_usage`, tombstone index) and re-drilled on a fresh backup (sha256 in the note): restore matched production on all 16 tables, up/down/up passed. **Not applied; production is `0006`.** Scratch schema `piko_drill_c90445` dropped (approved); new `piko_drill_c011fb` still exists.
- Real provider calls (one each, keys from the local `.env`): Aviationstack and RailRadar both answered `ok`. Server route end to end, error states and the phone button are mocked-only.
- Tests: targeted backend (journeys 19, live data 57) pass; Android JVM and emulator (98) pass; lint 0 errors. The local full serial backend run was stopped by the user's decision, but GitHub's `ci` run passed the full backend suite at `0340cfb`.
- Local `hmac.key` impact assessed (no production data written with the replacement key; run local tools against a non-production schema).
- Pushed to `origin/deployment` (no force). GitHub runs for `0340cfb`: Android APK & CI https://github.com/NeelakshSaxena/piko/actions/runs/40923511420 and ci https://github.com/NeelakshSaxena/piko/actions/runs/40923511112, both success; artifact `piko-android-0340cfb...` (unsigned release + debug APK, checksums, metadata). Three earlier failing runs exposed three real defects (all fixed); see `journeys-hardening-and-key-impact.md` section 8. Migration `0007` still not applied; nothing deployed.

