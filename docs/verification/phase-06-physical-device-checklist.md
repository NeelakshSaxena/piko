# Phase 6 — physical-device verification checklist (NOT YET PERFORMED)

Nothing below has been run. Every Phase 6 result so far comes from an Android 16 **emulator**. Do not
claim any of these behaviours until a row is filled in with a date, device model, Android version,
build (`app-debug.apk` hash or version), and the evidence file. Follow `docs/BATTERY_TEST_PROTOCOL.md`
for power measurements. Use a test family, a throwaway server schema and a phone that is not a
child's real phone (AGENTS.md rule 3: no real family location data in tests).

Setup: backend reachable from the phone (LAN address with a protected deployment, or `adb reverse`),
a parent account, the web dashboard open on a computer, the phone paired. Record the device's
battery-optimisation setting for Piko for every run ("Optimised" is the Android default).

| # | Check | How | Expected (what we claim) | Result / evidence |
|---|---|---|---|---|
| 1 | SOS online | Press Send SOS on the phone | Parent dashboard banner within ~30 s; phone says delivered, not seen | |
| 2 | SOS offline then reconnect | Airplane mode, send SOS, wait 5 min, airplane off | Exactly one incident; `triggered_at` is the press time; phone moves queued -> delivered | |
| 3 | Process death | Send SOS offline, swipe the app away from recents, restore network | Delivered without opening the app (JobScheduler) | |
| 4 | Reboot with a queued SOS | Send SOS offline, reboot, restore network, do not open the app | Delivered after boot (needs RECEIVE_BOOT_COMPLETED + persisted job). Record the delay | |
| 5 | Doze | Screen off, unplugged, idle 1 h+ (or `adb shell dumpsys deviceidle force-idle`), then network on | Record how long delivery takes; the claim is "eventually, when the OS runs the job", not a time | |
| 6 | Battery saver / restricted | Turn on Battery Saver and "Restricted" background usage for Piko | Record whether the job still runs; document the failure if it does not | |
| 7 | Reply polling | Sharing off, app closed; parent sends a message | NOT delivered until the app is opened (documented limitation). Confirm the screen text matches | |
| 8 | Reply polling, sharing on | Sharing on, app in background | Reply fetched on the next sync pass (~60 s POLLING); notification shows no message text | |
| 9 | Notification permission denied | Deny at the system prompt | Messages screen shows "Reply alerts are off"; nothing crashes; SOS still works | |
| 10 | Notification permission granted | Allow | Notification appears; lock screen hides content | |
| 11 | Real GPS fix | Outdoors, Realtime mode, send SOS | Position attached unflagged within 2 min of a fix; otherwise server's last-known flagged | |
| 12 | POLLING mode location | Polling mode, SOS | Record whether any fresh fix exists (the emulator had none in POLLING) | |
| 13 | Revoked device | Parent revokes the phone, phone sends SOS | Phone shows "unlinked"; no incident is created | |
| 14 | Unlink with queued items | Queue an SOS offline, unlink | Dialog warns that queued items are deleted; none are sent to a new family after re-pairing | |
| 15 | Battery | 7-8 h run per `BATTERY_TEST_PROTOCOL.md`, with and without SOS/messages idle | Record %; the 1-2 % figure is a target, not a claim | |
| 16 | Accessibility | TalkBack on: SOS button, dialog, Messages | Controls are announced; delivery state is read out | |
| 17 | Web on a phone and a tablet | Open the dashboard at 360 px, 768 px | SOS banner and cards readable; actions reachable by touch | |

Safety reminder to keep on screen: Piko does not call emergency services.
