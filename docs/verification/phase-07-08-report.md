# Phase 7 (read-only MCP) and Phase 8 (self-hosting) verification, 2026-10-27

**Gates: NOT PASSED.** Built and tested; held open by the items in "Needs you / not done". Nothing was committed, pushed or deployed. Migration 0006 is NOT applied to the persistent `piko` schema.

## Phase 6 re-verification (tree at start of session, commit be1da25)
| Suite | Result | Log |
|---|---|---|
| Backend `pytest backend/tests` | 378 passed, 0 failed, 47m21s, exit 0 | `phase-06-reverify-backend-pytest.txt` |
| Web | typecheck clean, 136 passed | terminal |
| Android JVM | 102 run, 0 failed (first pass was a Gradle cache hit; re-run later executed the tests fresh: 102/0) | `phase-06-reverify-android.txt` |
Not re-run: emulator instrumented tests, physical device. Phase 6 gate items needing the operator are unchanged (`phase-06-gate-report.md` section 8).

## Final tree
| Check | Result |
|---|---|
| Backend full suite (final tree) | **430 passed, 1 failed**, 56m57s. The one failure was a bad test input I wrote (a family name over the 255-char column); fixed, and that test passes alone (`phase-07-08-final-backend-pytest.txt`). The whole suite was not re-run after that fix. |
| `ruff format --check`, `ruff check`, `mypy backend/app` | clean (76 files formatted, 41 source files no issues) |
| Web | typecheck clean; 144 passed; production build ok |
| Android | `assembleDebug` + JVM tests: 102 passed, 0 failed |
| Live run on the emulator (Android 16 AVD) against a local backend on a throwaway schema | role screen -> link with a pairing code -> start sharing -> SOS -> parent acknowledges -> phone shows "A parent confirmed they saw your SOS" -> parent message arrives; notification channels `family_sos` / `family_messages` exist with the sound resources attached |
| Web (headless Edge) logged in against the same backend | Overview, Family, SOS (shows the emulator's SOS as acknowledged), Messages, Settings load with no console errors |

## What was added
- Phase 7: `backend/app/mcp_server/` (auth, 5 tools, stdio server), `app.cli mcp-token|mcp-revoke|mcp`, migration 0006, ADR-024, `docs/MCP.md`; tests `test_mcp.py` (30) and `test_mcp_transport.py` (6, real stdio JSON-RPC child process).
- Phase 8: `app.cli doctor|backup|restore`, startup refusal of public bind without https and of wildcards in production, complete `.env.example` (a test keeps it in step with `Settings`), rewritten `docs/SELF_HOSTING.md`; tests `test_selfhost.py` (backup restored into a fresh schema and used through the real API; refusal of non-empty schema, wrong revision, damaged/truncated file).
- Also: web parent onboarding (`/welcome`), alert sounds (web + Android), SEO/landing fixes and a "Deploy yourself" section, CI APK on every push with a rolling `android-latest` release, Android link screen pre-filled with the hosted server. See `launch-review-2026-10-27.md`.

## Needs you / not done
- **Independent audit** (`prompts/INDEPENDENT_AUDIT.md`) for the MCP adapter: not run. Phase 7 stays open until it is.
- **Apply migration 0006** to `piko` (after a backup): needs your approval. The deployed API (at 0005) rejects nothing today; MCP audit rows need 0006.
- **Clean-checkout setup test** (Phase 8 "fresh checkout"): not done (needs downloads). Backend steps were exercised only in the existing `.venv`.
- Backup restore was proven on PostgreSQL (Supabase) schemas only, not with `pg_dump` and not across versions.
- MCP is local stdio only; remote MCP is not built. Any process that can read the launcher's environment can use the token.
- Sounds: packaged and registered on the channels; **not heard** on a device. Emulator was slow (ANR dialog once) so timings are not representative.
- GitHub workflow: edited, YAML parses, **not run on GitHub**. The repo is public, so the `android-latest` APK will be publicly downloadable. The job requests `contents: write`; an org policy could still cap it.
- FreeSiteAudit comparison: tool not run (see launch review).
- **Leftover throwaway schemas in the Supabase DB (none dropped; each needs your approval):** `piko_test_4aa04b19`, `piko_test_a39da344`, `piko_test_e2e_1fc14f`, `piko_test_e2e_165c40`, `piko_test_e2e_36cfa8`, and this session's `piko_test_e2e_65543f` (its test family login is not stored anywhere in the repo). Also `piko_backup_0003` (the pre-migration snapshot; keep).
