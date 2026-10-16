<#
.SYNOPSIS
  Starts the project-local AVD (Piko_Test_Device) with the project-local emulator, then waits for
  boot completion. Records the emulator process id under .tmp so stop-emulator.ps1 can stop only it.
.PARAMETER Headless
  Run without a window (-no-window), e.g. for automated checks.
.PARAMETER BootTimeoutSeconds
  How long to wait for sys.boot_completed.
#>
[CmdletBinding()]
param([switch]$Headless, [int]$BootTimeoutSeconds = 300)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env-android.ps1') | Out-Null
$P = $script:PikoPaths

$emulator = Get-PikoTool emulator
$adb = Get-PikoTool adb
$pidFile = Join-Path $P.Tmp 'emulator.pid'

if (Test-Path -LiteralPath $pidFile) {
    $old = [int](Get-Content -LiteralPath $pidFile)
    if (Get-Process -Id $old -ErrorAction SilentlyContinue) { throw "An emulator started by this project is already running (pid $old). Use stop-emulator.ps1." }
}

# Hardware acceleration must be present; the emulator refuses to run usefully without it.
$accel = & $emulator -accel-check 2>&1 | Out-String
Write-Host $accel.Trim()
if ($accel -notmatch 'is installed and usable|accelerat\w+ can be used') {
    throw "Hardware acceleration is not usable. Not starting the emulator. Enabling 'Windows Hypervisor Platform' is a system change that needs your explicit approval."
}

$emuArgs = @('-avd', $script:AvdName, '-no-snapshot-save', '-no-boot-anim', '-netdelay', 'none', '-netspeed', 'full')
if ($Headless) { $emuArgs += @('-no-window', '-no-audio') }
$log = Join-Path $P.Reports 'emulator-last-run.log'
# The emulator ignores ANDROID_USER_HOME: it keeps its state in ANDROID_EMULATOR_HOME and writes its
# console auth token under the user's home directory. Neither can be set in the shared environment
# (ANDROID_EMULATOR_HOME breaks avdmanager), so both are redirected for the emulator's process ONLY
# and restored immediately afterwards.
$saved = @{}
foreach ($name in 'ANDROID_EMULATOR_HOME', 'USERPROFILE', 'HOME') { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:ANDROID_EMULATOR_HOME = $P.EmulatorHome
    $env:USERPROFILE = $P.EmulatorUser
    $env:HOME = $P.EmulatorUser
    $proc = Start-Process -FilePath $emulator -ArgumentList $emuArgs -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
$proc.Id | Set-Content -LiteralPath $pidFile
Write-Host "emulator pid $($proc.Id); log: $log"

$deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
& $adb wait-for-device
do {
    Start-Sleep -Seconds 3
    $boot = (& $adb shell getprop sys.boot_completed 2>$null | Out-String).Trim()
    if ($proc.HasExited) { throw "Emulator exited early (code $($proc.ExitCode)); see $log.err" }
} while ($boot -ne '1' -and (Get-Date) -lt $deadline)
if ($boot -ne '1') { throw "Boot did not complete within $BootTimeoutSeconds s. The emulator is still running; stop it with stop-emulator.ps1." }
Write-Host "Boot completed." -ForegroundColor Green
& $adb devices -l
