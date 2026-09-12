#Requires -Version 7.2
param(
    [string]$BackendUrl = 'https://configure-backend.invalid',
    [string]$JavaHome = 'C:\Program Files\Android\Android Studio\jbr',
    [string]$AndroidHome = "$env:LOCALAPPDATA\Android\Sdk"
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$signingDirectory = Join-Path $projectRoot 'work\private-beta-signing'
$releaseDirectory = Join-Path $projectRoot 'work\releases'
$keyFile = Join-Path $signingDirectory 'family-finance-beta.p12'
$passwordFile = Join-Path $signingDirectory 'keystore.password'
if ($BackendUrl -notmatch '^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$') { throw 'Use an HTTPS backend origin.' }
New-Item -ItemType Directory -Force -Path $signingDirectory, $releaseDirectory | Out-Null

function Protect-SigningFile([string]$Path) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $fileAcl = [Security.AccessControl.FileSecurity]::new()
    $fileAcl.SetAccessRuleProtection($true, $false)
    $fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'Allow'))
    # Persist only the access rules; Set-Acl can request unnecessary audit privileges on reuse.
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($Path), $fileAcl)
}

if (!(Test-Path -LiteralPath $keyFile) -or !(Test-Path -LiteralPath $passwordFile)) {
    throw 'Stage 2 requires the existing stage 1 signing key and password. Restore them; do not generate replacements.'
}
Protect-SigningFile $passwordFile
$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidHome
$env:FF_ANDROID_KEYSTORE = $keyFile
$env:FF_ANDROID_STORE_PASSWORD = [IO.File]::ReadAllText($passwordFile)
$env:FF_ANDROID_KEY_PASSWORD = $env:FF_ANDROID_STORE_PASSWORD
try {
    Protect-SigningFile $keyFile
    Push-Location (Join-Path $projectRoot 'android')
    try {
        & .\gradlew.bat --offline assembleRelease "-PbetaBackendUrl=$BackendUrl"
        if ($LASTEXITCODE -ne 0) { throw 'Release build failed.' }
    } finally { Pop-Location }
    $outputFile = Join-Path $releaseDirectory 'family-finance-stage2.apk'
    Copy-Item -LiteralPath (Join-Path $projectRoot 'android\app\build\outputs\apk\release\app-release.apk') -Destination $outputFile
    Write-Output "Signed release: $outputFile"
    if ($BackendUrl -eq 'https://configure-backend.invalid') {
        Write-Output 'Deployment address is pending. Enter the actual HTTPS server address in the app before setup.'
    }
    Write-Output 'Preserve the private signing directory in an encrypted backup; it is required for future app updates.'
} finally {
    Remove-Item Env:FF_ANDROID_STORE_PASSWORD, Env:FF_ANDROID_KEY_PASSWORD, Env:FF_ANDROID_KEYSTORE -ErrorAction SilentlyContinue
}
