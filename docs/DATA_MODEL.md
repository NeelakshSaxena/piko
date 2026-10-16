# Data Model — Finalized for Phase 1

**Status:** Phase 1 — Ready for implementation  
**Last Updated:** 2026-10-16  
**Database:** PostgreSQL (primary), SQLite (local test only where it matches PG behavior)

---

## Core Entities

### User

Represents an authenticated account (parent, operator, or child identity).

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,  -- bcrypt, min 12 rounds
  full_name VARCHAR(255),
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now(),
  status ENUM('active', 'suspended', 'deleted') DEFAULT 'active',
  deleted_at TIMESTAMP NULL
);

CREATE INDEX idx_users_email ON users(email) WHERE status = 'active';
CREATE INDEX idx_users_created_at ON users(created_at);
```

**Rules:**
- Email is immutable once set
- Password is never returned or logged
- Soft-delete only (mark `deleted_at`, do not remove rows)
- Updated_at is automatic on every change

---

### Family

Tenant boundary. Represents a group of parents and children.

```sql
CREATE TABLE families (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now(),
  retention_days INT DEFAULT 30,  -- how long to keep history
  status ENUM('active', 'archived') DEFAULT 'active'
);

CREATE INDEX idx_families_created_at ON families(created_at);
```

**Rules:**
- Created by first parent signup
- Retention_days defines how long to keep telemetry events before deletion
- Cannot be deleted; only archived

---

### FamilyMembership

Links users to families with role and status.

```sql
CREATE TABLE family_memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES families(id),
  user_id UUID NOT NULL REFERENCES users(id),
  role ENUM('parent', 'family_admin', 'guardian', 'child') NOT NULL,
  joined_at TIMESTAMP NOT NULL DEFAULT now(),
  invited_by_user_id UUID REFERENCES users(id),
  invited_at TIMESTAMP,
  status ENUM('active', 'pending', 'revoked') DEFAULT 'active',
  revoked_at TIMESTAMP NULL,
  revoked_by_user_id UUID REFERENCES users(id),
  UNIQUE(family_id, user_id)
);

CREATE INDEX idx_memberships_family ON family_memberships(family_id);
CREATE INDEX idx_memberships_user ON family_memberships(user_id);
CREATE INDEX idx_memberships_status ON family_memberships(status) WHERE status = 'active';
```

**Rules:**
- User must have at least one membership to access system
- Parents and family_admin can invite other parents or family_admin
- Only parents/family_admin can invite children (via device pairing)
- `pending` status means awaiting email confirmation
- `revoked` status means user lost access; keep audit trail
- Role: `parent` (default), `family_admin` (can manage users), `child` (read-only for own data)
- Child membership is created via device pairing, not explicit invite
- `guardian` (ADR-017): view-only adult (e.g. an elder sibling); sees the family, devices and
  locations but cannot pair, revoke or invite
- Adults join through `member_invitations` (below); the membership row is created at acceptance
  and is `active` immediately, so `pending` memberships are not used by invitations

### MemberInvitation (migration 0003, ADR-017)

```sql
CREATE TABLE member_invitations (
  id UUID PRIMARY KEY,
  family_id UUID NOT NULL REFERENCES families(id),
  created_by_user_id UUID NOT NULL REFERENCES users(id),
  invitee_email VARCHAR(255) NOT NULL,          -- normalised, lower-case
  role VARCHAR(16) NOT NULL CHECK (role IN ('parent', 'family_admin', 'guardian')),
  code_hash VARCHAR(64) NOT NULL UNIQUE,        -- HMAC-SHA256 under the server key; never the code
  status VARCHAR(16) NOT NULL DEFAULT 'pending',-- pending | used | expired | revoked
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,              -- created_at + 7 days
  used_at TIMESTAMPTZ NULL,
  used_by_member_id UUID NULL REFERENCES family_memberships(id)
);
-- partial index (family_id, invitee_email) WHERE status = 'pending'
```

---

### Device

Android device enrolled in family.

```sql
CREATE TABLE devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES families(id),
  owner_member_id UUID NOT NULL REFERENCES family_memberships(id),
  name VARCHAR(255) NOT NULL,
  device_model VARCHAR(255),
  android_version VARCHAR(255),
  app_version VARCHAR(255),
  paired_at TIMESTAMP NOT NULL DEFAULT now(),
  last_activity_at TIMESTAMP,
  status ENUM('active', 'inactive', 'revoked') DEFAULT 'active',
  revoked_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_devices_family ON devices(family_id);
