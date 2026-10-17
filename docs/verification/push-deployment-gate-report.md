# Push / security closure / deployment prep — gate report (2026-10-17)

**Gate: OPEN. Not approved. Nothing committed, pushed, deployed or applied to a persistent database.**

## Test results (final tree, this session)

| Check | Result | Log |
|---|---|---|
| ruff format / ruff check (backend) | 65 files formatted / all checks passed | console |
| mypy `backend/app` | no issues, 35 files | console |
| Backend pytest (real PostgreSQL, isolated `piko_test_*` schemas) | **378 passed**, 1 warning (starlette/httpx deprecation), 34m56s | `final-backend-pytest.log` |
| Web `tsc --noEmit` | clean | console |
| Web vitest | **135 passed** (5 files) | `final-web-vitest.log` |
| Web `npm run build` | built | console |
| Android JVM (`testDebugUnitTest`) | **102 run, 0 failed** | `final-android-tests.log`, `android/app/build/test-results` |
| Android instrumented, AVD `Piko_Test_Device` (Android 16) | **67 test cases, 0 failures/errors** (from the result XML; Gradle reported most tasks up-to-date, so these results are from the same build as the JVM run) | `final-android-tests.log` |

Not run: the GitHub Actions workflows (no GitHub access); a deployed build; any live FCM or live browser push.

## AVD push scenarios (honest status)

Verified on the emulator against a **simulated** FCM leg (the backend delivered through an adb-broadcast transport in `tests/e2e/run_e2e_server.py`, not through Google): token registration, dead-process delivery, reboot, app update, offline fallback to polling, invalid-token handling, revocation, SOS to Web Push leg on the backend. A bug found live (stale `CredentialRevoked` state after re-linking) was fixed and covered by a JVM test; it was not re-triggered live afterwards.
**Not executed / blocked:** real FCM (no Firebase project or credentials); real Chrome Web Push (needs a human to click the permission prompt); foreground-delivery case; multi-family isolation live (covered by backend tests only). One unexplained generic notification appeared once in a duplicate-push run and was not reproduced in two retries.
**Gap:** a per-scenario record of all 25 requested scenarios (steps, backend state, sanitized logs) was not saved as a file; only the summary above is supportable. Treat the scenario matrix as incomplete.

## Findings closed in code (with tests)

F-04 caps + retention job (dry-run default), F-06 message-read audit, F-10 clickjacking headers, L-4 (404 for revoked members), L-5, dependency updates (pytest >=9.0.3, setuptools >=83; audit in `dependency-audit-2026-10-17.txt`). See ADR-023. Independent re-review: **see "Re-review" below**.

## Migrations and database

- Migrations 0004 and 0005 are **UNAPPLIED** to the persistent `piko` schema. The backup is not done: no `pg_dump` is available locally, and a verified logical backup + restore-test script was planned but not written. Do not apply until a backup is made and its restore verified. Rollback: 0005 `downgrade` drops its three tables and restores the audit CHECK.
- Leftover test schemas (candidates; confirm names with a read-only inspection first, one name was never recorded): `piko_test_a39da344`, `piko_test_4aa04b19`, `piko_test_e2e_1fc14f`, `piko_test_e2e_165c40`, plus the partially migrated schema from the first failed e2e run. Proposed statements, **NOT RUN, need your explicit approval**:

```sql
DROP SCHEMA IF EXISTS piko_test_a39da344 CASCADE;
DROP SCHEMA IF EXISTS piko_test_4aa04b19 CASCADE;
DROP SCHEMA IF EXISTS piko_test_e2e_1fc14f CASCADE;
DROP SCHEMA IF EXISTS piko_test_e2e_165c40 CASCADE;
```

## MCP

`.mcp.json` has vercel and github entries with no credentials; supabase `type` fixed (backup `.tmp/mcp.json.bak`). **Neither server is authenticated or verified.** GitHub needs `PIKO_GITHUB_MCP_PAT` in the environment; approve servers via `/mcp`.

## Approvals needed from you

1. Backup tooling + backup, then applying 0004/0005 to the target schema.
2. The `DROP SCHEMA` statements above (after name confirmation).
3. GitHub + Vercel authentication; repo visibility and push are yours.
4. Firebase project creation/choice; accepting Vercel Hobby's non-commercial terms or choosing another host.
5. Deployment itself.

## Scope check

Phase 7 and 8 not started. The Phase 8 items (rate-limit/proxy work) remain open. Unverified physical-device checks stay in `phase-06-physical-device-checklist.md`.

## Re-review (independent read-only agent, 2026-10-17)

Result: 0 Critical, 0 High, 4 Low, 1 Info. No findings in SSRF validation, secret leakage, outbox concurrency, retention, middleware, migration 0005, Android push, service worker, CI workflows (actions pinned to major tags, not SHAs: Low, noted in `ci.yml`).

| # | Finding | Disposition |
|---|---|---|
| 1 | Empty/whitespace outbox token accepted an empty header | **Fixed**: startup refuses a token shorter than 32 bytes. No dedicated regression test was added (gap). |
| 2 | Internal endpoints rate-limited by IP before the token check (a proxy-shared IP could exhaust the scheduler's budget) | **Fixed**: token checked first, rate limit after. |
| 3 | Web-push endpoint re-registration can move a subscription across families | **Open (Low)**: needs knowledge of the unguessable endpoint URL; decision needed on same-family-only reassignment. |
| 4 | FCM token re-registration removes another device's row across families; simultaneous registration could 500 | **Open (Low)**: needs the device-local token. |
| 5 | Misleading comment in `deploy_env.py` | **Fixed**. Settings lower bounds (e.g. retention days 0) left as operator-controlled. |

After the fixes: ruff and mypy clean; `test_push.py`, `test_retention.py`, `test_deploy_env.py` re-run: 61 passed. The full 378-test backend run predates these small edits and was not repeated.
