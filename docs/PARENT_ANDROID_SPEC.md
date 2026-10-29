# Android parent mode - specification (DRAFT for review, nothing built)

Status: draft written 2026-10-30 from the owner's requests. No code exists. Per CLAUDE.md this is its own phase: it needs the
owner's review, a phase prompt in `prompts/`, and an ADR before implementation. Decisions already made by the owner are marked **[decided]**.

## 1. Goal
First launch asks "Are you a parent or a child?" and continues accordingly. A parent can do on Android everything the web
dashboard offers, so a parent does not need a browser. A child device keeps today's behaviour (pairing, location/status
sharing, SOS, messages, Journeys).

## 2. Decisions so far
- **[decided] Scope: everything at once** - all web screens (below), not a core-first slice.
- **[decided] Map: OpenStreetMap through osmdroid**, no API key. The web map uses Leaflet 1.9.4, so both clients use OSM-style
  tiles. Tile requests go to the OSM tile servers (respect their usage policy; cache tiles; set a proper User-Agent). Add the
  one dependency in an ADR with its licence (osmdroid is Apache-2.0; OSM data is ODbL, attribution is shown on the map).
- **[decided] Roles are switchable in Settings** (not one role per install). Rules in section 5.
- **[decided] Order:** migration `0007` and the matching backend are deployed first (see `STATE.md`; pending the owner).

## 3. Screens and the API each one uses (web page -> Android screen)
Endpoints are taken from `backend/app/api/routes.py`; all rows use a parent (user) token and exist today, except where marked **NEW**.
| Web page | Android screen | Endpoints |
|---|---|---|
| Login / session | Parent sign-in, sign-out | `POST /auth/session`, `/auth/session/refresh`, `/auth/session/revoke` |
| Join (invitation) | Accept invitation | `POST /invitations/accept` |
| Signup | "Request access" opens the email composer, as the web does (no signup API exists) | none |
| Overview | Family summary: members, last seen, battery, open SOS | `GET /families`, `GET /families/{id}`, `GET /members/{id}/location` |
| Map | osmdroid map, one marker per member, freshness label | `GET /members/{id}/location` |
| Activity | History list/timeline | `GET /members/{id}/history` |
| Health | Device health (battery, network, permissions, freshness) | `GET /devices/{id}` |
| Family | Members, invite a member, pair a child's device (pairing code), remove a device | `POST /families/{id}/members`, `POST /devices/pairing-code`, `DELETE /devices/{id}` |
| SOS | Incident list, detail, acknowledge/resolve | `GET /sos/incidents`, `GET/PUT /sos/incidents/{id}` |
| Messages | Conversation list, send, delivery state | `POST /messages`, `GET /messages`, `POST /messages/{id}/ack` |
| Alerts | Alert feed (derived the same way as the web) | same data as SOS/Health/Messages (confirm in the phase prompt) |
| Settings | Account, notification settings, role switch | `GET /push/config`, `PUT/DELETE /push/device-token`, session endpoints |
| Push (parent phone) | Receive SOS/message pushes (FCM), not Web Push | **NEW:** a parent-scoped FCM token registration. Verified in `routes.py`: `PUT/DELETE /push/device-token` require a *device* credential and `PUT /push/web-subscription` is for browsers, so a parent phone has no way to register today. Needs a server endpoint, a table/ownership rule for user push tokens, outbox routing to them, and tests. |

