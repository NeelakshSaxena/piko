# AGENTS.md — Piko Project Constitution

This file is authoritative for every coding agent, autonomous workflow, human contributor, and generated skill working in this repository.

## 1. Product purpose

Piko is a personal safety and family connectivity product. Parent-facing features include shared location, freshness/accuracy indicators, device telemetry, historical activity, SOS events, and safety messaging. The Android app must support REALTIME and POLLING modes when online and durable store-and-forward behaviour when offline. Piko is self-hostable. An optional MCP interface lets explicitly authorized AI clients query narrowly scoped information.

Safety, truthfulness, privacy, reliability, and understandable self-hosting outrank feature count.

## 2. Hard constraints

1. **Project-local only.** All project-specific dependencies, virtual environments, caches, toolchains, build artifacts, databases, test data, and generated files must remain under the project root. Python uses `.venv/`. Never install project dependencies globally. Never write caches or generated artifacts to another drive. See `docs/LOCAL_ONLY_POLICY.md`.
2. Do not execute install, download, migration, deletion, database-reset, deployment, or permission-changing commands without explaining the intended action and getting approval where required.
3. Never access, display, log, commit, or transmit real family location data, tokens, secrets, or credentials in tests or reports.
4. Never invent successful test results, benchmarks, test coverage, security properties, or completion status.
5. Never weaken or delete a test to make a build pass without an explicit, documented decision and replacement coverage.
6. No direct database access from MCP handlers. MCP calls application services that enforce the same authorization rules as the API.
7. No model-generated identity or authorization decisions. The server authorizes every request.
8. No unrestricted agent tool, shell tool, SQL tool, generic HTTP proxy, arbitrary URL fetch, arbitrary file read, remote command execution, or device-control tool exposed through MCP.
9. No remote SOS, sharing changes, family membership changes, or other high-impact mutations through AI in the initial release. Read-only MCP tools first. Any later mutation requires a separate threat review, explicit consent/confirmation, narrow schema, audit record, and tests.
10. No hidden tracking. Location sharing and permissions must be transparent to the child and compliant with platform and applicable legal requirements.
11. Do not claim continuous location or guaranteed battery use. Measure behaviour on physical devices under a documented test protocol.
12. Keep implementation minimal. No speculative abstractions, generic frameworks, microservices, duplicate models, unnecessary wrappers, dead code, or dependencies without a documented need.
13. Prefer boring, maintained, well-documented technology and small modules with clear ownership.
14. Do not put real secrets in `.env.example`, docs, prompts, screenshots, logs, fixtures, or source.
15. Never expose production services to `0.0.0.0` or the public internet by default. Local development binds to loopback unless the operator explicitly configures a protected deployment.
16. Never mark a phase complete unless its written exit criteria and required tests pass and evidence is recorded.
17. Preserve user changes. Inspect `git status` before edits. Never overwrite or delete unrelated work.
18. If requirements conflict, stop and ask rather than guessing.

## 3. Architecture rules

- Start with a modular monolith, not microservices.
- Keep domain logic separate from HTTP, database, Android UI, and MCP transport.
- Use explicit DTOs and versioned API contracts.
- Store telemetry as append-only events with stable event IDs/sequence numbers and occurrence timestamps.
- Keep latest device state separate from historical events.
- Make ingestion idempotent; old offline events must not overwrite newer current state.
- Acknowledge an event/batch only after durable acceptance.
- Store pending Android events durably before attempting delivery.
- Model delivery states explicitly: queued, submitted, delivered, acknowledged, resolved where relevant.
- Distinguish event occurrence time from server receipt time.
- Display location freshness and accuracy; never present stale data as live.
- Apply family/tenant authorization at every data-access boundary, including list, detail, history, exports, and MCP.
- Use migrations, not ad hoc schema mutation.
- Add indexes only for demonstrated query patterns.
- Use UTC internally; convert for display at the edge.
- Avoid storing location more often or for longer than required by the product's documented retention policy.

## 4. Android rules

- Kotlin; follow current Android platform constraints and foreground-service/permission rules.
- Separate UI from collectors, persistence, sync, and transport.
- Store event records durably before network send.
- Use bounded batching, compressed/compact payloads, exponential backoff with jitter, and idempotent retries.
- Do not wake GPS every minute merely because polling is one minute. Use appropriate platform location APIs and cached readings where valid; disclose freshness/accuracy.
- REALTIME mode means low-latency delivery when OS, network, permissions, and service state permit; do not promise impossible guarantees.
- POLLING targets a 60-second online upload/check interval when the platform permits it.
- Offline means store-and-forward, not dropping events. Prioritize SOS and safety events when reconnecting.
- Never falsely show SOS as delivered before confirmation.
- Avoid aggressive wakelocks, tight loops, frequent polling of device metrics, or unnecessary foreground work.
- Battery target (1–2% over 7–8 hours) is a target to measure, not a guaranteed claim. Establish a repeatable baseline and test on physical devices.
- If an OS restriction prevents a requirement, document the limitation and propose a compliant fallback; do not evade platform restrictions.

