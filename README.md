# Piko — Engineering Starter Pack

Piko is a family-safety platform: Android safety node + parent web dashboard + self-hostable backend + optional, tightly scoped MCP interface for AI clients.

This starter pack is an **architecture and agent-engineering specification**, not a claim that the application is already implemented. It deliberately starts with documents, contracts, tests, and small vertical slices before adding features.

## Non-negotiable project-local rule

All project-specific source, dependencies, virtual environments, package caches, build output, local databases, generated artifacts, and toolchains must live under this repository. Do not install project dependencies globally or write project caches to another drive.

Expected local paths:
- Python virtual environment: `.venv/`
- Python package cache: `.cache/pip/`
- Node runtime (if downloaded locally): `.tools/node/`
- Android SDK (if needed locally): `.tools/android-sdk/`
- Gradle user home: `.gradle-home/`
- Gradle build output: project build directories
- npm cache: `.cache/npm/`
- test data and local database: `.data/`
- temporary files: `.tmp/`
- generated reports: `artifacts/`

Do not assume Docker is project-local: Docker image layers usually live in the Docker engine's own storage. Docker is optional and is prohibited for the strict local-only workflow unless the operator has explicitly configured the engine's data root to a location on the approved project drive. A self-hosting guide must disclose this clearly.

Do not download or install tools automatically without explicit operator approval. Scripts must print planned paths before changing anything.

## Start here

1. Read `AGENTS.md` completely.
2. Read `CLAUDE.md` if using Claude Code.
3. Read `docs/PRODUCT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_MODEL.md`, and `docs/LOCAL_ONLY_POLICY.md`.
4. Run Phase 0 only. Do not begin implementation phases until Phase 0 passes its gate.
5. Use the phase prompts in `prompts/` one at a time.
6. Record evidence in `docs/verification/` and update `STATE.md` only when a phase's exit criteria are proven.

## Current status

- Product and architecture specifications: starter draft
- Implementation: not yet started
- Security review: required before any remote MCP exposure
- Real-device battery validation: required before making battery claims
- Production deployment: not approved until security, backup/restore, and recovery tests pass

## Core design

Use a modular monolith first:
- Backend/API: Python + FastAPI
- Primary production database: PostgreSQL
- Local development/test mode: SQLite only where it does not mask PostgreSQL-specific behaviour; integration tests must also run against PostgreSQL
- Android: Kotlin, Android platform APIs, local durable event storage
- Parent web: Next.js/TypeScript
- MCP: Python MCP server adapter calling the same authenticated application services as the REST API
- Deployment: self-hostable, documented, no mandatory vendor cloud

MCP must not have direct database access and must not receive broad credentials. It calls narrow application services and inherits server-side identity and family-level authorization.

See `docs/ARCHITECTURE.md` for boundaries and `docs/SECURITY_MODEL.md` for the mandatory threat model.
