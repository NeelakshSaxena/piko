# Piko Project State

Status: **Phases 2-5 IMPLEMENTED and tested; NO formal gate passed (see `docs/PHASE_02_03_GATE_BACKLOG.md` and `docs/verification/phase-04-05-android-and-web.md`)**
Current phase owner: human operator (decisions below) + independent auditor
Implementation status: backend (Phases 2-3 plus history endpoint, invitations/guardian, refresh rotation), Android node (Phase 4) and parent dashboard (Phase 5) exist and were run end to end on the project-local emulator. No gate is passed. Phase 6 is built and verified on an emulator (2026-10-17) but its gate is NOT passed (see `docs/verification/phase-06-gate-report.md`); Phases 7 and 8 have NOT been started.
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
| 7 | Read-only MCP integration | ⏳ BLOCKED | Gates on Phase 2 & Phase 1 security approval |
| 8 | Self-hosting and operations | ⏳ BLOCKED | Gates on Phase 5+ |
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

