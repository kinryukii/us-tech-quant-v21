param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_98b_r5_active_research_base_weight_registry_builder.py"

Write-Host "STAGE_NAME=V20.98B-R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILDER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "IS_OFFICIAL_WEIGHT=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"
Write-Host "V20_107_EXECUTION_STATUS=NOT_RUN"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.98B-R5 registry builder failed with exit code $ExitCode"
    }
    if (-not ($Output -contains "PASS_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILT")) {
        throw "V20.98B-R5 registry builder did not report PASS"
    }
}
catch {
    Write-Host "BLOCKED_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILDER"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
