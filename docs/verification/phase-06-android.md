# Phase 6 — SOS and messaging: Android part

> **Superseded in parts (2026-10-17, later the same day):** the web pages now exist (`phase-06-web.md`); the Android
> code changed after the runs below (audit fixes: control characters, poisoned-item ordering, parents-only fetch,
> own-message status). Final results (JVM 90, instrumented 56) and the final live run are in
> `phase-06-gate-report.md` and `phase-06-final-android-tests.txt`. The run below is the first-pass record.

## What was built
- `core/Comms.kt`: outbox model, `CommEngine` (send + refresh), `CommCodec`, `CommLabels` (the only place that
  turns state into words), shared `Backoff.kt` (extracted from `SyncEngine`, behaviour unchanged).
- `data/SqliteCommStore.kt`: durable outbox in its own DB file (`piko-comms.db`, `synchronous=FULL`).
- `net/ApiClient.kt`: SOS / message delivery, ack, and fetches (generalised `post` into `call`).
- `comms/CommsRunner.kt`, `OutboxJobService.kt` (JobScheduler, any network, persisted, system backoff),
  `CommsNotifier.kt`; Compose UI in `ui/CommsScreens.kt`; wiring in `MainActivity`, `Screens.kt`, `SharingService`.
- Manifest: `OutboxJobService`, `RECEIVE_BOOT_COMPLETED` (only so a pending job survives a reboot; no receiver).

## Tests
| Suite | Result | Evidence |
|---|---|---|
| JVM unit (`gradle :app:testDebugUnitTest`) | **79 run, 0 failed** (48 existing + 31 new: 13 engine, 6 model/labels/codec, 12 store contract) | `phase-06-android-tests.txt` |
| Instrumented on the emulator (Android 16 AVD `Piko_Test_Device`, `gradle :app:connectedDebugAndroidTest`) | **53 run, 0 failed** (30 existing + 23 new: 12 SQLite store contract, 4 durability across restart, 7 HTTP client) | same; run before a label-text-only change (JVM suite re-run after it) |
| Backend full suite | **262 passed** (`pytest exit 0`, 19m48s) | `phase-06-backend-pytest.txt` |

## Live run on the emulator (real app, real backend, throwaway schema `piko_test_e2e_1fc14f`)
Backend on `127.0.0.1:8000` reached through `10.0.2.2`; screenshots in `artifacts/android/phase6/`.
| Phase 6 verification item | Observed |
|---|---|
| Offline SOS is retained | Wi-Fi and data disabled, SOS sent: server had **0** incidents; app showed "Sending… the server has not answered yet" (shot 04); a persisted job 6001 existed in `dumpsys jobscheduler`. |
| Reconnect sends exactly one incident, priority/ retry without the app | App process killed (`am kill`, app in background), network restored: the **job** relaunched the process and the server then listed **1** incident (`triggered` 08:31:36, `received` 08:32:12: occurrence time kept). |
| Queued is not shown as delivered | Shot 04 (not delivered), then shot 05: "Delivered to your family's Piko server. No parent has confirmed seeing it yet." |
| Acknowledgement does not auto-resolve | Parent ack -> phone showed "A parent confirmed they saw your SOS" (06); server status stayed `acknowledged`. |
| Resolution is explicit, no reopen | Parent resolve -> phone: "A parent marked this SOS as resolved" (13); a following ack returned `409 CONFLICT`. |
| Notification permission denied handled honestly | Messages screen shows "Reply alerts are off … you will only see replies when you open this screen" (07); no crash. |
| Notification permission granted | After the system dialog "Allow" (09), the card disappeared and a parent message produced a notification: channel `family`, importance HIGH, lock-screen visibility PRIVATE, no body text. |
| Message states | "Delivered to the server, not yet seen" (08) vs parent view `delivered`; child "Got it" -> parent saw `acknowledged`. |
| SOS location | Fresh fix (<2 min) attached unflagged, `captured_at` = `triggered_at`. Stale phone fix -> not attached; server attached its latest known position flagged `is_latest_known: true` with its own capture time. |

## Not done / limitations (do not claim otherwise)
- (At the time of this first run the parent side was exercised through the API only; the web pages were built afterwards.)
- **No push to parents** and **no replies/notifications while the app is closed and sharing is off** (only the
  outbox job runs then). Documented on screen; a push channel or WorkManager+periodic polling is future work.
- Only an **emulator** was used. Not verified: a physical phone, Doze/battery-saver effects on JobScheduler timing,
  reboot persistence of the job, OEM background limits, battery impact, TalkBack/accessibility pass.
- The attach-fresh-location decision in `CommsRunner.submitSos` is verified live once but has no automated test
  (it is bound to Android types).
- Announcements: a parent message that arrives while notification permission is denied is marked announced and
  never notified later (still shown unread in the app).
- Not covered live: both an SOS and a message queued together (ordering is covered by the JVM engine test).
- Independent audit not run; ADR-022 deviations still need operator approval; migration `0004` not applied to the
  persistent `piko` schema.
- The throwaway schema `piko_test_e2e_1fc14f` still exists in the remote database (safe to drop:
  `DROP SCHEMA piko_test_e2e_1fc14f CASCADE`), the e2e server and emulator were stopped.
