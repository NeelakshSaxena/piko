# Piko — Family Safety Platform

A modular, self-hostable family safety system with an Android safety node, parent web dashboard, and self-hosted backend.

**Status:** Phases 2–5 implemented and tested; gates pending (see [`STATE.md`](STATE.md) and [`docs/verification/`](docs/verification/)).
- ✅ Backend: FastAPI with auth, invitations, location ingestion, device health tracking
- ✅ Android app: Kotlin/Compose, real-time location sharing, secure pairing
- ✅ Parent dashboard: React/Vite SPA with live map, device health, activity timeline
- ⏳ SOS/messaging: Phase 6 (not yet started)
- ⏳ Security audit & production readiness: gated on Phase 2–3 re-audit

## Quick Start

### For testing (everything local, no setup)

If you already have Node.js, Python 3.11+, and Android emulator with Gradle:

```powershell
# Start backend, frontend, and Android emulator in one command:
.\scripts\start-all.ps1
```

This opens:
- **Parent dashboard:** http://127.0.0.1:5173
- **Backend API:** http://127.0.0.1:8000
- **Android emulator:** automatically configured with test app

Login with:
| Role | Email | Password |
|---|---|---|
| Parent | `test.parent@example.com` | `g838-w3fp-k54z` |
| Guardian | `test.guardian@example.com` | `33te-nqs5-p5df` |

