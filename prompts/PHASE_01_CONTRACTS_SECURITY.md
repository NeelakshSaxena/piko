# Phase 1 — Contracts and Threat Model

Read AGENTS.md and Phase 0 evidence. Do not implement feature code.

## Goal
Finalize product boundaries, API DTOs, data model, authorization matrix, threat model, event ordering, freshness rules, retention policy, and error contracts before implementation.

## Required deliverables
- Updated `docs/API_CONTRACTS.md`
- Updated `docs/DATA_MODEL.md`
- Updated `docs/SECURITY_MODEL.md`
- Decision records for unresolved choices
- `docs/verification/phase-01-contracts.md`
- Test case matrix mapping each requirement to tests

## Requirements
- Define parent, child/device, family admin, and self-host operator capabilities.
- Define device pairing lifecycle and revocation.
- Define event IDs/sequence rules, occurred-at vs received-at, idempotency, batch bounds, and durable acknowledgement.
- Define location freshness thresholds and how unknown/stale states appear.
- Define SOS lifecycle and message delivery states.
- Define retention and deletion semantics.
- Define MCP caller identity, scopes, family authorization, allowlisted read tools, and local stdio trust boundary.
- Do not assume the model supplies trusted identity.
- Decide the initial auth/session model with security review.

## Verification
- Every endpoint/tool has authentication and authorization requirements.
- Cross-family negative tests are specified.
- Every sensitive field has a retention/logging policy.
- All open questions are listed, assigned, and explicitly block affected implementation.
- No implementation code is added.

## Exit gate
PASS when the contracts are reviewable and internally consistent, and a human approves security-sensitive decisions. Otherwise BLOCKED.
