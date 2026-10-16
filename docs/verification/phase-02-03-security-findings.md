# Phase 2/3 Security Review Findings

**Date:** 2026-10-16
**Reviewer:** coding agent (self-review using `skills/security-review/SKILL.md`). This is **not** an independent audit; `prompts/INDEPENDENT_AUDIT.md` has not been run (see the evidence report).
**Method:** traced identity from transport to service to query for every route; adversarial reading of `backend/app`; tests at the HTTP boundary against real PostgreSQL.

Defects are documented here before any fix, per the skill.

## Defects found during review (documented before fixing)

| ID | Severity | Finding | Reproduction / impact | Status |
|---|---|---|---|---|
| F-01 | Medium | The contract's global fallback rate limit (100 requests/minute) was not implemented. Only per-endpoint limits existed, and for authenticated endpoints they run *after* the authentication lookup. | Unauthenticated callers can send unlimited requests to any protected route; each one costs a database lookup (device-token/session check). Amplified DoS. | **Fixed**: router-level `global_rate_limit` (100/min/IP, runs before auth). Tests: `test_global_rate_limit_applies_before_authentication`, `test_rate_limit_headers_are_reported_on_successful_responses` |
| F-02 | Low | A deeply nested JSON body (for example 100,000 `[`) raises `RecursionError` inside the JSON parser and is returned as HTTP 500 `INTERNAL_ERROR` instead of a 400 `VALIDATION_ERROR`. No detail leaks, but it is a client error reported as a server fault. | `POST /api/v1/telemetry/batches` with body `[[[[...` ~100k deep, within the 512 KiB cap. | **Not reproduced; withdrawn.** Reproduced against the running app on 2026-10-16: three deep-nesting bodies all returned 400 `VALIDATION_ERROR` because FastAPI wraps parser failures. No code change. Regression test kept: `test_deeply_nested_json_is_a_client_error_never_a_500` |
| F-03 | Medium | No `Host` header validation. `docs/SECURITY_MODEL.md` section 6 requires origin *and host* validation, and the API contract has a "CORS & Host Validation" section. | Requests with a forged `Host` are served. Enables host-header attacks if any future feature builds URLs from `Host`; also required for safe reverse-proxy deployment. | **Fixed**: `HostMiddleware` with `PIKO_ALLOWED_HOSTS` (default loopback names plus the host of `PIKO_PUBLIC_BASE_URL`). Test: `test_unexpected_host_headers_are_rejected` |

## Residual risks and accepted limitations (not fixed; need your awareness)

| ID | Severity | Item |
|---|---|---|
| R-01 | Medium | Refresh tokens are not rotated and have no reuse detection (the contract's refresh response returns only an access token). A stolen refresh token works for up to 7 days until the session is revoked. Mitigation: immediate revocation via `/auth/session/revoke`; per-request database check of session state. Recommend rotation in a later contract revision. |
| R-02 | Low | Login lockout is keyed by email, so an attacker who knows a parent's email can lock that account for 15 minutes (10 failures). The alternative (per-IP only) permits distributed guessing. Documented in ADR-012. |
| R-03 | Low | Rate limits are in-process (per instance, reset on restart). Fine for single-instance self-hosting; a multi-instance deployment needs a shared store. Durable login lockout is in the database. |
| R-04 | Low | Client IP is `request.client.host`; forwarded headers are not trusted. Behind a reverse proxy every client shares the proxy's IP until a proxy mode is designed (Phase 8). Per-IP limits would then be shared across all users. |
| R-05 | Low | TLS is not terminated by the application. Production configuration requires an `https` public base URL, but enforcement of HTTPS is the reverse proxy's job (Phase 8). Local development is plain HTTP on loopback. |
| R-06 | Low | Failed logins for nonexistent emails are written to `audit_events` (needed for uniform lockout). Volume is bounded by the 5/minute per-IP limit; there is no retention job yet (the Phase 1 policy of 1 year is not enforced until an operations phase). |
| R-07 | Info | Response compression (gzip) is enabled for bodies over 1 KiB. Responses reflect no attacker-controlled data next to secrets, so BREACH-style attacks do not apply today; revisit if that changes. |
| R-08 | Info | No password change/reset, email verification or MFA: not in the Phase 2 contracts. |
| R-09 | Info | The in-memory rate limiter caps tracked keys at 50,000 and evicts stale entries; a sustained flood from more than 50,000 distinct IPs could still grow memory briefly. |
| R-11 | Low | `pip-audit` (2026-10-16, `docs/verification/phase-02-03-pip-audit.txt`): advisories only in dev/build tooling (`pytest 8.4.2`, fixed in 9.0.3 but the project pins `<9`; venv `setuptools 65.5.0`, fixed in 83.0.0). No runtime dependency is affected. Bumps need operator approval. |
| R-10 | Info | Event-age limit and pairing-code length depart from the contract text (ADR-011, ADR-008) and are **awaiting your confirmation**. |

~~No Critical or High finding was identified in the scope reviewed.~~ **Superseded 2026-10-16:** the independent audit (`phase-02-03-independent-audit.md`) found one High (H-1, a malformed event crashed a whole batch) that this self-review missed, and it showed that R-04 ("forwarded headers are not trusted") and the "every id appears exactly once" claim were overstated (M-2, M-4). Those were fixed under ADR-018; see `phase-02-03-fixes.md`. A self-review is not a proof of security.
