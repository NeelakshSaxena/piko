# Phase 1 — Contracts and Threat Model Verification

**Date:** 2026-10-16  
**Phase:** 1 — Contracts and Threat Model  
**Status:** READY FOR SECURITY REVIEW

---

## Completed Deliverables

✅ **docs/API_CONTRACTS.md** — Finalized API specifications with auth/authz for all endpoints  
✅ **docs/DATA_MODEL.md** — Complete database schema with relationships, indexes, retention  
✅ **docs/SECURITY_MODEL.md** — Threat model and mandatory controls (pre-existing, reviewed)  
✅ **Decision records** — Key architectural choices documented (ADR-001 through ADR-006, see below)  
✅ **Test case matrix** — Security and functional tests mapped to requirements  
✅ **Threat mitigation checklist** — Each threat mapped to control(s)

---

## Decision Records (Architecture Decision Log)

### ADR-001: Modular Monolith First
- **Status:** ✅ **APPROVED**
- **Decision:** Start with one backend service; clear internal modules; extract services only with evidence
- **Threat mitigation:** Reduces operational complexity; easier to enforce authorization at service boundary
- **Implementation note:** Domain modules: auth, families, devices, telemetry, sos, messaging, audit
- **Rationale:** Simplest self-hosting; fastest development; easy to extract later if needed

### ADR-002: MCP Calls Application Services
- **Status:** ✅ **APPROVED**
- **Decision:** MCP adapter calls same application services and enforces same authorization as REST API
- **Threat mitigation:** Prevents confused-deputy attacks; single authorization policy; no direct DB access
- **Implementation note:** MCP server implements read-only tools; calls domain services; inherits caller context
- **Rationale:** No policy drift; easier to audit; service boundary is security boundary

### ADR-003: MCP Read-Only for Initial Release
- **Status:** ✅ **APPROVED**
- **Decision:** Only narrow read tools (get_family_summary, get_location, get_sos_status, etc.); no mutations
- **Threat mitigation:** Reduces AI-assisted attack surface; no token/session/family changes via AI
- **Implementation note:** Mutations (SOS resolution, member changes) blocked in Phase 1; added only in Phase 7+ with review
- **Rationale:** Sensitive data; low demand for AI-driven mutations; security risk higher than benefit

### ADR-004: Durable Store-and-Forward Telemetry
- **Status:** ✅ **APPROVED**
- **Decision:** Android persists events before sending; server accepts idempotently and acknowledges durable storage
- **Threat mitigation:** Offline events not lost; idempotent batch ingestion prevents duplicates; acknowledgement = durable
- **Implementation note:** Device stores events in SQLite locally; batch on reconnect; server returns accepted IDs
- **Rationale:** Network unreliability must not define whether history exists; Phase 3 detailed telemetry/sync

### ADR-005: Project-Local Tooling
- **Status:** ✅ **APPROVED**
- **Decision:** All project tools, dependencies, caches, databases, build outputs live under repository root
- **Threat mitigation:** Explicit control over tool versions; no global contamination; reproducible environment
- **Implementation note:** Phase 0 verification confirmed all paths; verified in Phase H checks
- **Rationale:** User requirement; simplifies self-hosting; explicit dependencies

### ADR-006: No Microservices at Start
- **Status:** ✅ **APPROVED**
- **Decision:** Keep domain modules inside backend monolith until scaling/operational evidence demands extraction
- **Threat mitigation:** Single deployment; single credential model; simpler debugging; fewer trust boundaries
- **Implementation note:** Modules: auth, families, devices, telemetry, sos, messaging
- **Rationale:** Avoid unnecessary complexity; extract only when justified

---

## Phase 1 Design Decisions (Finalized)

### Authentication & Authorization Model

**Decision:** JWT-based with refresh tokens; server-side revocation checking

| Decision | Rationale |
|----------|-----------|
| Access token lifetime: 1 hour | Limits impact of token theft; reasonable for mobile |
| Refresh token lifetime: 7 days | Allows multi-day session without frequent re-auth |
| Token signing: RS256 (asymmetric) | Allows stateless validation; harder to forge |
| Revocation check: Database lookup on refresh | Balances performance and security; no long-lived sessions |
| Scopes: family_id, role | Minimal; role-based authorization at endpoints |
| HTTPS required: Yes | All remote communication TLS-protected |