See [Local test credentials](#local-test-credentials) for details.

### For fresh setup (downloads & installs everything)

```powershell
# On Windows, download Node, Python, Android SDK, Gradle, and configure everything:
.\scripts\setup-windows.ps1
```

This checks for prerequisites, downloads them into `.tools/` and `.gradle-home/`, sets up Python venv, installs dependencies, and prepares the Android emulator. Then run `.\scripts\start-all.ps1`.

On macOS/Linux, see [Platform-specific setup](#platform-specific-setup).

---

## More documentation
- Self-hosting (setup, doctor, backup/restore, upgrade): `docs/SELF_HOSTING.md`; hosted deployment: `docs/DEPLOYMENT.md`
- Android app (latest APK, linking a child's phone, sounds, building): `docs/ANDROID_APP.md`
- Read-only AI (MCP) adapter: `docs/MCP.md`
- Push notifications: `docs/PUSH_NOTIFICATIONS.md`

## Architecture

**Modular monolith** with strict boundaries:

| Component | Tech | Database | Purpose |
|---|---|---|---|
| **Backend** | Python + FastAPI | PostgreSQL (prod), SQLite (dev) | Authentication, location ingestion, device health, REST API |
| **Android** | Kotlin + Compose | SQLite (local) | Real-time location sharing, offline event queue, secure pairing |
| **Dashboard** | React + Vite + TypeScript | None (API client) | Parent view of family locations, device health, activity timeline |
| **MCP Server** | Python | API calls only | Read-only interface for AI clients (Phase 7) |

**Deployment:** self-hostable, single-region, no mandatory vendor cloud. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Security:** threat model at [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md).

---

## Project-local toolchain

All dependencies, caches, and build output live under the repository root:

```
.venv/                # Python virtual environment
.cache/pip/           # pip cache
.cache/npm/           # npm cache
.tools/               # Downloaded tools (Node, Android SDK, Gradle)
.gradle-home/         # Gradle cache and config
.data/                # Local databases and test data
.tmp/                 # Temporary files
artifacts/            # Generated reports (git-ignored)
```

**This is mandatory.** Do not install dependencies globally or outside the repo. See [`docs/LOCAL_ONLY_POLICY.md`](docs/LOCAL_ONLY_POLICY.md).

---

## Manual setup (if you prefer step-by-step)

### 1. Backend

```powershell
$env:PIP_CACHE_DIR = "$PWD\.cache\pip"
$env:TEMP = "$PWD\.tmp"
$env:TMP = "$PWD\.tmp"

# Install Python dependencies
.venv\Scripts\python -m pip install -e ".[dev,api,test]"

# Configure database (PostgreSQL only)
copy .env.example .env
# Edit .env: set PIKO_DATABASE_URL to your PostgreSQL instance

# Generate encryption keys
cd backend
..\.venv\Scripts\python -m app.cli generate-keys --dir ..\.data\keys
# Copy the printed key file paths into .env (PIKO_PRIVATE_KEY_FILE, PIKO_PUBLIC_KEY_FILE)

# Run migrations
..\.venv\Scripts\python -m alembic upgrade head

# Create first family
..\.venv\Scripts\python -m app.cli create-family --email admin@example.com --family-name "Home"

# Start server
..\.venv\Scripts\python -m app          # http://127.0.0.1:8000
```

### 2. Parent dashboard

```powershell
cd web
$env:npm_config_cache = "$PWD\..\.cache\npm"

# Install dependencies
npm install

# Start dev server
npm run dev                              # http://127.0.0.1:5173
```

### 3. Android app (emulator)

```powershell
. .\scripts\android\env-android.ps1      # Set up project-local Android tools

# Start emulator
.\scripts\android\start-emulator.ps1

# Build and install app
cd android
& (Get-PikoTool gradle) :app:assembleDebug --no-daemon
& (Get-PikoTool adb) install -r app\build\outputs\apk\debug\app-debug.apk
& (Get-PikoTool adb) shell am start -n app.piko.android/.ui.MainActivity
```

In the app:
1. Choose "Continue as Child"
2. Enter `http://10.0.2.2:8000` (emulator's address for localhost)
3. Paste a pairing code from the dashboard's Family Members page
4. Agree to permissions and link

To test with synthetic location (emulator has no network location by default):
```powershell
& (Get-PikoTool adb) emu geo fix -122.4194 37.7749   # San Francisco
```

---

## Testing

### Backend

```powershell
# Full suite (requires PostgreSQL running)
.venv\Scripts\python -m pytest

# Specific tests
.venv\Scripts\python -m pytest tests/test_auth.py -v
```

### Dashboard

```powershell
cd web

# Unit and integration tests (72 tests)
npm test

# Type check
tsc --noEmit

# Build check
npm run build
```

### Android

```powershell
. .\scripts\android\env-android.ps1
cd android

# JVM unit tests (48)
& (Get-PikoTool gradle) :app:testDebugUnitTest

# Device/emulator tests (30)
& (Get-PikoTool gradle) :app:connectedDebugAndroidTest
```

---

## Local test credentials

These credentials access a **throwaway test family** ("TEST FAMILY (safe to delete)") created in the local `piko` schema. They contain no real data and work only when running the backend on `127.0.0.1:8000`.

**IMPORTANT:** Before publishing, deploying, or sharing this repository, delete the test family, rotate these credentials, and remove this section.

| Role | Email | Password | Scope |
|---|---|---|---|
| Parent | `test.parent@example.com` | `g838-w3fp-k54z` | Full family access |
| Guardian | `test.guardian@example.com` | `33te-nqs5-p5df` | View-only access |

The test family includes one linked phone: "Test_Child_Phone" (running on the project-local Android emulator).

---

## Platform-specific setup

### macOS / Linux

On macOS and Linux, use the same commands as Windows but replace `.venv\Scripts\python` with `.venv/bin/python` and `.venv\Scripts\` with `.venv/bin/`.

```bash
export PIP_CACHE_DIR="$PWD/.cache/pip"
export TEMP="$PWD/.tmp"
export TMP="$PWD/.tmp"

# Python
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,api,test]"

# Node / npm (install or use system node)
npm install
cd web && npm run dev

# Android: requires Java, Android SDK, and Gradle
# See docs/RUNNING_LOCALLY.md for details
```

### Docker (optional)

Docker is **not** required. The project is designed for local development without containerization. If you use Docker, ensure its storage location is on an approved drive (see `docs/LOCAL_ONLY_POLICY.md`).

---

## Documentation

- [`AGENTS.md`](AGENTS.md) — Project constitution and agent roles (read first)
- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — Features and design
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — System design and boundaries
- [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) — Threat model and controls
- [`docs/RUNNING_LOCALLY.md`](docs/RUNNING_LOCALLY.md) — Detailed local setup
- [`STATE.md`](STATE.md) — Implementation status and gate details
- [`DECISIONS.md`](docs/DECISIONS.md) — Architecture and security decisions (ADRs)

---

## Development workflow

1. Create a branch from `main`
2. Make changes; run tests locally (`npm test`, `pytest`, `gradle connectedAndroidTest`)
3. Ensure lint passes (`ruff check`, `tsc --noEmit`)
4. Push and open a pull request
5. After merge, the CI ensures the gate criteria remain met (no breaking changes to contracts, all tests pass)

---

## Contributing

This is a reference implementation and proof-of-concept. The project uses a phased, contract-first approach:
- Phases are sequential; later phases depend on earlier gates
- Each phase has a formal exit gate with evidence
- Security-critical phases (2–3, 7, 10) require independent audit
- No phase is marked complete until its gate passes

See [`AGENTS.md`](AGENTS.md) and [`STATE.md`](STATE.md) for current phase status.

---

## License & Credits

Built with [FastAPI](https://fastapi.tiangolo.com/), [React](https://react.dev/), [Kotlin](https://kotlinlang.org/), and [Leaflet](https://leafletjs.com/).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
