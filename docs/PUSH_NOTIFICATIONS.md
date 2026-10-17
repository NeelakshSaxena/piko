# Push notifications

Status: implemented and tested against fakes and a simulated FCM leg. **Not verified against live FCM or a live browser push service** (no Firebase project exists; see "Not verified").

## Who receives what

| Event | Recipient | Channel |
|---|---|---|
| SOS raised | every parent/guardian browser subscription in the family | W3C Web Push (VAPID) |
| SOS acknowledged / resolved | the child's phone | FCM data message |
| Message from parent | the child's phone | FCM data message |
| Message from child | parents' browsers | Web Push |

Payloads carry only `{v, type, id}`. No message text, no location, no names. The receiving app fetches authoritative state itself, so a push can be duplicated, delayed or dropped without producing wrong content. Lock-screen text is generic ("Piko: new activity").

## Delivery semantics (honest)

- **Accepted** means the push service (FCM / browser vendor) took the message. It does **not** mean delivered, displayed or seen.
- No "delivered" or "read" claim is made anywhere in the API or UI.
- Android also polls (JobScheduler persisted job) so a lost push degrades to delay, not loss. SOS is device-originated (ADR-022 A).
- Invalid/unregistered tokens are marked and the target is removed; revoked devices/members are re-checked at send time and the row is `skipped`.

## Outbox

`notification_outbox` rows are written in the same transaction as the event. Worker (`NotificationService.drain`): `FOR UPDATE SKIP LOCKED`, one transaction per row, exponential backoff with jitter (base 10 s, cap 1 h), max 8 attempts, then `dead`. Dedupe key `kind:variant:subject:target` with `ON CONFLICT DO NOTHING`. Statuses: `pending, accepted, dead, skipped, expired`. A missing transport leaves the row pending without consuming an attempt. TTLs apply (`expired`).

Drain triggers (no persistent worker is required):
1. best-effort after the request that created the event;
2. `POST /api/v1/internal/outbox/run` with header `X-Piko-Outbox-Token` (for GitHub Actions cron or Supabase pg_cron + pg_net);
3. `python -m app.cli outbox` for self-hosting.

Health: `GET /api/v1/internal/outbox/health` (token-guarded) returns a delivery-health summary (counts by status/age only; no content).

## Secrets

Server credentials are files referenced by `*_FILE` settings (or `*_B64` env secrets on a serverless host, materialized by `app/deploy_env.py`). Never in the APK, web bundle or Git. The APK holds only the public Firebase client identifiers, read from gitignored `android/local.properties`. The web bundle holds only the public VAPID key (served by `/push/config`).

## Firebase manual steps (human, console)

1. Create a Firebase project (Spark/free). Do not enable billing.
2. Add an Android app with package `app.piko.android`. Copy project id, app id, API key, sender id.
3. Put them in `android/local.properties`: `piko.firebase.projectId`, `piko.firebase.appId`, `piko.firebase.apiKey`, `piko.firebase.senderId` (file is gitignored; never commit).
4. Project settings → Service accounts → generate a key for the Cloud Messaging (HTTP v1) sender. Store it as a host secret (base64 into `PIKO_FCM_SERVICE_ACCOUNT_B64`) and set `PIKO_FCM_PROJECT_ID`. Delete the downloaded file afterwards.
5. `python -m app.cli generate-push-secrets` for VAPID keys; set `PIKO_VAPID_SUBJECT` (a mailto: you control).

## Not verified

- A real FCM message to a real/emulated device (blocked: no credentials).
- Real browser push (the Chrome permission prompt needs a human click; subscription registration and the service worker are covered by tests, not by a live push).
- Physical-device behaviour (Doze, OEM battery killers): see the physical-device checklist.
