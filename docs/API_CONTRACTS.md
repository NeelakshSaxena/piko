# API Contracts — Finalized for Phase 1

**Status:** Phase 1 — Ready for implementation  
**Last Updated:** 2026-10-16

---

## Conventions

- **Versioning:** All endpoints use `/api/v1/...` prefix
- **Timestamps:** UTC ISO 8601 format (e.g., `2026-10-16T12:34:56Z`)
- **IDs:** UUIDs for resources; stable, non-enumerable
- **Authentication:** Bearer token in `Authorization: Bearer <token>` header
- **Errors:** Structured JSON with stable error codes; no stack traces or coordinates in client responses
- **Pagination:** `limit` (default 50, max 500) and `offset` (default 0)
- **Resource scope:** All family-scoped endpoints require authenticated family membership and role authorization

---

## Authentication & Sessions

### `POST /api/v1/auth/session`

**Purpose:** Authenticate parent/operator and create session.

**Request:**
```json
{
  "email": "parent@example.com",
  "password": "password_hash",
  "device_fingerprint": "optional_device_id"
}
```

**Response:** `200 OK`
```json
{
  "access_token": "jwt_token",
  "refresh_token": "jwt_token",
  "expires_in": 3600,
  "user_id": "uuid",
  "family_id": "uuid",
  "role": "parent|family_admin|operator",
  "families": [{"id": "uuid", "name": "...", "role": "..."}]
}
```

**Error codes:** `AUTH_INVALID`, `FORBIDDEN` (user not in family), `RATE_LIMIT`  
**Requirements:**
- Rate limit: 5 attempts per IP per minute
- Reject after 10 failed attempts within 15 minutes (exponential backoff)
- Validate email/password against bcrypt hash
- Token expiry: 1 hour access, 7 days refresh
- HTTPS only

---

### `POST /api/v1/auth/session/refresh`

**Purpose:** Refresh access token using valid refresh token.

**Request:** `Authorization: Bearer <refresh_token>`

**Response:** `200 OK`
```json
{
  "access_token": "jwt_token",
  "refresh_token": "jwt_token",
  "expires_in": 3600
}
```

**Error codes:** `AUTH_INVALID`, `AUTH_REQUIRED`, `RATE_LIMIT`  
**Requirements:**
- Validate refresh token issuer, audience, expiry
- Check revocation status in database
- Rate limit: 10 per minute per user (applied before rotation)
- **Rotation (ADR-019):** every refresh returns a new refresh token and voids the old one. The client
  must store the new token before using it. Presenting a superseded token revokes the whole session
  (the client must log in again); this is also what a lost refresh response looks like, so clients
  should retry a refresh only if they know the request never reached the server.

---

### `POST /api/v1/auth/session/revoke`

**Purpose:** Revoke current session immediately.

**Request:** `Authorization: Bearer <access_token>`

**Response:** `204 No Content`

**Requirements:**
- Mark token as revoked in database
- Immediate effect (no caching)

---

## Families & Membership

### `GET /api/v1/families`

**Purpose:** List families user is member of.

**Response:** `200 OK`
```json
{
  "families": [
    {
      "id": "uuid",
      "name": "Smith Family",
      "created_at": "2026-01-01T00:00:00Z",
      "member_count": 4,
      "device_count": 2,
      "my_role": "parent|family_admin|child",
      "status": "active"
    }
  ]
}
```

**Requirements:**
- Return only families where user is active member
- No child families listed (children see nothing)

---

### `GET /api/v1/families/{family_id}`

