# Tester builds (signed with the project's test key)

Debug APKs from CI cannot be updated in place (CI makes a new debug key every run), and the CI release APK is unsigned.
For people who test over weeks, sign a release build with ONE long-lived test key so every new build installs over the last
one and keeps the tester's journeys and settings.

## The key
- Keystore `.data/signing/piko-test.p12` (alias `piko-test`) and its password file `.data/signing/piko-test.pass`. `.data/` is
  git-ignored: **never commit, upload to CI, paste or email either file.** The password is never printed by any command here.
- **Back it up** (encrypted, off this disk, for example in your password manager). If it is lost, every tester must uninstall
  and reinstall, which deletes their local journeys.
- Certificate SHA-256 (public, safe to share so a tester or you can confirm the signer):
  `30:E8:85:9A:E0:5D:8B:B7:44:56:E9:97:07:3D:4E:DE:F1:E7:41:36:FD:30:86:42:9E:00:34:30:13:BC:C7:FC`
- This is a **test** key, not a Play Store key. Do not reuse it for a store release.

## Build and sign a new version
From the repo root, with the project-local tools (see `docs/LOCAL_ONLY_POLICY.md`). Every build needs a higher
`piko.versionCode` than the last one given to testers (first tester build: 1001).
1. Build: in `android/`, `gradle assembleRelease -Ppiko.versionCode=<N> "-Ppiko.defaultServer=https://piko-api-ten.vercel.app"`
   (output `app/build/outputs/apk/release/app-release-unsigned.apk`; minified).
2. Align: `.tools/android/build-tools/36.0.0/zipalign.exe -f -p 4 <unsigned.apk> .tmp/piko-aligned.apk`
3. Sign: `.tools/android/build-tools/36.0.0/apksigner.bat sign --ks .data/signing/piko-test.p12 --ks-key-alias piko-test --ks-pass file:.data/signing/piko-test.pass --out .data/tester-builds/piko-test-v<N>-<sha>.apk .tmp/piko-aligned.apk`
   (do not add `--key-pass file:` with the same file: the second read hits end-of-file).
4. Verify: `apksigner.bat verify --verbose --print-certs <apk>` must say `Verifies` and show the SHA-256 above.
5. Delete the `.idsig` file next to the output, record the APK's `sha256sum`, and send the APK.

## What testers need to know
- Android 12 or newer (`minSdk 31`). Install from the file: allow "install unknown apps" for the app used to open it.
- The app talks to the server it was built with (the default above). A parent has to give the tester's phone a pairing code
  from a parent account on that server; use a dedicated test family unless real family members have agreed.
- Journeys are saved on the phone only. Server backup is off by default and cannot work until migration `0007` is applied and
  the matching backend is deployed. Live flight/train status works only if the server has provider keys.
- Piko's core feature is sharing a device's location and status with the family it is paired to, so everyone whose phone is paired must know and agree. Journeys add a visible notification while a trip is being followed.
