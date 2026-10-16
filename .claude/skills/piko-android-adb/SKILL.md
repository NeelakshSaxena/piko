# Skill: Piko Android ADB

Use when interacting with Android devices for testing, debugging, or APK installation.

## Prerequisites

- **ADB executable:** `.tools/android/platform-tools/adb.exe` (project-local)
- **Connected device:** Verified via `adb devices -l` before any operation

## Required workflow

1. **Verify device connection**
   - Run: `.\.tools\android\platform-tools\adb.exe devices -l`
   - Confirm exactly one device is connected and **device** status
   - If multiple devices present, require explicit device selection via `-s DEVICE_ID`

2. **Before APK operations**
   - Verify device name, model, Android version
   - Check available storage: `adb shell df /data`
   - Verify app not already installed (or request uninstall confirmation if needed)

3. **Capture evidence**
   - Save logcat output to `artifacts/android/` with timestamp
   - Take screenshots of UI state before/after significant operations
   - Redact sensitive data: locations, tokens, email addresses, device IDs

4. **Safety gates (require explicit confirmation)**
   - ❌ Clear app data: `adb shell pm clear`
   - ❌ Uninstall app: `adb uninstall`
   - ❌ Reset device or wipe data
   - ❌ Change device settings (developer options, permissions)
   - ❌ Access real location data

5. **Never bypass Android platform requirements**
   - Do not modify AndroidManifest.xml to remove required permissions
   - Do not conceal Piko's tracking service
   - Do not implement covert tracking
   - Do not auto-grant dangerous permissions without user interaction in the UI

6. **Use explicit project-local ADB path**
   - Always invoke: `.\.tools\android\platform-tools\adb.exe`
   - Do not use system `adb` or assume PATH
   - Scripts and commands must hardcode this path

## Workflow example

```powershell
# 1. Verify device
.\.tools\android\platform-tools\adb.exe devices -l

# 2. Check device state
.\.tools\android\platform-tools\adb.exe -s DEVICE_ID shell getprop ro.build.version.release

# 3. Install APK
.\.tools\android\platform-tools\adb.exe -s DEVICE_ID install -r .\build\outputs\apk\release\piko.apk

# 4. Launch app
.\.tools\android\platform-tools\adb.exe -s DEVICE_ID shell am start -n com.piko/.MainActivity

# 5. Capture logs
.\.tools\android\platform-tools\adb.exe -s DEVICE_ID logcat -d > artifacts\android\logcat-TIMESTAMP.log
```

## Verification

After any device operation:
- Confirm action succeeded (exit code 0, visual feedback on device)
- Record evidence (screenshot, log snippet) to `artifacts/android/`
- Report any errors with full context
- Never invent device state or successful outcomes

## Not in scope for Phase 0

- Building APK
- Running Espresso/instrumentation tests
- Profiling or benchmarking
- Configuring emulator from scratch

These are Phase 4 (Android node) and later activities.
