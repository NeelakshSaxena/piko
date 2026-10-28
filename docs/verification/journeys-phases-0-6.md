# Journeys phases 0-6 verification (2026-10-28)

Scope: `prompts/PHASE_TRANSPORT.md`, built on the operator's instruction to continue past the phase 1 gate. ADR-025,
ADR-026, `docs/JOURNEYS.md`. **No phase gate is claimed as passed** (see "Gate" below).

## Results

| Check | Command | Result |
|---|---|---|
| Android JVM unit | `gradle :app:testDebugUnitTest --offline --no-daemon` (project-local JDK/Gradle) | **184 run, 0 failed** (102 existing + 82 journeys: rules, form parsing, store contracts on the fake, sync engine incl. events, tracking controller, arrival policy, reminders, battery policy, connections, expected times, inference, wire formats) |
| Android instrumented, full suite on the project-local emulator (Piko_Test_Device, API 36) | `gradle :app:connectedDebugAndroidTest -Ppiko.versionCode=99` | **93 run, 0 failed**: includes the existing suites (queue, comms, vault, push, API clients), the SQLite journey and tracking store contracts, v1 -> v3 database migration, restart durability, and a smoke test that starts the real tracking service, pauses, resumes, stops it, takes a flight reading and checks no position is in it |
| Backend lint and types | `ruff check backend`, `ruff format --check backend`, `mypy backend/app` | clean |
| Backend journeys + migrations + retention | `pytest tests/test_api_journeys.py tests/test_migrations.py tests/test_retention.py` | 13 journeys tests pass (ownership, last-edit-wins, replay, tombstones, validation, event batches, 90-day retention); migrations up, idempotent, down to base, up again pass |
| Backend full suite | three parallel `pytest` runs (A: `test_api_*`, B: cli/deploy_env/mcp/migrations, C: the rest), then a rerun of every failure | A 174 passed, B 61 passed, C 208 passed + 1 skipped; **6 tests failed or errored** (`test_account_locks_after_ten_failures...`, `test_concurrent_pairing...`, `test_concurrent_duplicate_submission...`, `test_a_message_from_a_fast_clock...`, `test_each_family_keeps_its_own_telemetry_window`, `test_identity_fields_in_arguments_are_rejected_not_obeyed`), every one with `server closed the connection unexpectedly` / `503 database unavailable (OperationalError)` from the remote database. **All 6 pass when rerun alone** (together with the 13 journeys tests: 19 passed) |
| Cross-check of the Android wire form against the server schema | `JourneyPutRequest.model_validate` on the body the Android codec produces | valid |

## Not done, and why

- **No provider integration** (flight, rail, routing, taxi): no vendor, key or contract was chosen; each has cost, licensing and data-sharing consequences for the operator. Connection checks use only times the user entered or updated.
- **No physical-device run.** Battery cost, Doze behaviour, OEM battery managers, the 20-minute job's real cadence, and arrival detection while moving are unmeasured (checklist added to `docs/BATTERY_TEST_PROTOCOL.md`). The emulator run proves the service lifecycle, not detection accuracy or battery.
- **The Compose screens were never exercised on a screen** (reaching Home needs a paired phone and a backend). The follow card, expected-time dialog, connection notes and backup switch compile and are used by the code paths above, but no screenshot, TalkBack or large-text pass exists. A manual review fixed the one finding (the backup switch and the location checkbox are now whole-row toggles so a screen reader reads their labels).
- **Android lint and the minified release build could not run offline** (their tool/dependency jars are not in the project cache; downloading them needs approval). The release build with R8 is therefore unverified: the new services/receivers are declared in the manifest, but no minified APK was produced.
- **Migration `0007` is not applied to the persistent `piko` schema**, and no deployment was made. Applying it follows `docs/SELF_HOSTING.md` after a backup and needs the operator's approval.
- **No independent audit** of the new authorization, sync or location code was run.
- The web dashboard milestone view, taxi integrations, booking-reference storage, drag reorder and date pickers are not built.
- The full backend suite was run in parallel groups because one serial run takes about an hour against the remote database; the failures above are connection drops under that load, confirmed only by rerunning each test alone.

## Gate

Phases 0-1: storage-level criterion met and re-verified. Phase 2: backend and sync built and tested; the migration is unapplied. Phases 3-5: built; lifecycle verified on an emulator; arrival detection, battery and Doze behaviour unverified on hardware. Phase 6: connection handling, completion and release documentation done; taxi integrations, physical-device battery tests, independent review and the screen-reader pass are **not done**. None of the phases is marked passed.