## 4. Shared journeys for parents (NEW, requires its own ADR and migration)
Today journeys are private to the owning device: the server rejects every other reader, family members included
(ADR-026). A parent seeing a child's journey is a **new sharing feature**, not a change to backup. Proposed rules:
1. **Off by default, per journey, chosen by the child (or the phone's owner).** A "Share with my family" switch on each journey
   (not one global switch), showing exactly who will see it (the parents of the family the device belongs to).
2. **Backup must be on** for a journey to be shared (the server needs the copy); turning backup off stops sharing.
3. **Server rule:** a parent may read a journey only if (a) they are an active guardian of the device's family and (b) the
   journey has an explicit, unrevoked share row. Everything else stays "not found", as today. New table
   `journey_shares(journey_id, family_id, created_at, revoked_at)` and a read-only endpoint
   `GET /families/{family_id}/shared-journeys` (+ `/{journey_id}`); never a write path for parents.
4. **What a parent sees:** title, legs, scheduled times, the child's own expected times, and arrival status. Not raw GPS trails,
   not the free-text of anything the child did not choose to share. The tracking events stay private unless a later ADR says otherwise.
5. **Revocation is immediate and deleting the journey (or the share) removes parent access at once**; the audit log records
   share/revoke (who, when), never the content.
6. **Transparency:** the child's phone shows who can see a shared journey; the parent's list marks "shared by <child>".
7. Open question for the owner: should a *child under a given age* be unable to turn sharing off (parent-enforced)? Default
   proposal: the child decides, because forced sharing needs a stronger consent model than this project has (PRODUCT_SPEC).

## 5. Roles and switching **[decided: switchable in Settings]**
- The role is stored with the install (`parent` or `child`), set at first launch.
- A phone holds **either** a device credential (child) **or** parent tokens, never both. Switching:
  - child -> parent: stop location sharing and Journeys tracking, ask for confirmation, tell the user that this phone stops
    appearing as a child device (the server-side device is **not** deleted; a parent can remove it), clear the device credential,
    then show parent sign-in.
  - parent -> child: sign out (revoke the session), clear parent tokens and cached family data, then show the pairing screen.
  - Local Journeys stay on the phone in both directions (they belong to the phone, not to the role).
- A child's phone cannot become a dashboard without a parent's email and password, so choosing "parent" never reveals family data by itself.
- First-launch choice screen has plain wording and a back path; nothing is requested (location, notifications) until a role is chosen.

## 6. Security and privacy requirements
- Parent tokens (access/refresh) are stored only in Android Keystore-backed storage, never logged, never in backups
  (`allowBackup=false` stays), never in screenshots of the recents screen (FLAG_SECURE on the map and message screens).
- Refresh-token rotation and revoked-session handling match the server; a 401 after refresh signs the parent out cleanly.
- Release builds refuse cleartext HTTP; debug-only exception for the emulator stays.
- Map tiles are the only third-party request; no analytics, no ad or crash SDK. Member coordinates are never sent to the tile server (only tile x/y/zoom).
- Every dashboard action that changes data (SOS update, send message, invite, remove device) shows the server result, not an
  optimistic success, and works offline only as "queued, not sent" where the web does.
- Rate limits are the server's; the client backs off on 429.
- TalkBack labels, 48 dp targets and large-text layouts are acceptance criteria for every new screen, not a later polish pass.

## 7. Explicit non-goals (this phase)
Account signup by API, billing, multiple families per parent (follow the web's behaviour), iOS, tablets/landscape polish,
exposing child tracking events or GPS trails of journeys, and any change to the child device's data collection.

## 8. Delivery outline (the owner chose everything at once; this is how to stay verifiable)
Build vertically but gate in this order so each step is testable on the emulator against a local backend:
1. Role choice, role storage, switching rules, parent auth + secure storage, parent shell/navigation.
2. Overview, Map (osmdroid), Activity, Health (read-only).
3. Family management, SOS, Messages, Alerts, Settings and parent push.
4. Shared journeys (section 4): ADR, migration `0008`, server endpoints and tests first, then both apps.
5. Hardening: TalkBack/large text pass, independent audit, signed tester build.
Each step ends with tests (JVM + emulator + backend), a verification note under `docs/verification/`, and no claim of a
passed phase gate without evidence.

## 9. Open questions for the owner
1. Parent push on Android: confirm the parent phone should receive SOS/message pushes through FCM. This is new server work
   (see section 3); without it a parent only sees SOS/messages when the app is open or refreshed.
2. Shared journeys: child-decides (proposed) or parent-enforced?
3. Should a single install be allowed to stay signed in as parent on several family accounts? (Proposed: no, one at a time.)
4. Hosted-vs-self-hosted: the "Request access" screen on Android needs the contact address from `config.contactEmail`; confirm where the Android build gets it (build property).
