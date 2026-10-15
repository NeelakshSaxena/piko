# Phase 4 — Android Durable Node and Modes

## Goal
Implement the smallest reliable Android node for telemetry, local durable queue, REALTIME/POLLING modes, offline store-and-forward, and connection state.

## Required behaviour
- Kotlin and approved Android architecture.
- Explicit, transparent permissions and sharing state.
- Durable local event storage before transmission.
- POLLING targets a 60-second online sync/check cadence when platform constraints permit.
- REALTIME uses a suitable persistent connection only while useful and allowed.
- Offline queue survives process restart and network flapping.
- Bounded batch upload, backoff with jitter, idempotent retry.
- Delete/mark local records only after backend acknowledgement.
- Do not overwrite event occurrence timestamps during recovery.
- Do not wake GPS every minute solely to satisfy polling.
- Respect Android foreground-service, background location, notification, and battery restrictions.
- Show accurate pending/failed/delivered state.

## Verification
- Unit tests for queue ordering, duplicate prevention, retry, ack handling, and state machine.
- Instrumented tests for network transitions and process recreation where feasible.
- Manual/automated permission denial and battery saver tests.
- Network loss mid-batch, reconnect, partial ack, and duplicate retry scenarios.
- Measure network payload size.
- Battery protocol documented; do not claim 1–2% until physical-device evidence exists.
- Run local-path check for Gradle and SDK configuration.

## Exit gate
No dropped acknowledged/unacknowledged event bugs, no false delivered state, no unbounded retry, and test evidence for offline recovery.
