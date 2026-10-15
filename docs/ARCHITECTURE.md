# Architecture

## 1. Initial shape

Use a modular monolith with explicit internal modules. Split services only after measured scaling, operational, or isolation requirements justify the cost.

```text
Android app
  ├── location/telemetry collectors
  ├── durable local event store
  ├── sync scheduler + batch uploader
  ├── realtime transport (optional)
  ├── SOS/message inbox + notifications
  └── UI

Parent web (Next.js)
  └── authenticated API client

Backend (FastAPI)
  ├── identity + sessions
  ├── families + memberships
  ├── devices + pairing
  ├── telemetry ingestion + reconciliation
  ├── location/history queries
  ├── SOS + messaging
  ├── audit + retention
  └── health + operations

MCP adapter (optional)
  └── authenticated application-service calls only

Persistence
  ├── PostgreSQL (production/self-host)
  ├── SQLite (local quick start/test only, where appropriate)
  └── Android local database (durable queue)
```

## 2. Suggested repository structure

```text
piko/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── STATE.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── screens/                         # existing user-owned screen assets; preserve
├── docs/
│   ├── PRODUCT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── SECURITY_MODEL.md
│   ├── LOCAL_ONLY_POLICY.md
│   ├── API_CONTRACTS.md
│   ├── DATA_MODEL.md
│   ├── SELF_HOSTING.md
│   ├── TEST_STRATEGY.md
│   ├── DECISIONS.md
│   └── verification/
├── prompts/
│   ├── PHASE_00_INVENTORY.md
│   ├── PHASE_01_CONTRACTS_SECURITY.md
│   ├── PHASE_02_BACKEND_FOUNDATION.md
│   ├── PHASE_03_TELEMETRY_SYNC.md
│   ├── PHASE_04_ANDROID_NODE.md
│   ├── PHASE_05_PARENT_WEB.md
│   ├── PHASE_06_SOS_MESSAGING.md
│   ├── PHASE_07_MCP_READ_ONLY.md
│   ├── PHASE_08_SELF_HOSTING.md
│   ├── PHASE_09_HARDENING.md
│   ├── PHASE_10_RELEASE_AUDIT.md
│   ├── RESUME.md
│   └── INDEPENDENT_AUDIT.md
├── skills/
│   ├── phase-runner/SKILL.md
│   ├── security-review/SKILL.md
│   ├── mcp-security/SKILL.md
│   ├── android-battery/SKILL.md
│   └── self-hosting/SKILL.md
├── .claude/
│   └── skills/                      # optional Claude Code local skill copies
├── scripts/
│   ├── bootstrap.ps1
│   ├── bootstrap.sh
│   ├── doctor.py
│   └── verify_local_paths.py
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── domain/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── db/
│   │   └── main.py
│   ├── migrations/
│   └── tests/
├── mcp_server/
│   ├── server.py
│   └── tests/
├── web/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   └── tests/
├── android/
│   ├── app/
│   └── gradle/
├── tests/
│   ├── contracts/
│   ├── security/
│   ├── integration/
│   └── fixtures/
├── .venv/                            # generated locally; never commit
├── .tools/                           # project-local toolchains, if approved
├── .cache/                           # project-local caches
├── .gradle-home/                     # project-local Gradle user home
├── .data/                            # local DB and test data; never commit
├── .tmp/
└── artifacts/                        # reports and build evidence
```

Only create implementation directories when their phase begins. Do not populate empty folders with placeholder source code just to make the tree look complete.

## 3. Module boundaries

- `domain`: domain entities and invariants, no web framework or database details.
- `services`: use cases and authorization-aware operations.
- `repositories`: persistence interfaces/adapters.
- `api`: request/response DTOs and HTTP mapping.
- `mcp_server`: translates MCP tool calls into the same application services.
- `web`: presentation and typed API client; no authorization decisions trusted solely to UI.
- `android`: collectors, durable queue, sync, notifications, UI.

## 4. Telemetry ingestion contract

Every event should include a stable event ID, device identity derived from authenticated enrollment, monotonic sequence or another duplicate-detection key, schema version, occurrence timestamp, event type, and minimal payload.

The server adds received timestamp and ingestion result. The server must:
1. authenticate the device;
2. verify it is still enrolled/authorized;
3. validate payload size/schema/ranges;
4. deduplicate;
5. durably store accepted events;
6. update current state only if the event is newer under the defined ordering rule;
7. acknowledge accepted IDs/batches;
8. expose gaps and freshness honestly.

Do not use client-supplied family IDs as authority. Device-to-family association comes from server-side enrollment.

## 5. Deployment boundary

Local development should run with loopback listeners and project-local paths. Remote self-hosting requires an explicit deployment configuration for TLS/reverse proxy, domain, secrets, backups, updates, and firewall rules. Do not expose debug mode or development credentials publicly.