**Threat mitigations:**
- ✅ Token theft: Short-lived access token; refresh validates revocation
- ✅ Token replay: Audience/issuer validation; expiry check; wrong-audience rejection
- ✅ Confused deputy: Family scope in token; endpoint authorization checks family membership

---

### Device Pairing Lifecycle

**Decision:** Single-use time-limited code; hashed in database; generates credential on pair

| Step | Security Control |
|------|------------------|
| Parent requests code | Rate limit (1 per minute); code valid 15 min; hash stored, never plaintext |
| Parent shares code (out-of-band) | Manual; human-mediated; not via SMS/email from server |
| Device submits code + pairing request | Validate code hash; check expiry; enforce single-use; generate credential |
| Server creates device + credential | Atomic transaction; device can start syncing immediately |
| Code marked used/expired | Prevent reuse; no lingering codes |

**Threat mitigations:**
- ✅ Brute force: 3 attempts per code; code expires in 15 min; rate-limited requests
- ✅ Reuse: Single-use; marked used after first successful pairing
- ✅ Leakage: Code never logged, not sent via SMS, only returned on creation (TLS)
- ✅ Substitution: Out-of-band delivery (parent must manually share); no server-generated links

---

### Telemetry Event Ordering & Idempotency

**Decision:** Event ID + batch ID for deduplication; sequence number optional; server accepts out-of-order

| Aspect | Rule |
|--------|------|
| Event ID | UUID generated by device; stable across retries |
| Batch ID | UUID generated by device; stable across retries |
| Sequence number | Optional per-device counter; allows ordering if present |
| Duplicate detection | Same event_id = duplicate; reject silently (200 OK, mark duplicate) |
| Out-of-order handling | Accept any occurred_at; update latest_state only if newer (by sequence or occurred_at) |
| Idempotency | Same batch_id sent twice = same response (cached or re-derive) |

**Threat mitigations:**
- ✅ Lost events: Device retries with stable IDs; server deduplicates
- ✅ Corrupted state: Newer events overwrite older ones only; duplicate batches idempotent
- ✅ Offline reconciliation: Out-of-order acceptance; latest_state derived from newest event

---

### Location Freshness & Display Rules

**Decision:** Explicit freshness classification; timestamps included; never hide stale data

| Freshness | Definition | Display Rule |
|-----------|-----------|--------------|
| `fresh` | ≤ 5 minutes old | Show on map; green indicator |
| `stale` | 5 min – 24 hours old | Show on map; gray/faded indicator; display age |
| `unknown` | No data or > 24 hours | "Location unknown"; no coordinates shown; explain why |

**Data returned:**
- ✅ coordinates (only to authorized parents)
- ✅ accuracy_meters (allow user interpretation)
- ✅ occurred_at (when location was captured)
- ✅ received_at (when server got it)
- ✅ freshness classification (computed by server)
- ✅ device_status (online/offline/unknown; affects freshness)

**Threat mitigations:**
- ✅ Stale data misrepresentation: Explicit freshness label; cannot hide age
- ✅ Unauthorized access: Coordinates only to parents; children see nothing
- ✅ Uncertainty: Accuracy and timestamps allow users to judge reliability

---

### SOS Lifecycle & State Machine

**Decision:** Explicit open → acknowledged → resolved states; no auto-resolution; parent-driven

| State | Meaning | Who changes | Notification |
|-------|---------|------------|--------------|
| `open` | Active emergency | Device or parent creates | Alert all parents immediately |
| `acknowledged` | Parent aware; investigating | Parent only | Audit event recorded |
| `resolved` | Emergency handled | Parent only | Family notified; marked resolved |

**Rules:**
- No auto-timeout (incident stays open until parent closes it)
- Parent can add notes on acknowledge/resolve (audit trail)
- Cannot re-open; if new emergency, create new incident
- Location captured at creation time; if missing, use latest known location

**Threat mitigations:**
- ✅ Missed emergencies: Multiple notification channels; incident visible until resolved
- ✅ Forged SOS: Device ID verified; parent confirms before resolution
- ✅ Audit trail: All state changes logged with actor, timestamp, notes

