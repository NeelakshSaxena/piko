<#
.SYNOPSIS
  Starts the Piko backend, the web dashboard and the project-local Android emulator.
.DESCRIPTION
  Assumes setup is done (.venv, web\node_modules, .env, emulator AVD). Everything binds to loopback.
  Logs go to .tmp\logs. Press Ctrl+C (or close the window) to stop the backend and dashboard;
  the emulator is stopped with scripts\android\stop-emulator.ps1.
.EXAMPLE
  .\scripts\start-all.ps1
  .\scripts\start-all.ps1 -SkipAndroid
#>
param(
    [switch]$SkipBackend,
    [switch]$SkipWeb,
    [switch]$SkipAndroid,
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logs = Join-Path $root '.tmp\logs'
New-Item -ItemType Directory -Force -Path $logs, (Join-Path $root '.cache\npm'), (Join-Path $root '.cache\pip') | Out-Null

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python venv missing ($python). Run .\scripts\setup-windows.ps1" }
if (-not (Test-Path (Join-Path $root '.env'))) { throw ".env missing. Copy .env.example to .env and set PIKO_DATABASE_URL." }
if (-not $SkipWeb -and -not (Test-Path (Join-Path $root 'web\node_modules'))) { throw "web\node_modules missing. Run .\scripts\setup-windows.ps1" }

# Process-only environment (nothing machine-wide is changed).
$env:TEMP = Join-Path $root '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $root '.cache\pip'
$env:npm_config_cache = Join-Path $root '.cache\npm'
$env:PIKO_ALLOWED_ORIGINS = '["http://127.0.0.1:5173","http://localhost:5173"]'
$env:PIKO_ALLOWED_HOSTS = '["127.0.0.1","localhost","[::1]","10.0.2.2"]'

$localNode = Join-Path $root '.tools\node'
if (Test-Path (Join-Path $localNode 'node.exe')) { $env:Path = "$localNode;$env:Path" }
if (-not $SkipWeb -and -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw "npm not found. Install Node.js or run .\scripts\setup-windows.ps1" }

$started = @()
try {
    if (-not $SkipBackend) {
        Write-Host "Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
        $p = Start-Process -FilePath $python -ArgumentList '-m', 'app' -WorkingDirectory (Join-Path $root 'backend') `
            -RedirectStandardOutput (Join-Path $logs 'backend.log') -RedirectStandardError (Join-Path $logs 'backend.err.log') `
            -WindowStyle Hidden -PassThru
        $started += $p
        $ready = $false
        for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
            Start-Sleep -Seconds 1
            if ($p.HasExited) { break }
            try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/health/live' -UseBasicParsing -TimeoutSec 2; $ready = $true } catch { }
        }
        if (-not $ready) {
            $tail = if (Test-Path (Join-Path $logs 'backend.err.log')) { (Get-Content (Join-Path $logs 'backend.err.log') -Tail 15) -join "`n" } else { '' }
            throw "Backend did not become ready. See $logs\backend.err.log`n$tail"
        }
        Write-Host "  backend ready" -ForegroundColor Green
    }

    if (-not $SkipWeb) {
        Write-Host "Starting dashboard on http://127.0.0.1:5173 ..." -ForegroundColor Cyan
        $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort' `
            -WorkingDirectory (Join-Path $root 'web') `
            -RedirectStandardOutput (Join-Path $logs 'web.log') -RedirectStandardError (Join-Path $logs 'web.err.log') `
            -WindowStyle Hidden -PassThru
        $started += $p
        $ready = $false
        for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
            Start-Sleep -Seconds 1
            if ($p.HasExited) { break }
            try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2; $ready = $true } catch { }
        }
        if (-not $ready) { throw "Dashboard did not become ready. See $logs\web.err.log and $logs\web.log" }
        Write-Host "  dashboard ready" -ForegroundColor Green
    }

    if (-not $SkipAndroid) {
        Write-Host "Starting Android emulator (first boot can take a few minutes) ..." -ForegroundColor Cyan
        $emu = Join-Path $root 'scripts\android\start-emulator.ps1'
        if ($Headless) { & $emu -Headless } else { & $emu }
        Write-Host "  install the app with: see docs\RUNNING_LOCALLY.md section 3" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Dashboard : http://127.0.0.1:5173" -ForegroundColor Green
    Write-Host "API       : http://127.0.0.1:8000  (docs at /docs)" -ForegroundColor Green
    Write-Host "Test login: see README.md, 'Local test credentials'" -ForegroundColor Green
    Write-Host "Logs      : $logs"
    Write-Host "Press Ctrl+C to stop the backend and dashboard." -ForegroundColor Yellow
    while ($true) {
        Start-Sleep -Seconds 3
        foreach ($proc in $started) {
            if ($proc.HasExited) { throw "A service exited (pid $($proc.Id)). See logs in $logs" }
        }
    }
}
finally {
    foreach ($proc in $started) {
        if (-not $proc.HasExited) { & taskkill.exe /PID $proc.Id /T /F 2>&1 | Out-Null }
    }
    Write-Host "Backend and dashboard stopped."
}
