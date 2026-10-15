# API Contracts — Draft for Phase 1

This file defines initial contract intentions, not implemented endpoints. Finalize schemas and error codes in Phase 1 before backend coding.

## Conventions

- Version API paths (for example `/api/v1/...`).
- UTC timestamps in ISO 8601.
- Explicit request/response schemas.
- Stable error codes; no stack traces or sensitive data in client errors.
- Authentication and authorization are mandatory for family data.
- Pagination and bounded limits for history/events.
- Never accept client-supplied family ownership as authority.

## Candidate route groups

- `/api/v1/auth/*`
- `/api/v1/families/*`
- `/api/v1/devices/*`
- `/api/v1/telemetry/batches`
- `/api/v1/members/{member_id}/location`
- `/api/v1/members/{member_id}/status`
- `/api/v1/members/{member_id}/history`
- `/api/v1/sos/*`
- `/api/v1/messages/*`
- `/api/v1/health/live`
- `/api/v1/health/ready`

## Telemetry batch

A batch includes schema version, stable batch ID, and bounded event list. Each event includes stable event ID, sequence number if supported, event type, occurred-at timestamp, and minimal validated payload. Device identity must be derived from its authenticated credential.

Response identifies accepted and duplicate event IDs and any rejected event with a safe error code. Acknowledgement means durable acceptance, not merely request receipt.

## Location response

Must include:
- coordinates only if caller is authorized;
- observed/occurred timestamp;
- server received timestamp when useful;
- accuracy in metres when available;
- freshness classification;
- device connectivity/source state;
- explicit unknown/unavailable state.

## Error categories

- `AUTH_REQUIRED`
- `AUTH_INVALID`
- `FORBIDDEN`
- `NOT_FOUND_OR_NOT_VISIBLE`
- `VALIDATION_ERROR`
- `RATE_LIMITED`
- `CONFLICT`
- `SERVICE_UNAVAILABLE`
- `INTERNAL_ERROR`

Use a non-enumerating response for resources the caller is not allowed to discover.
