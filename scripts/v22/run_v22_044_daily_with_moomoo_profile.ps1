[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [switch]$Execute,
    [switch]$QuoteProbe
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$ProfileScript = Join-Path $RepoRoot "scripts\v22\v22_047_r1c_moomoo_opend_connection_profile.py"
$ProfilePath = Join-Path $RepoRoot "config\moomoo_opend_connection.json"
$DailyScript = Join-Path $RepoRoot "scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1"
$PreflightOutput = Join-Path $RepoRoot "outputs\v22\V22.047_R1C_MOOMOO_OPEND_CONNECTION_PROFILE\v22_047_r1c_daily_preflight.json"

if (-not (Test-Path $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path $ProfileScript)) { throw "Profile script not found: $ProfileScript" }
if (-not (Test-Path $ProfilePath)) { throw "Profile not found: $ProfilePath" }
if (-not (Test-Path $DailyScript)) { throw "V22.044 daily entrypoint not found: $DailyScript" }

$Profile = Get-Content $ProfilePath -Raw | ConvertFrom-Json
if ($Profile.host -notin @("127.0.0.1", "localhost", "::1")) {
    throw "Remote OpenD host blocked by daily wrapper: $($Profile.host)"
}

$HostKeys = @("MOOMOO_OPEND_HOST", "FUTU_OPEND_HOST", "MOOMOO_HOST", "FUTU_HOST", "OPEND_HOST")
$PortKeys = @("MOOMOO_OPEND_PORT", "FUTU_OPEND_PORT", "MOOMOO_PORT", "FUTU_PORT", "OPEND_PORT")
foreach ($Key in $HostKeys) { Set-Item -Path "Env:$Key" -Value ([string]$Profile.host) }
foreach ($Key in $PortKeys) { Set-Item -Path "Env:$Key" -Value ([string]$Profile.port) }

$ProbeArgs = @($ProfileScript, "--profile", $ProfilePath, "--output", $PreflightOutput, "--require-tcp")
if ($QuoteProbe) { $ProbeArgs += "--quote-probe" }
& $Python @ProbeArgs
if ($LASTEXITCODE -ne 0) { throw "OpenD preflight failed; daily fetch was not started." }

Write-Host "daily_opend_host=$($Profile.host)"
Write-Host "daily_opend_port=$($Profile.port)"
Write-Host "daily_entrypoint=$DailyScript"

if (-not $Execute) {
    Write-Host "final_status=PASS_V22_047_R1C_DAILY_PROFILE_PREFLIGHT_ONLY"
    Write-Host "daily_child_executed=False"
    exit 0
}

& $DailyScript -Execute
$ChildExitCode = $LASTEXITCODE
Write-Host "v22_044_child_exit_code=$ChildExitCode"
exit $ChildExitCode
