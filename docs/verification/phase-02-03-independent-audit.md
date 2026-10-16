# Independent Audit: Phases 2 and 3 (backend foundation, auth, pairing, telemetry)

**Date:** 2026-10-16
**Method:** `prompts/INDEPENDENT_AUDIT.md`. Read-only static review of the code, tests, migrations, lock file and evidence logs. Written by an independent reviewer with no prior context.
**Gate:** this audit does not mark any phase complete. See the verdict at the end.

## 1. What was checked

- Read `AGENTS.md`, `docs/SECURITY_MODEL.md`, `docs/DECISIONS.md` (ADR-007..016), the Phase 2 and Phase 3 prompts, the relevant parts of `docs/API_CONTRACTS.md`, and the evidence under `docs/verification/phase-02-03-*`.
- Read all of `backend/app/**` (routes, deps, principals, authz, auth, devices, telemetry, locations, families, security, middleware, errors, config, main, cli, models, session).
- Read the migrations only partly: grep for grants/RLS, and a check that the models agree. The Alembic migration bodies were not reviewed line by line.
- Read `.env.example` (not `.env` or any key file), `requirements.lock`, and the test suite structure. I read in full the authorization, telemetry and platform tests that matter for the claims, and skimmed the rest.
- Ran `ruff check backend --no-cache` and `mypy backend/app` with the project `.venv`. Both pass, matching the evidence (ruff: "All checks passed!"; mypy: no issues in 25 files). mypy created `.cache/mypy`, a project-local cache.
- Ran two pure-Python expressions (no DB, no network) to confirm that `math.isfinite(10**400)` and `datetime.fromisoformat("0001-01-01T00:00:00+05:00").astimezone(UTC)` raise `OverflowError` (finding H-1).
- Compared the per-file test counts in `phase-02-03-pytest-output.txt` against the evidence report. The counts match: 196 PASSED lines; auth 23, authz 13, location 10, pairing 14, telemetry 37, cli 6, migrations 6, platform 20, domain 33, security 34.

## 2. What was NOT checked

- **No test was executed.** Per the hard rules, pytest was not run, so every "passed" statement is taken from the log file only. I cannot independently confirm that the log came from the current tree. The `.pyc` files and log timestamps were not forensically compared.
- No connection to the database or any network. Migrations were not applied, and the actual PostgreSQL constraint behaviour was not observed.
- No dynamic or fuzz testing. Concurrency behaviour (row locks, `ON CONFLICT`, deadlocks) was reasoned about from the code, not observed.
- Out of scope, noted as absent: MCP, self-hosting docs (`docs/SELF_HOSTING.md` is referenced by `__main__.py` but was not checked for existence), SOS and messaging, Android. There is no MCP code and no SOS code in the backend. That is consistent with the phase scope.
- Not reviewed line by line: `test_cli.py`, `test_migrations.py`, `test_unit_domain.py`, the rest of `test_platform.py`, `test_api_location.py`, and the migration file bodies.
- TLS, reverse-proxy behaviour, the Supabase pooler, and load or performance.

This report makes no claim of universal security. The absence of a finding below means "not observed in the scope above".

## 3. Findings

No Critical findings. No finding was exploitable by an unauthenticated or cross-family attacker in what I reviewed. The IDOR and credential-type separation controls appear sound (section 5).

### H-1 (High): One malformed event can turn a batch into an HTTP 500 and block the device's offline queue

**Evidence**
- `backend/app/domain/telemetry.py:67` (`_number`): `math.isfinite(value)` on a Python `int` larger than a double raises `OverflowError`. Python's `json` accepts such integers. Example: a `latitude` of 1 followed by 400 zeros.
- `backend/app/domain/telemetry.py:47` (`parse_occurred_at`): `parsed.astimezone(UTC)` is outside the `try`. `"0001-01-01T00:00:00+05:00"` and `"9999-12-31T23:59:59-05:00"` raise `OverflowError`. I confirmed this with the project's Python 3.11.
- `backend/app/services/telemetry.py:117`: only `EventRejected` is caught around `validate_event`. The `OverflowError` propagates out of `ingest`, no per-event result is produced, nothing is committed, and the generic handler in `errors.py` returns 500 `INTERNAL_ERROR`.