## 5. MCP and agentic workflow rules

- MCP is an optional adapter, not a second backend.
- Start with read-only tools: `get_my_family_summary`, `get_member_location`, `get_member_status`, `get_recent_safety_events`, and `get_sos_status`, subject to a finalized authorization model.
- Each tool returns only the minimum necessary fields and includes freshness/observed-at metadata.
- The authenticated principal and allowed family scope come from verified server-side credentials, never from model-supplied `user_id`, `family_id`, or claims.
- Validate token issuer, audience/resource, expiry, scopes, and revocation status according to the selected auth system. Use TLS for remote access.
- For local stdio MCP, the launching process is a security boundary; do not assume HTTP bearer-token middleware protects stdio.
- For remote MCP, use a reviewed OAuth-based authorization flow supported by the chosen MCP SDK and clients. Do not invent a bespoke OAuth protocol.
- Deny by default. Reject unknown tools, unknown fields, oversized input, invalid IDs, and unsupported filters.
- Rate-limit requests and enforce timeouts and output-size limits.
- Treat model prompts, tool descriptions, tool arguments, retrieved data, and device messages as untrusted.
- Prevent prompt injection from influencing authorization or causing a tool to reveal unrelated family data.
- Never let the model decide whether a caller is a parent/guardian.
- Audit security-relevant access without logging exact location or message bodies by default.
- MCP results must communicate uncertainty, timestamps, and offline/stale status.
- No AI-triggered SOS resolution, deletion, membership changes, or sharing changes in the initial release.

## 6. Self-hosting rules

- One documented setup path for Windows PowerShell and one for Linux/macOS shell where feasible.
- No mandatory SaaS dependency.
- Provide `.env.example`, health checks, database migrations, backup/restore instructions, update/rollback guidance, and an uninstall/data-retention explanation.
- Bind to localhost by default.
- Clearly explain TLS, reverse proxy, DNS, firewall, backups, secrets, and update responsibilities for public deployment.
- Docker is optional. Do not claim Docker artifacts are project-local unless the engine data root is explicitly configured accordingly.
- Keep app data in `.data/` for local development; never commit it.
- Provide a safe `doctor`/preflight command before setup.
- Setup must be repeatable and must not silently overwrite existing data.

## 7. Code quality and minimality

Before adding code:
1. Find the existing implementation and reuse it if correct.
2. Identify the smallest change that satisfies the requirement.
3. State why a new dependency or abstraction is necessary.
4. Add a regression test for the defect or behaviour.
5. Remove only dead code that the current task directly makes obsolete and that is proven unused.

Do not:
- implement future phases early;
- create speculative plugin systems;
- add abstractions with only one trivial implementation unless they establish a real security/platform boundary;
- duplicate validation in unrelated layers when a shared domain rule is appropriate;
- catch exceptions and silently continue;
- use broad `Any`/untyped payloads at trust boundaries;
- use `except: pass`;
- leave TODOs for required functionality while reporting completion;
- generate multiple competing implementations of the same feature.

## 8. Required workflow for every task

1. Read this file, `STATE.md`, and the relevant phase spec.
2. Inspect repository status and relevant files.
3. Restate the task and acceptance criteria briefly.
4. Identify risks, assumptions, and files expected to change.
5. Implement only the current phase/task.
6. Run focused tests, then relevant full checks.
7. Inspect the diff for accidental changes, secrets, dead code, and scope creep.
8. Record exact commands, exit codes, test counts, failures, and evidence paths in `docs/verification/`.
9. Update `STATE.md` only with evidence-backed facts.
10. Stop at the phase gate.

## 9. Stop conditions

Stop without continuing implementation if:
- an acceptance criterion is ambiguous in a safety/security-sensitive area;
- authorization cannot be proven;
- a test fails and the cause is not understood;
- the only proposed fix weakens security or deletes test coverage;
- a dependency/toolchain would install outside the project root;
- a command could destroy user data or change a remote system without approval;
- platform behaviour cannot be verified;
- a secret or real personal data is discovered;
- a requirement contradicts Android, MCP, or applicable platform constraints;
- the phase time/attempt budget is exhausted;
- the implementation would require broad refactoring outside the phase;
- the agent cannot truthfully establish completion.

When stopped, report: blocker, evidence, affected requirement, safe next action, and what must not be attempted.

## 10. Phase completion contract

A phase is complete only when:
- all phase-specific acceptance criteria pass;
- required tests pass;
- relevant security/privacy checks pass;
- local-only paths are verified;
- documentation is updated;
- no unresolved critical/high finding remains without explicit acceptance;
- an evidence report is saved;
- an independent audit prompt has been run for security-critical phases.

A green build alone is never sufficient.

## 11. Response format for agents

At the end of each task, report:
- **Changed:** files and behaviour
- **Tests:** exact commands and results
- **Evidence:** report paths
- **Risks/limitations:** known gaps
- **Scope:** confirm no unrelated work
- **Gate:** PASS / FAIL / BLOCKED
- **Next phase:** do not start it automatically

Do not claim completion without evidence.
