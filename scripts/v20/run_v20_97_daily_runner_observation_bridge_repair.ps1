param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_97_daily_runner_observation_bridge_repair.py"

Write-Host "STAGE_NAME=V20.97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

Push-Location $RepoRoot
$Output = @()
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    $Allowed = @(
        "PASS_V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIRED",
        "WARN_V20_97_NO_VALID_DAILY_RUNNER_OBSERVATIONS_FOUND",
        "BLOCKED_V20_97_MISSING_REQUIRED_V20_96_CONTEXT"
    )
    $DetectedStatus = ($Output | Where-Object { $Allowed -contains $_ } | Select-Object -Last 1)
    if (-not $DetectedStatus) {
        throw "V20.97 did not report an allowed final status"
    }
    if ($ExitCode -ne 0 -and $DetectedStatus -ne "BLOCKED_V20_97_MISSING_REQUIRED_V20_96_CONTEXT") {
        throw "V20.97 reported non-zero exit code $ExitCode"
    }
    Write-Host $DetectedStatus
    if ($DetectedStatus -eq "BLOCKED_V20_97_MISSING_REQUIRED_V20_96_CONTEXT") {
        exit 1
    }
}
catch {
    $PreservedStatus = $null
    if ($null -ne $Output) {
        $PreservedStatus = ($Output | Where-Object { $_ -match "^(PASS|WARN|BLOCKED)_V20_97_" } | Select-Object -Last 1)
    }
    if ($PreservedStatus) {
        Write-Host $PreservedStatus
    }
    else {
        Write-Host "BLOCKED_V20_97_MISSING_REQUIRED_V20_96_CONTEXT"
    }
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