**Reproduction.** Send an authenticated device batch with one valid event and one event whose `occurred_at` is `"0001-01-01T00:00:00+05:00"`. Expect HTTP 500 for the whole batch and no per-event result. The same happens with `data.latitude = 10**400`.

**Impact.** This breaks Phase 3 verification case 4 ("partial batch failure has unambiguous per-event result") and case 5 ("invalid timestamp rejected"). A device that treats 5xx as retryable would resend the same poisoned batch indefinitely. The valid offline events in it are never acknowledged, and a persistent client bug could block SOS-priority delivery later. Reachable only with a valid device credential, so this is a reliability and robustness defect, not an auth bypass.

**Why the tests miss it.** The 12 parametrised invalid-event cases (`test_api_telemetry.py` around lines 195-225) do not include out-of-range years or huge integers. The domain tests were not shown to cover them either.

**Required fix.** Make `validate_event` total: wrap the whole validation body, or at least `parse_occurred_at` and `_number`, so that `OverflowError` (and `ValueError`) becomes `EventRejected`. Add regression tests for the year-1 and year-9999 offsets and for huge integers in latitude, longitude, accuracy, percent and signal_strength. Add a test asserting that no input can make `ingest` raise a non-`EventRejected` exception.

### M-1 (Medium): A pairing code stays redeemable after its issuer loses authority or the family is archived

**Evidence**
- `backend/app/services/devices.py:189-198` (`_lock_invitation`) joins `Family` but applies no `Family.status == 'active'` filter. `pair()` (lines 125-187) never re-checks that the creator is still an active `parent` or `family_admin`, nor that the creator `User.status` is `active`.
- `PairingInvitation` carries no session reference, so session revocation does not cascade.
- No test covers this. `test_api_authorization.py` covers revoked membership and archived family only for the authenticated routes.

**Reproduction.** A parent requests a code. The parent's membership is then revoked (or the family archived, or the user suspended). Within 15 minutes, `POST /devices/pair` with the code still succeeds, creating a child identity, membership, device and credential in a family the issuer no longer administers. (Static reasoning from the code; I did not run it.)

**Impact.** A stale code can enrol a device into a family after access was withdrawn. This matters for incident response, where revocation must be immediate. The window is bounded to 15 minutes and the attacker needs the code.

**Required fix.** In `pair()`, re-check that the family is active, and that the creator still has an active admin-role membership and an active user account. Treat failure like any other invalid code, with the same `AUTH_INVALID` response. Revoke pending invitations when a membership is revoked. Add negative tests.

### M-2 (Medium): Pairing brute-force protection is weaker than the contract and depends on a spoofable, in-process per-IP limit (ADR-008 not fully sound as written)

**Evidence**
- The contract (`docs/API_CONTRACTS.md:256`) says "3 attempts per code". ADR-008 replaces this with 5 attempts per minute per client IP on an in-process limiter (`backend/app/api/routes.py` `pair_device`; `backend/app/core/ratelimit.py`). There is no global or per-family failure counter and no durable counter.
- The client IP comes from `request.client.host` (`deps.py:61`). The comment says forwarded headers are not trusted. That is not what happens at runtime: `backend/app/__main__.py` calls `uvicorn.run(...)` with its default `proxy_headers=True` and `forwarded_allow_ips="127.0.0.1,::1"` (also overridable via the `FORWARDED_ALLOW_IPS` environment variable; I confirmed these defaults in `.venv/Lib/site-packages/uvicorn/config.py:225,363`). Any process on loopback, or the reverse proxy recommended for deployment, can therefore set `X-Forwarded-For` and choose the "client IP" used by every per-IP limit (login, pair, global).
- The limiter state resets on restart and is per process.
- IPv6 clients can rotate through a very large address space, so per-IP limiting gives little protection against a distributed or IPv6 attacker.

