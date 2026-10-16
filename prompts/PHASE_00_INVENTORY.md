# Phase 0 — Inventory and Project-Local Environment

You are the implementation agent. Read AGENTS.md, CLAUDE.md, STATE.md, PRODUCT_SPEC, ARCHITECTURE, SECURITY_MODEL, and LOCAL_ONLY_POLICY before acting.

## Goal
Inspect the existing repository and the user-owned `screens/` folder without changing or deleting existing assets. Establish the actual environment and a safe, project-local setup plan.

## Scope
- Inspect current files and git status.
- Determine OS, available language runtimes, and existing project files without scanning unrelated user folders.
- Verify project root and free space.
- Check whether `screens/` contains design assets and catalogue them without modifying them.
- Propose the minimal directory tree needed for the next phase.
- Create `docs/verification/phase-00-inventory.md` with observed facts, commands, exit codes, and path decisions.
- Implement `scripts/verify_local_paths.py` and a safe `scripts/doctor.py` only if the scope is clear; these must not install packages or modify system settings.

## Do not
- Do not install dependencies or download toolchains.
- Do not generate app/backend implementation.
- Do not move or rename screens.
- Do not create empty source modules for future phases.
- Do not run Docker.
- Do not edit global environment variables or shell profiles.

## Verification
- Confirm all planned project-managed paths resolve beneath repository root.
- Confirm `.env`, `.data`, `.venv`, caches, toolchains, and artifacts are ignored where appropriate.
- Confirm no user-owned file was modified or deleted.
- Confirm scripts are dry-run/read-only unless an explicit safe action is requested.
- Run available static checks without installing anything.

## Exit gate
PASS only when the inventory report exists, path policy is verified, user changes are preserved, and no unresolved out-of-root toolchain requirement is hidden. If a required tool is missing, report it; do not install it.

## Stop conditions
Stop if root path is unclear, free space is insufficient, a required tool would install outside the root, `screens/` includes sensitive real family data, or the repository contains unexpected work that could be overwritten.

## History
create and always maintain a file `logs.md' in root where you store in a very short version what phase is runnning, what's being worked on, what's queued and any errors faced.