**Purpose:** Get family summary and member list.

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "name": "...",
  "created_at": "...",
  "my_role": "parent|family_admin|child",
  "members": [
    {
      "id": "uuid",
      "email": "parent@example.com",
      "name": "Parent Name",
      "role": "parent|family_admin|child",
      "joined_at": "...",
      "status": "active|pending|revoked"
    }
  ],
  "devices": [
    {
      "id": "uuid",
      "name": "Child Phone",
      "device_type": "android",
      "owner_member_id": "uuid",
      "paired_at": "...",
      "last_seen": "...",
      "status": "active|inactive|revoked"
    }
  ]
}
```

**Error codes:** `AUTH_REQUIRED`, `FORBIDDEN`, `NOT_FOUND_OR_NOT_VISIBLE`

**Requirements:**
- Verify caller is family member (prevent enumeration of unrelated families)
- Parents see all members and devices
- Children see only their own device
- Return `NOT_FOUND_OR_NOT_VISIBLE` for non-existent or unauthorized families

---

### `POST /api/v1/families/{family_id}/members`

**Purpose:** Invite a new adult family member (parent/family_admin only). Revised by ADR-017: no
email is sent; the inviter receives a single-use invite code and gives it to the invitee.

**Request:**
```json
{
  "email": "new_member@example.com",
  "role": "parent|family_admin|guardian"
}
```

**Response:** `201 Created`
```json
{
  "invitation_id": "uuid",
  "email": "new_member@example.com",
  "role": "parent|family_admin|guardian",
  "status": "pending",
  "invite_code": "ABC-DEF-GHI",
  "expires_at": "2026-10-23T12:34:56Z"
}
```

**Error codes:** `AUTH_REQUIRED`, `FORBIDDEN`, `NOT_FOUND_OR_NOT_VISIBLE`, `VALIDATION_ERROR`
(invalid role or email), `RATE_LIMIT` (10 invitations per hour per user)

**Requirements:**
- Only parent/family_admin can invite; a `guardian` cannot
- Invitation expires in 7 days; a new invitation for the same email supersedes the old one
- The code is shown once and stored only as a keyed HMAC; it dies with its issuer's membership
- Cannot invite child users via API (separate pairing flow)

**Roles:** `guardian` (for example an elder sibling) may view the family, its devices and members'
locations (each location read is audited). A guardian cannot create pairing codes, revoke devices,
or invite anyone. A user belongs to exactly one family through invitations.

### `POST /api/v1/invitations/accept`

**Purpose:** Redeem an invite code and create the invitee's account (no authentication).

**Request:**
```json
{
  "invite_code": "ABC-DEF-GHI",
  "email": "new_member@example.com",
  "password": "at least 12 characters, at most 72 bytes",
  "full_name": "optional"
}
```

**Response:** `201 Created` - `{ "user_id", "family_id", "membership_id", "role" }`. The invitee then
logs in through `POST /api/v1/auth/session`.

**Error codes:** `AUTH_INVALID` (every refusal is identical: unknown, malformed, used, expired,
superseded, wrong email, email already registered, issuer no longer authorised),
`VALIDATION_ERROR`, `RATE_LIMIT` (5/minute per IP)

---

## Devices & Pairing

### `POST /api/v1/devices/pairing-code`

**Purpose:** Request a pairing code (parent initiates).

**Response:** `201 Created`
```json
{
  "pairing_code": "ABC-DEF-GHI",
  "expires_at": "2026-10-16T12:49:56Z",
  "expires_in_seconds": 900
}
```

**Requirements:**
- Code expires in 15 minutes
- 6 alphanumeric characters, user-friendly format
- One code per user per family at a time (invalidate previous)
- Parent must be authenticated
- Code returned only on creation (not retrievable later)

---

### `POST /api/v1/devices/pair`

**Purpose:** Enroll device using pairing code (Android device calls).

**Request:**
```json
{
  "pairing_code": "ABC-DEF-GHI",
  "device_name": "Child Phone",
  "device_model": "Pixel 7",
  "android_version": "14",
  "app_version": "1.0.0"
}
```

**Response:** `201 Created`
```json
{
  "device_id": "uuid",
  "device_credential": "signed_jwt_or_encrypted_secret",
  "api_endpoint": "https://piko.example.com/api/v1",
  "polling_interval_seconds": 60,
  "family_id": "uuid"
}
```

**Error codes:** `VALIDATION_ERROR`, `CONFLICT` (code already used), `AUTH_INVALID` (expired/invalid code), `RATE_LIMIT`

**Requirements:**
- Validate pairing code: exists, not expired, not used
- Code is single-use; reject after first successful pairing
- Rate limit: 3 attempts per code
- Generate device credential (JWT with RS256, includes device_id, family_id, can be rotated)
- Store device publicly visible metadata
- Mark pairing invitation as used
- Return credential securely (TLS only)

---

### `GET /api/v1/devices/{device_id}`

**Purpose:** Get device status (parent/device).

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "family_id": "uuid",
  "name": "Child Phone",
  "owner_member_id": "uuid",
  "device_model": "Pixel 7",
  "android_version": "14",
  "app_version": "1.0.0",
  "paired_at": "2026-10-01T00:00:00Z",
  "last_activity": "2026-10-16T12:30:00Z",
  "connectivity_status": "online|offline|unknown",
  "battery_percent": 45,
  "battery_updated_at": "2026-10-16T12:32:00Z",
  "battery_is_charging": true,
  "network_type": "wifi|cellular|ethernet|vpn|other|none",
  "network_updated_at": "2026-10-16T12:32:00Z",
  "status": "active|revoked"
}
```

