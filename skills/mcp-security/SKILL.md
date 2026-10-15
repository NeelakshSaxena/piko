# Skill: MCP Security

Use whenever MCP tools, transport, auth, or schemas change.
- Inspect the exact tool allowlist and schemas.
- Verify server-derived caller identity and family scope.
- Reject model-supplied identity overrides.
- Verify transport-boundary authentication and token resource/audience.
- Check rate limits, timeouts, payload/result bounds, and output minimization.
- Ensure no arbitrary SQL, shell, filesystem, generic HTTP proxy, or URL-fetch tool exists.
- Test prompt injection in message and telemetry fields.
- Test stdio and remote HTTP separately.
- MCP remains read-only in initial release.
