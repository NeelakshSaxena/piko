<#
.SYNOPSIS
  Stops only the emulator this project started (via the recorded pid), asking it to shut down
  cleanly first. Does not touch other emulators, devices, or processes.
#>
[CmdletBinding()]
param([int]$GraceSeconds = 30)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env-android.ps1') | Out-Null
$P = $script:PikoPaths
$adb = Get-PikoTool adb
$pidFile = Join-Path $P.Tmp 'emulator.pid'

if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No project emulator recorded; nothing to stop.'; return }
$id = [int](Get-Content -LiteralPath $pidFile)
$proc = Get-Process -Id $id -ErrorAction SilentlyContinue
if ($null -eq $proc -or $proc.ProcessName -notmatch '^(emulator|qemu-system)') {
    Write-Host "Recorded pid $id is not a running emulator process; clearing the record."
    Remove-Item -LiteralPath $pidFile -Force
    return
}
# Ask the emulator console to power off cleanly, only for the emulator we started.
& $adb -e emu kill 2>$null | Out-Null
$deadline = (Get-Date).AddSeconds($GraceSeconds)
while ((Get-Process -Id $id -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
    Write-Host "Emulator did not exit within $GraceSeconds s; stopping process $id."
    Stop-Process -Id $id -Force
}
Remove-Item -LiteralPath $pidFile -Force
Write-Host 'Emulator stopped.' -ForegroundColor Green