**Error codes:** `AUTH_REQUIRED`, `FORBIDDEN`, `NOT_FOUND_OR_NOT_VISIBLE`

**Requirements:**
- Parents see all family devices
- Child app sees only own device
- Never enumerate unrelated families' devices

---

### `DELETE /api/v1/devices/{device_id}`

**Purpose:** Revoke device credential (parent only).

**Response:** `204 No Content`

**Error codes:** `AUTH_REQUIRED`, `FORBIDDEN`, `NOT_FOUND_OR_NOT_VISIBLE`

**Requirements:**
- Parent/family_admin only
- Mark device as revoked (do not delete; keep audit trail)
- Invalidate any refresh tokens for this device
- Notify device if online (next sync will fail, app should re-pair)

---

## Location & Status

### `GET /api/v1/members/{member_id}/location`

**Purpose:** Get current or latest known location of family member.

**Response:** `200 OK`
```json
{
  "member_id": "uuid",
  "device_id": "uuid",
  "coordinates": {
    "latitude": 40.7128,
    "longitude": -74.0060
  },
  "accuracy_meters": 15,
  "occurred_at": "2026-10-16T12:34:00Z",
  "received_at": "2026-10-16T12:34:05Z",
  "freshness": "fresh|stale|unknown",
  "freshness_seconds": 180,
  "device_status": "online|offline|unknown",
  "available": true
}
```

**Freshness rules:**
- `fresh`: within last 5 minutes of current time
- `stale`: older than 5 minutes, within last 24 hours
- `unknown`: no location data available or device never paired

**Error codes:** `AUTH_REQUIRED`, `FORBIDDEN`, `NOT_FOUND_OR_NOT_VISIBLE`

**Requirements:**
- Parents/family_admin can see children's location
- Children cannot request other members' locations
- Return `available: false` if no data; do not return null coordinates
- Include exact accuracy and timestamps for interpretation
- Coordinates only returned to authorized callers
- Rate limit: 30 requests per minute per user

---

### `GET /api/v1/members/{member_id}/history`

**Purpose:** Get location/status history with pagination.

**Query params:** `limit` (default 50, max 500), `offset` (default 0, max 100000), `start_time` and
`end_time` (ISO 8601 **with** a timezone offset), `event_type` (`location|battery|connectivity`)

**Response:** `200 OK` (as built; `device_status` is per member, `custom` events do not exist yet,
`freshness` is also `unknown` for events older than 24h)
```json
{
  "member_id": "uuid",
  "device_status": "online|offline|unknown",
  "history": [
    {
      "event_id": "uuid",
      "occurred_at": "2026-10-16T12:34:00Z",
      "received_at": "2026-10-16T12:34:05Z",
      "event_type": "location|battery|connectivity",
      "freshness": "fresh|stale|unknown",
      "data": {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "accuracy_meters": 15
      }
    }
  ],
  "total_count": 10000,
  "has_more": true
}
```

