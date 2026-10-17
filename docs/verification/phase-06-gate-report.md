# Phase 6 gate report (2026-10-17)

**Gate: NOT PASSED. Awaiting the operator.** Everything buildable inside the sandbox is built and verified; the
gate is held by items that need a decision, an approval, an independent second look, or a physical phone (listed in
section 6). Nothing was committed. Phases 7 and 8 were not started.

## 1. What exists
- Backend: `sos_incidents` / `messages` (migration 0004), `services/sos.py`, `services/messages.py`, routes, DTOs.
- Android: durable outbox, retry job, SOS and Messages screens, honest delivery wording, notifications without text.
- Parent web: SOS Centre, Messages, Alerts, app-wide SOS banner, nav count, Overview SOS tile.
- Decisions A and B recorded (ADR-022 addendum 2): device-only SOS; guardians read, never act.

## 2. Final test evidence (commands run on the final tree)
| Suite | Command | Result | Log |
|---|---|---|---|
| Backend full | `pytest backend/tests -v` (started after the last backend code change) | **297 passed**, 1 warning, 25m40s, exit 0 | `phase-06-final-backend-pytest.txt` |
| Backend, one test added afterwards | `pytest backend/tests/test_migrations.py` (0003 -> 0004 with data) | 7 passed | terminal (not in the full log; total on the tree = 298) |
| Backend lint / types | `ruff format --check`, `ruff check`, `mypy backend/app` | 53 files formatted, all checks passed, 29 files no issues | `phase-06-final-backend-lint.txt`, `-mypy.txt` |
| Web | `tsc --noEmit`, `vitest run`, `vite build` | exit 0, **116 passed**, build ok | `phase-06-web-tests.txt` |
| Android JVM | `gradle :app:testDebugUnitTest` | **90 run, 0 failed** | `phase-06-final-android-tests.txt` |
| Android emulator (Android 16 AVD) | `gradle :app:connectedDebugAndroidTest` | **56 run, 0 failed** (includes the final label wording) | same |
Earlier first-pass logs (`phase-06-backend-pytest.txt` 262 passed, `phase-06-android-tests.txt` 79/53) are kept as history
and are **not** the current results.

## 3. End-to-end flow, live (real Android app on the emulator, real backend, real Chrome on the production web build)
Throwaway schema `piko_test_e2e_1fc14f`; screenshots in `artifacts/android/phase6/`, `artifacts/android/phase6-final/`.
| # | Case requested | Result |
|---|---|---|
| 1 | Online SOS | Reached the server in ~1 s; phone: "Delivered ... No parent has confirmed seeing it yet" |
| 2 | Offline SOS, then reconnect | Server had 0 while offline; exactly 1 after reconnect (total 5 -> 6); `triggered_at` kept apart from `received_at` |
| 3 | App process killed | `am kill` with the app in the background; the system job delivered it without opening the app (first and final runs) |
| 4 | Duplicate / retry | Automated: 6 concurrent identical sends -> 1 row; replay returns the stored row (backend); lost-answer resend by id (JVM + SQLite) |
| 5 | Parent acknowledges, not resolves | Acknowledge on the web page; phone showed "A parent confirmed they saw your SOS"; status stayed acknowledged |
| 6 | Resolve, then invalid transition | Web confirmation panel -> Resolved; a later acknowledge returned 409 (API); the resolved card has no actions (test) |
| 7 | Parent reply and wording | Dashboard message: Sending -> "Delivered to the Piko server. The phone has not confirmed seeing it." -> after the phone's "Got it": "The phone confirmed it was seen". Phone message: "Delivered to the server, not yet seen" -> after "Mark as seen": "Seen by a parent" |
| 8 | Unauthorized parent / guardian / unpaired device | Automated (backend): guardian 403 on every write, child role 403, forged/unpaired/revoked device 401, parent cannot create an SOS (401) |
| 9 | Cross-family | Automated: 404 with the same body as a nonexistent id for incidents and messages |
| 10 | Missing / stale / fresh location | Live: no position stated plainly; last-known flagged with its own time and "Not current"; a fresh fix attached unflagged. Automated: server rules (fresh, 23 h, 25 h, none, old offline fix cannot replace a newer one) and the phone's 2-minute rule (`SosLocationPolicyTest`, 5 tests) |
| 11 | Notification permission denied / granted | Denied: "Reply alerts are off" card, no crash, SOS works; granted: card disappears and a notification (channel `family`, high importance, private on the lock screen, no text) posts |
| 12 | Network errors, loading, malformed replies | Automated: web (error with retry, last data kept with a warning, wrong-shape reply is an error), Android (garbled 2xx -> not confirmed -> resent by id; offline -> in doubt) |
Two defects were found only by the live run and fixed with regression tests: the resolve confirmation stayed on a
resolved incident (web), and the phone could never show "Seen by a parent" (Android).