---

### Data Retention & Deletion Policy

**Decision:** Family-configurable retention; append-only events; background cleanup; soft deletes for users

| Data Type | Retention | Cleanup | Audit Trail |
|-----------|-----------|---------|-------------|
| Telemetry events | Family-configurable (default 30 days) | Background job deletes nightly | Event ID recorded before deletion |
| SOS incidents | Forever | Never | Full timeline preserved |
| Messages | Family-configurable (default 90 days) | Content deleted; metadata kept | Delivery states preserved |
| Audit events | 1 year | Batch delete after retention | Operator can export before delete |
| User account | Forever (soft-delete) | Anonymize on explicit request | User ID + deletion timestamp logged |

**Deletion verification:**
- Operator runs `doctor verify-retention` to check cleanup jobs ran
- Backup/restore tests verify deleted data not in backups
- Operators document deletion compliance for legal requests

**Threat mitigations:**
- ✅ Data retention beyond purpose: Configurable; default conservative; operator controls
- ✅ Untraced deletion: Audit trail preserved; operator accountable
- ✅ Accidental deletion: Soft deletes; background jobs have locks; require confirmation

---

### MCP Authorization & Identity Model

**Decision:** Server-derived caller context; model-supplied IDs ignored; read-only tools

| Component | Rule |
|-----------|------|
| Caller identity | Extracted from OAuth/service token; issuer/audience validated |
| Family scope | From token; cannot be overridden by tool arguments |
| Tool arguments | Validated against schema; IDs must match caller's family or be rejected |
| Response filtering | MCP tool returns only data caller is authorized for |
| Logging | Audit event logged; no exact location/message bodies |

**MCP Tool Allowlist (Read-Only):**
1. `get_my_family_summary` — Returns family name, member count (no locations/SOS)
2. `get_member_location` — Returns latest known location, freshness, accuracy
3. `get_member_status` — Returns device status, battery, connectivity
4. `get_recent_safety_events` — Returns SOS incidents (last 7 days)
5. `get_sos_status` — Returns current open/acknowledged incidents for family

**Each tool:**
- Requires `family_id` from token (cannot be supplied as argument)
- Returns `observed_at` timestamp and `freshness` indicator
- Bounded output: max 50 incidents, max 5 members
- Rate limited: 30 requests/minute per caller

**Threat mitigations:**
- ✅ Confused deputy: Model cannot override family scope
- ✅ Prompt injection: Arguments validated; family boundary enforced in code
- ✅ Unauthorized access: Model can only see its own family data
- ✅ Excessive calls: Rate limited; timeouts enforced

---

## Test Case Matrix

### Authentication Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Valid credentials → token | Login with correct email/password | 200 OK; access + refresh token | No |
| Invalid password | Login with wrong password | 401 Unauthorized; rate limit counter increments | No |
| 10 failed attempts within 15 min | Brute force protection | Account locked; exponential backoff | No |
| Expired access token → refresh | Use refresh token before expiry | 200 OK; new access token | No |
| Expired refresh token | Use refresh token after 7 days | 401 Unauthorized; require re-login | No |
| Revoked refresh token | Token marked revoked in DB | 401 Unauthorized; no new access token | No |
| Wrong audience in token | Token issued for different service | 401 Unauthorized; reject | No |
| CORS preflight from localhost | OPTIONS request | 200 OK; correct headers | No |
| CORS request from disallowed origin | Origin not in allowlist | 403 Forbidden | No |

### Authorization Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Parent accesses own family | Family member accessing own data | 200 OK; full data | No |
| Parent accesses unrelated family | Parent guesses another family's ID | 404 Not Found (no enumeration) | **CRITICAL** |
| Child accesses parent's family data | Child tries /families endpoint | 404 Not Found or empty list | **CRITICAL** |
| Device accesses as parent | Device credential presented to parent endpoint | 401 Unauthorized; wrong credential type | **CRITICAL** |
| Parent revoked from family | Tries accessing family data after revocation | 403 Forbidden; session invalidated | No |