CREATE INDEX idx_devices_owner ON devices(owner_member_id);
CREATE INDEX idx_devices_status ON devices(status) WHERE status = 'active';
CREATE INDEX idx_devices_last_activity ON devices(last_activity_at DESC);
```

**Rules:**
- Device credential is separate (see below)
- Owner is derived from initial pairing
- Inactive: no activity for 7 days
- Revoked: parent explicitly revoked; device should re-pair
- Last_activity_at updates on each batch ingest

---

### DeviceCredential

Secure credential for device authentication (rotatable).

```sql
CREATE TABLE device_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id UUID NOT NULL UNIQUE REFERENCES devices(id),
  family_id UUID NOT NULL REFERENCES families(id),
  credential_material TEXT NOT NULL,  -- encrypted JWT private key or symmetric key
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  rotated_at TIMESTAMP,
  revoked_at TIMESTAMP NULL,
  status ENUM('active', 'revoked') DEFAULT 'active'
);

CREATE INDEX idx_credentials_device ON device_credentials(device_id);
CREATE INDEX idx_credentials_family ON device_credentials(family_id);
```

**Rules:**
- Credential material is encrypted at rest (AES-256-GCM)
- Devices present signed JWT: `{device_id, family_id, credential_version, iat, exp}`
- Exp: 24 hours
- Only latest credential accepted
- Previous active credentials kept for replay detection

---

### PairingInvitation

Single-use code for device enrollment.

```sql
CREATE TABLE pairing_invitations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES families(id),
  created_by_user_id UUID NOT NULL REFERENCES users(id),
  pairing_code_hash VARCHAR(255) NOT NULL UNIQUE,  -- bcrypt hash of code
  used_by_member_id UUID REFERENCES family_memberships(id),
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  expires_at TIMESTAMP NOT NULL,  -- 15 minutes from creation
  used_at TIMESTAMP NULL,
  attempt_count INT DEFAULT 0,
  status ENUM('pending', 'used', 'expired', 'revoked') DEFAULT 'pending'
);

