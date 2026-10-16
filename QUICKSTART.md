# Quick Start — Get Piko Running in 2 Steps

## For fresh setup (Windows)

### Step 1: Setup (10–15 minutes, downloads ~3 GB)

```powershell
cd C:\path\to\piko
.\scripts\setup-windows.ps1
```

This downloads Node.js, Android SDK, and configures Python. **It will print instructions if PostgreSQL needs to be configured.**

### Step 2: Start (instant)

```powershell
.\scripts\start-all.ps1
```

Opens:
- **Dashboard:** http://127.0.0.1:5173
- **Backend:** http://127.0.0.1:8000
- **Android:** Emulator window

### Step 3: Login

| Field | Value |
|-------|-------|
| **Email** | `test.parent@example.com` |
| **Password** | `g838-w3fp-k54z` |

---

## For existing setup

```powershell
.\scripts\start-all.ps1
```

That's it. Services start in parallel with real-time logs.

---

## Troubleshooting

### PowerShell execution policy error
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Backend won't connect to database
1. Check PostgreSQL is running: `psql -U postgres -d postgres`
2. Edit `.env` and set `PIKO_DATABASE_URL`
3. Restart with `.\scripts\start-all.ps1`

### Android emulator not starting
```powershell
.\scripts\android\doctor-android.ps1   # Diagnose the issue
.\scripts\android\start-emulator.ps1   # Try again
```

### Services exit immediately
Check the background job log: `Get-Job | Receive-Job`

---

## Next Steps

- **Testing:** See `docs/RUNNING_LOCALLY.md` for test commands
- **Architecture:** Read `docs/ARCHITECTURE.md`
- **API docs:** http://127.0.0.1:8000/docs (when backend is running)

---

## Project structure

```
piko/
├── backend/          # Python FastAPI backend
├── web/              # React dashboard (Vite)
├── android/          # Kotlin Android app
├── .venv/            # Python virtual environment
├── .tools/           # Downloaded tools (Node, Android SDK)
├── .gradle-home/     # Gradle cache
├── .data/            # Local database & keys
└── scripts/
    ├── start-all.ps1          # Start all services (new)
    ├── setup-windows.ps1      # Initial setup (new)
    └── android/               # Android helpers
```

See `README.md` for full documentation and `docs/LOCAL_ONLY_POLICY.md` for the project-local toolchain philosophy.
