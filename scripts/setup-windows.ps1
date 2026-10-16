#!/usr/bin/env pwsh
<#
.SYNOPSIS
Complete setup for Piko on Windows: downloads and configures all dependencies.

.DESCRIPTION
Downloads Node.js, Android SDK, and configures the project for local development.
All downloads are project-local (under .tools/, .gradle-home/, etc.).

This script is idempotent: running it multiple times is safe.

Prerequisites:
  - Windows 10+ (PowerShell 5.1+)
  - Python 3.11+ (user-installed, not from Microsoft Store)
  - Git
  - ~15 GB free disk space
  - PostgreSQL (local or remote) for the backend

.EXAMPLE
  .\scripts\setup-windows.ps1
  # Then:
  .\scripts\start-all.ps1
#>

param(
  [switch]$SkipNode,
  [switch]$SkipAndroid,
  [switch]$SkipPython,
  [switch]$OfflineMode
)

$ErrorActionPreference = "Stop"
$InformationPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Piko - Windows Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

@(".tools", ".tools\node", ".tools\android", ".gradle-home", ".cache\pip", ".cache\npm", ".tmp", ".data\keys") | ForEach-Object {
  $path = Join-Path $repoRoot $_
  if (-not (Test-Path $path)) {
    Write-Host "Creating directory: $_"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
  }
}

Write-Host "[OK] Directories ready" -ForegroundColor Green
Write-Host ""

Write-Host "Checking prerequisites..." -ForegroundColor Yellow

try {
  python --version 2>&1 | Select-String "3\.1[1-9]|3\.[2-9]" | Out-Null
  Write-Host "[OK] Python 3.11+ found" -ForegroundColor Green
}
catch {
  Write-Host "[WARN] Python 3.11+ not found (required)" -ForegroundColor Yellow
}

try {
  git --version | Out-Null
  Write-Host "[OK] Git found" -ForegroundColor Green
}
catch {
  Write-Host "[WARN] Git not found" -ForegroundColor Yellow
}

Write-Host ""

if (-not $SkipPython) {
  Write-Host "Setting up Python environment..." -ForegroundColor Cyan

  if (Test-Path "$repoRoot\.venv") {
    Write-Host "[OK] Venv already exists, skipping" -ForegroundColor Green
  }
  else {
    Write-Host "Creating Python virtual environment..."
    python -m venv "$repoRoot\.venv"
    Write-Host "[OK] Venv created" -ForegroundColor Green
  }

  Write-Host "Installing Python dependencies..."
  $env:PIP_CACHE_DIR = "$repoRoot\.cache\pip"
  $env:TEMP = "$repoRoot\.tmp"
  $env:TMP = "$repoRoot\.tmp"

  & "$repoRoot\.venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null
  & "$repoRoot\.venv\Scripts\pip.exe" install -e "$repoRoot\.[dev,api,test]" 2>&1 | Out-Null

  Write-Host "[OK] Python dependencies installed" -ForegroundColor Green
  Write-Host ""
}

if (-not $SkipNode) {
  Write-Host "Setting up Node.js..." -ForegroundColor Cyan

  $nodeVersion = "20.15.0"
  $nodeDir = "$repoRoot\.tools\node"
  $nodePath = "$nodeDir\node.exe"

  if (Test-Path $nodePath) {
    Write-Host "[OK] Node.js already installed, skipping" -ForegroundColor Green
  }
  elseif ($OfflineMode) {
    Write-Host "[ERROR] Node.js not found and offline mode enabled" -ForegroundColor Red
    exit 1
  }
  else {
    Write-Host "Downloading Node.js $nodeVersion..."

    $downloadUrl = "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-win-x64.zip"
    $zipPath = "$repoRoot\.tmp\node-$nodeVersion.zip"

    try {
      Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -TimeoutSec 300
    }
    catch {
      Write-Host "[ERROR] Failed to download Node.js" -ForegroundColor Red
      exit 1
    }

    Write-Host "Extracting Node.js..."
    Expand-Archive -Path $zipPath -DestinationPath "$repoRoot\.tools" -Force

    $extracted = Get-Item "$repoRoot\.tools\node-v$nodeVersion-win-x64"
    Get-ChildItem -Path $extracted | Move-Item -Destination $nodeDir -Force
    Remove-Item -Path $extracted -Force
    Remove-Item -Path $zipPath -Force

    Write-Host "[OK] Node.js installed" -ForegroundColor Green
  }

  $env:PATH = "$nodeDir;$nodeDir\..;$env:PATH"

  Write-Host "Installing npm dependencies..."
  Set-Location "$repoRoot\web"
  $env:npm_config_cache = "$repoRoot\.cache\npm"

  & npm install 2>&1 | Out-Null

  Write-Host "[OK] npm dependencies installed" -ForegroundColor Green
  Write-Host ""
}

