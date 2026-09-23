param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_82_r5_multi_path_strategy_benchmark_validation_layer.py"

Write-Host "STAGE_NAME=V20.82_R5_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "SHADOW_ONLY=TRUE"
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
        "PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED",
        "PARTIAL_PASS_V20_82_R5_MULTI_PATH_EVIDENCE_ATTACHED_WITH_CATEGORY_BLOCKERS"
    )
    $DetectedStatus = ($Output | Where-Object { $Allowed -contains $_ } | Select-Object -Last 1)
    if (-not $DetectedStatus) {
        throw "V20.82-R5 did not report an allowed final status"
    }
    if ($ExitCode -ne 0) {
        throw "V20.82-R5 reported non-zero exit code $ExitCode"
    }
    Write-Host $DetectedStatus
}
catch {
    $PreservedStatus = $null
    if ($null -ne $Output) {
        $PreservedStatus = ($Output | Where-Object { $_ -match "^(PASS|PARTIAL_PASS|BLOCKED)_V20_82_" } | Select-Object -Last 1)
    }
    if ($PreservedStatus) {
        Write-Host $PreservedStatus
    }
    else {
        Write-Host "BLOCKED_V20_82_WRAPPER_FAILURE"
    }
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
