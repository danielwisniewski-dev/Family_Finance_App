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

if ((Test-Path -LiteralPath $keyFile) -and !(Test-Path -LiteralPath $passwordFile)) {
    throw 'Existing signing key has no local password file. Restore its password; do not replace the key.'
}
if (!(Test-Path -LiteralPath $passwordFile)) {
    $newPassword = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
    [IO.File]::WriteAllText($passwordFile, $newPassword)
}
Protect-SigningFile $passwordFile
$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidHome
$env:FF_ANDROID_KEYSTORE = $keyFile
$env:FF_ANDROID_STORE_PASSWORD = [IO.File]::ReadAllText($passwordFile)
$env:FF_ANDROID_KEY_PASSWORD = $env:FF_ANDROID_STORE_PASSWORD
try {
    if (!(Test-Path -LiteralPath $keyFile)) {
        & (Join-Path $JavaHome 'bin\keytool.exe') -genkeypair -keystore $keyFile -storetype PKCS12 `
            -alias family-finance-beta -keyalg RSA -keysize 3072 -validity 10000 `
            -dname 'CN=Family Finance Private Beta' -storepass:env FF_ANDROID_STORE_PASSWORD -keypass:env FF_ANDROID_KEY_PASSWORD
        if ($LASTEXITCODE -ne 0) { throw 'Signing key creation failed.' }
    }
    Protect-SigningFile $keyFile
    Push-Location (Join-Path $projectRoot 'android')
    try {
        & .\gradlew.bat --offline assembleRelease "-PbetaBackendUrl=$BackendUrl"
        if ($LASTEXITCODE -ne 0) { throw 'Release build failed.' }
    } finally { Pop-Location }
    $outputFile = Join-Path $releaseDirectory 'family-finance-stage1.apk'
    Copy-Item -LiteralPath (Join-Path $projectRoot 'android\app\build\outputs\apk\release\app-release.apk') -Destination $outputFile
    Write-Output "Signed release: $outputFile"
    if ($BackendUrl -eq 'https://configure-backend.invalid') {
        Write-Output 'Deployment address is pending. Enter the actual HTTPS server address in the app before setup.'
    }
    Write-Output 'Preserve the private signing directory in an encrypted backup; it is required for future app updates.'
} finally {
    Remove-Item Env:FF_ANDROID_STORE_PASSWORD, Env:FF_ANDROID_KEY_PASSWORD, Env:FF_ANDROID_KEYSTORE -ErrorAction SilentlyContinue
}