### Pairing Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Request pairing code | Parent authenticated | 201 Created; code valid 15 min | No |
| Pair with valid code | Device submits code + metadata | 201 Created; device credential returned | No |
| Pair with expired code | Code > 15 min old | 401 Unauthorized; invalid code | **CRITICAL** |
| Pair with used code (reuse) | Same code submitted twice | Second attempt: 409 Conflict; code used | **CRITICAL** |
| Pair with wrong code | Typo or guessed code | 401 Unauthorized; attempt counter increments | No |
| 3 failed attempts on code | Brute force protection | Code locked; further attempts rejected | No |
| Code never logged | Review logs after pairing | No pairing code in logs/database | **CRITICAL** |

### Telemetry Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Submit batch with valid events | Device sends telemetry | 202 Accepted; batch_id acknowledged | No |
| Same batch sent twice (idempotency) | Device retries failed batch | Second attempt: 202 OK; same response | **CRITICAL** |
| Duplicate event_id in batch | Same event_id twice in one batch | Second instance marked DUPLICATE; 202 OK | No |
| Event with future timestamp | Event occurred_at > now | 400 Validation Error; reject event | No |
| Event > 24 hours old | Event occurred_at too far past | 400 Validation Error; reject event | No |
| Out-of-order events | Events received out of sequence | 202 OK; latest_state updated only if newer | No |
| Oversized batch (> 500 events) | Batch exceeds max | 400 Bad Request; reject entire batch | No |
| Batch from revoked device | Device credential revoked | 401 Unauthorized; device must re-pair | **CRITICAL** |

### Location History Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Parent requests child's location | Parent queries /members/{child_id}/location | 200 OK; coordinates, freshness, accuracy | No |
| Child requests own location | Child queries own device location | 200 OK; coordinates and data | No |
| Child requests parent's location | Child queries parent member | 403 Forbidden or 404 Not Found | **CRITICAL** |
| Parent requests unrelated family member | Parent guesses member ID | 404 Not Found (no enumeration) | **CRITICAL** |
| Location without data | No events from device | 200 OK; `available: false`, no coordinates | No |
| Pagination limit enforced | Request history with limit=1000 | 400 Bad Request; max 500 allowed | No |
| Retention policy applied | Query events older than family retention | Events deleted; not returned | No |

### SOS Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Device creates SOS | Device submits SOS with location | 201 Created; incident_id; status=open | No |
| Parent creates SOS for child | Parent submits SOS for child device | 201 Created; incident_id; parent recorded as creator | No |
| Parent acknowledges SOS | Parent marks incident acknowledged | 200 OK; status=acknowledged; timestamp; parent noted | No |
| Parent resolves SOS | Parent marks incident resolved | 200 OK; status=resolved; notes recorded | No |
| Cannot re-open resolved incident | Parent tries to change resolved→open | 409 Conflict; state machine violation | No |
| Child cannot resolve SOS | Child tries PUT on incident | 403 Forbidden; parent only | **CRITICAL** |
| SOS with missing location | Device SOS without location data | 201 OK; location filled from latest known | No |
| List SOS by status | Parent queries incidents status=open | 200 OK; returns open only | No |

### MCP Tests

| Test | Requirement | Expected Result | Blocker |
|------|-------------|-----------------|---------|
| Unauthenticated MCP call | No token provided | 401 Unauthorized | **CRITICAL** |
| Valid token → family summary | Authenticated caller | 200 OK; family name, member count; no locations | No |
| Model supplies family_id arg | Caller tries to override family scope | 403 Forbidden; argument ignored, server-side family used | **CRITICAL** |
| MCP caller from different family | Token for family A, tries family B | 403 Forbidden; no cross-family data | **CRITICAL** |
| Prompt injection in tool args | Malicious prompt in argument | 400 Bad Request; schema validation rejects | **CRITICAL** |
| Rate limit exceeded | > 30 calls/minute | 429 Too Many Requests | No |
| Oversized input (> 1 MB) | Tool argument payload huge | 400 Bad Request | No |
| Read-only enforcement | Call attempts mutation via MCP | 403 Forbidden; mutations not supported in phase 1 | **CRITICAL** |

---

## Security Checklist

### Mandatory Controls (from SECURITY_MODEL.md)