CREATE INDEX idx_pairing_family ON pairing_invitations(family_id);
CREATE INDEX idx_pairing_created_by ON pairing_invitations(created_by_user_id);
CREATE INDEX idx_pairing_status ON pairing_invitations(status) WHERE status = 'pending';
CREATE INDEX idx_pairing_expires ON pairing_invitations(expires_at);
```

**Rules:**
- Code is 6 alphanumeric characters, user-friendly
- Hash stored (never plaintext); code returned only on creation
- Expires in 15 minutes
- Single-use: marked `used` after successful pairing
- Rate limit: 3 incorrect attempts before code is locked
- One pending code per user per family

---

### TelemetryEvent

Append-only, immutable event log.

```sql
CREATE TABLE telemetry_events (
  id UUID PRIMARY KEY,  -- stable from device
  family_id UUID NOT NULL REFERENCES families(id),
  device_id UUID NOT NULL REFERENCES devices(id),
  batch_id UUID,  -- for deduplication
  sequence_number BIGINT,  -- per-device counter; may be null
  event_type ENUM('location', 'battery', 'connectivity', 'custom') NOT NULL,
  occurred_at TIMESTAMP NOT NULL,  -- when event happened
  received_at TIMESTAMP NOT NULL DEFAULT now(),  -- when server got it
  schema_version INT DEFAULT 1,
  data JSONB NOT NULL,  -- event-type-specific payload
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_events_family ON telemetry_events(family_id);
CREATE INDEX idx_events_device ON telemetry_events(device_id);
CREATE INDEX idx_events_occurred ON telemetry_events(device_id, occurred_at DESC);
CREATE INDEX idx_events_received ON telemetry_events(received_at DESC);
CREATE UNIQUE INDEX idx_events_dedup ON telemetry_events(device_id, id);  -- prevent re-insert
```

**Constraints:**
- `id` is stable (UUID from device); same id ≠ insert twice
- `occurred_at` ≤ now(), not > 24 hours in past
- `received_at` is server-assigned, immutable
- `sequence_number` is optional (devices may not support ordering)
- `data` schema depends on event_type:
  - `location`: `{latitude, longitude, accuracy_meters}`
  - `battery`: `{percent, is_charging}`
  - `connectivity`: `{network_type, signal_strength}`
  - `custom`: app-defined
- Events are never deleted (append-only); retention enforced via background job

**Data example:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "family_id": "...",
  "device_id": "...",
  "event_type": "location",
  "occurred_at": "2026-10-16T12:34:00Z",
  "received_at": "2026-10-16T12:34:05Z",
  "data": {
    "latitude": 40.7128,
    "longitude": -74.0060,
    "accuracy_meters": 15
  }
}
```

---

### DeviceLatestState

Derived, mutable snapshot of device's latest known state.

```sql
CREATE TABLE device_latest_state (
  device_id UUID PRIMARY KEY REFERENCES devices(id),
  family_id UUID NOT NULL REFERENCES families(id),
  latest_event_id UUID REFERENCES telemetry_events(id),
  latest_event_received_at TIMESTAMP,
  battery_percent INT,
  battery_updated_at TIMESTAMP,
  location_latitude DECIMAL(10, 7),
  location_longitude DECIMAL(10, 7),
  location_accuracy_meters INT,
  location_occurred_at TIMESTAMP,
  location_received_at TIMESTAMP,
  connectivity_status ENUM('online', 'offline', 'unknown') DEFAULT 'unknown',
  connectivity_updated_at TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_latest_family ON device_latest_state(family_id);
CREATE INDEX idx_latest_updated ON device_latest_state(updated_at DESC);
```

**Rules:**
- Updated only by events newer than last_event_received_at
- Never used for authorization (derive from family membership)
- Rebuilt nightly (ensure consistency with events)
- Nullable fields mean no data available

---

### SOSIncident

SOS/emergency event and lifecycle.

```sql
CREATE TABLE sos_incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES families(id),
  device_id UUID NOT NULL REFERENCES devices(id),
  created_by_member_id UUID NOT NULL REFERENCES family_memberships(id),
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  status ENUM('open', 'acknowledged', 'resolved') DEFAULT 'open',
  acknowledged_at TIMESTAMP,
  acknowledged_by_member_id UUID REFERENCES family_memberships(id),
  resolved_at TIMESTAMP,
  resolved_by_member_id UUID REFERENCES family_memberships(id),
  message TEXT,
  location_latitude DECIMAL(10, 7),
  location_longitude DECIMAL(10, 7),
  location_accuracy_meters INT,
  location_captured_at TIMESTAMP,
  parent_notes TEXT,
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_sos_family ON sos_incidents(family_id);
CREATE INDEX idx_sos_device ON sos_incidents(device_id);
CREATE INDEX idx_sos_status ON sos_incidents(status) WHERE status IN ('open', 'acknowledged');
CREATE INDEX idx_sos_created ON sos_incidents(created_at DESC);
```

**Rules:**
- Created by device or parent
- Status lifecycle: `open` → `acknowledged` → `resolved`
- Cannot transition backwards
- Never auto-resolves; requires explicit parent action
- Location is optional (captured at creation time if available)
- Never deleted; audit trail preserved indefinitely
- Parent notes recorded with timestamp and actor

---

### Message

Intra-family message (future expansion; initially minimal).

```sql
CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID NOT NULL REFERENCES families(id),
  sender_member_id UUID NOT NULL REFERENCES family_memberships(id),
  recipient_member_id UUID REFERENCES family_memberships(id),  -- null = broadcast to family
  content_hash VARCHAR(64),  -- SHA256 of encrypted content
  delivery_status ENUM('queued', 'delivered', 'read') DEFAULT 'queued',
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  delivered_at TIMESTAMP,
  read_at TIMESTAMP
);

CREATE INDEX idx_messages_family ON messages(family_id);
CREATE INDEX idx_messages_sender ON messages(sender_member_id);
CREATE INDEX idx_messages_recipient ON messages(recipient_member_id);
CREATE INDEX idx_messages_status ON messages(delivery_status) WHERE delivery_status IN ('queued', 'delivered');
```

**Rules:**
- Content stored separately and encrypted (not in this table)
- Hash allows checking for duplicates without decrypting
- Delivery status tracks: queued (pending), delivered (to device/app), read (user opened)
- Messages for offline devices queued indefinitely (platform does not guarantee delivery)

---

### RefreshSession

Revocable session tokens for browsers.

```sql
CREATE TABLE refresh_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  family_id UUID,  -- may be null; defaults to user's primary
  token_hash VARCHAR(255) NOT NULL UNIQUE,  -- SHA256 of token
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  expires_at TIMESTAMP NOT NULL,  -- 7 days
  revoked_at TIMESTAMP,
  last_used_at TIMESTAMP,
  device_fingerprint VARCHAR(255)  -- optional
);

CREATE INDEX idx_sessions_user ON refresh_sessions(user_id);
CREATE INDEX idx_sessions_expires ON refresh_sessions(expires_at) WHERE revoked_at IS NULL;
```

**Rules:**
- Token never stored plaintext; hash only
- Checked on every refresh request
- Revoked_at set on logout or token rotation
- Expires even if not revoked (max 7 days)

---

### AuditEvent

Security-relevant actions.

```sql
CREATE TABLE audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id UUID REFERENCES families(id),
  actor_user_id UUID REFERENCES users(id),
  actor_device_id UUID REFERENCES devices(id),
  action ENUM('login', 'logout', 'device_paired', 'device_revoked', 'member_invited',
              'member_revoked', 'location_accessed', 'sos_created', 'sos_resolved',
              'credential_rotated', 'session_revoked', 'settings_changed') NOT NULL,
  resource_type ENUM('user', 'family', 'device', 'member', 'incident') NOT NULL,
  resource_id UUID,
  outcome ENUM('success', 'failure') DEFAULT 'success',
  reason TEXT,  -- why it failed, if relevant
  metadata JSONB,  -- request_id, ip_address, user_agent (safe data only)
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_family ON audit_events(family_id);
CREATE INDEX idx_audit_actor ON audit_events(actor_user_id);
CREATE INDEX idx_audit_action ON audit_events(action);
CREATE INDEX idx_audit_created ON audit_events(created_at DESC);
```

**Logging policy:**
- ✅ Log: action, actor, resource ID, outcome
- ❌ Never log: exact coordinates, message content, passwords, device IDs in location contexts

---

## Relationship Diagram

```
User
  ├─ 1:N → FamilyMembership
  ├─ 1:N → AuditEvent (actor)
  ├─ 1:N → PairingInvitation (created_by)
  └─ 1:N → RefreshSession

Family
  ├─ 1:N → FamilyMembership
  ├─ 1:N → Device
  ├─ 1:N → TelemetryEvent
  ├─ 1:N → SOSIncident
  ├─ 1:N → Message
  ├─ 1:N → PairingInvitation
  └─ 1:N → AuditEvent

FamilyMembership
  ├─ N:1 → Family
  ├─ N:1 → User
  ├─ 1:N → Device (owner)
  ├─ 1:N → SOSIncident (created_by, acknowledged_by, resolved_by)
  └─ 1:N → Message (sender, recipient)

Device
  ├─ N:1 → Family
  ├─ N:1 → FamilyMembership (owner)
  ├─ 1:1 → DeviceCredential
  ├─ 1:1 → DeviceLatestState
  ├─ 1:N → TelemetryEvent
  └─ 1:N → SOSIncident

TelemetryEvent
  ├─ N:1 → Family
  ├─ N:1 → Device
  └─ 1:1 → DeviceLatestState (latest_event)

DeviceLatestState
  └─ References TelemetryEvent (latest_event_id)

SOSIncident
  ├─ N:1 → Family
  ├─ N:1 → Device
  ├─ N:1 → FamilyMembership (created_by)
  ├─ N:1 → FamilyMembership (acknowledged_by)
  └─ N:1 → FamilyMembership (resolved_by)

Message
  ├─ N:1 → Family
  ├─ N:1 → FamilyMembership (sender)
  └─ N:1 → FamilyMembership (recipient, optional)
```

---

## Retention & Cleanup

### Data Lifecycle

| Entity | Retention | Cleanup |
|--------|-----------|---------|
| User | Forever (soft-delete) | Never; anonymize on explicit request |
| Family | Forever | Never; can archive |
| FamilyMembership | Forever | Keep audit; mark revoked |
| Device | Forever | Keep history; mark revoked |
| TelemetryEvent | Family-configurable (default 30 days) | Background job deletes nightly |
| SOSIncident | Forever | Never; keep full audit trail |
| Message | Family-configurable (default 90 days) | Background job deletes content after retention |
| AuditEvent | 1 year | Batch delete after retention |
| RefreshSession | 7 days (auto-expire) | Nightly cleanup of expired rows |
| PairingInvitation | Until used or expired (15 min) | Cleanup of expired after 1 day |

**Rules:**
- Never cascade-delete family data; use soft deletes and audit trails
- Operator must be able to prove data was deleted (backups, retention logs)
- Backups are outside scope of this model but must be documented in Phase 8 (Self-Hosting)

---

## Query Patterns & Indexes

**Frequently accessed queries:**
1. Get family members and devices (via family_id)
2. Get device latest state (via device_id)
3. Get location history (via device_id, date range)
4. Get SOS incidents (via family_id, status)
5. Check family membership (via user_id, family_id)
6. Fetch events for retention cleanup (via created_at, family_id)

All indexes created above support these patterns efficiently.

---

## Transactions & Constraints

**Atomic operations:**
- Pairing: create device + device_credential + update membership in transaction
- Event batch ingest: validate + insert events + update latest_state in transaction
- SOS creation: insert incident + audit event in transaction
- Member revocation: mark membership revoked + revoke device credentials + audit in transaction

**Constraints:**
- Foreign keys enforced
- Unique constraints on (family_id, user_id) for membership
- Unique constraints on (device_id) for credentials
- Soft deletes enforced via WHERE clauses (active only)

---

## Open Questions for Phase 1 Review

1. Should message content be in same table or separate encrypted blob table?
2. Device credential rotation strategy: automatic (e.g., 30 days) or manual only?
3. Event archival: export to cold storage after retention or just delete?
4. Time-series optimization: use separate partition by month for events?

These are finalized once architecture review approves scalability and operational requirements.
