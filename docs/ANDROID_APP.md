# Piko Android app: install, link a child's phone, build

The app runs on the **child's** phone. Parents use the web dashboard. Requires Android 12 (API 31) or newer.

## Get the latest build
- Every push to any branch builds the app and uploads a debug APK as a workflow artifact named `piko-android-debug-apk-<commit>` (kept 14 days).
- Pushes to `main` and `deployment` also refresh one stable download: the **`android-latest`** pre-release on GitHub, file `piko-latest.apk`, with the build number and commit in its notes.
- The APK is debug-signed, for testing. Android will ask you to allow installs from your browser or file manager. Each CI build has a higher version code, so it installs over the previous one and keeps the link to the family.
- CI builds the app with the hosted server address pre-filled (`PIKO_API_URL` repository variable, falling back to the hosted API). A self-hoster sets that variable to their own https address, or edits the address on the link screen.

## Link a child's phone (child onboarding)
1. A parent signs in to the dashboard and opens **Family Members**, then **Create pairing code** (valid 15 minutes, works once). The dashboard's welcome guide does this too.
2. On the phone: open Piko, choose **Continue as Child**.
3. The server address is pre-filled in release-style builds; otherwise type the https address your family uses (emulator: `http://10.0.2.2:8000`).
4. Type the pairing code, check the name shown to the family, read what will be shared, tick the agreement, and press **Link this phone**.
5. Allow location and notifications when asked. A notification stays on while sharing is on, and the child can stop sharing at any time.
Nothing is uploaded before the phone is linked, and events queued for an earlier family are discarded, never sent to a new one.

## Sounds
Replies from the family use `general_notification.mp3`; SOS updates use `sos_notification.mp3` (`app/src/main/res/raw`). Android fixes a channel's sound when the channel is first created, so these live on the channels `family_messages` and `family_sos`; the old `family` channel is removed on the first notification. A user can change a channel's sound in system settings, and Do Not Disturb applies. Notification text never contains a message body.

## Build it yourself
```powershell
. .\scripts\android\env-android.ps1
cd android
& (Get-PikoTool gradle) :app:testDebugUnitTest :app:assembleDebug "-Ppiko.defaultServer=https://piko.example.com" "-Ppiko.versionCode=7"
```
`piko.defaultServer` and `piko.versionCode` are optional. Firebase settings (`piko.firebase.*`) are optional; without them the app falls back to polling. Output: `android/app/build/outputs/apk/debug/app-debug.apk`.

## Known limits
Not verified on a physical device. The sounds and the new notification channels have been built and packaged but not heard on a device. A debug APK is not a store release.
