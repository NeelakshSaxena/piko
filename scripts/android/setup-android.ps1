<#
.SYNOPSIS
  Installs or verifies the pinned, project-local Android toolchain. Idempotent; never deletes.
.DESCRIPTION
  Stages (run one or all):
    Tools     command-line tools, JDK, Gradle bootstrap  (checksum verified before extraction)
    Packages  SDK packages through sdkmanager            (requires licenses already accepted)
    Avd       creates the Piko_Test_Device virtual device
  Licenses are NEVER accepted by this script. Accept them yourself, interactively, with:
    . .\scripts\android\env-android.ps1
    & (Get-PikoTool sdkmanager) --sdk_root=$env:ANDROID_HOME --licenses
.PARAMETER Stage
  Tools | Packages | Avd | All
#>
[CmdletBinding()]
param(
    [ValidateSet('Tools', 'Packages', 'Avd', 'All')][string]$Stage = 'All',
    [switch]$WhatIf
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Windows PowerShell 5.1 downloads are very slow with progress on
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12   # TLS verification stays ON

. (Join-Path $PSScriptRoot 'env-android.ps1')
$P = $script:PikoPaths

# ---- pinned inputs (checksums come from the vendors' own metadata; see the installation report) ----
$Pins = [ordered]@{
    CmdlineTools = @{
        File   = 'commandlinetools-win-15859902_latest.zip'
        Url    = 'https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip'
        Sha256 = '90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a'
    }
    Jdk = @{
        File   = 'OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip'
        Url    = 'https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip'
        Sha256 = 'e53a79c3c3d86865bd7e787903884331068e71321714ffd44f145785affc7cb0'
    }
    Gradle = @{
        File   = 'gradle-9.8.1-bin.zip'
        Url    = 'https://services.gradle.org/distributions/gradle-9.8.1-bin.zip'
        Sha256 = 'dce76f55f8e251a3a1f130eb120f30b3d271de2b76c9b0729d316b5a1b6dc01f'
    }
}
# Filled in after inspecting `sdkmanager --list` (see the report for the reasoning).
$SdkPackages = @(
    'platform-tools',
    'emulator',
    'platforms;android-36',
    'build-tools;36.0.0',
    'system-images;android-36;google_apis;x86_64'
)
$AvdImage = 'system-images;android-36;google_apis;x86_64'
$AvdDevice = 'pixel_6'

function Step([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

function Get-VerifiedDownload {
    param([hashtable]$Pin)
    $dest = Join-Path $P.Downloads $Pin.File
    Assert-UnderRoot -Path $dest
    if (-not (Test-Path -LiteralPath $dest)) {
        Write-Host "  downloading $($Pin.Url)"
        if ($WhatIf) { return $dest }
        Invoke-WebRequest -UseBasicParsing -Uri $Pin.Url -OutFile $dest
    } else {
        Write-Host "  archive already present: $dest"
    }
    if ($WhatIf) { return $dest }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $dest).Hash.ToLowerInvariant()
    Write-Host "  expected sha256: $($Pin.Sha256)"
    Write-Host "  observed sha256: $actual"
    if ($actual -ne $Pin.Sha256.ToLowerInvariant()) {
        throw "CHECKSUM MISMATCH for $($Pin.File). The archive was NOT extracted. Investigate before retrying."
    }
    return $dest
}

function Expand-ToTarget {
    <# Extracts into a temp dir, then moves the single top-level folder's CONTENTS into $Target. #>
    param([string]$Archive, [string]$Target, [string]$TopFolder)
    Assert-UnderRoot -Path $Target
    if ((Test-Path -LiteralPath $Target) -and @(Get-ChildItem -LiteralPath $Target -Force).Count -gt 0) {
        Write-Host "  target already populated, leaving untouched: $Target"
        return
    }
    if ($WhatIf) { Write-Host "  would extract to $Target"; return }
    $work = Join-Path $P.Tmp ("extract-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $work
    $src = if ($TopFolder) { Join-Path $work $TopFolder } else { (Get-ChildItem -LiteralPath $work -Directory | Select-Object -First 1).FullName }
    if (-not (Test-Path -LiteralPath $src)) { throw "Unexpected archive layout; expected '$TopFolder' in $Archive" }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Get-ChildItem -LiteralPath $src -Force | Move-Item -Destination $Target
    Remove-Item -LiteralPath $work -Recurse -Force
}

function Install-Tools {
    Step 'Android command-line tools'
    $zip = Get-VerifiedDownload $Pins.CmdlineTools
    Expand-ToTarget -Archive $zip -Target $P.CmdlineTools -TopFolder 'cmdline-tools'

    Step 'JDK 17 (Eclipse Temurin)'
    $zip = Get-VerifiedDownload $Pins.Jdk
    Expand-ToTarget -Archive $zip -Target $P.JavaHome -TopFolder $null

    Step 'Gradle bootstrap distribution (only used to generate the project wrapper)'
    $zip = Get-VerifiedDownload $Pins.Gradle
    Expand-ToTarget -Archive $zip -Target $P.GradleHome -TopFolder $null
}

function Test-LicensesAccepted {
    $lic = Join-Path $P.SdkRoot 'licenses\android-sdk-license'
    return (Test-Path -LiteralPath $lic)
}

function Install-Packages {
    Step 'SDK packages (sdkmanager)'
    if (-not (Test-LicensesAccepted)) {
        throw "Android SDK licenses have not been accepted. This script never accepts them. Run interactively:`n  & (Get-PikoTool sdkmanager) --sdk_root=`$env:ANDROID_HOME --licenses"
    }
    $sdkmanager = Get-PikoTool sdkmanager
    $args2 = @("--sdk_root=$($P.SdkRoot)") + $SdkPackages
    Write-Host "  $sdkmanager $($args2 -join ' ')"
    if ($WhatIf) { return }
    & $sdkmanager @args2
    if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed with exit code $LASTEXITCODE" }
}

function New-TestAvd {
    Step "AVD $script:AvdName"
    $avdmanager = Get-PikoTool avdmanager
    $ini = Join-Path $P.AvdHome "$script:AvdName.ini"
    if (Test-Path -LiteralPath $ini) { Write-Host "  AVD already exists, leaving untouched: $ini"; return }
    if ($WhatIf) { Write-Host "  would create AVD from $AvdImage"; return }
    # avdmanager asks about a custom hardware profile; answer "no". Windows PowerShell 5.1 prepends a BOM to
    # piped text, which avdmanager rejects, so the answer is supplied through cmd's echo instead.
    cmd /c "echo no| `"$avdmanager`" create avd --name $script:AvdName --package $AvdImage --device $AvdDevice" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "avdmanager failed with exit code $LASTEXITCODE" }
    $cfg = Join-Path $P.AvdHome "$script:AvdName.avd\config.ini"
    if (Test-Path -LiteralPath $cfg) {
        # Modest, explicit sizing for UI testing; appended keys override earlier ones.
        Add-Content -LiteralPath $cfg -Value @('hw.ramSize=2048', 'disk.dataPartition.size=6G', 'hw.gps=yes', 'hw.keyboard=yes')
    }
}

Write-Host "Project root: $($P.Root)"
if ($Stage -in 'Tools', 'All')    { Install-Tools }
if ($Stage -in 'Packages', 'All') { Install-Packages }
if ($Stage -in 'Avd', 'All')      { New-TestAvd }
Write-Host "`nDone. Run scripts\android\doctor-android.ps1 to verify." -ForegroundColor Green