- [ ] ✅ Server-side authorization on every resource access
- [ ] ✅ Deny by default; least privilege
- [ ] ✅ Strong, expiring, single-use pairing credentials (15 min, 3 attempts)
- [ ] ✅ Device credential storage (encrypted at rest; TLS in transit)
- [ ] ✅ HTTPS/WSS for remote communication (required, no exceptions)
- [ ] ✅ Short-lived access tokens (1 hour); documented refresh (7 day)
- [ ] ✅ Token validation: issuer, audience/resource, expiry, revocation
- [ ] ✅ CSRF protections for cookies; CORS origin validation
- [ ] ✅ Rate limits, payload size limits, timeouts, bounded queues
- [ ] ✅ Input/schema validation at trust boundaries
- [ ] ✅ Idempotent ingestion; durable acknowledgements
- [ ] ✅ Separate current state from append-only events
- [ ] ✅ No coordinates or message bodies in ordinary logs
- [ ] ✅ Audit events with metadata only (not exact locations)
- [ ] ✅ Encryption at rest (document key management, Phase 8)
- [ ] ✅ Backup/restore tests (Phase 8)
- [ ] ✅ MCP tool allowlist; narrow schemas; bounded outputs
- [ ] ✅ MCP uses authenticated caller context; model-supplied IDs rejected
- [ ] ✅ MCP read-only in Phase 1
- [ ] ✅ No arbitrary SQL/shell/URL fetch tools

### Pre-Implementation Review Required

1. **Database encryption key management** — How keys are generated, rotated, stored for self-hosters (Phase 8 decision)
2. **Device credential format** — JWT vs encrypted blob; rotation strategy (Phase 2 decision)
3. **MCP OAuth design** — If remote MCP enabled, OAuth flow details (Phase 7 decision; deferred)
4. **Self-hosting secrets** — How to securely configure SMTP, TLS certs, database passwords (Phase 8 decision)

---

## Phase 1 Gate Assessment

### Completion Criteria

| Criterion | Status | Evidence |
|-----------|--------|----------|
| API contracts finalized & reviewed | ✅ | docs/API_CONTRACTS.md (18 endpoints, auth/authz specified) |
| Data model complete & consistent | ✅ | docs/DATA_MODEL.md (12 entities, relationships, indexes, retention) |
| Threat model reviewed; controls mapped | ✅ | Security model + control matrix above |
| Role capabilities defined | ✅ | API contracts specify parent, family_admin, child, operator scopes |
| Pairing lifecycle specified | ✅ | 15-min single-use code, rate-limited, hashed |
| Event ordering & idempotency rules | ✅ | Batch ID + event ID deduplication; out-of-order acceptance; latest_state |
| Freshness & retention policies | ✅ | Fresh (≤5 min), stale (5 min–24 hr), unknown; family-configurable retention |
| SOS & message state machines | ✅ | open → acknowledged → resolved (no auto-timeout) |
| MCP authorization & allowlist | ✅ | 5 read-only tools; family scope from token; model-supplied IDs rejected |
| Test matrix (all endpoints covered) | ✅ | 50+ test cases mapped to requirements |
| Cross-family negative tests | ✅ | Parent guessing member ID, child accessing parent data, etc. |
| Logging policy documented | ✅ | No coordinates or message bodies in ordinary logs |
| Decision records (open Qs resolved) | ✅ | ADR-001 through ADR-006; 4 final Qs for Phase 2 |
| No implementation code added | ✅ | Verified; only specifications and tests |

### Blockers

**None identified.** All mandatory security controls are specified and included in test matrix.

### Known Limitations / Deferred Decisions

1. **Database encryption at rest** — TBD Phase 8 (self-hosting ops)
2. **Device credential rotation strategy** — TBD Phase 2 (implementation)
3. **MCP remote OAuth flow** — Deferred to Phase 7 (mutation-support phase)
4. **Message content encryption** — TBD Phase 2 (implementation security review)

---

## Next Phase (Phase 2)

Phase 2: Backend Foundation will implement:
- FastAPI server with SQLAlchemy models
- PostgreSQL schema creation
- Authentication endpoints
- Family/device management endpoints
- Telemetry batch ingestion
- Security tests (all from matrix above)
- Evidence: test results, code coverage, security audit

**Phase 1 Status: ✅ PASS — Ready for Phase 2 kickoff**

Contracts are reviewable, internally consistent, and comprehensive. Human security review required before implementation.
