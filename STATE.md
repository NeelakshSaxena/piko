# Piko Project State

Status: **Phase 0 — not yet verified**
Current phase owner: human operator + coding agent
Implementation status: not started by this starter pack
Last verified commit: none
Open blockers: choose/confirm supported OS/toolchain versions; review architecture and threat model; approve Phase 0.

## Phase ledger

| Phase | Name | Status | Evidence |
|---|---|---|---|
| 0 | Inventory and project-local environment | NOT STARTED | `docs/verification/` |
| 1 | Contracts and threat model | BLOCKED on Phase 0 | `docs/verification/` |
| 2 | Backend foundation and auth | BLOCKED | `docs/verification/` |
| 3 | Telemetry ingestion and offline reconciliation | BLOCKED | `docs/verification/` |
| 4 | Android durable node and modes | BLOCKED | `docs/verification/` |
| 5 | Parent web dashboard | BLOCKED | `docs/verification/` |
| 6 | SOS and messaging | BLOCKED | `docs/verification/` |
| 7 | Read-only MCP integration | BLOCKED | `docs/verification/` |
| 8 | Self-hosting and operations | BLOCKED | `docs/verification/` |
| 9 | Security, privacy, reliability, battery validation | BLOCKED | `docs/verification/` |
| 10 | Release candidate and independent audit | BLOCKED | `docs/verification/` |

## Rules

- Change a status only when the relevant phase gate has evidence.
- Do not mark a phase PASS based only on code review or a successful build.
- Never auto-advance.
- Record blockers and failed tests without hiding them.
