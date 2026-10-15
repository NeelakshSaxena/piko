# Data Model — Initial Proposal

Finalize in Phase 1. Avoid adding fields without a use case and retention rationale.

Core entities:
- `User`: authentication subject and account state.
- `Family`: tenant boundary.
- `FamilyMembership`: user, family, role, status, timestamps.
- `Device`: enrolled Android device, public metadata, credential reference/status.
- `PairingInvitation`: hashed invitation secret, expiry, use count/state.
- `TelemetryEvent`: append-only event ID, device ID, sequence, occurred-at, received-at, schema version, event type, minimal payload.
- `DeviceLatestState`: current derived status, latest accepted event timestamp, location freshness and selected latest fields.
- `SOSIncident`: stable ID, sender device, created-at, status and delivery/acknowledgement/resolution timestamps.
- `Message`: sender, recipient/family context, minimal content, created-at and delivery state.
- `AuditEvent`: actor, action, resource class/ID where safe, outcome, timestamp, request correlation ID; no exact coordinates or message body by default.
- `RefreshSession` or equivalent: revocable session metadata.

Rules:
- Foreign keys and indexes reflect actual access patterns.
- Every family-scoped query verifies membership/role.
- Device ownership is derived from server-side enrollment.
- Event history is append-only except explicitly documented retention/deletion.
- Current state is derived separately and updated only by a newer accepted event.
- Retention and deletion semantics must be tested.
