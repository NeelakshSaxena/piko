# Phase 2 — Backend Foundation and Authentication

Read all governing docs and approved Phase 1 contracts.

## Goal
Implement the smallest working FastAPI modular monolith, database configuration, migrations, health checks, and authentication/authorization foundations.

## Scope
- Minimal app entry point and configuration.
- Database session and migration setup.
- Health live/ready endpoints.
- User/family membership primitives only as approved by contracts.
- Central authorization helpers/services.
- Structured safe errors and request correlation IDs.
- Unit and integration tests.
- Project-local dependency lock and environment.

## Non-goals
No telemetry pipeline, UI, MCP, background jobs, microservices, or speculative plugin architecture.

## Verification
- Fresh local setup works with paths inside root.
- Migrations apply on a clean database and upgrade a previous schema.
- Unauthenticated requests are denied.
- Cross-family access tests fail closed.
- Secrets are not logged.
- Lint, type checks, unit and integration tests pass.
- PostgreSQL integration test passes; SQLite-only success is insufficient for production data logic.

## Exit gate
PASS only with exact test evidence and reviewed auth model. Stop on any authorization ambiguity.
