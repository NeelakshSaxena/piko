# Product Specification

## 1. Product definition

Piko is a personal safety and family connectivity platform. It consists of:
- Android child/family safety client.
- Parent web dashboard.
- Self-hostable backend and storage.
- Optional MCP adapter for explicitly authorized AI clients.

The product must be transparent about location sharing, permission limits, data freshness, offline state, and message/SOS delivery state. It must not promise absolute safety, guaranteed location frequency, or guaranteed battery consumption.

## 2. Core requirements

### Android
- Two online modes: REALTIME and POLLING.
- POLLING targets a 60-second upload/check interval when Android execution, permissions, network, and power state permit.
- REALTIME uses an appropriate low-latency bidirectional channel when available.
- Persist telemetry and important events locally before network delivery.
- When offline, continue permitted collection and queue events durably.
- After reconnection, upload historical events in bounded batches.
- Use stable event IDs and/or per-device sequence numbers; retries must be idempotent.
- Backend acknowledgements occur only after durable acceptance.
- Old events must not overwrite latest device state.
- SOS and critical events receive priority in delivery.
- Incoming SOS/messages are shown through supported Android notifications when delivery is possible.
- Keep permissions and sharing transparent.

### Parent web
- Family overview and member states.
- Map with last known location, accuracy, and freshness.
- Device telemetry and connectivity.
- SOS inbox and incident lifecycle.
- Family messages and check-ins.
- Activity timeline and historical route with visible data gaps.
- Device pairing/invitation management.
- Privacy, retention, and account settings.
- Offline, empty, error, loading, and permission states.

### Backend
- Authenticated API.
- Family membership and role authorization.
- Telemetry ingestion, event history, latest state.
- Idempotent batch ingestion.
- SOS/message state tracking.
- Audit events for security-relevant operations.
- Data retention and deletion behaviour.
- Health checks, migrations, backups, restore and upgrade instructions.

### MCP
- Optional feature; disabled by default.
- Initially read-only.
- Narrow tools for current user's authorized family only.
- No direct database tool and no arbitrary SQL/HTTP/shell tool.
- Every call passes through application services and server-side authorization.
- Include timestamps, freshness, and uncertainty in responses.
- AI is not an authority and cannot change permissions.

## 3. Non-functional requirements

- Privacy by default and data minimization.
- Secure transport for remote deployments.
- Local development binds to loopback.
- Maintainable modular monolith.
- Testable service boundaries.
- Clear, repeatable self-hosting.
- Project-local development dependencies and caches.
- Observability without logging exact locations or message bodies by default.
- Bounded retries, timeouts, payload sizes, and queues.
- Explicitly documented limitations for Android background behaviour.

## 4. Out of scope for initial release

- AI-triggered SOS creation/resolution.
- AI-triggered family membership or privacy changes.
- Remote shell or arbitrary device commands.
- Microservices.
- Complex plugin marketplace.
- Predictive safety scoring.
- Claims of guaranteed protection or guaranteed battery drain.
- Covert location collection.

## 5. Acceptance principles

A requirement is not complete merely because a screen exists. Each capability needs a test proving state transitions and authorization. See phase specs and `docs/verification/`.
