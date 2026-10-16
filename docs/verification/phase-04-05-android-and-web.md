# Phases 4 and 5: Android node and parent dashboard - evidence

**Date:** 2026-10-16. **Gate: NOT PASSED for either phase** (see "Not verified"). The Phase 2-3 gate is
still open (`docs/PHASE_02_03_GATE_BACKLOG.md`), so neither phase can be gated-complete on top of it.
Decisions: ADR-019 (refresh rotation), ADR-020 (web), ADR-021 (Android) in `docs/DECISIONS.md`.

## What exists
- `android/` Kotlin app: durable SQLite queue, sync engine, REALTIME/POLLING, foreground service,
  pairing, transparency UI (screens: role, pair, child home, transparency), Piko adaptive icon.
- `web/` React SPA: sign in, join with invite code, family overview, map, device details, activity with
  route and gaps, manage (pairing code, invitations, unlink).
- Backend additions: `GET /members/{id}/history`; refresh-token rotation with reuse detection.

## Automated results (exact)
| What | Command | Result | Log |
|---|---|---|---|
| Android JVM unit tests | `gradle :app:testDebugUnitTest` | **48 run, 0 failed** (16 queue-contract on the fake, 15 sync-engine, 17 rules) | `phase-04-android-gradle-tests.log` |
| Android instrumented tests (emulator, Android 16) | `gradle :app:connectedDebugAndroidTest` | **30 run, 0 failed** (16 queue-contract on real SQLite, 5 restart durability, 6 HTTP client, 3 credential vault) | same |
| Mutation check | broke the "outage never costs data" rule on purpose | exactly 1 test failed (`aLongOutageNeverCostsAnyData`), then reverted | `artifacts/android/mutation-check-outage-rule.log` (not committed) |
| Web tests | `npm test` | **54 passed** (API client 15, pure logic 11, pages 28, incl. axe accessibility checks on login, join, overview, map, activity, manage) | run output in this session |
| Web type-check / build | `tsc --noEmit`, `vite build` | exit 0; 446 kB JS (137 kB gzip) | n/a |
| Web dependencies | `npm install`, `npm audit` | 110 packages, 0 vulnerabilities, lockfile committed | `artifacts/npm-install.log` |
| Backend history endpoint | `pytest test_api_history.py` | 8 passed | n/a |
| Backend refresh rotation | `pytest test_api_auth.py test_unit_security.py` | 60 passed | n/a |
| Backend lint / types (final tree) | ruff format, ruff check, mypy | all clean, 27 source files | `phase-04-05-backend-lint.txt`, `-mypy.txt` |
| **Backend full suite (final tree)** | `pytest -v` | **NOT FINISHED when this was written**; started ~11:56, log is `phase-04-05-backend-pytest.txt` (its last line `pytest exit N` is the result) | `phase-04-05-backend-pytest.txt` |

## Verified live (real browser + real backend + real emulator)
- Emulator app paired with the real API through the emulator's host alias, uploaded battery and
  connectivity events (confirmed by the server), and in REALTIME mode uploaded synthetic locations
  (±5 m, one event is about 350 bytes). The parent dashboard showed that phone Online with "Updated N s
  ago", battery, map marker and a route; later it showed Offline and "Not current - last seen 15 min ago"
  once the phone stopped, and "This is where the phone was, not where it is now" on the map.
- Dashboard at a 390 px frame: no horizontal overflow on Family, Map and Manage.
- Session restore across rapid full reloads (after the fix below).
- Screens: `artifacts/android/01..14-*.png` (not committed; `artifacts/` is ignored).

## Defects found by running it, and fixed
1. Dashboard logged the user out after quick reloads (token rotation replayed): access token now kept
   per tab so reloads do not refresh (ADR-020); regression tests added.
2. OpenStreetMap refused tile requests because of `Referrer-Policy: no-referrer`: now origin-only.
3. Instrumented vault tests used the app's real preferences and wiped the emulator pairing: vault takes
   a file name, tests use their own.
4. Translucent Android cards drew a shadow rectangle: opaque tints. "1 readings" wording: fixed in
   source (not yet rebuilt or re-run on the emulator).
5. POLLING gets no location on the emulator by design (network location, no GPS): not a bug, but it
   means POLLING's location path is **unverified**.

## Not verified (why the gates are not passed)
- **No physical device**: POLLING location, battery (protocol only: `docs/BATTERY_TEST_PROTOCOL.md`),
  Doze/battery saver, reboot, notification behaviour on real OEMs.
- Permission denial and "location off" flows were not exercised on the emulator; network loss and
  reconnect were covered by tests and not by yanking the emulator's network live.
- Gradle wrapper download hung at 0 bytes: builds used `.tools\gradle` (same 9.8.1, checksum-verified).
- Release build (minify, signing) never built. The production CSP was only checked as emitted HTML, not
  in a browser with map tiles.
- Web: no screen-reader (NVDA/VoiceOver) pass; axe ran without colour-contrast (jsdom), contrast was
  checked by calculation only; keyboard use was not tested by hand. Tile source is OSM's public server
  (not for production). Plus Jakarta Sans font not bundled.
- The dashboard has no password change, SOS inbox or messages (Phase 6) and no demo/offline fixtures.
- The Android app has no SOS, check-ins or chat (Phase 6); transparency screen says so.
- Independent audit not run for Phases 4/5 (security-relevant: credential storage, token handling).

## Test data created
Family "TEST FAMILY (safe to delete)" in the `piko` schema (parent, guardian, one emulator phone).
Passwords were shown to the operator once and are not stored in the repository. Migration 0003 was
applied to the `piko` schema on 2026-10-16.
