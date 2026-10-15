# Phase 7 — Read-Only MCP Integration

## Goal
Add an optional MCP server that exposes only approved read-only Piko capabilities to authorized AI clients.

## Initial candidate tools
- `get_my_family_summary`
- `get_member_location`
- `get_member_status`
- `get_recent_safety_events`
- `get_sos_status`

Finalize names and schemas in Phase 1. Do not expose arbitrary SQL, shell, filesystem, generic HTTP, URL fetching, or unrestricted tool execution.

## Security requirements
- Disabled by default.
- Each tool calls existing application services.
- Server-derived caller identity and family scope; never trust model-supplied identity.
- Authenticate every remote HTTP request; validate issuer, audience/resource, expiry, scope, and revocation as designed.
- TLS for remote transport.
- Apply rate limits, timeouts, bounded arguments and results.
- Treat messages/events/prompts as untrusted data.
- Output only the minimum fields required.
- Include observed timestamp, freshness, source status, and uncertainty.
- Separate local stdio security from remote HTTP security; stdio relies on the launching process boundary.
- Read-only initial release. No AI-driven mutation.
- Audit access without logging exact location by default.

## Required security tests
- Missing/invalid/expired/wrong-audience credentials denied at transport boundary.
- Parent cannot query another family's member.
- Supplied `family_id`/`user_id` cannot override identity.
- Prompt-injection strings in messages or event fields do not alter authorization or expand data access.
- Tool allowlist and schemas enforced.
- Oversized arguments/results rejected or bounded.
- MCP disabled means no listener/route is exposed.
- Test actual transport, not only direct function calls.

## Exit gate
Any unresolved critical/high MCP authorization issue blocks completion. Run `prompts/INDEPENDENT_AUDIT.md`.
