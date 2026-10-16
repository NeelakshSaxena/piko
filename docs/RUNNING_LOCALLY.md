# Running Piko locally (development)

Everything stays under the repository root (`docs/LOCAL_ONLY_POLICY.md`). Commands are PowerShell, run
from the repository root. Nothing here binds to a public address.

## Quick start: start all services at once

```powershell
.\scripts\start-all.ps1
```

This starts the backend, web dashboard, and Android emulator in parallel. See `README.md` for login credentials and URLs.

---

## Manual setup (step by step)

If you prefer to start services individually or want more control:

### 1. Backend (API) on loopback
```powershell
$env:TEMP = "$PWD\.tmp"; $env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = "$PWD\.cache\pip"
# Allow the dashboard's dev origin and the Android emulator's alias for this machine (process only):
$env:PIKO_ALLOWED_ORIGINS = '["http://127.0.0.1:5173","http://localhost:5173"]'
$env:PIKO_ALLOWED_HOSTS   = '["127.0.0.1","localhost","[::1]","10.0.2.2"]'

# First time only: set up venv and install dependencies
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,api,test]"

# First time: configure database
copy .env.example .env
# Edit .env: set PIKO_DATABASE_URL to your PostgreSQL instance

# First time: generate encryption keys
cd backend
..\.venv\Scripts\python -m app.cli generate-keys --dir ..\.data\keys
# Copy the printed paths into .env

# First time: run migrations
..\.venv\Scripts\python -m alembic upgrade head

# Create first family
..\.venv\Scripts\python -m app.cli create-family --email admin@example.com --family-name "Home"

# Start server
..\.venv\Scripts\python -m app          # http://127.0.0.1:8000
```

Database tests (requires PostgreSQL running):
```powershell
.venv\Scripts\python -m pytest
```

### 2. Parent dashboard
```powershell
Set-Location web
$env:npm_config_cache = "$PWD\..\.cache\npm"
npm install          # first time only; packages go to web/node_modules
npm run dev          # http://127.0.0.1:5173

# In another terminal:
npm test             # 72 tests
npm run build        # static files in web/dist (tsc + vite; adds a strict CSP)
```

Environment variables (set before `npm run dev`):
- `VITE_API_BASE` — backend URL (default: `http://127.0.0.1:8000`)
- `VITE_TILE_URL` — map tile provider (default: OpenStreetMap; set to `off` to disable)

### 3. Android app on the project-local emulator

First time only: set up the emulator and install the app:
```powershell
. .\scripts\android\env-android.ps1                  # Load Android tools
.\scripts\android\start-emulator.ps1                 # Start emulator window
```

In another terminal:
```powershell
. .\scripts\android\env-android.ps1
cd android
& (Get-PikoTool gradle) :app:assembleDebug --no-daemon
& (Get-PikoTool adb) install -r app\build\outputs\apk\debug\app-debug.apk
& (Get-PikoTool adb) shell am start -n app.piko.android/.ui.MainActivity
```

In the app:
1. Choose "Continue as Child"
2. Enter `http://10.0.2.2:8000` (emulator's address for localhost)
3. Paste a pairing code from the dashboard's Family Members page
4. Agree and link

To test with synthetic location (emulator has no network location by default):
```powershell
. .\scripts\android\env-android.ps1
& (Get-PikoTool adb) emu geo fix -122.4194 37.7749   # San Francisco
```

Tests:
```powershell
. .\scripts\android\env-android.ps1
cd android
& (Get-PikoTool gradle) :app:testDebugUnitTest          # JVM unit tests (48)
& (Get-PikoTool gradle) :app:connectedDebugAndroidTest  # Emulator tests (30)
```

---

## Complete fresh setup (from scratch)

On Windows, if you don't have Node.js, Python venv, or Android SDK installed locally:

```powershell
.\scripts\setup-windows.ps1
```

This downloads Node.js, Android SDK, and configures everything under `.tools/` and `.gradle-home/`.
Then run `.\scripts\start-all.ps1` to begin development.

On macOS/Linux, see the manual section above and adapt paths (`.venv/bin/` instead of `.venv\Scripts\`).

---

## Test data

A test family named **"TEST FAMILY (safe to delete)"** was created in the `piko` schema on 2026-10-16
for manual testing. See `README.md` for login credentials. Delete it when no longer needed.

Use throwaway families only; never test with real family location data.