**Reproduction.** (Static reasoning.) From loopback or from behind the proxy, send `POST /devices/pair` repeatedly with a different `X-Forwarded-For` each time. The 5 per minute limit never triggers.

**Impact.** The effective brute-force cost is what the 45-bit code space (about 3.5e13 combinations, 15-minute validity, HMAC lookup) provides. That is probably adequate against a single host, but the control the ADR relies on can be bypassed. The ADR's "under 2.1e-10 per IP per day" figure assumes per-IP limits that an attacker may be able to evade.

**Required fix.**
1. Decide explicitly on proxy handling: pass `proxy_headers=False` (or an explicit `forwarded_allow_ips`) and document it, so that R-04 in `phase-02-03-security-findings.md` is true.
2. Add a global (all-IP) failed-pairing throttle, for example a durable count of `device_paired`/`failure` audit rows in the last N minutes with a cap that applies to everyone. This restores a per-population attempt cap in place of the contract's unattainable per-code limit.
3. Ask the operator to confirm ADR-008. I consider 9 symbols the safer reading of the contract conflict, so the length deviation itself is sound.

### M-3 (Medium): Refresh tokens are not rotated and have no reuse detection (acknowledged as R-01)

**Evidence.** `backend/app/services/auth.py:111-135` (`refresh`) returns only an access token and leaves the refresh token valid for its full 7 days. This is recorded as residual risk R-01 but classified there as Medium and left unfixed. The contract does show a refresh response with only an access token, so this is a gap in the contract, not a deviation.

**Impact.** A stolen refresh token gives access for up to 7 days to location data until the user explicitly revokes the session. The revoke endpoint requires a valid access token, so a user who has lost every token has no self-service path to revoke. There is also no "revoke all sessions" or password-change path, and no session-listing endpoint.

**Required fix.** Either implement rotation with reuse detection (rotate `token_hash`, revoke the session on reuse of an old token) via a contract revision, or record an explicit human risk acceptance with a date (SECURITY_MODEL.md requires this for any Critical or High, and for Medium I recommend the same). Add an operator command to revoke all sessions for a user.

### M-4 (Medium): An accepted event can also be reported as rejected in the same batch response; the evidence overstates "unambiguous"

**Evidence**
- `backend/app/services/telemetry.py:101-105`: a repeated `event_id` inside one batch adds a `DUPLICATE` entry to `rejected_events`. The first instance is accepted, so the same id appears in both `accepted_event_ids` and `rejected_events`. `test_event_repeated_inside_one_batch_second_instance_rejected_as_duplicate` (`test_api_telemetry.py:83-93`) asserts exactly this.
- The evidence report (`phase-02-03-backend.md`, section 4, Phase 3 case 4) says "every id appears exactly once". The cited test (`test_partial_batch_has_an_unambiguous_per_event_result`, around lines 185-208) asserts `every == {all ids}` using a set union. That would pass even if an id appeared in several lists, so it does not prove "exactly once". The in-batch duplicate test shows the claim is false in that case.
- `rejected_events[].error_code` allows `DUPLICATE`, while `duplicate_event_ids` is a separate list that is reserved for already-stored events. The two representations of "duplicate" are inconsistent.

**Impact.** A client that treats any id in `rejected_events` as a permanent failure and deletes or flags it (the correct reading of "rejected") could mark an event as failed that the server actually stored. For SOS-class events later, "never falsely show delivered/failed" is a stated rule.

**Required fix.** Report an in-batch repeat only once (as `duplicate_event_ids`, or ignore the second instance), so each id is in exactly one list. Strengthen the test to assert the lists are disjoint and that their lengths sum to the number of distinct ids. Correct the evidence wording.

