# Architecture Decision Log

## ADR-001: Modular monolith first
Status: Proposed
Decision: Start with one backend deployment and clear modules.
Reason: Simplest self-hosting and testing; extract services only when evidence justifies it.

## ADR-002: MCP is an adapter, not a separate authority
Status: Proposed
Decision: MCP tools call the same application services and authorization policy as the API.
Reason: Prevents policy drift and direct database exposure.

## ADR-003: MCP read-only for initial release
Status: Proposed
Decision: Only narrow read tools are in the first MCP release.
Reason: Family location and safety events are sensitive; mutation adds consent, replay, and misuse risks.

## ADR-004: Durable store-and-forward telemetry
Status: Proposed
Decision: Android persists events before sending; server accepts idempotently and acknowledges durable storage.
Reason: Network availability must not define whether history exists.

## ADR-005: Project-local tooling
Status: Required
Decision: Project-specific tools, dependencies, caches, databases, and build outputs live inside repository root.
Reason: Explicit user requirement.

## ADR-006: No microservices at the start
Status: Proposed
Decision: Keep domain modules inside the backend until real scaling/operational evidence demands extraction.
Reason: Avoid unnecessary complexity and deployment burden.
