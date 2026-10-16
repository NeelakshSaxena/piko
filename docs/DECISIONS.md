# Architecture Decision Log

## ADR-001: Modular monolith first
Status: Approved (human operator confirmed the Phase 1 contracts, 2026-10-16)
Decision: Start with one backend deployment and clear modules.
Reason: Simplest self-hosting and testing; extract services only when evidence justifies it.

## ADR-002: MCP is an adapter, not a separate authority
Status: Approved (human operator confirmed the Phase 1 contracts, 2026-10-16)
Decision: MCP tools call the same application services and authorization policy as the API.
Reason: Prevents policy drift and direct database exposure.

## ADR-003: MCP read-only for initial release
Status: Approved (human operator confirmed the Phase 1 contracts, 2026-10-16)
Decision: Only narrow read tools are in the first MCP release.
Reason: Family location and safety events are sensitive; mutation adds consent, replay, and misuse risks.

## ADR-004: Durable store-and-forward telemetry
Status: Approved (human operator confirmed the Phase 1 contracts, 2026-10-16)
Decision: Android persists events before sending; server accepts idempotently and acknowledges durable storage.
Reason: Network availability must not define whether history exists.

## ADR-005: Project-local tooling
Status: Required
Decision: Project-specific tools, dependencies, caches, databases, and build outputs live inside repository root.
Reason: Explicit user requirement.

## ADR-006: No microservices at the start
Status: Approved (human operator confirmed the Phase 1 contracts, 2026-10-16)
Decision: Keep domain modules inside the backend until real scaling/operational evidence demands extraction.
Reason: Avoid unnecessary complexity and deployment burden.

---

# Phase 2/3 decisions (2026-10-16)

Each entry states its approval status. **Proposed** entries are implemented and tested but need
explicit human confirmation before the phase gate is treated as fully accepted.

## ADR-007: Device credentials are opaque random tokens, stored hashed
Status: Approved (the human operator delegated this choice in the Phase 1 gate answer, 2026-10-16)
Decision: A device credential is `pkd_` + 256 bits from `secrets.token_urlsafe`, returned once at
pairing. Only its SHA-256 is stored (`device_credentials.credential_hash`, unique). Every request
looks the hash up and joins device and family status, so revocation is immediate. Rotation is manual
(re-pair) in this release.
Reason: Contracts left "JWT or encrypted blob" open. A JWT would need a second secret and a renewal
channel on the device every 24h, and still cannot be revoked without a database lookup. Hashing a
256-bit random token is safe without a slow hash; a database leak does not yield usable tokens.
Supersedes: `credential_material` (encrypted key) in docs/DATA_MODEL.md.

