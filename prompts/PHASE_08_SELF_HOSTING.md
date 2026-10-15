# Phase 8 — Self-Hosting and Operations

## Goal
Deliver a predictable setup, upgrade, backup, restore, and recovery path that respects the project-local rule for development.

## Scope
- Preflight/doctor command.
- `.env.example` and safe config validation.
- Database initialization/migrations.
- Local startup instructions.
- Production self-hosting guide.
- Health/readiness checks.
- Backup/restore commands and restore test.
- Upgrade/rollback documentation.
- Secure first-admin creation; no default password.
- Optional container deployment only with clear Docker data-root warning.

## Verification
- Clean local setup from a fresh checkout.
- Setup is repeatable and does not overwrite existing `.data`.
- All project-managed paths are inside root.
- No mandatory SaaS.
- Backup restore validated.
- Remote mode refuses unsafe defaults and requires explicit TLS/auth config.
- MCP remains off unless deliberately enabled.