## 4. Security
Independent audit: `phase-06-independent-audit.md` (no Critical/High; 3 Medium, 4 Low, 4 Info). Remediation:
`phase-06-audit-disposition.md`. **Fixed and tested:** F-01 (clock skew could lose an SOS), F-02 (NUL -> 500 and a
blocked outbox), F-03 (banner from a truncated page), F-05, F-07, F-11. **Open:** F-04 (no volume cap / retention),
F-06 (message reads not audited; decision), F-10 (frame headers, Phase 8). **Accepted:** F-08, F-09, F-12.
The fixes have not been re-reviewed by an independent reviewer.

## 5. Migration and schema
`phase-06-migration-and-schema-status.md`: the persistent `piko` schema is at **0003**; 0004 is **not applied** (plan and
rollback implications written; needs your approval and a backup). Three leftover test schemas exist, **none dropped**:
`piko_test_e2e_1fc14f` (this work), `piko_test_a39da344` and `piko_test_4aa04b19` (interrupted earlier runs).

## 6. Why the gate is not passed (acceptance criteria)
| Criterion | State |
|---|---|
| Backend contracts implemented and tested | met |
| Android offline retention and idempotent retry verified | met on an emulator; **not on a physical device** |
| Web SOS Centre, Messages, Alerts implemented and tested | met (116 web tests + live run); no real-browser accessibility or responsive pass |
| Backend authorization matches parent/guardian/device policy | met (tests) |
| Fresh vs stale location has automated coverage | met (backend and Android) |
| Relevant suites pass, limits recorded | met; limits in `phase-06-web.md`, `phase-06-android.md` |
| Independent security review done, material findings addressed | review done, material findings fixed; **fixes not independently re-reviewed**; F-04/F-06/F-10 open |
| Phase 2-3 backlog closed or blocked with named blockers | **not closed**: `phase-02-03-backlog-closure.md` (items 1, 7, 8, 10, 11, 13 need you; 12 is Phase 8) |
| Migration and test-schema status recorded | recorded; **nothing applied or dropped** (needs approval) |
| Docs describe capabilities and limits accurately | done in this pass (ADR-022 addenda, contract note, reports); no push channel is claimed |
| No unapproved destructive action or secret exposure | met: no DROP, no migration on `piko`, read-only DB inspection (counts only), no `.env` read by the reviewer, test credentials were throwaway |
Physical-device checks still owed: `phase-06-physical-device-checklist.md` (17 rows, none run).

## 7. Product limitations (stated on screen as well)
No push to parents or to phones; the dashboard only updates while open and visible (30 s); the phone fetches replies only
while the app is open or sharing is on; no emergency-service integration; messages are plain text on the server; no
retention job; parent-initiated help requests are a separate future requirement.

## 8. Approvals needed from you
1. Confirm the contract revision behind decision A (the Phase 1 text let a parent create an SOS; your policy removes it).
2. Approve (or refuse) applying migration `0004` to `piko`, after a backup (plan in the migration report).
3. Approve the exact `DROP SCHEMA` statements you want run (three candidates listed; I ran none).
4. Decide F-04 (cap/retention), F-06 (audit conversation reads?), Phase 2-3 items 1, 7, 8, 10, 11.
5. Run the physical-device checklist, then say whether the gate passes.
