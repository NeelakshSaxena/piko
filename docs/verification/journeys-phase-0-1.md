# Journeys phases 0-1 verification (2026-10-28)

Scope: local-first journey builder (`prompts/PHASE_TRANSPORT.md` phases 0-1). ADR-025.

| Check | Command | Result |
|---|---|---|
| Android JVM unit | `gradle :app:testDebugUnitTest --offline --no-daemon` (project-local JDK/Gradle, `GRADLE_USER_HOME=.gradle-home`) | **123 run, 0 failed** (102 existing + 21 new: 8 rules, 7 form parsing, 6 store contract on the fake) |
| Instrumented compile | `gradle :app:compileDebugAndroidTestKotlin` | exit 0 |
| SQLite store contract on the project-local emulator (Piko_Test_Device, API 36) | `gradle :app:connectedDebugAndroidTest -Ppiko.versionCode=99` with `class=app.piko.android.SqliteJourneyStoreContractTest` | **6 run, 0 failed** |
| Durability (close/reopen the DB file) | same, `class=app.piko.android.JourneyDurabilityTest` | **2 run, 0 failed** |

Not done / limitations
- The Compose screens (list, detail, editor, leg dialog, Back handling) compile but were **not exercised on a screen**: reaching Home needs a paired phone and a running backend. No screenshot, no accessibility (TalkBack) or large-text pass.
- The two instrumented classes were run separately; a combined `class=a,b` filter ran only the first.
- Process-death survival is shown at the database level (reopen), not by killing the app mid-edit. An unsaved edit in the editor is lost on process death by design (nothing is stored until Save).
- Date/time entry is typed text (`yyyy-MM-dd HH:mm` plus IANA zone), not a picker. A time inside a DST gap is shifted by `java.time` rules without a warning.
- Existing instrumented suites were not re-run; the existing JVM suites were.
- Stitch designs (4 screens in the request) were not fetched; the screens use the app's existing Clay theme.

Gate: phases 0-1 exit criterion ("a multi-leg trip survives restart and works offline") is met at the storage level only; the on-screen flow is unverified. Phase 2 not started.
