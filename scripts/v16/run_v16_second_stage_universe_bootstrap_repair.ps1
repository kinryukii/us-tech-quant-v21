param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "repair_v16_second_stage_universe.py"
$StatusPath = Join-Path $RepoRoot "outputs\v16\universe\V16_SECOND_STAGE_UNIVERSE_REPAIR_STATUS.csv"

Write-Host "STAGE_NAME=V16_SECOND_STAGE_UNIVERSE_BOOTSTRAP_REPAIR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "PORTFOLIO_WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    $exitCode = $LASTEXITCODE
    $row = $null
    if (Test-Path $StatusPath) {
        $row = Import-Csv $StatusPath | Select-Object -First 1
    }
    if ($null -ne $row) {
        $validation = if ($row.STATUS -eq "PASS_V16_SECOND_STAGE_UNIVERSE_REPAIR") { "PASS" } else { "BLOCKED" }
        Write-Host "final_status=$($row.STATUS)"
        Write-Host "source_file=$($row.selected_source_path)"
        Write-Host "generated_file=$($row.yaml_path)"
        Write-Host "ticker_count=$($row.ticker_count)"
        Write-Host "duplicate_count=$($row.duplicate_count)"
        Write-Host "validation_status=$validation"
    }
    else {
        Write-Host "final_status=BLOCKED_V16_SECOND_STAGE_UNIVERSE_REPAIR"
        Write-Host "source_file="
        Write-Host "generated_file=configs/v16/universe/us_full_second_stage_generated.yaml"
        Write-Host "ticker_count=0"
        Write-Host "duplicate_count=0"
        Write-Host "validation_status=BLOCKED"
    }
    if ($exitCode -ne 0) {
        throw "V16 second-stage universe bootstrap repair failed with exit code $exitCode"
    }
}
finally {
    Pop-Location
}