**Requirements:**
- Default time range: last 30 days
- Enforce retention policy: delete events older than configured period
- Return events in reverse chronological order (newest first)
- Rate limit: 10 requests per minute per user

---

## Telemetry Ingestion

### `POST /api/v1/telemetry/batches`

**Purpose:** Submit batch of telemetry events (Android device).

**Request:**
```json
{
  "batch_id": "uuid",
  "schema_version": 1,
  "device_id": "uuid",
  "events": [
    {
      "event_id": "uuid",
      "event_type": "location|battery|connectivity",
      "sequence_number": 123,
      "occurred_at": "2026-10-16T12:34:00Z",
      "data": {
        "latitude": 40.7128,
        "longitude": -74.0060,
        "accuracy_meters": 15,
        "battery_percent": 85
      }
    }
  ]
}
```

**Response:** `202 Accepted`
```json
{
  "batch_id": "uuid",
  "status": "accepted",
  "accepted_event_ids": ["uuid", "uuid", ...],
  "duplicate_event_ids": ["uuid"],
  "rejected_events": [
    {
      "event_id": "uuid",
      "error_code": "VALIDATION_ERROR|DUPLICATE",
      "reason": "..."
    }
  ]
}
```

**Error codes:** `AUTH_REQUIRED`, `VALIDATION_ERROR`, `RATE_LIMIT`, `CONFLICT` (batch_id used before)

**Requirements:**
- Device authenticated via JWT token (includes device_id, family_id)
- Batch ID is stable; identical batch sent twice returns same result (idempotent)
- Accept/reject events individually; partial success allowed
- Validate batch size: max 500 events per batch
- Validate event timestamp: occurred_at ≤ current server time, not > 24 hours in past
- Validate accuracy: 0–10000 meters or null
- Store events durably before responding (202 Accepted means persisted)
- Update device's latest state only if event is newer (by sequence or occurred_at)
- Rate limit: 10 batches per device per minute
- Response must list accepted and rejected separately; acknowledge only accepted
- Deduplicate by event_id: an event_id already stored (this or an earlier batch) is listed in
  `duplicate_event_ids`; an event_id repeated *inside one batch* is reported once, by its first copy
  (ADR-018 / audit M-4; each id appears in exactly one result list)
- Age limit is the family retention window, not 24 hours (ADR-011); future skew up to 60 s
- If batch_id was seen before, return same response (cached or re-derive)

---

## SOS & Messaging

> **As built in Phase 6 (ADR-022, decisions pending operator approval) — this note overrides the
> original text below where they differ:**
> - `POST /sos/incidents` is **device-only**. Body: `incident_id` (device-generated UUID),
>   `device_id` (must equal the authenticated device), `triggered_at` (UTC, not in the future),
>   optional `message` (<=280), optional `location {latitude, longitude, accuracy_meters}`.
>   `201` on first store, `200` with the stored incident on a replay, `409 CONFLICT` if the id
>   belongs to another device. Response: `incident_id, device_id, family_id, status, triggered_at,
>   received_at, message, location {…, captured_at, is_latest_known} | null, acknowledged_at,
>   resolved_at, parent_notes` (`parent_notes` is never sent to a device). `delivery_status` is not
>   used: `status=open` means durably stored by the server, nothing more.
> - `triggered_at` / `sent_at` are the phone's claim. A claim in the future is **capped at the server's
>   receipt time** (never refused); a claim in the past is stored as claimed. Both `triggered_at` and
>   `received_at` are returned. Free text (`message`, `notes`, message `body`) may not contain control
>   characters other than newline, carriage return and tab (400).
> - `GET /sos/incidents[?status&limit&offset]` and `GET /sos/incidents/{id}`: parent, family_admin
>   and guardian see the family's incidents; a device sees only its own. Reads are audited (a list read at
>   most once a minute per user; a detail read every time; detail reads are limited to 60/min/user).
> - `PUT /sos/incidents/{id}`: parent/family_admin only (guardian `403`). `open->acknowledged`,
>   `open|acknowledged->resolved`; repeating the current state is a `200` no-op; anything else is
>   `409`. Notes <=500.
> - Messages: `POST /messages {message_id, body(1..500), sent_at, device_id?}` (device: own
>   conversation, `device_id` optional; parent/family_admin: `device_id` required; guardian `403`),
>   `GET /messages[?device_id&sender=device|parent&limit&offset]`, `POST /messages/{id}/ack` (recipient side only).
>   States: `delivered` (stored by the server) and `acknowledged`.

