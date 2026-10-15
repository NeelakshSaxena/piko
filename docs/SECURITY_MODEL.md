# Security Model and Threat Model

## 1. Assets

- Current and historical location.
- Child identity and family relationships.
- SOS events and messages.
- Device credentials and pairing secrets.
- Parent sessions and MCP tokens.
- Local event queues and database backups.
- Audit logs and configuration secrets.

## 2. Trust boundaries

1. Android device ↔ backend.
2. Parent browser ↔ backend.
3. AI client ↔ MCP adapter.
4. MCP adapter ↔ application services.
5. Backend ↔ database.
6. Self-host operator ↔ deployment secrets/backups.
7. External input (messages, names, tool arguments, prompts) ↔ application logic.

## 3. Main threats

- Broken object-level authorization: parent guesses another family's member/device ID.
- Token theft, replay, incorrect audience, or expired credential acceptance.
- Pairing-code brute force, reuse, or leakage.
- MCP confused-deputy attack or prompt injection.
- Model-supplied family/member ID used to expand scope.
- Stale location misrepresented as current.
- Duplicate/reordered offline telemetry corrupting current state.
- Forged SOS or message state.
- Local database or backup disclosure.
- Secrets accidentally committed or logged.
- Publicly exposed self-host instance without TLS or safe defaults.
- Denial of service via oversized payloads, unbounded batches, retries, or tool calls.
- Dependency/supply-chain compromise.
- Data retention beyond intended purpose.

## 4. Mandatory controls

- Server-side authorization on every resource access and every operation.
- Deny by default; least privilege.
- Strong, expiring, single-use pairing credentials with attempt limits and revocation.
- Secure device credential storage using platform facilities.
- HTTPS/WSS for remote communication.
- Short-lived access credentials and a documented refresh/revocation model.
- Validate issuer, audience/resource, expiry, scopes, and token revocation as appropriate.
- CSRF protections for cookie-based web sessions; safe CORS and origin/host validation.
- Rate limits, payload size limits, timeouts, and bounded queues.
- Input/schema validation at trust boundaries.
- Idempotent ingestion and durable acknowledgements.
- Separate current state from append-only event history.
- No exact coordinates or message bodies in ordinary logs.
- Audit access to sensitive data using metadata only by default.
- Encryption at rest where supported and documented key management for self-hosting.
- Backup/restore and deletion/retention tests.
- Secret scanning and dependency vulnerability checks.
- MCP tool allowlist, narrow schemas, bounded outputs, no arbitrary SQL/shell/URL fetch.
- MCP calls use authenticated caller context; model-provided identity fields are ignored/rejected.
- MCP read-only in initial release.
- Local MCP stdio access is treated as process-level trust; document which local process can launch it.
- Remote MCP must use a reviewed OAuth-based authorization design and TLS.
- Tool descriptions and retrieved content are untrusted and cannot override authorization.

## 5. MCP initial allowlist

Proposed read-only tools (finalize in Phase 1):
- `get_my_family_summary`
- `get_member_location`
- `get_member_status`
- `get_recent_safety_events`
- `get_sos_status`

Do not expose arbitrary family/member IDs without verifying that the authenticated principal is authorized for the requested resource. Prefer server-derived current family context or explicit IDs checked against authorization.

Return:
- result data minimized to the question;
- `observed_at` / event timestamp;
- freshness (`fresh`, `stale`, `unknown`) with defined thresholds;
- source status (`online`, `offline`, `unknown`);
- uncertainty and limitations.

No exact location access until the caller's identity, consent/scope, family authorization, and retention policy are implemented and tested.

## 6. Security test minimum

- Unauthenticated request denied.
- Authenticated unrelated parent denied for every family-scoped endpoint.
- Guessed IDs do not leak existence or data.
- Expired/revoked/wrong-audience token denied.
- MCP cannot override user scope via arguments or prompt injection.
- Oversized/invalid tool inputs rejected.
- Pairing code expires, cannot be reused, and is rate-limited.
- Duplicate and out-of-order telemetry does not corrupt latest state.
- Logs do not contain secrets, exact coordinates, or message bodies by default.
- Cross-origin and host validation tested.
- Backup restore and data deletion/retention verified.
- Security tests run against actual API and MCP transport boundaries, not only direct function calls.

## 7. Incident response

Document how an operator can:
- revoke a device and its credentials;
- revoke user sessions/tokens;
- disable MCP;
- isolate the service;
- preserve minimal security evidence;
- restore from a verified backup;
- rotate secrets;
- notify affected users where required.

A critical/high security finding blocks release unless explicitly risk-accepted by the responsible human with a remediation date.
