[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 18441,
    [switch]$PersistUserEnvironment,
    [switch]$Show
)

$ErrorActionPreference = "Stop"
$ProfilePath = Join-Path $RepoRoot "config\moomoo_opend_connection.json"
if (-not (Test-Path $ProfilePath)) { throw "OpenD profile not found: $ProfilePath" }

if ($Show) {
    Get-Content $ProfilePath -Raw
    exit 0
}

if ($HostAddress -notin @("127.0.0.1", "localhost", "::1")) {
    throw "Remote OpenD host is blocked. Use 127.0.0.1, localhost, or ::1."
}
if ($Port -lt 1 -or $Port -gt 65535) { throw "Invalid OpenD port: $Port" }

$Profile = Get-Content $ProfilePath -Raw | ConvertFrom-Json
$Profile.host = $HostAddress
$Profile.port = $Port
$Profile.allow_remote_host = $false
$Profile.profile_name = "LOCAL_MOOMOO_OPEND_$Port"
$ProfileJson = $Profile | ConvertTo-Json -Depth 10
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    $ProfilePath,
    $ProfileJson + [Environment]::NewLine,
    $Utf8NoBom
)

$HostKeys = @("MOOMOO_OPEND_HOST", "FUTU_OPEND_HOST", "MOOMOO_HOST", "FUTU_HOST", "OPEND_HOST")
$PortKeys = @("MOOMOO_OPEND_PORT", "FUTU_OPEND_PORT", "MOOMOO_PORT", "FUTU_PORT", "OPEND_PORT")
foreach ($Key in $HostKeys) { Set-Item -Path "Env:$Key" -Value $HostAddress }
foreach ($Key in $PortKeys) { Set-Item -Path "Env:$Key" -Value ([string]$Port) }

if ($PersistUserEnvironment) {
    foreach ($Key in $HostKeys) { [Environment]::SetEnvironmentVariable($Key, $HostAddress, "User") }
    foreach ($Key in $PortKeys) { [Environment]::SetEnvironmentVariable($Key, [string]$Port, "User") }
}

Write-Host "final_status=PASS_V22_047_R1C_OPEND_PROFILE_UPDATED"
Write-Host "opend_host=$HostAddress"
Write-Host "opend_port=$Port"
Write-Host "persist_user_environment=$($PersistUserEnvironment.IsPresent)"
Write-Host "profile_path=$ProfilePath"
