# Phase 2-3 gate backlog: closure report (2026-10-17)

Source checklist: `docs/PHASE_02_03_GATE_BACKLOG.md`. Rule applied: nothing is marked closed without evidence, and
no acceptance criterion was changed to fit the implementation. **The Phase 2-3 gate is still NOT closed**: items
that need an operator decision or approval remain open and are listed with the exact decision required.

| # | Item | State | Evidence / blocker | Decision or approval needed |
|---|---|---|---|---|
| 1 | Re-audit (or written acceptance) of fixes H-1, M-1, M-2, M-4, ADR-017 invites/guardian, ADR-019 rotation | **OPEN** | The independent audit run on 2026-10-17 (`phase-06-independent-audit.md`) was scoped to Phase 6. It read auth/authz code and the lockout change and found no authorization defect, but it did **not** re-review those fixes, so it does not close this item | Run `prompts/INDEPENDENT_AUDIT.md` on the Phase 2-3 fixes, or record an explicit exception in `DECISIONS.md` (AGENTS.md section 10) |
| 2 | One clean full-suite run on the final tree | **DONE for the current tree** | `phase-06-final-backend-pytest.txt` (full run after the last code change; result in the Phase 6 gate report) | none |
| 3 | Apply migrations to the persistent `piko` schema | **PARTLY DONE / OPEN** | Read-only inspection 2026-10-17: `piko` is at **0003** (0003 was already applied by someone; the backlog text was out of date). **0004 is not applied** (`phase-06-migration-and-schema-status.md`) | Approve applying 0004 after a backup (plan in that report) |
| 4 | L-1 SQL parameters in logs | **DONE** | `db/session.py` `hide_parameters=True`; `test_database_errors_do_not_carry_bound_values` (SQLAlchemy's dump is gone). Caveat: PostgreSQL may quote an offending value in its own message; the app logs only exception types | none |
| 5 | L-2 lockout reset / atomicity | **DONE** | `services/auth.py`: failures count since the last success, per-email `pg_advisory_xact_lock`; tests: reset after success, 16-thread burst records exactly the limit. Trade-off recorded (audit F-08): serialised attempts per email, 9 fresh guesses after each success | none (trade-off noted) |
| 6 | L-3 `Cache-Control: no-store` | **DONE** | `NoStoreMiddleware` on every `/api/` response incl. 401/404; `test_every_api_response_forbids_caching`. Unhandled-500 responses from Starlette's outer handler do not carry it (no user data) | none |
| 7 | L-4 403 vs 404 for revoked members | **OPEN (decision)** | Current 403 is deliberate and tested (`test_revoked_membership_loses_access_immediately`); changing it alters a contract status code | Choose: keep 403 and document the exception, or return 404 and change that test |
| 8 | L-5 trust in device clocks | **OPEN (decision)** | Telemetry keeps the 60 s skew (ADR-011). Phase 6 SOS/messages cap future claims at receipt time instead of refusing | Accept the bounded trust in writing, or choose a stricter rule |
| 9 | L-6 dead/speculative code, lock file | **PARTLY DONE** | Done: three inert `.env.example` keys removed, ADR-008 reference fixed. Left: unused columns/audit actions that come from the approved data model, the uniform unused `now` argument in two telemetry helpers, `requirements.lock` runtime/dev split and hashes (needs tooling) | Approve the lock-file split / hash pinning |
| 10 | Dependency bumps (`pytest <9`, venv `setuptools` 65.5.0) | **OPEN** | ADR-016; not installed (project rule: ask first) | Approve the bumps and where they install |
| 11 | Retention/cleanup job | **OPEN** | Nothing deletes telemetry, audit rows or messages. SOS rows are intentionally kept | Decide retention semantics (it deletes data), then implement |
| 12 | Shared rate-limit store; proxy-aware client IP | **Phase 8** | Rate limits are per process; `proxy_headers=False` | Phase 8 |
| 13 | Physical-device verification | **OPEN** | `phase-06-physical-device-checklist.md` (not performed) | Run on a phone |

## Accepted limitations carried forward (unchanged)
Invite codes do not prove email ownership; a client that loses a refresh response must log in again (ADR-019); rate
limits are per process; guardian rights for SOS are now decided (ADR-022 addendum 2: read-only).

## What this does not claim
It does not claim the fixes from ADR-017/018/019 were independently re-reviewed, that the persistent schema is current,
or that any retention policy is enforced.
