# Test Strategy

## Pyramid

1. Unit tests: domain rules, event ordering, authorization policy.
2. Contract tests: API schemas, error shapes, MCP tool schemas.
3. Integration tests: database constraints, batch ingestion, migrations, authentication.
4. Security tests: cross-family access, token checks, pairing, MCP scope, injection-like inputs.
5. End-to-end tests: parent journey, child pairing, offline recovery, SOS lifecycle.
6. Android tests: local queue durability, reconnect, permission states, notification states.
7. Physical-device tests: battery, background restrictions, GPS behaviour, network transitions.
8. Operations tests: clean install, upgrade, backup/restore, rollback, local-path verification.

## Minimum test scenarios

### Telemetry
- Same event submitted twice produces one stored event.
- Out-of-order events do not replace newer latest state.
- Batch acknowledgement occurs only after durable acceptance.
- Reconnection uploads queued history and retains original timestamps.
- Oversized or invalid events are rejected safely.
- One device cannot submit as another device.

### Authorization
- Unauthenticated requests denied.
- Parent A cannot read Parent B's family, members, locations, messages, or events.
- Guessed IDs do not leak existence.
- Revoked/expired/wrong-audience tokens denied.
- Membership removal takes effect promptly.

### MCP
- MCP disabled by default.
- Unauthorized MCP request denied before tool execution.
- Model-supplied user/family identity cannot change scope.
- Tool allowlist enforced.
- Oversized arguments and output bounded.
- Prompt injection in a message/event cannot trigger unauthorized access.
- Responses include freshness and uncertainty.
- No arbitrary SQL, shell, URL fetch, or generic proxy tools exist.
- Stdio and remote HTTP deployment boundaries tested separately.

### SOS and messages
- Offline SOS persists locally.
- Queued SOS is not labelled delivered.
- Delivery and acknowledgement are distinct.
- Duplicate delivery does not duplicate incidents/messages.
- Resolved state requires authorized explicit action.

### Android battery/reliability
- Record device model, Android version, battery start/end, test duration, network conditions, location settings, screen state, and mode.
- Compare baseline idle phone, Piko installed but idle, POLLING, REALTIME, and offline recovery.
- Repeat tests; report median and spread.
- Do not assert the 1–2% / 7–8 hour target until measured on representative physical devices.
- Test network flapping, process restart, reboot if supported, denied permissions, battery saver, and low-storage behaviour.

### Self-hosting
- Fresh checkout setup.
- Setup with existing `.data` does not overwrite it.
- No path escapes repository root for project-managed artifacts.
- Database migration from previous supported version.
- Backup restore verified.
- No default credentials.
