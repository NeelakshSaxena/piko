# Phase 10 — Release Candidate and Independent Audit

## Goal
Produce a release candidate only after the full implementation is independently checked against specifications and evidence.

## Required deliverables
- Release checklist.
- Version and migration notes.
- Self-hosting instructions tested from a clean environment.
- Security review and unresolved-risk register.
- Test report with exact commands/results.
- Backup/restore evidence.
- Android physical-device battery and offline test report.
- MCP tool inventory and permissions review.
- Known limitations.
- Rollback plan.

## Independent audit
Use `prompts/INDEPENDENT_AUDIT.md` with an agent that did not implement the relevant change if possible. The auditor must inspect code and run tests, not merely read the implementer's summary.

## Stop conditions
No release if critical/high findings remain without written risk acceptance; a required test is unrun and represented as passed; self-hosting setup is destructive/ambiguous; a secret is exposed; cross-family access is possible; stale location is presented as live; or MCP can bypass authorization.

## Exit gate
Human release approval required. Do not deploy automatically.
