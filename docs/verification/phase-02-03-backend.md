# Phases 2-3 Verification: Backend Foundation, Auth, Telemetry Ingestion

**Date:** 2026-10-16
**Scope:** Phase 2 (`prompts/PHASE_02_BACKEND_FOUNDATION.md`) and Phase 3 (`prompts/PHASE_03_TELEMETRY_SYNC.md`) only. Phase 4 was **not** started.
**Commit:** none (working tree uncommitted)
**Reviewer:** none yet. The independent audit has **not** been run.
**Gate:** **NOT PASSED.** Implementation and tests are complete; the formal gate is withheld for the reasons in section 7 and `STATE.md`.

Nothing in this report contains credentials, tokens, pairing codes, coordinates from real people, or connection strings. All test data is synthetic.

## 1. Environment

| Item | Value |
|---|---|
| Python | 3.11.0, project `.venv` (requirement relaxed from 3.12 on operator instruction, ADR-016) |
| Key packages | FastAPI 0.143.2, SQLAlchemy 2.1.4, Alembic 1.20.0, psycopg 3.3.6, PyJWT 2.15.1, bcrypt 4.3.0 (`requirements.lock`) |
| Database | PostgreSQL 17.11 (operator's Supabase development project, session pooler, TLS verified client-side) |
| Isolation | Piko uses its own schema; tests use `piko_test_<random>` schemas that are dropped afterwards; Supabase-managed schema names are refused by configuration |
| Local-only paths | `scripts/verify_local_paths.py` -> PASS (exit 0). pip cache `.cache/pip`, npm cache `.cache/npm`, pip-audit cache `.cache/pip-audit`, temp `.tmp`; keys in `.data/keys` (git-ignored) |

Connection check (sanitised): `SELECT 1` returned 1; client TLS in use = True; the project had only Supabase's default schemas before testing. No credentials were printed at any point.

## 2. Commands and results

All commands run from `G:\Projects\piko` with the project virtual environment.

| Command | Result |
|---|---|
| `.venv\Scripts\python -m ruff check backend` | exit 0, "All checks passed!" (`docs/verification/phase-02-03-lint.txt`) |
| `.venv\Scripts\python -m ruff format --check backend` | exit 0, 41 files already formatted |
| `.venv\Scripts\python -m mypy backend/app` | exit 0, "no issues found in 25 source files" (strict mode; tests are linted but not type-checked; output `docs/verification/phase-02-03-mypy.txt`) |
| `.venv\Scripts\python -m pytest -v --durations=10` (final code) | **196 passed, 0 failed, 0 skipped, 0 errors, 1 warning, exit 0 (876s)** (`docs/verification/phase-02-03-pytest-output.txt`) |
| earlier full run, before the CLI tests/key-creation hardening were added | 190 passed, 1 warning, 825s (`docs/verification/phase-02-03-pytest-run1-before-cli.txt`) |
| `.venv\Scripts\python scripts/verify_local_paths.py` | exit 0, PASS |
| `.venv\Scripts\python -m pip_audit --cache-dir .cache/pip-audit` | exit 1: 10 findings, 5 distinct advisories, **all in dev/build tooling** (`pytest 8.4.2`, venv `setuptools 65.5.0`); **no runtime dependency affected** (`docs/verification/phase-02-03-pip-audit.txt`) |
| Real-transport smoke test (uvicorn on 127.0.0.1:18765, curl, temp schema) | see section 5 |
| `PIKO_BIND_HOST=0.0.0.0 python -m app` | exit 1, refused; nothing listened |

Skipped tests: **none**. A missing database makes the suite *fail* (`conftest.py`), it never skips. No database access is mocked; the only mocks are (a) a forced commit failure to prove acknowledgement ordering and (b) replacing the CLI's password prompt.

Warnings: 1 (`StarletteDeprecationWarning` about the httpx-based test client; test tooling only).

## 3. Migrations

| Revision | Purpose | Applied to |
|---|---|---|
| `0001_phase2_core` | users, families, family_memberships, devices, device_credentials, pairing_invitations, refresh_sessions, audit_events | throwaway test schemas only |
| `0002_phase3_telemetry` | telemetry_events (append-only, PK `(device_id, id)`), device_latest_state | throwaway test schemas only |

**No persistent schema (`piko`) has been migrated on the remote database.** Every migration run went to a `piko_test_*` schema that the test (or smoke script) then dropped. The final check found no leftover `piko*` schemas (section 6). Running `alembic upgrade head` against the real `piko` schema is a remote change that needs your go-ahead.

Migration tests (`test_migrations.py`, all pass): head creates exactly the expected tables and nothing in `public`; ORM models and migrations agree (`compare_metadata` is empty); upgrade from `0001` with a row present preserves the row and reaches `0002`; upgrade is idempotent; downgrade to `0001` and to base is clean and re-upgrade works; check constraints reject bad states; Supabase `anon`/`authenticated` roles have no `USAGE` on the Piko schema.

## 4. Requirement traceability

Status vocabulary: **Verified** = covered by a passing runtime test; **Decision** = implemented but departs from the written contract and needs your confirmation; **Blocked** = not implemented.

### Phase 2

| Requirement | Implementation | Evidence (tests in `backend/tests/`) | Status |
|---|---|---|---|
| App entry point + configuration | `app/main.py`, `app/__main__.py`, `app/core/config.py` | `test_platform.py::test_launcher_refuses_public_bind_unless_explicitly_allowed`, `::test_docs_are_disabled_in_production`, `::test_default_bind_is_loopback_and_secrets_are_not_in_repr`; `test_unit_security.py` settings guards (weak bcrypt, reserved schema, https in production) | Verified |
| Database session + migrations | `app/db/session.py`, `migrations/` | `test_migrations.py` (6 tests) | Verified |
| Health live/ready, no secrets | `app/api/routes.py` | `test_platform.py::test_liveness_needs_no_auth`, `::test_readiness_*` (including 503 with unreachable DB leaking no host/credential text) | Verified |
| Password hashing | `app/core/security.py` (bcrypt, 72-byte limit enforced) | `test_unit_security.py::test_password_*`, `::test_unusable_and_malformed_hashes_fail_closed` | Verified |
| Authentication: login, refresh, revoke, expiry, audience, revocation | `app/services/auth.py`, `app/services/principals.py` | `test_api_auth.py` (23 tests) + JWT tests in `test_unit_security.py` (expired, wrong audience/issuer/key, alg=none, HS256 key confusion, refresh-vs-access confusion) | Verified |
| Brute-force controls | per-IP limit, durable per-email lockout | `test_api_auth.py::test_per_ip_login_rate_limit`, `::test_account_locks_after_ten_failures_*`, `::test_lockout_also_applies_to_unknown_emails_*` | Verified |
| Central authorization / family isolation | `app/services/authz.py` | `test_api_authorization.py` (13 tests): default-deny route enumeration, cross-family reads/deletes indistinguishable from nonexistent, child-role limits, revoked membership, archived family | Verified |
| Credential-type separation (user vs device) | `app/api/deps.py` | `test_api_auth.py::test_device_credential_is_rejected_on_parent_endpoints`, `::test_user_token_is_rejected_on_device_endpoint` | Verified |
| Device pairing lifecycle | `app/services/devices.py` | `test_api_pairing.py` (14 tests): single use, expiry, indistinguishable failures, rate limits, concurrent race (4 threads -> exactly 1 device), hash-only storage | Verified (see ADR-008 Decision) |
| Device revocation | `DeviceService.revoke` | `test_api_authorization.py::test_revoking_a_device_kills_its_credential_and_keeps_the_record` | Verified |
| Safe errors + request IDs | `app/core/errors.py`, `app/core/middleware.py` | `test_platform.py::test_unknown_route_*`, `::test_request_ids_*`, `::test_validation_errors_never_echo_*`, `::test_internal_errors_are_generic`; `assert_error` helper in `test_api_auth.py` | Verified |
| Secrets not logged | request logging omits query/body/headers | `test_platform.py::test_logs_contain_no_credentials_tokens_codes_or_coordinates`, `::test_request_log_line_omits_query_strings`; smoke test log grep | Verified |
| Origin/host validation, CORS | `HostMiddleware`, `OriginMiddleware`, CORS | `test_platform.py::test_disallowed_origin_*`, `::test_cors_preflight`, `::test_unexpected_host_headers_are_rejected` | Verified |
| Body bounds incl. gzip bombs | `BodyLimitMiddleware` | `test_api_telemetry.py::test_oversized_and_compressed_bodies_are_bounded`, `test_platform.py::test_invalid_content_length_*` | Verified |
| Global + per-endpoint rate limits | `app/core/ratelimit.py`, `routes.py` | `test_platform.py::test_global_rate_limit_applies_before_authentication` and per-endpoint tests above | Verified |
| Operator bootstrap (no signup endpoint exists) | `app/cli.py`, `app/services/bootstrap.py` | `test_cli.py` (6 tests) | Verified |
| Project-local lock + environment | `requirements.lock`, `.venv`, `.env.example` | `verify_local_paths.py` PASS; lock lists 73 pinned packages | Verified (no hashes) |
| Family members: invite parent (`POST /families/{id}/members`) | none | none | **Blocked** (contract gap; ADR open decision 3) |
| `operator` role | none | none | Not applicable: no data-model basis (ADR-012) |

### Phase 3 (verification cases from the prompt)

| # | Case | Test(s) in `test_api_telemetry.py` | Status |
|---|---|---|---|
| 1 | New event accepted (separate occurred/received timestamps) | `test_new_event_is_accepted_and_stored_with_both_timestamps` | Verified |
| 2 | Duplicate does not create history | `test_same_event_in_another_batch_is_a_duplicate_*`, `test_event_repeated_inside_one_batch_*`, `test_replaying_the_same_batch_*`, `test_replay_after_partial_success_is_stable`, `test_concurrent_duplicate_submission_stores_one_row` | Verified |
| 3 | Older delayed event stored, never overwrites newer state | `test_older_delayed_event_*`, `test_newer_event_after_older_*`, `test_equal_timestamps_*`, `test_state_groups_advance_independently`, `test_shuffled_offline_backlog_converges_*` (60 events, 72h old, shuffled, 3 batches), `test_concurrent_batches_cannot_regress_latest_state` | Verified (ADR-011 Decision for age window) |
| 4 | Partial failure has unambiguous per-event result | `test_partial_batch_has_an_unambiguous_per_event_result` (accepted + duplicate + 3 rejected, every id appears exactly once) | Verified |
| 5 | Invalid timestamp/payload rejected | 12 parametrised `test_invalid_events_are_rejected_without_echoing_values`, `test_request_level_schema_errors_*`, plus 33 domain tests in `test_unit_domain.py` (many parametrised) | Verified |
| 6 | Unenrolled/revoked device rejected; no cross-device submission | `test_unenrolled_and_revoked_devices_are_rejected`, `test_a_device_cannot_submit_as_another_device`, `test_event_ids_are_scoped_per_device_and_leak_nothing` | Verified |
| 7 | Batch limits and rate limits | `test_batch_of_exactly_500_*` (500 ok / 501 rejected whole), `test_oversized_and_compressed_bodies_*`, `test_telemetry_is_rate_limited_per_device`, `test_rate_limit_is_per_device_not_shared` | Verified |
| 8 | Ack not sent before commit | `test_ack_is_never_returned_unless_the_commit_succeeded` (forced commit failure -> 503, no ids, nothing stored, identical retry then succeeds once) | Verified |
| 9 | Retention job | **Not included in this phase** (the prompt says "if included"). Ingestion rejects events older than the family retention window; deletion is deferred. | Not included |

Also verified: freshness and honest unknown (`test_api_location.py`, 10 tests: fresh/stale/>24h withheld/no data/offline inference/cross-family 404/device credential refused/audit without coordinates/30 per minute limit); low-bandwidth handling (gzip requests accepted, large acknowledgements gzip-compressed: `test_gzip_requests_are_accepted_and_large_responses_compressed`); device contact tracking (`test_contact_updates_device_activity_*`, `test_rejected_only_batch_still_counts_as_device_contact`).

Not implemented in Phase 3 by design: history endpoint (`GET /members/{id}/history`), SOS, messaging, realtime transport, Android sync. Latest-location read (`GET /members/{id}/location`) *is* implemented because the phase must "expose stale/unknown status honestly".

## 5. Real-transport smoke test (uvicorn, loopback, curl)

Run against a throwaway schema with production-strength settings (`PIKO_ENV=development`, bcrypt cost 12), then the schema was dropped.

| Check | Observed |
|---|---|
| `GET /health/live`, `/health/ready` | 200, `ready` with database ok |
| `GET /families` without a token | 401 |
| `Host: evil.example` | 400 |
| `Origin: https://evil.example` | 403 |
| Login with wrong password / correct password | 401 / 200 (about 1.2-1.4s each over the remote database, bcrypt cost 12) |
| `GET /families` with the token | `[('Smoke', 'parent')]` |
| Listener address | `127.0.0.1:18765` only |
| Server log contained the query-string secret / password / access token | 0 / 0 / 0 occurrences |

## 6. Cleanup verification

After the final run: no `piko*` schemas remain on the database; only Supabase's default schemas (`auth`, `extensions`, `graphql`, `graphql_public`, `public`, `realtime`, `storage`, `vault`) exist. The 196 tests break down as: auth 23, authorization 13, location 10, pairing 14, telemetry 37, CLI 6, migrations 6, platform 20, domain 33, security/crypto units 34.

## 7. Remaining risks, deviations and decisions needed

Detailed in `docs/DECISIONS.md` (ADR-007..016 and "Open decisions") and `docs/verification/phase-02-03-security-findings.md`. In short:

1. **Independent audit not run** (required by AGENTS.md section 10 for security-critical phases). The security review in this repo was a self-review.
2. **Needs your confirmation:** ADR-008 (9-character pairing code instead of 6; per-IP attempt limiting instead of per-code), ADR-011 (event-age window = family retention days instead of 24h; 60s future skew).
3. **Not implemented:** parent invitation endpoint (workflow undefined).
4. **Residual risks:** no refresh-token rotation (R-01), email-keyed lockout can be abused to lock a known account for 15 minutes (R-02), in-process rate limits (R-03), no trusted-proxy mode (R-04), TLS left to a reverse proxy (R-05), audit growth for failed unknown-email logins (R-06).
5. **Not tested:** physical devices, any non-PostgreSQL database, multi-instance deployment, TLS, load/performance, and the Android client (Phase 4).
6. **Dev tooling advisories:** `pytest 8.4.2` (pinned `<9`) and venv `setuptools 65.5.0`; bumps await approval.
7. **An empty `backend/app/core/__init__.py` could not be created** (that write was blocked by the permission classifier and was not circumvented), so subpackages are implicit namespace packages. Imports, tests and `python -m app` work; it only matters if the package is later built as a wheel.

## 8. Scope check

Changed: `backend/` (new), `pyproject.toml`, `.env.example`, `README.md` (status + quick start), `STATE.md`, `docs/DECISIONS.md`, `requirements.lock` (new), these verification documents, `.claude/skills/supabase*` and `skills-lock.json` (installed on your instruction). Untouched: `AGENTS.md`, `CLAUDE.md`, product/architecture/security specifications, `screens/`, `docs/API_CONTRACTS.md` and `docs/DATA_MODEL.md` (your Phase 1 edits left as found). `.env` was extended with `PIKO_DATABASE_URL`, `PIKO_JWT_PRIVATE_KEY_FILE`, `PIKO_HMAC_KEY_FILE`, `PIKO_DB_SCHEMA` (git-ignored); your original connection key is unchanged.