### L-1 (Low): Unhandled-exception path is re-raised and logged by the server; log hygiene on that path is unproven

**Evidence.** Starlette's `ServerErrorMiddleware` always re-raises after the app's generic `Exception` handler runs (`.venv/Lib/site-packages/starlette/middleware/errors.py:183-186`). `uvicorn` then logs the full traceback. `test_internal_errors_are_generic` only checks the response body, and `test_logs_contain_no_credentials_tokens_codes_or_coordinates` does not trigger an unhandled exception. For a non-`DBAPIError` SQLAlchemy `StatementError`, the exception text includes `[parameters: ...]`, which on the telemetry insert would contain coordinates and on the pairing insert a code hash. `DBAPIError` and subclasses are caught by a dedicated handler and are not re-raised, so I did not find a concrete leak.

**Required fix.** Add a test that forces an unhandled error and a `StatementError` on the telemetry path and asserts the captured log lacks coordinates and tokens, or configure SQLAlchemy `hide_parameters=True` on the engine (`create_engine(..., hide_parameters=True)`), which is a one-line fix.

### L-2 (Low): Lockout counter is never reset by a successful login, and the lockout check is not atomic

**Evidence.** `auth.py:156-168`: failures are counted over the 15-minute window by audit rows only. A user with 9 failures who then logs in successfully still has 9 failures on the books, so one more typo locks the account. The count-then-verify sequence is not serialised, so a burst of concurrent requests from many IPs can exceed the limit of 10 before the audit rows commit. The email-keyed lockout can also be used to deny service to a known account for 15 minutes (acknowledged as R-02). The contract mentions exponential backoff; a flat 15-minute window is used instead.

**Required fix.** Optional: count failures only since the last successful login, and take a per-email advisory lock (`pg_advisory_xact_lock(hashtextextended(email_key, 0))`) around the check and insert. Document the flat window as a deviation.

### L-3 (Low): Responses carrying credentials and coordinates do not set `Cache-Control: no-store`

**Evidence.** `grep` for `Cache-Control`/`no-store` in `backend/app` found nothing. The login, refresh, pairing-code, pair and location responses contain tokens, a pairing code, a device credential or exact coordinates.

**Required fix.** Add `Cache-Control: no-store` (and `Pragma: no-cache`) to `/api/v1` responses, with a test.

### L-4 (Low): Former members can distinguish "exists in my old family" from "does not exist"

**Evidence.** `authz.py:require_family_role` returns `FORBIDDEN` (403) when the caller's membership in the resource's family is `revoked`, but `NOT_FOUND_OR_NOT_VISIBLE` for non-members. For a user whose membership was revoked, a guessed device or member id of that family returns 403 while an unknown id returns 404. This leaks only the existence of ids in a family the user used to belong to. Tests assert 403 for the revoked case (`test_revoked_membership_loses_access_immediately`), so the behaviour is deliberate but contradicts "guessed IDs do not leak existence" (SECURITY_MODEL.md section 6).

**Required fix.** Return `NOT_FOUND_OR_NOT_VISIBLE` for revoked members on id-addressed routes, or document the exception.

### L-5 (Low): Event ordering is based on the device-supplied clock

**Evidence.** `telemetry.py` and ADR-011. A device (or a compromised credential) can send `occurred_at` up to 60 seconds in the future; the 60-second future skew means such an event blocks every real event with an earlier timestamp from becoming "latest" until real time catches up. Equal timestamps keep the first writer, so a stale equal-stamp event can block a better one. `classify_freshness` clamps negative age to 0 (`freshness.py`), so a future-dated reading is shown as "fresh". Freshness is measured from the device's `occurred_at`, not the server's receive time, which is what the contract states, but a device with a bad clock can present old data as fresh within the allowed skew. This is a design trade-off, not a defect, and is limited to the credential holder's own device data.

**Suggestion.** Document that device-clock trust is bounded by the 60-second skew. Consider also surfacing `received_at` age to the parent.

