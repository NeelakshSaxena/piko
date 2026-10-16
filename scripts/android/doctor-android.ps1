<#
.SYNOPSIS
  Read-only inspection of the project-local Android toolchain. Exits 1 if anything is missing or
  resolves outside the project root. Prints no secrets.
#>
[CmdletBinding()]
param([switch]$Quiet)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env-android.ps1') | Out-Null
$P = $script:PikoPaths
$failures = New-Object System.Collections.Generic.List[string]

function Check([string]$name, [scriptblock]$probe) {
    try {
        $out = & $probe
        Write-Host ("  OK    {0,-14} {1}" -f $name, $out)
    } catch {
        Write-Host ("  FAIL  {0,-14} {1}" -f $name, $_.Exception.Message) -ForegroundColor Red
        $failures.Add($name)
    }
}
function Version([string]$tool, [string[]]$toolArgs, [string]$pattern) {
    $exe = Get-PikoTool $tool
    $r = Invoke-Native -Exe $exe -Arguments $toolArgs
    $line = if ($pattern) { $r.Output | Where-Object { $_ -match $pattern } | Select-Object -First 1 } else { $r.Output | Select-Object -First 1 }
    if (-not $line) { throw "no version output (exit $($r.ExitCode))" }
    "$($line.Trim())  [$exe]"
}

Write-Host "Tools (explicit project-local paths; no PATH fallback)"
Check 'java'       { Version 'java' @('-version') 'version' }
Check 'javac'      { Version 'javac' @('-version') 'javac' }
Check 'sdkmanager' { Version 'sdkmanager' @("--sdk_root=$($P.SdkRoot)", '--version') '^\d' }
Check 'adb'        { Version 'adb' @('version') 'Android Debug Bridge' }
Check 'emulator'   { Version 'emulator' @('-version') 'Android emulator version' }
Check 'gradle'     { Version 'gradle' @('--version') '^Gradle ' }

Write-Host "`nSDK content"
foreach ($d in 'platforms', 'build-tools', 'system-images') {
    Check $d { $items = Get-ChildItem -LiteralPath (Join-Path $P.SdkRoot $d) -Directory -ErrorAction Stop; if (-not $items) { throw 'empty' }; ($items | ForEach-Object Name) -join ', ' }
}
Check 'licenses' { if (-not (Test-Path (Join-Path $P.SdkRoot 'licenses\android-sdk-license'))) { throw 'not accepted yet' }; 'android-sdk-license present' }

Write-Host "`nAVD"
Check 'avd-config' {
    $ini = Join-Path $P.AvdHome "$script:AvdName.ini"
    if (-not (Test-Path -LiteralPath $ini)) { throw "missing: $ini" }
    "$script:AvdName at $($P.AvdHome)"
}

Write-Host "`nEffective environment must all be under $($P.Root)"
foreach ($v in 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'ANDROID_USER_HOME', 'ANDROID_AVD_HOME', 'JAVA_HOME', 'GRADLE_USER_HOME', 'TEMP', 'TMP') {
    Check $v {
        $val = [Environment]::GetEnvironmentVariable($v, 'Process')
        Assert-UnderRoot -Path $val -Label $v
        $val
    }
}

if ($failures.Count -gt 0) {
    Write-Host "`n$($failures.Count) check(s) failed: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "`nAll checks passed." -ForegroundColor Green