if (-not $SkipAndroid) {
  Write-Host "Setting up Android environment..." -ForegroundColor Cyan

  $androidHome = "$repoRoot\.tools\android"
  $gradleHome = "$repoRoot\.gradle-home"

  $env:ANDROID_HOME = $androidHome
  $env:GRADLE_USER_HOME = $gradleHome

  $cmdlineToolsPath = "$androidHome\cmdline-tools\latest\bin"

  if (Test-Path $cmdlineToolsPath) {
    Write-Host "[OK] Android SDK already installed" -ForegroundColor Green
  }
  elseif ($OfflineMode) {
    Write-Host "[WARN] Android SDK not found and offline mode enabled" -ForegroundColor Yellow
  }
  else {
    Write-Host "Note: This requires ~10 GB and may take several minutes"
    Write-Host ""

    if (Test-Path "$repoRoot\scripts\android\setup-android.ps1") {
      Write-Host "Running Android setup script..."
      & "$repoRoot\scripts\android\setup-android.ps1"
    }
    else {
      Write-Host "[WARN] Android setup script not found" -ForegroundColor Yellow
    }
  }

  Write-Host "[OK] Android environment ready" -ForegroundColor Green
  Write-Host ""
}

Write-Host "Configuring environment..." -ForegroundColor Cyan

if (Test-Path "$repoRoot\.env") {
  Write-Host "[OK] .env already exists" -ForegroundColor Green
}
else {
  Write-Host "Creating .env from template..."
  Copy-Item -Path "$repoRoot\.env.example" -Destination "$repoRoot\.env" -Force

  Write-Host ""
  Write-Host "[WARN] .env created but requires manual configuration:" -ForegroundColor Yellow
  Write-Host "  Edit $repoRoot\.env and set:" -ForegroundColor Yellow
  Write-Host "    PIKO_DATABASE_URL=postgresql://user:pass@localhost/piko" -ForegroundColor Cyan
  Write-Host "    PIKO_PRIVATE_KEY_FILE=.data/keys/piko-private-key.pem" -ForegroundColor Cyan
  Write-Host "    PIKO_PUBLIC_KEY_FILE=.data/keys/piko-public-key.pem" -ForegroundColor Cyan
  Write-Host ""
}

if ((Test-Path "$repoRoot\.env") -and -not (Test-Path "$repoRoot\.data\keys\piko-private-key.pem")) {
  Write-Host "Generating encryption keys..."

  Set-Location "$repoRoot\backend"
  & "$repoRoot\.venv\Scripts\python.exe" -m app.cli generate-keys --dir "$repoRoot\.data\keys" 2>&1 | Out-Null

  Write-Host "[OK] Keys generated" -ForegroundColor Green
  Write-Host "  Add the paths to .env (printed above)" -ForegroundColor Yellow
  Write-Host ""
}

if (Test-Path "$repoRoot\.env") {
  Write-Host "Running database migrations..." -ForegroundColor Cyan

  try {
    Set-Location "$repoRoot\backend"
    & "$repoRoot\.venv\Scripts\python.exe" -m alembic upgrade head 2>&1 | Out-Null
    Write-Host "[OK] Migrations complete" -ForegroundColor Green
  }
  catch {
    Write-Host "[WARN] Migration failed (PostgreSQL may not be configured)" -ForegroundColor Yellow
  }
  Write-Host ""
}

Write-Host "========================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

if ((Test-Path "$repoRoot\.venv\Scripts\python.exe") -and (Test-Path "$repoRoot\web\node_modules" -or $SkipNode)) {
  Write-Host ""
  Write-Host "Ready to start development:" -ForegroundColor Green
  Write-Host "  .\scripts\start-all.ps1" -ForegroundColor Cyan
}
else {
  Write-Host ""
  Write-Host "Setup incomplete. Missing:" -ForegroundColor Yellow
  if (-not (Test-Path "$repoRoot\.venv\Scripts\python.exe")) {
    Write-Host "  - Python venv (.venv/)" -ForegroundColor Yellow
  }
  if (-not (Test-Path "$repoRoot\web\node_modules") -and -not $SkipNode) {
    Write-Host "  - npm dependencies (web/node_modules)" -ForegroundColor Yellow
  }
  Write-Host ""
  Write-Host "Run: .\scripts\setup-windows.ps1" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Documentation: https://github.com/yourusername/piko" -ForegroundColor Cyan
Write-Host "Status: docs/STATE.md | Running: docs/RUNNING_LOCALLY.md" -ForegroundColor Cyan
Write-Host ""

Set-Location $repoRoot