### `POST /api/v1/sos/incidents`

**Purpose:** Create SOS incident (device or parent).

**Request:**
```json
{
  "device_id": "uuid",
  "message": "Help needed at home",
  "location": {
    "latitude": 40.7128,
    "longitude": -74.0060,
    "accuracy_meters": 25
  }
}
```

**Response:** `201 Created`
```json
{
  "incident_id": "uuid",
  "device_id": "uuid",
  "family_id": "uuid",
  "created_at": "2026-10-16T12:34:00Z",
  "status": "open|acknowledged|resolved",
  "message": "Help needed at home",
  "location": {...},
  "delivery_status": "pending|delivered|acknowledged"
}
```

**Error codes:** `AUTH_REQUIRED`, `FORBIDDEN`, `VALIDATION_ERROR`

**Requirements:**
- Device can create SOS only for itself
- Parents can create SOS for child's device
- Location is optional; if omitted, use latest known location
- Mark as `open` initially; only parent/family_admin can `acknowledge` or `resolve`
- SOS never auto-resolves; requires explicit parent action
- Notify all family parents immediately (push/email/SMS if configured)
- Log incident with actor, timestamp, and resolution

---

### `GET /api/v1/sos/incidents`

**Purpose:** List SOS incidents for family (paginated).

**Query params:** `status` (open|acknowledged|resolved), `limit`, `offset`

**Response:** `200 OK`
```json
{
  "incidents": [
    {
      "incident_id": "uuid",
      "device_id": "uuid",
      "created_at": "...",
      "status": "open",
      "message": "...",
      "acknowledged_at": null,
      "resolved_at": null,
      "parent_notes": "..."
    }
  ],
  "total_count": 5,
  "has_more": false
}
```

---

### `PUT /api/v1/sos/incidents/{incident_id}`

**Purpose:** Update SOS status (parent only).

**Request:**
```json
{
  "status": "acknowledged|resolved",
  "notes": "All safe, false alarm"
}
```

**Response:** `200 OK`
```json
{
  "incident_id": "uuid",
  "status": "resolved",
  "resolved_at": "2026-10-16T12:45:00Z",
  "parent_notes": "All safe, false alarm"
}
```

**Requirements:**
- Parent/family_admin only
- Status transitions: `open` → `acknowledged`, `open/acknowledged` → `resolved`
- Record timestamp and parent identity
- Cannot re-open resolved incidents

---

## Health & System

### `GET /api/v1/health/live`

**Purpose:** Liveness check (no auth required).

**Response:** `200 OK`
```json
{
  "status": "ok"
}
```

---

### `GET /api/v1/health/ready`

**Purpose:** Readiness check (database connectivity, etc.).

**Response:** `200 OK` or `503 Service Unavailable`
```json
{
  "status": "ready|degraded",
  "database": "ok|degraded",
  "checks": {"database": {...}}
}
```

---

## Error Response Format

