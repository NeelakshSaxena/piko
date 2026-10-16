#!/usr/bin/env pwsh
<#
.SYNOPSIS
Start all Piko services for local development: backend, web dashboard, and Android emulator.

.DESCRIPTION
Launches the FastAPI backend, React dev server, and Android emulator in parallel.
Assumes all dependencies are installed (Python, Node.js, Android SDK, Gradle).

Prerequisites:
  - .venv/ directory with dependencies installed
  - node_modules/ in web/
  - Android emulator named "Piko_Test_Device" (optional)
  - PostgreSQL configured in .env (PIKO_DATABASE_URL)

All services bind to 127.0.0.1 (loopback only).

Note: On Windows, if you get an execution policy error, run this in PowerShell (as admin):
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

.EXAMPLE
  .\scripts\start-all.ps1                    # Start all services
  .\scripts\start-all.ps1 -SkipAndroid       # Skip Android emulator
  .\scripts\start-all.ps1 -SkipBackend       # Skip backend (use external API)
  .\scripts\start-all.ps1 -Headless          # Android without display window
#>

param(
  [switch]$SkipBackend,
  [switch]$SkipWeb,
  [switch]$SkipAndroid,
  [switch]$Headless  # Run Android emulator without display window
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Piko - Starting all services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verify prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

if (-not (Test-Path "$repoRoot\.venv\Scripts\python.exe")) {
  Write-Host "[ERROR] Python venv not found at .venv/" -ForegroundColor Red
  Write-Host "   Run: .\scripts\setup-windows.ps1" -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path "$repoRoot\web\node_modules")) {
  Write-Host "[ERROR] npm dependencies not installed in web/" -ForegroundColor Red
  Write-Host "   Run: cd web; npm install" -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path "$repoRoot\.env")) {
  Write-Host "[ERROR] .env not found" -ForegroundColor Red
  Write-Host "   Copy .env.example to .env and configure PIKO_DATABASE_URL" -ForegroundColor Yellow
  exit 1
}

# Load environment
$env:TEMP = "$repoRoot\.tmp"
$env:TMP = "$repoRoot\.tmp"
$env:PIP_CACHE_DIR = "$repoRoot\.cache\pip"
$env:npm_config_cache = "$repoRoot\.cache\npm"
$env:PIKO_ALLOWED_ORIGINS = "[`"http://127.0.0.1:5173`",`"http://localhost:5173`"]"
$env:PIKO_ALLOWED_HOSTS = "[`"127.0.0.1`",`"localhost`",`"[::1]`",`"10.0.2.2`"]"

Create-Item -ItemType Directory -Force -Path "$repoRoot\.tmp", "$repoRoot\.cache\pip", "$repoRoot\.cache\npm" | Out-Null

Write-Host "[OK] Prerequisites OK" -ForegroundColor Green
Write-Host ""

$jobs = @()

# Start Backend
if (-not $SkipBackend) {
  Write-Host "Starting backend (http://127.0.0.1:8000)..." -ForegroundColor Cyan

  $backendJob = Start-Job -Name "piko-backend" -ScriptBlock {
    param($root)
    Set-Location "$root\backend"
    $env:TEMP = "$root\.tmp"
    $env:TMP = "$root\.tmp"
    $env:PIP_CACHE_DIR = "$root\.cache\pip"
    $env:PIKO_ALLOWED_ORIGINS = "[`"http://127.0.0.1:5173`",`"http://localhost:5173`"]"
    $env:PIKO_ALLOWED_HOSTS = "[`"127.0.0.1`",`"localhost`",`"[::1]`",`"10.0.2.2`"]"

    # Load .env
    Get-Content "$root\.env" | ForEach-Object {
      if ($_ -match "^([^=]+)=(.*)$") {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim().Trim("`"")
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
      }
    }

    & "$root\.venv\Scripts\python" -m app
  } -ArgumentList $repoRoot

  $jobs += $backendJob
  Start-Sleep -Seconds 2
}

# Start Web Dashboard
if (-not $SkipWeb) {
  Write-Host "Starting web dashboard (http://127.0.0.1:5173)..." -ForegroundColor Cyan

  $webJob = Start-Job -Name "piko-web" -ScriptBlock {
    param($root)
    Set-Location "$root\web"
    $env:npm_config_cache = "$root\.cache\npm"
    $env:VITE_API_BASE = "http://127.0.0.1:8000"
    & npm run dev
  } -ArgumentList $repoRoot

  $jobs += $webJob
  Start-Sleep -Seconds 2
}

# Start Android Emulator
if (-not $SkipAndroid) {
  Write-Host "Starting Android emulator..." -ForegroundColor Cyan

  # Source Android environment
  & "$repoRoot\scripts\android\env-android.ps1"

  $emulatorArgs = @("-avd", "Piko_Test_Device")
  if ($Headless) {
    $emulatorArgs += "-no-window"
  }

  $emulatorJob = Start-Job -Name "piko-android" -ScriptBlock {
    param($root, $args)
    . "$root\scripts\android\env-android.ps1"
    $emulatorPath = Get-PikoTool emulator
    & $emulatorPath $args
  } -ArgumentList $repoRoot, $emulatorArgs

  $jobs += $emulatorJob
}

Write-Host ""
Write-Host "All services starting... waiting for readiness..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Wait for backend to be ready
if (-not $SkipBackend) {
  $maxRetries = 30
  $retry = 0
  while ($retry -lt $maxRetries) {
    try {
      $null = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health/live" -ErrorAction Stop -TimeoutSec 2
      Write-Host "[OK] Backend ready" -ForegroundColor Green
      break
    }
    catch {
      $retry++
      Start-Sleep -Seconds 1
      if ($retry -eq $maxRetries) {
        Write-Host "[FAIL] Backend failed to start" -ForegroundColor Red
        Write-Host "  Check the logs in the background job for errors" -ForegroundColor Yellow
        break
      }
    }
  }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "OK - All services are running!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Dashboard:  http://127.0.0.1:5173" -ForegroundColor Cyan
Write-Host "API:        http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Android:    Emulator launching (Android 16)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test credentials:" -ForegroundColor Green
Write-Host "  Email:    test.parent@example.com" -ForegroundColor Cyan
Write-Host "  Password: g838-w3fp-k54z" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Guardian: test.guardian@example.com / 33te-nqs5-p5df" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop all services" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Display logs from jobs
foreach ($job in $jobs) {
  Receive-Job -Job $job -Keep 2>&1
}

# Keep script running and forward Ctrl+C
try {
  while ($true) {
    Start-Sleep -Seconds 5
    foreach ($job in $jobs) {
      if ($job.State -eq "Failed") {
        Write-Host "[WARN] Job failed: $($job.Name)" -ForegroundColor Red
        Receive-Job -Job $job | Out-Host
      }
    }
  }
}
catch {
  # Catch Ctrl+C
}
finally {
  Write-Host ""
  Write-Host "Stopping all services..." -ForegroundColor Yellow
  $jobs | Stop-Job -ErrorAction SilentlyContinue
  $jobs | Remove-Job -ErrorAction SilentlyContinue
  Write-Host "[OK] All services stopped" -ForegroundColor Green
}
