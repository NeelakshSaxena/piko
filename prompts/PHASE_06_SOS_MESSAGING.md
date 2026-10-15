# Phase 6 — SOS and Messaging

## Goal
Implement reliable, explicit SOS and family message lifecycle.

## Required state distinctions
SOS: created locally, queued, submitted, delivered/received as defined, acknowledged, resolved.
Message: queued, submitted, delivered, acknowledged where supported, failed.

Do not collapse states into one “sent” label.

## Required behaviour
- Offline SOS/message persistence on Android.
- Priority delivery after reconnect.
- Idempotent server processing.
- Parent alert/inbox and child notification handling.
- Authorized acknowledgement and explicit resolution.
- No claim of emergency-service dispatch unless a real integration exists.
- Audit security-sensitive transitions without logging message bodies by default.

## Verification
- Offline SOS is retained.
- Reconnect sends exactly one incident.
- Queued is not shown as delivered.
- Unauthorized users cannot read or resolve incidents.
- Acknowledgement does not auto-resolve.
- Notification permission denied is handled honestly.
- Duplicate/replayed requests do not duplicate events.