### L-6 (Low): Dead or speculative code, scope drift and stale documentation

- `.env.example` defines `PIKO_MCP_ENABLED`, `PIKO_MCP_TRANSPORT` and `PIKO_AUDIT_LOCATION_PAYLOADS`. None are read by `Settings` (it has `extra="ignore"`), so they are inert and misleading. Remove or implement them in their own phase.
- Unused or speculative schema and code: `DeviceCredential.rotated_at`, `RefreshSession.family_id`, `Device.status = 'inactive'`, `AUDIT_ACTIONS` entries for `logout`, `member_invited`, `member_revoked`, `sos_*`, `credential_rotated`, `settings_changed`, and the `now` parameter on `_battery_values` and `_connectivity_values` in `services/telemetry.py`. AGENTS.md section 7 asks for no speculative code. Some of these come from the approved data model, so I rate this Low.
- `security.py` comment cites "See ADR-009" for the pairing code; the pairing ADR is ADR-008.
- `GET /members/{id}/location` (and its audit action `location_accessed`) is Phase 4/5 territory by the evidence report's own words, but it is argued as needed for the "expose stale/unknown status honestly" requirement. I accept that justification, and it is covered by authorization tests.
- `requirements.lock` mixes runtime, dev and audit tooling (pytest, ruff, mypy, pip_audit, cyclonedx) in one file with no hashes. The evidence discloses the missing hashes. Split runtime and dev locks before release.
- The evidence says `pytest 8.4.2` and venv `setuptools 65.5.0` have open advisories (pip-audit: 10 findings, 2 packages). This is disclosed honestly and affects only dev tooling.

### I-1 (Info): Pairing identity model

Pairing creates a placeholder child `User` (`device-<uuid>@piko.invalid`, password hash `!`). `verify_password` rejects `!` immediately without running bcrypt, so these addresses return faster than unknown ones. Only the non-routable `.invalid` placeholders are distinguishable this way, which exposes nothing real. Noted for completeness.

## 4. Assessment of the proposed deviations

- **ADR-008 (9-character code, HMAC lookup, per-IP limit instead of per-code limit): partly sound.** 45 bits with single use, 15-minute expiry, keyed HMAC storage and uniform failure responses is a reasonable design, and 9 symbols is the safer reading of the contract's example. The justification that "3 attempts per code" is unenforceable for unknown codes is correct. The compensating control (per-IP in-process limit) is not adequate on its own because of the proxy-header behaviour and IPv6 (M-2), and the stale-code issue (M-1) needs fixing. Recommend: approve the length and the HMAC design, require the global throttle and the proxy-header decision before approval.
- **ADR-011 (accept events up to the family retention window, 60 second future skew): sound with caveats.** Accepting delayed offline events is consistent with AGENTS.md ("offline means store-and-forward, not dropping events"), and a literal 24-hour cutoff would permanently reject a device's multi-day offline backlog, which a device treats as final. The ordering rule (strictly newer `occurred_at`, one conditional `UPDATE`, three independent groups, the first writer wins on equal timestamps) is correct for concurrent batches by my reading. Caveats: no retention job exists, so "the window equals retention" has no deletion behind it yet, and the future-skew trade-off in L-5. The operator should record the decision.
- **ADR-010 (event key scoped to `(device_id, id)`):** good, and it prevents cross-family probing through `duplicate_event_ids`.
- **ADR-007 (opaque hashed device tokens instead of JWT):** sound. SHA-256 of a 256-bit random token is adequate, lookup is indexed, and revocation is immediate through the database join.

## 5. Controls reviewed with no finding