All errors return JSON:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "request_id": "uuid",
    "timestamp": "2026-10-16T12:34:56Z"
  }
}
```

**Never include:**
- Stack traces
- SQL queries
- File paths
- Exact coordinates or location details
- API keys or secrets
- User passwords or tokens

**Error codes with status codes:**
- `AUTH_REQUIRED` → 401 Unauthorized
- `AUTH_INVALID` → 401 Unauthorized
- `FORBIDDEN` → 403 Forbidden
- `NOT_FOUND_OR_NOT_VISIBLE` → 404 Not Found
- `VALIDATION_ERROR` → 400 Bad Request
- `RATE_LIMIT` → 429 Too Many Requests
- `CONFLICT` → 409 Conflict
- `SERVICE_UNAVAILABLE` → 503 Service Unavailable
- `INTERNAL_ERROR` → 500 Internal Server Error

---

## Rate Limiting

**Strategy:** Token bucket per user/IP per endpoint

- 100 requests per minute (global fallback)
- Endpoint-specific overrides documented above
- Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Reject with 429 and `Retry-After: <seconds>` header

---

## CORS & Host Validation

- **Web origin:** HTTPS only, validate `Origin` header against allowlist
- **Device:** Accept requests from any origin (devices don't have origin concept)
- **Self-hosted:** Allow configurable origin list (default: localhost)

---

## Summary Table

| Endpoint | Auth | Method | Purpose |
|----------|------|--------|---------|
| `/api/v1/auth/session` | None | POST | Create session |
| `/api/v1/auth/session/refresh` | Token | POST | Refresh token |
| `/api/v1/auth/session/revoke` | Token | POST | Revoke session |
| `/api/v1/families` | Token | GET | List my families |
| `/api/v1/families/{id}` | Token | GET | Family summary |
| `/api/v1/families/{id}/members` | Token | POST | Invite member |
| `/api/v1/devices/pairing-code` | Token | POST | Request code |
| `/api/v1/devices/pair` | None | POST | Enroll device |
| `/api/v1/devices/{id}` | Token | GET | Device status |
| `/api/v1/devices/{id}` | Token | DELETE | Revoke device |
| `/api/v1/members/{id}/location` | Token | GET | Current location |
| `/api/v1/members/{id}/history` | Token | GET | Location history |
| `/api/v1/telemetry/batches` | Token | POST | Ingest events |
| `/api/v1/sos/incidents` | Token | POST/GET | Create/list SOS |
| `/api/v1/sos/incidents/{id}` | Token | PUT | Update SOS |
| `/api/v1/health/live` | None | GET | Liveness |
| `/api/v1/health/ready` | None | GET | Readiness |

---

## Open Questions for Phase 1 Review

1. Should device credential be a JWT or encrypted blob? (JWT assumed; rotate strategy TBD)
2. Should messaging be synchronous or queued? (Queued + polling assumed)
3. MCP caller identity model: OAuth or service account? (OAuth assumed for phase 2)
4. Self-hosting: TLS required or optional? (Required for remote, optional for localhost)

These are finalized once security review approves threat mitigations.


---

## Journeys (ADR-026, migration 0007)

All journey endpoints require a **device credential** (`pkd_...`). A user token is refused with `401 AUTH_INVALID`
(wrong credential type); a journey of another device or family is indistinguishable from a missing one
(`404 NOT_FOUND_OR_NOT_VISIBLE`). Parents get no access through family membership. Rate limit: 60 requests/minute per
device (30 for event batches). Requests forbid unknown fields; text is plain, at most 80 characters.

The plan's proposed per-leg endpoints (`POST /journeys`, `PATCH`, `/legs`, `/reorder`, `/start`, `/pause`,
`/complete`, `/refresh`) are **not** implemented (a read-only live lookup, below, replaces `/refresh`). The phone is the source of truth and sends the whole journey, so one
idempotent upsert replaces them and reordering cannot be half-applied. Tracking state is not synced; it is described by
events. The live lookup never writes to a journey.

### `PUT /api/v1/journeys/{journey_id}`
`journey_id` is a UUID chosen by the phone.
```json
{
  "title": "Vellore to Lucknow",
  "status": "DRAFT | PLANNED",
  "created_at": "2026-10-28T09:00:00Z",
  "updated_at": "2026-10-28T10:00:00Z",
  "legs": [
    {"id": "<uuid>", "mode": "FLIGHT|TRAIN|TAXI|BIKE_TAXI|METRO|BUS|WALKING|OTHER",
     "service_number": "6E 123 | null", "origin": "Bengaluru", "destination": "Lucknow",
     "departure_at": "2026-11-01T07:45:00+05:30 | null", "departure_zone": "Asia/Kolkata | null",
     "arrival_at": "... | null", "arrival_zone": "... | null"}
  ]
}
```
At most 20 legs; leg order is the sequence; a time needs its zone and an offset. Response `200`:
`{"journey": {...as stored, with sequence per leg...}, "applied": true|false}`.

- **Which write wins:** the one with the later `updated_at` (the owner's edit time, capped at the server clock so a fast
  clock cannot win every later edit). An equal or older `updated_at` is not an error: `applied=false` and the stored
  journey is returned unchanged. That makes retries after a lost response and out-of-order uploads safe.
- `409 CONFLICT`: the journey was deleted (it can never come back), a leg id belongs to another journey, the id is in use
  elsewhere, or the device has 200 journeys.

### `GET /api/v1/journeys` / `GET /api/v1/journeys/{id}`
Own journeys, newest edit first / one journey. A deleted journey is `404`.

### `GET /api/v1/journeys/live/flight?flight=AI101&day=2026-11-02` and `GET /api/v1/journeys/live/train?number=12919` (ADR-027)
Device credential only (a parent token is refused). A read-only lookup: nothing is stored and no journey is changed.
Rate limit: 10 requests/minute per device. `flight` is 2 letters/digits + 1-4 digits (+ optional letter), spaces and case
ignored; `number` is exactly 5 digits; anything else is `400 VALIDATION_ERROR`. Answers `200` even when no data is
available, so the phone can show the reason:
```json
{"state": "ok | disabled | not_configured | not_found | auth_failed | rate_limited | unavailable | unusable",
 "provider": "aviationstack | railradar | null", "checked_at": "2026-11-02T14:02:03+05:30",
 "status": "active | null", "departure_delay_minutes": 10, "arrival_delay_minutes": 25, "running_delay_minutes": null,
 "departure_gate": "A12", "departure_terminal": "3", "arrival_gate": null, "arrival_terminal": "2",
 "provider_updated_at": "2026-11-02T14:00:00+05:30 | null", "notices": ["DIVERTED"]}
