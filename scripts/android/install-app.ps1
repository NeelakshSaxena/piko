<#
.SYNOPSIS
  Assembles and installs the latest Piko Android debug APK onto a connected
  Android device or emulator, then optionally launches the main activity.
.DESCRIPTION
  Uses the project-local Android toolchain and tools (Gradle, ADB) to compile
  and deploy app-debug.apk directly to the target device.
.PARAMETER DeviceId
  Specific ADB target device ID (e.g. emulator-5554). If omitted, targets the only connected device.
.PARAMETER SkipBuild
  Skip Gradle build and install existing app-debug.apk.
.PARAMETER NoLaunch
  Do not launch MainActivity after installation.
.EXAMPLE
  .\scripts\android\install-app.ps1
  .\scripts\android\install-app.ps1 -SkipBuild
  .\scripts\android\install-app.ps1 -DeviceId emulator-5554
#>
[CmdletBinding()]
param(
    [string]$DeviceId,
    [switch]$SkipBuild,
    [switch]$NoLaunch
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'env-android.ps1') | Out-Null
$P = $script:PikoPaths

$adb = Get-PikoTool adb
$gradle = Get-PikoTool gradle
$apkPath = Join-Path $script:PikoRoot 'android\app\build\outputs\apk\debug\app-debug.apk'

# Verify device connectivity
$devicesOut = Invoke-Native -Exe $adb -Arguments @('devices', '-l')
$lines = @($devicesOut.Output | Where-Object { $_ -match '^\S+\s+device\b' })

if ($lines.Count -eq 0) {
    throw "No active Android device or emulator detected by ADB. Start the emulator via scripts\android\start-emulator.ps1"
}

if (-not $DeviceId) {
    if ($lines.Count -eq 1) {
        $DeviceId = ($lines[0] -split '\s+')[0]
    } else {
        $list = ($lines | ForEach-Object { ($_ -split '\s+')[0] }) -join ', '
        throw "Multiple devices connected ($list). Please specify -DeviceId (e.g. -DeviceId emulator-5554)."
    }
}

Write-Host "Target device: $DeviceId" -ForegroundColor Cyan

# 1. Build debug APK
if (-not $SkipBuild) {
    Write-Host "Building debug APK via Gradle (:app:assembleDebug)..." -ForegroundColor Cyan
    Push-Location (Join-Path $script:PikoRoot 'android')
    try {
        $res = Invoke-Native -Exe $gradle -Arguments @(':app:assembleDebug', '--no-daemon')
        if ($res.ExitCode -ne 0) {
            $errSnippet = ($res.Output | Select-Object -Last 25) -join "`n"
            throw "Gradle build failed with exit code $($res.ExitCode):`n$errSnippet"
        }
        Write-Host "  APK build complete." -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $apkPath)) {
    throw "APK file not found at $apkPath. Run without -SkipBuild to assemble."
}

# 2. Install APK to device
Write-Host "Installing $apkPath to $DeviceId ..." -ForegroundColor Cyan
$installOut = Invoke-Native -Exe $adb -Arguments @('-s', $DeviceId, 'install', '-r', $apkPath)
$installText = $installOut.Output -join "`n"

if ($installOut.ExitCode -ne 0 -or $installText -notmatch 'Success') {
    throw "ADB install failed (exit $($installOut.ExitCode)):`n$installText"
}
Write-Host "  Install successful." -ForegroundColor Green

# 3. Launch MainActivity
if (-not $NoLaunch) {
    Write-Host "Launching Piko on $DeviceId ..." -ForegroundColor Cyan
    $launchOut = Invoke-Native -Exe $adb -Arguments @('-s', $DeviceId, 'shell', 'am', 'start', '-n', 'app.piko.android/.ui.MainActivity')
    $launchText = $launchOut.Output -join "`n"
    if ($launchOut.ExitCode -ne 0) {
        Write-Warning "Could not launch MainActivity (exit $($launchOut.ExitCode)):`n$launchText"
    } else {
        Write-Host "  Piko launched on $DeviceId." -ForegroundColor Green
    }
}
