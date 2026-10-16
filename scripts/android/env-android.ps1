<#
.SYNOPSIS
  Configures the CURRENT PowerShell process for the project-local Android toolchain.
.DESCRIPTION
  Dot-source this file:  . .\scripts\android\env-android.ps1
  It changes process environment variables only. It never edits the user/system environment,
  PATH, PowerShell profiles or the registry, and it never falls back to a global installation.
  Every location is derived from this script's own location, not the caller's working directory.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:PikoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

$script:PikoPaths = [ordered]@{
    Root          = $script:PikoRoot
    SdkRoot       = Join-Path $script:PikoRoot '.tools\android'
    CmdlineTools  = Join-Path $script:PikoRoot '.tools\android\cmdline-tools\latest'
    PlatformTools = Join-Path $script:PikoRoot '.tools\android\platform-tools'
    Emulator      = Join-Path $script:PikoRoot '.tools\android\emulator'
    JavaHome      = Join-Path $script:PikoRoot '.tools\java\jdk'
    GradleHome    = Join-Path $script:PikoRoot '.tools\gradle'
    GradleUser    = Join-Path $script:PikoRoot '.gradle-home'
    AndroidUser   = Join-Path $script:PikoRoot '.android-home'
    AvdHome       = Join-Path $script:PikoRoot '.android-home\avd'
    EmulatorHome  = Join-Path $script:PikoRoot '.android-home\emulator'
    EmulatorUser  = Join-Path $script:PikoRoot '.android-home\emulator-userprofile'
    Downloads     = Join-Path $script:PikoRoot '.cache\downloads'
    AndroidCache  = Join-Path $script:PikoRoot '.cache\android'
    Tmp           = Join-Path $script:PikoRoot '.tmp'
    Reports       = Join-Path $script:PikoRoot 'artifacts\android-toolchain'
}
$script:AvdName = 'Piko_Test_Device'

function Assert-UnderRoot {
    param([Parameter(Mandatory)][string]$Path, [string]$Label = $Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = $script:PikoRoot.TrimEnd('\') + '\'
    if (-not ($full + '\').StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing: $Label resolves outside the project root ($full)."
    }
}

foreach ($entry in $script:PikoPaths.GetEnumerator()) { Assert-UnderRoot -Path $entry.Value -Label $entry.Key }
foreach ($dir in 'Downloads', 'AndroidCache', 'Tmp', 'Reports', 'GradleUser', 'AndroidUser', 'AvdHome', 'EmulatorHome', 'EmulatorUser') {
    New-Item -ItemType Directory -Force -Path $script:PikoPaths[$dir] | Out-Null
}

# Process-scoped variables only.
$env:ANDROID_HOME         = $script:PikoPaths.SdkRoot
$env:ANDROID_SDK_ROOT     = $script:PikoPaths.SdkRoot       # deprecated alias; some tools still read it
$env:ANDROID_USER_HOME    = $script:PikoPaths.AndroidUser   # adb keys, sdkmanager cache, avd root
$env:ANDROID_AVD_HOME     = $script:PikoPaths.AvdHome
# NOTE: do NOT also set ANDROID_PREFS_ROOT or ANDROID_EMULATOR_HOME. Together with ANDROID_USER_HOME they
# conflict, and avdmanager then fails with "Can't locate Android SDK installation directory for the AVD
# .ini file". Inherited values are cleared so a stale shell cannot reintroduce that failure.
foreach ($stale in 'ANDROID_PREFS_ROOT', 'ANDROID_EMULATOR_HOME', 'AVDMANAGER_OPTS') {
    [Environment]::SetEnvironmentVariable($stale, $null, 'Process')
}
$env:JAVA_HOME            = $script:PikoPaths.JavaHome
$env:GRADLE_USER_HOME     = $script:PikoPaths.GradleUser
$env:TEMP                 = $script:PikoPaths.Tmp
$env:TMP                  = $script:PikoPaths.Tmp
$env:PIP_CACHE_DIR        = Join-Path $script:PikoRoot '.cache\pip'
$env:npm_config_cache     = Join-Path $script:PikoRoot '.cache\npm'

# Project-local tools first on this process's PATH (explicit paths are still used by the scripts).
$localBins = @(
    (Join-Path $script:PikoPaths.JavaHome 'bin'),
    (Join-Path $script:PikoPaths.GradleHome 'bin'),
    (Join-Path $script:PikoPaths.CmdlineTools 'bin'),
    $script:PikoPaths.PlatformTools,
    $script:PikoPaths.Emulator
)
$env:Path = (($localBins | Where-Object { Test-Path $_ }) -join ';') + ';' + $env:Path

function Get-PikoTool {
    <# Explicit executable path inside the project; throws if missing (no PATH fallback). #>
    param([Parameter(Mandatory)][ValidateSet('java', 'javac', 'sdkmanager', 'avdmanager', 'adb', 'emulator', 'gradle')][string]$Name)
    $p = switch ($Name) {
        'java'       { Join-Path $script:PikoPaths.JavaHome 'bin\java.exe' }
        'javac'      { Join-Path $script:PikoPaths.JavaHome 'bin\javac.exe' }
        'sdkmanager' { Join-Path $script:PikoPaths.CmdlineTools 'bin\sdkmanager.bat' }
        'avdmanager' { Join-Path $script:PikoPaths.CmdlineTools 'bin\avdmanager.bat' }
        'adb'        { Join-Path $script:PikoPaths.PlatformTools 'adb.exe' }
        'emulator'   { Join-Path $script:PikoPaths.Emulator 'emulator.exe' }
        'gradle'     { Join-Path $script:PikoPaths.GradleHome 'bin\gradle.bat' }
    }
    Assert-UnderRoot -Path $p -Label $Name
    if (-not (Test-Path -LiteralPath $p)) { throw "$Name is not installed at the project-local path: $p (run scripts\android\setup-android.ps1)" }
    return $p
}

function Invoke-Native {
    <# Runs a native tool, capturing stdout+stderr as text. Windows PowerShell 5.1 turns native
       stderr into terminating errors under $ErrorActionPreference='Stop' (java -version prints
       to stderr), so the preference is relaxed for the call only. #>
    param([Parameter(Mandatory)][string]$Exe, [string[]]$Arguments = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $text = @(& $Exe @Arguments 2>&1 | ForEach-Object { $_.ToString() })
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $text }
    } finally {
        $ErrorActionPreference = $previous
    }
}

Write-Host "Piko Android environment (this process only)"
Write-Host "  root          : $($script:PikoRoot)"
Write-Host "  ANDROID_HOME  : $env:ANDROID_HOME"
Write-Host "  ANDROID_USER_HOME / AVD : $env:ANDROID_USER_HOME  |  $env:ANDROID_AVD_HOME"
Write-Host "  JAVA_HOME     : $env:JAVA_HOME"
Write-Host "  GRADLE_USER_HOME : $env:GRADLE_USER_HOME"
Write-Host "  TEMP/TMP      : $env:TEMP"