```
Fields other than `state`, `provider` and `checked_at` are present only for `ok`, and a field the provider did not state
is `null`, never `0`. Flights report `departure_`/`arrival_delay_minutes`; trains report `running_delay_minutes`
(only when the provider calls the run live; otherwise `notices` contains `NOT_LIVE`). `disabled` = provider is `manual`;
`not_configured` = a provider is selected but its key is missing. No provider text, URL, key or body is ever returned.
Results are cached 5 minutes per (provider, number, date); after an auth or quota failure the provider is not called for
15 minutes, after a network error or 5xx for 60 seconds.

### `DELETE /api/v1/journeys/{journey_id}` -> `204`
Idempotent. Removes the title, legs and events and leaves a tombstone (id, owner, time). Deleting an id the server never
saw also leaves a tombstone, so an older upload still in flight cannot create it afterwards.

### `POST /api/v1/journeys/{journey_id}/events` -> `202`
Same response shape as `POST /telemetry/batches` (`accepted_event_ids`, `duplicate_event_ids`, `rejected_events`).
```json
{"batch_id": "<uuid>", "events": [
  {"event_id": "<uuid>", "event_type": "tracking_started", "occurred_at": "2026-11-01T06:00:00Z",
   "data": {"location_detection": true}}]}
```
1-100 events. Types: `tracking_started`, `tracking_paused`, `tracking_resumed`, `tracking_stopped`, `arrival_detected`
(noticed by location), `arrival_confirmed` (by the user), `observation`, `network_restored`, `journey_completed`.
`data` is flat (string, number, boolean or null), at most 12 keys and 1 KiB. A replayed `event_id` is a duplicate;
an id already used for another journey is rejected. `occurred_at` is capped at server time + 60 s. Events are
acknowledged only after the commit.

### `GET /api/v1/journeys/{journey_id}/events?limit=&offset=`
The owner's events in occurrence order (limit <= 200). Delivery time (`received_at`) is separate from `occurred_at`.
