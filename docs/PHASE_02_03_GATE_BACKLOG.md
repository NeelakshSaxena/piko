# Phase 2-3 gate backlog (come back here to close the gate)

Created 2026-10-16 at the operator's instruction. Phases 2 and 3 are implemented and tested but the
formal gate (AGENTS.md section 10) is **deliberately left open** while Phases 4-5 proceed. Phase 4/5
work must not be reported as gated-complete on top of an open Phase 2-3 gate.

## Operator decisions already made
- ADR-008 (9-symbol pairing code) and ADR-011 (retention window) approved.
- Invite by code, `guardian` role, no multi-family (ADR-017).
- M-3: refresh-token rotation with reuse detection (ADR-019, implemented).
- **No independent re-audit** of the fixes (operator declined, 2026-10-16). To close the gate the
  operator must either run `prompts/INDEPENDENT_AUDIT.md` once more, or record in `docs/DECISIONS.md`
  an explicit acceptance of the unreviewed fixes (AGENTS.md section 10 requires an independent audit
  for security-critical phases, so acceptance is a documented exception).

## Checklist to close the gate
| # | Item | Source | State |
|---|---|---|---|
| 1 | Re-audit, or explicit written acceptance, of fixes H-1, M-1, M-2, M-4, ADR-017 invites/guardian, ADR-019 rotation | audit | OPEN |
| 2 | One clean full-suite run on the final tree, log saved (last full run: 218 passed, 1 failed before the PUBLIC fix; rotation tests added since) | `phase-02-03-fixes.md` | OPEN |
| 3 | Apply migration `0003` (and `0001`/`0002` if not yet) to the persistent `piko` schema, with a backup first | operator action | OPEN |
| 4 | L-1: `hide_parameters=True` on the engine, plus a test that an unhandled error log carries no SQL parameters | audit | OPEN |
| 5 | L-2: reset/ignore login-failure count after a successful login; make the lockout check atomic | audit | OPEN |
| 6 | L-3: `Cache-Control: no-store` on responses carrying tokens, codes or coordinates | audit | OPEN |
| 7 | L-4: 404 instead of 403 for revoked members on id-addressed routes | audit | OPEN |
| 8 | L-5: decide how much to trust device clocks for ordering/freshness (60 s skew today) | audit | OPEN |
| 9 | L-6: remove the three unused `.env.example` keys, unused schema columns, wrong ADR reference; split runtime vs dev in `requirements.lock`; hash-pin | audit | OPEN |
| 10 | Approve or reject dependency bumps: `pytest` (pinned `<9`, advisory fixed in 9.0.3) and venv `setuptools` 65.5.0 (fixed in 83.0.0) | ADR-016 | OPEN |
| 11 | Retention/cleanup job for telemetry and audit events (nothing deletes old data yet) | ADR-011, R-06 | OPEN |
| 12 | Shared rate-limit store before any multi-instance deployment; proxy-aware client IP before a reverse-proxy deployment | R-03, R-04, M-2 | Phase 8 |
| 13 | Physical-device verification of pairing + telemetry | AGENTS.md 4 | Phase 4/9 |

## Accepted limitations (documented, not blockers)
- Invite codes do not prove email ownership; the redeemer needs the code and the invited address.
- A client that loses a refresh response must log in again (ADR-019).
- Guardian rights for SOS are a Phase 6 decision.
- Rate limits are per process (single-instance self-hosting only).

## Evidence
`docs/verification/phase-02-03-backend.md`, `phase-02-03-security-findings.md`,
`phase-02-03-independent-audit.md`, `phase-02-03-fixes.md`.