## ADR-008: Pairing code format, lookup key and attempt limits
Status: Approved (human operator, 2026-10-16: keep the 9-symbol code)
Contract conflict: docs/API_CONTRACTS.md says "6 alphanumeric characters" but its own example is
`ABC-DEF-GHI` (9). Implemented: 9 symbols from a 32-symbol alphabet without `I O 0 1`, shown as
`XXX-XXX-XXX` (45 bits). Input is case- and separator-insensitive. One constant
(`PAIRING_CODE_LENGTH`) controls this; moving to 6 is a one-line change plus tests, but 6 symbols
(30 bits) is weaker, so the longer form was chosen as the safer reading of both texts.
Lookup: bcrypt cannot be searched, so codes are stored as HMAC-SHA256 under a server key
(`PIKO_HMAC_KEY_FILE`, at least 32 random bytes, domain label `pairing-code`). A database leak does
not allow offline guessing without the key. Rotating the key invalidates outstanding codes (15
minutes of validity) and login-lockout counters; nothing else depends on it.
Attempt limits: "3 attempts per code" cannot be enforced for codes that do not exist, so
`pairing_invitations.attempt_count` is **not implemented**. Compensating controls: 5 attempts per
minute per IP on `/devices/pair`, 15-minute expiry, single use, one live code per parent per family,
and audited failures. At the limit, an attacker guessing a live code succeeds with probability under
2.1e-10 per IP per day (about 7,200 tries over a 2^45 space).
Responses: unknown, malformed, superseded and expired codes return the same `AUTH_INVALID` body.
A used code returns `CONFLICT` (required by the contract's test matrix), which reveals only that
the code was once valid.

## ADR-009: Batch idempotency by re-derivation; no batch table
Status: Approved by contract text ("cached or re-derive"); implementation choice recorded here
Decision: Idempotency is enforced per event by the primary key `(device_id, event_id)` with
`INSERT .. ON CONFLICT DO NOTHING`. A re-sent batch is re-derived: events stored under the same
`batch_id` are re-acknowledged as accepted (identical to the original answer), events stored under a
different batch are `duplicate_event_ids`, and validation failures are rejected again. No batch
table was added. `CONFLICT (batch_id used before)` is never produced: a reused `batch_id` with the
same events is a normal retry.
Response `status` is `accepted`, or `partial` when any event was rejected (the contract shows only
`accepted`; the per-event lists are the authoritative outcome).
Acknowledgement is built only after `COMMIT` returns; a failed commit returns 503 with no ids.

## ADR-010: Event identity is scoped to the device
Status: Approved (security-motivated deviation from docs/DATA_MODEL.md)
Decision: the `telemetry_events` primary key is `(device_id, id)`, not a global `id`. A global key
lets one device probe or block another family's event ids ("duplicate" would leak existence). The
`latest_event_id` foreign key in `device_latest_state` was dropped for the same reason, and because
retention deletion would otherwise need `SET NULL` on a composite key.

## ADR-011: Ordering rule, clock skew, and accepted age
Status: Approved (human operator, 2026-10-16: retention window, not the literal 24h)
Ordering: derived latest state has three independent groups (location, battery, connectivity). A
group advances only for an accepted event whose `occurred_at` is **strictly newer** than the stored
group timestamp, applied as one conditional `UPDATE` so concurrent batches cannot regress it. Equal
timestamps keep the first writer. `sequence_number` is stored with history but not used for
ordering: mixing clock and sequence comparisons is not transitive, and devices may lack sequences.
Future skew: `occurred_at <= now + 60s` (the contract says `<= now`). A phone with a slightly fast
clock would otherwise have every event rejected permanently, which a device treats as final.
Accepted age: **the contract says reject events older than 24 hours; the implemented limit is the
family's `retention_days` (default 30).** AGENTS.md section 4 ("offline means store-and-forward, not
dropping events") takes precedence, and an event older than retention would be deleted anyway.
Freshness still follows the 24h rule: a location older than 24h is reported `unknown` and its
coordinates are withheld. For the literal 24h limit, change one line in `TelemetryService.ingest`.

## ADR-012: Authentication details
Status: Approved by the Phase 1 contracts; specifics recorded here
- Access token: RS256 JWT, 1h, audience `piko-api`. Refresh token: RS256 JWT, 7d, audience
  `piko-refresh`. `typ` is checked so neither works as the other. The signing key is a PEM file
  (`PIKO_JWT_PRIVATE_KEY_FILE`).
- The refresh token's SHA-256 and session id are stored (`refresh_sessions`). The contract's refresh
  response returns only an access token, so refresh tokens are not rotated.
- Every authenticated request re-checks the session (not revoked, not expired) and user status in the
  database, and every family-scoped request re-reads membership and role from the database. The
  token's `fam` claim is advisory only (it selects which family a pairing code is for).
- Passwords: bcrypt, at least 12 rounds outside tests, 72-byte limit enforced (never truncated).
- Login lockout: 10 failures in 15 minutes per email (HMAC of the normalised email, so unknown
  emails lock identically and account existence is not revealed), counted from `audit_events` so it
  survives restarts and works across instances. Trade-off: an attacker can lock a known parent out
  for 15 minutes. Plus 5 logins/minute per IP (in-process).
- Rate limits are in-process (single instance). A multi-instance deployment needs a shared store.
- Forwarded headers are not trusted for the client IP; a reverse-proxy mode is a Phase 8 decision.
- The `operator` role in the session contract has no data-model basis and is not implemented.
- Pairing creates a placeholder child identity (`device-<uuid>@piko.invalid`, unusable password
  hash `!`) so `devices.owner_member_id` and `family_memberships.user_id` constraints hold. Children
  never authenticate with a password.
- The contracts define no public signup endpoint. The first parent and family are created by the
  operator command `python -m app.cli create-family`.

## ADR-013: Data model deviations (migrations 0001 and 0002)
Status: Approved (mechanical; recorded for traceability)
`TIMESTAMPTZ` instead of `TIMESTAMP` (AGENTS.md: UTC internally); `VARCHAR` + `CHECK` instead of
PostgreSQL enums; `audit_events.metadata` is named `meta` (reserved name in SQLAlchemy);
`credential_hash` replaces `credential_material` (ADR-007); `device_latest_state` stores
`battery_is_charging`, `connectivity_network_type` and `connectivity_updated_at` and derives
online/offline from last contact instead of storing `connectivity_status`; no `attempt_count`
(ADR-008); no `messages` or `sos_incidents` tables (later phases); `retention_days` constrained to
1-365. Indexes are limited to demonstrated query patterns.

## ADR-014: Supabase PostgreSQL for development, plain PostgreSQL in code
Status: Approved (human operator, 2026-10-16)
Decision: the development database is the operator's Supabase project, reached through the session
pooler with TLS. Piko uses no Supabase client, key, RLS or Auth, and runs on any PostgreSQL.
Everything lives in a dedicated schema (`PIKO_DB_SCHEMA`, default `piko`); Supabase-managed schema
names are refused by configuration. Tests create and drop only `piko_test_<random>` schemas, and a
test asserts that the `anon` and `authenticated` API roles cannot use the schema.

## ADR-015: Code layout
Status: Approved (follows docs/ARCHITECTURE.md with one deliberate omission)
`backend/app/{api,core,db,domain,services}`. The suggested `repositories/` layer was **not**
created: with one implementation it is the speculative abstraction AGENTS.md section 7 forbids.
Pure rules (freshness, event validation) live in `domain/` with no framework or database imports.

## Open decisions requiring the human operator
1. ADR-008 and 2. ADR-011: RESOLVED 2026-10-16 (9-symbol code; retention window).
3. RESOLVED 2026-10-16: invite endpoint implemented with an invite code (ADR-017).
4. RESOLVED 2026-10-16: no multi-family for now; invitations always create a new single-family
   account (ADR-017). Users created by `create-family` could still be added to other families only
   by direct database edits; no API does it.
5. RESOLVED 2026-10-16: audit M-3, refresh tokens rotate with reuse detection (ADR-019).

## ADR-016: Dependencies added in Phase 2 and the lock file
Status: Approved (project-local, installed into `.venv` on the operator's instruction)
Each addition has a documented need (AGENTS.md section 7):
- `PyJWT[crypto]`: RS256 access/refresh tokens required by the Phase 1 contract. Pulls `cryptography`.
- `bcrypt`: password hashing required by the contract (bcrypt, >= 12 rounds). Used directly; no wrapper library.
- `email-validator`: normalising and validating email addresses (also what Pydantic's `EmailStr` uses).
- Removed `aiosqlite` from the `test` extra: tests run on PostgreSQL only, because SQLite success does
  not prove PostgreSQL behaviour (Phase 2 verification requirement).
- `requires-python` relaxed from `>=3.12` to `>=3.11` on the operator's instruction (the project
  virtual environment is Python 3.11.0).
`requirements.lock` pins the exact versions that were tested (`pip freeze`, no hashes; hash-pinned
locking needs a tool that is not installed and is deferred to the release phase).
Known advisories in the lock (dev/build tooling only, none in runtime dependencies; `pip-audit`
2026-10-16): `pytest 8.4.2` (PYSEC-2026-1845, fixed in 9.0.3, but the project pins `pytest<9`) and
the virtual environment's bootstrap `setuptools 65.5.0` (four advisories, fixed in 83.0.0). Neither
is shipped or imported by the application. Remediation needs a version bump that the operator has
not yet approved.

## ADR-017: Member invitations by single-use code, and the `guardian` role
Status: Approved (human operator, 2026-10-16: invite code; new limited role; no multi-family)
Decision: `POST /families/{id}/members` returns a one-time invite code (same 9-symbol alphabet as
pairing codes, stored as HMAC-SHA256 under the server key with label `member-invite`, 7-day expiry,
one live invitation per family+email). The inviter shares it out of band. The invitee redeems it at
`POST /invitations/accept` with the invited email and a new password (12+ chars), which creates a
**new** account and an active membership. Migration `0003` adds `member_invitations`, the `guardian`
role and the `member_joined` audit action.
Reasons: no mail transport exists and self-hosting must not require one; reusing the pairing-code
design keeps the code small and already-reviewed. Because the account is always new, an invitation
can never graft an existing account (and its other family) onto this family, which is how
"no multi-family" is enforced. The endpoint answers every refusal identically (code, email,
account existence are not oracles); an existing email is refused at acceptance, not at invitation,
so inviters cannot probe which emails have accounts.
Contract deviations: the response carries `invitation_id` and `invite_code` instead of
`membership_id` (the membership does not exist until acceptance, avoiding placeholder users); no
email is sent.
Guardian: `VIEW_ROLES = parent, family_admin, guardian` may log in, list/view the family, view
devices and read member locations (audited). `ADMIN_ROLES` alone may create pairing codes, revoke
devices and invite. The guardian's SOS rights are a Phase 6 decision.
Residual risks: the code is as strong as the channel used to share it; email ownership is not
verified, only that the redeemer holds both the code and the invited address. Brute force: 45-bit
code, 5 attempts/minute/IP in-process (same caveat as ADR-008), plus the email must match.

## ADR-018: Fixes from the independent audit of Phases 2-3 (2026-10-16)
Status: Implemented; tests listed in `docs/verification/phase-02-03-fixes.md`
- H-1: `OverflowError` from out-of-range timestamps or huge integers is now a per-event rejection.
- M-1: a pairing code is refused (and revoked) if its issuer is no longer an active parent/admin
  of an active family (`issuer_is_authorised`, shared with invitations).
- M-2: the launcher runs uvicorn with `proxy_headers=False` so `X-Forwarded-For` cannot choose the
  client IP used by rate limits.
- M-4: an event id repeated inside one batch is reported once (the first copy decides); the earlier
  `DUPLICATE` rejection could make an accepted id also appear as rejected.
Not changed: M-3 (refresh rotation, awaiting a decision) and the Low items L-1..L-6.

## ADR-019: Refresh-token rotation with reuse detection (audit M-3)
Status: Approved (human operator, 2026-10-16)
Decision: `POST /auth/session/refresh` returns a new refresh token and stores its SHA-256 in the session; the previous token is void. A validly signed refresh token for a live session whose hash is not the stored one has already been replaced, so presenting it revokes the whole session and writes a failed `session_revoked` audit row (reason `refresh_token_reuse`). Expiry slides: each rotation sets the session and token to a fresh 7 days, so an idle session still dies after 7 days.
Trade-offs: a client that loses a refresh response is logged out on its next attempt (it must log in again); only one concurrent refresher per session is supported. The per-user rate limit runs before rotation so a 429 can never discard a new token. Supersedes the "refresh tokens are not rotated" statement in ADR-012 and risk R-01.

## ADR-020: Parent dashboard is a Vite + React single-page app
Status: Approved (human operator, 2026-10-16: Vite SPA; configurable OpenStreetMap default tiles)
Decision: `web/` is a static TypeScript SPA (React 19, react-router, Leaflet). Dependencies are
exact-pinned in `package-lock.json` (110 packages, `npm audit` clean on 2026-10-16); TypeScript is
5.9.3 on purpose (7.x is a rewrite). Any static file host works; unknown paths must fall back to
`index.html`. Departs from the Next.js sketch in docs/ARCHITECTURE.md: no server-side code means
the UI can never be mistaken for an authority, and self-hosting needs no Node process.
Session handling: the API is bearer-token only. The access token and the (rotating, ADR-019) refresh
token live in `sessionStorage` (per tab: two tabs sharing one refresh token would revoke each other).
The access token is stored so a page *reload does not refresh*: a first version refreshed on every
load, and a reload that interrupted a refresh replayed a rotated token and ended the session (found
live in a browser, 2026-10-16). Refreshes are now about hourly and are single-flight. Residual risk:
a reload exactly during that hourly refresh still ends the session. `sessionStorage` is readable by
any script running on the page, so the build ships a strict CSP (script-src 'self') and no
third-party scripts.
Honesty rules implemented and tested: freshness is recomputed from the capture time on every render
(never "live"; older than 5 minutes is "Not current"; older than 24 hours shows no position);
unavailable values read "Unknown", never 0; route lines break at gaps over 15 minutes and the gap is
drawn dashed and labelled; permissions are server decisions (the UI hides controls as a convenience
only, and shows the server's refusal when it happens).
Map tiles: the default is OpenStreetMap, disclosed on every map, replaceable with `VITE_TILE_URL`, or
off with `VITE_TILE_URL=off` (marker and coordinates only). Each tile request tells the tile server
roughly where the family is; OSM's public servers also require a Referer origin (the page sends
origin-only, never paths or queries) and are not meant for heavy production use: operators should
configure their own tile source. Not verified: behaviour under the production CSP in a browser with
tiles (the build injects it; only the dev server was exercised live).
Backend addition for this phase: `GET /members/{id}/history` (contract section updated), with the
same authorization as the location endpoint, a 10/minute rate limit, and audit rows without data.
Design deviation: muted text is #5f5d70 instead of the design's #777588, which fails WCAG AA
contrast. The Plus Jakarta Sans font is not bundled (system font used) until a font file is approved.

## ADR-021: Android node (Phase 4)
Status: Approved by the operator for the parts asked (minSdk 31/targetSdk 36; dependency downloads
into .gradle-home); the rest is implementation detail recorded here.
- Kotlin, Jetpack Compose UI, minSdk 31, compile/target 36. Newest AndroidX (Compose 1.12.1,
  core 1.19.1, lifecycle 2.11) require compileSdk 37, and only platform 36 is installed, so the
  previous stable lines are pinned (Compose BOM 2026.06.01, core-ktx 1.18.0, lifecycle 2.10.0).
- No Room/KSP, OkHttp, Play Services or analytics: the durable queue is the framework SQLite
  (`synchronous=FULL`, one transaction per mutation), HTTP is `HttpURLConnection`, location is the
  platform fused provider. Runtime dependencies: AndroidX core/activity/lifecycle/Compose and
  kotlinx-coroutines. Test-only: JUnit, AndroidX Test, org.json.
- Delivery rules (all unit-tested on the JVM against a fake and on SQLite on a device through one
  shared contract): events are on disk before any send; the same in-doubt batch (same batch id and
  events) is re-sent after a lost response; an event is deleted only when the server lists it as
  accepted or duplicate; unmentioned events stay queued (partial ack); occurrence time is the capture
  time and is never rewritten; bounded batches (100) and bounded work per run (20 batches);
  exponential backoff with jitter capped at 15 min; Retry-After honoured; a poison event is isolated
  by halving the batch and is only given up on while the server is acknowledging other events (an
  outage never costs data); 401 stops sending and keeps the queue; a full queue drops the oldest
  normal-priority events and counts them, visibly. Re-pairing discards the old queue so history is
  never uploaded to a different family.
- Modes: POLLING checks the queue every 60 s, asks for balanced-power location with a 20 m movement
  gate (the GPS is not woken every minute), and sends a connectivity heartbeat after 4 minutes of
  silence so the server does not call a stationary phone offline (the server's window is 5 minutes).
  REALTIME asks for high-accuracy location every 10 s and uploads within about 2 s of each event.
  REALTIME is *prompt HTTPS uploads*, not a persistent socket: the backend has no push channel yet.
- Foreground service (type location) is started only from the visible activity, shows a persistent
  notification with a Stop action, is not restarted by the system (START_NOT_STICKY), and the UI
  reports "interrupted" if it dies. No background-location permission is requested.
- Findings from running it (2026-10-16, emulator): POLLING's balanced-power request makes Android use
  network location and leave the GPS off, and the emulator has no network-location source, so POLLING
  location could not be exercised there (REALTIME was). It needs a physical phone. A first set of
  instrumented tests shared the app's real preferences and wiped the emulator's pairing; the vault
  now takes a file name and the tests use their own.
- Not verified: any physical device; battery (protocol only: docs/BATTERY_TEST_PROTOCOL.md); Doze and
  battery-saver behaviour; reboot (the service cannot start from a boot receiver on Android 14+, so
  the user must open the app); the Gradle wrapper download (it hung at 0 bytes, so builds used the
  checksum-verified project-local Gradle 9.8.1); a release build and signing.
- UI follows screens/drishti_child_safety_home and drishti_choose_your_role in the Tactile Clay
  palette, limited to features that exist. The design's SOS button, check-ins and chat are NOT built
  (Phase 6) and the transparency screen says so; the design's "PIN and QR handshake" claim is not
  made because no such mechanism exists. The brand name in the screens is "Drishti"; the app and this
  repository use "Piko" and the supplied Piko icon.

## ADR-020 addendum: dashboard follows the four parent-web designs (2026-10-16)
Status: Approved (human operator: complete the web development from `screens/`).
The sidebar/top-bar shell, Command Centre, Live Map, Device Health and SOS pages follow the designs. Every figure is real API data. Elements with no backing data are omitted, and the SOS Centre, Messages and Alerts are pages that say "Not available in this version" (badge "Soon"), because SOS and messaging are Phase 6 and a simulated incident would be a false safety claim. The top-bar chip says "Synced" (dashboard refresh), never a location age. `GET /devices/{id}` gained `battery_is_charging`, `network_type` and `network_updated_at`. Detail and gaps: `docs/verification/phase-05-web.md`. The font is not bundled until a dependency is approved.
