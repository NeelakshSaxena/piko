# Phase 2-3 closure work: audit fixes, invitations, guardian role

**Date:** 2026-10-16. **Gate: NOT PASSED** (see "Remaining").

## Inputs
- Independent audit: `phase-02-03-independent-audit.md` (read-only reviewer; did not run pytest).
- Operator decisions: ADR-008 (9-symbol code) and ADR-011 (retention window) approved; invite endpoint
  by invite code; new limited `guardian` role; no multi-family (ADR-017).

## Changes
| Finding / request | Change | Regression tests |
|---|---|---|
| H-1 (High) malformed event crashed a batch | `domain/telemetry.py`: `OverflowError` from `astimezone` and `float()` now rejects the event | 4 new cases in `test_invalid_events_are_rejected_without_echoing_values` (year 1 with +05:00, year 9999 with -05:00, `10**400` latitude, huge accuracy) |
| M-1 pairing code outlived its issuer | `services/devices.py` + `authz.issuer_is_authorised`; code is revoked and refused with the uniform `AUTH_INVALID` | `test_code_dies_with_its_issuers_membership_or_family` |
| M-2 `X-Forwarded-For` could pick the rate-limit IP | `__main__.py`: `proxy_headers=False` | assertion added to `test_launcher_refuses_public_bind_unless_explicitly_allowed` (checks the launch argument only; no live-proxy test) |
| M-4 id both accepted and rejected | `services/telemetry.py`: repeated id in one batch reported once | `test_event_repeated_inside_one_batch_is_reported_exactly_once` (replaces the old DUPLICATE-expecting test; the old behaviour was the defect) |
| Open decision 3 | `POST /families/{id}/members`, `POST /invitations/accept`, `services/invitations.py`, migration `0003`, `MemberInvitation` | `backend/tests/test_api_invitations.py` (18 tests) |
| Open decision 4 | `guardian` role (`VIEW_ROLES`); `admin_member` renamed `viewable_member` | `test_guardian_can_view_but_not_manage`, `test_guardian_cannot_reach_another_family` |
| Existing test | `/invitations/accept` added to `PUBLIC` in `test_every_route_denies_unauthenticated_requests_by_default` (a deliberate public route; assertions unchanged) | n/a |

Docs updated: `API_CONTRACTS.md`, `DATA_MODEL.md`, `DECISIONS.md` (ADR-008/011 approved, ADR-017, ADR-018).

## Commands and exact results
All against the operator's Supabase PostgreSQL in throwaway `piko_test_*` schemas (ADR-014).
| Command | Result |
|---|---|
| `ruff format --check backend` / `ruff check backend` / `mypy backend/app` (final state) | 44 files formatted / All checks passed / no issues in 26 source files |
| Focused: `test_api_telemetry.py test_api_pairing.py` (after audit fixes) | 56 passed, 1 warning, 511s (`phase-02-03-fixes-focused-pytest.txt`) |
| Focused: `test_api_invitations.py test_migrations.py` | 24 passed, 1 warning, 298s |
| **Full suite** `pytest -v` (`phase-02-03-fixes-pytest-output.txt`) | **218 passed, 1 failed**, 1 warning, 1597s, exit 1. The failure was `test_every_route_denies_unauthenticated_requests_by_default` (new public route not listed in `PUBLIC`) |
| Re-run after adding the route to `PUBLIC`: `test_api_authorization.py test_platform.py` | 33 passed, 1 warning |
| Re-run after final formatting: `test_api_invitations.py` | 18 passed, 1 warning |

**There is no single full-suite run on the final tree.** The full run above preceded the one-line
`PUBLIC` fix and a whitespace-only reformat of one test file; the affected files were re-run as listed.
Run the full suite once more before relying on a clean count. (Earlier baseline: 196 passed.)

## Remaining (why the gate is not passed)
1. **M-3** refresh tokens are not rotated (stolen token valid 7 days): needs an operator decision.
2. The fixes have **not** been re-reviewed by an independent auditor.
3. Audit Low items L-1..L-6 are not addressed (log-parameter hygiene, lockout reset/atomicity,
   `Cache-Control: no-store`, 403 vs 404 for revoked members, device-clock trust, unused `.env.example`
   keys and lock-file hygiene). The invite response carries a secret and, like pairing codes, has no
   `no-store` header (L-3).
4. `pytest`/`setuptools` advisories (ADR-016) still await approval.
5. Migration `0003` has been applied only to throwaway test schemas, not to the persistent `piko` schema.
   Its downgrade deletes guardian memberships and `member_joined` audit rows by necessity.
6. Invitations: email ownership is not verified (the redeemer needs the code and the invited address);
   rate limits are in-process (ADR-008 caveat). Guardian rights for SOS are undecided (Phase 6).
