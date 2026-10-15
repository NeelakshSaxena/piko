# Phase 3 — Telemetry Ingestion and Offline Reconciliation

## Goal
Implement the minimal event schema and idempotent batch ingestion that safely reconciles delayed offline records.

## Required behaviour
- Validate authenticated device identity server-side.
- Bound event count and payload size.
- Deduplicate by stable event ID and/or sequence key.
- Store occurrence timestamp and server receipt timestamp separately.
- Acknowledge only durable accepted records.
- Update current state only when an accepted event is newer by the approved ordering rule.
- Preserve out-of-order history.
- Expose stale/unknown status honestly.
- Provide integration tests with a real PostgreSQL test database.

## Verification cases
1. New event accepted.
2. Duplicate event does not create duplicate history.
3. Older delayed event is stored but does not overwrite newer latest state.
4. Partial batch failure has unambiguous per-event result.
5. Invalid timestamp/payload rejected.
6. Unenrolled/revoked device rejected.
7. Batch limits and rate limits enforced.
8. Ack is not sent before commit.
9. Retention job (if included in this phase) respects approved policy.

## Stop conditions
Stop if event ordering, idempotency, device identity, or acknowledgement semantics are ambiguous. Do not start Android sync until the contract is stable.