- **Authentication on every route.** Every non-public route depends on `current_user`, `current_device` or `AnyPrincipal`. Public routes are limited to health, login, refresh (which requires a refresh token) and pairing. A default-deny route-enumeration test exists, and it walks the router, so new routes are private unless added to its allowlist.
- **Family-level authorization / IDOR.** Every family-scoped query resolves through `authz.py` using the user's membership read from the database on each request, not from the token. Cross-family `GET`/`DELETE` on families, devices and member location return the same 404 body as a nonexistent id (verified by tests that compare the body). `DevicePrincipal`'s family comes from enrolment, never the request. A device batch whose `device_id` differs from the authenticated device is rejected (403). Telemetry rows are written with the principal's `device_id` and `family_id`.
- **Credential-type separation.** User tokens on device endpoints and device tokens on parent endpoints are rejected, and tested. Access and refresh tokens are distinguished by audience and `typ`.
- **JWT validation.** RS256 only (`algorithms=["RS256"]`), audience, issuer, and required `exp/iat/iss/aud/sub/sid/typ` claims, plus a database check of session state and user status on every request, so revocation is immediate. `alg=none` and HS256 key-confusion tests exist.
- **Pairing token handling.** Pairing codes are stored only as keyed HMAC; device credentials only as SHA-256; both are returned once. Unknown, malformed, superseded and expired codes give identical responses, apart from the contract-required 409 for a used code. Concurrent redemption is serialised with `SELECT ... FOR UPDATE` (a 4-thread test exists).
- **Ack-after-commit.** The acknowledgement is built after `db.commit()`. A failed commit raises and rolls back, returning a generic 503 with no ids. A replayed batch is re-derived from stored rows. A test forces a commit failure.
- **Idempotency and ordering.** Per-event idempotency by primary key with `ON CONFLICT DO NOTHING`; latest state advanced by a conditional `UPDATE ... WHERE stamp IS NULL OR stamp < new`, which is safe under READ COMMITTED because Postgres re-evaluates the predicate after the row lock. Old offline events are stored but cannot overwrite newer state (shuffled backlog and concurrent tests exist). A possible deadlock when two concurrent batches insert overlapping ids in different order is unobserved; it would surface as a retryable error (DBAPIError handled), not data loss.
- **Secrets and location in logs and errors.** The request log line carries method, path, status, duration and request id only (no query string, headers or body). Validation errors report field names only. Audit rows carry no coordinates. Hosts and origins are allow-listed. The server binds to loopback and refuses a public bind without an explicit override.
- **Body and rate limits.** The body is limited before parsing, including after gzip decompression. A global per-IP limit runs before authentication; the per-endpoint limits match the contract's numbers.
- **Dependencies.** Project-local `.venv`; no runtime dependency has an open advisory in the supplied pip-audit output (which I did not re-run, as it needs the network).

## 6. Unsupported or overstated claims in the evidence

1. "every id appears exactly once" (Phase 3 case 4): not proven by the test and false for in-batch duplicates (M-4).
2. R-04 states "forwarded headers are not trusted" and "per-IP limits would be shared behind a proxy". Runtime behaviour with uvicorn's defaults differs: the headers are honoured from loopback peers (M-2).
3. "Verified" for Phase 3 case 5 (invalid timestamp or payload rejected): the cases tested do not include inputs that make the validator raise a non-domain exception (H-1).
4. The evidence correctly states the audit was not yet independent and the gate is withheld. The "No Critical or High finding was identified" statement in `phase-02-03-security-findings.md` is contradicted by H-1 in this audit.
5. All test results are consistent with the log files I read (196 passed, per-file counts match), but I did not run them, so I cannot confirm they reflect the current tree.

## 7. Verdict

Phase 2 and Phase 3 should **not** be marked complete yet. Blocking before the gate: H-1 (fix and add tests), M-1 (fix and add tests) and M-2 (proxy-header decision and global pairing throttle), plus an explicit human decision recorded for ADR-008, ADR-011 and M-3 (refresh-token rotation or risk acceptance). M-4 should be fixed or documented as an accepted contract deviation before Android sync (Phase 4) depends on the response shape. The Low items can be scheduled. After fixes, the full suite must be re-run and logged, and this review re-checked against the new diff.
