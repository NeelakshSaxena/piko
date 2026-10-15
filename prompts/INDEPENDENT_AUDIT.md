# Independent Audit Prompt — Piko

Act as a skeptical independent reviewer. Do not implement fixes before documenting findings. Read AGENTS.md, the relevant phase spec, security model, tests, and verification evidence.

Review actual code, actual configuration, actual test commands, and diffs. Do not trust the implementer's summary.

## Audit checklist
- Does implementation match approved contracts?
- Are authentication and family-level authorization enforced server-side on every path?
- Can IDs, tool arguments, prompt injection, stale data, or retries cross a trust boundary?
- Are event ordering and durable acknowledgement correct?
- Are SOS/message states truthful?
- Are errors handled without leaking secrets?
- Are dependencies and caches project-local?
- Are new abstractions/dependencies necessary?
- Is there dead code, duplicated logic, unrelated refactoring, or scope creep?
- Do tests cover negative cases, not just happy paths?
- Are any test claims unsupported by logs/results?
- Are location and message content excluded from routine logs?
- Does self-hosting fail safely when required configuration is missing?
- Does MCP have only the intended tool allowlist and no direct database access?
- Are remote MCP auth, token audience, TLS, and origin/host checks actually enforced?
- Are stdio and HTTP trust boundaries documented separately?

## Output
Create a findings report with severity (Critical/High/Medium/Low), file/line evidence, reproduction, impact, and required fix. If no finding is observed, state the scope and tests actually performed; do not claim a universal proof of security.

Do not mark a phase complete yourself unless you ran the required checks and the human release policy permits it.
