# Piko read-only MCP adapter

Optional. Lets an AI client you run on **this machine** ask five narrow, read-only questions about **your own family**. It cannot change anything, has no network listener, and is off until you turn it on. Design and limits: ADR-024.

## Turn it on
1. Set `PIKO_MCP_ENABLED=true` in `.env` (default `false`).
2. Issue a credential for an adult account (parent, family admin or guardian; not a child):
   `python -m app.cli mcp-token --email you@example.com --ttl-hours 168`
   It prints a session id and the token **once**. Keep the token like a password.
3. Configure your MCP client to launch `python -m app.cli mcp` (working directory `backend`, using the project `.venv`) with the token in **that launch's** environment as `PIKO_MCP_TOKEN`. Do not put the token in `.env`.

## Turn it off / revoke
- Stop launching it, or set `PIKO_MCP_ENABLED=false`.
- Revoke one credential immediately: `python -m app.cli mcp-revoke --session-id <id>` (the next call fails).

## Tools
| Tool | Returns |
|---|---|
| `get_my_family_summary` | family name, your role, members (id, name, role) and linked phones |
| `get_member_location` | latest position (4-decimal rounded), accuracy, observed time, age, freshness |
| `get_member_status` | online/offline (inferred), last contact, battery, network, each with observed time |
| `get_recent_safety_events` | up to 20 battery/connectivity/location-report events from the last 24 h, no positions |
| `get_sos_status` | SOS incidents and status; no message text or position; cannot acknowledge or resolve |

Freshness: fresh = captured within 5 minutes; stale = up to 24 hours; unknown = older or none. A stale position is where the phone was, not where it is. "No SOS" is not proof anyone is safe.

## Security properties you can rely on (each has a test)
Identity comes only from the credential; `family_id`/`user_id` arguments are rejected. Another family's member id looks identical to a nonexistent one. Unknown tools, extra fields and oversized input are refused. Rate limit, timeout and result-size caps apply. Calls are audited without positions or text.

## Where the data goes
The adapter runs on your machine, but **whatever a tool returns is sent to the AI service your client uses** (for example a model provider). That includes family member names, positions to about 11 m with their age, battery and phone status, and SOS history. Use only a client and provider you trust with that information, and revoke the credential when you stop using it.

## What it does not do
No remote/HTTP transport (needs a separately reviewed OAuth design). No mutation of any kind. Treat the client and the model as untrusted for authorization: they only ever see what these five tools return, and names in results are data, never instructions. A process that can read the launcher's environment can use the token.
