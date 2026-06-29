Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_066a_d_latest_data_ranking_viewer.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\d_weight_optimized\v21_066a_latest_data_ranking_viewer"
$SummaryPath = Join-Path $OutputDir "V21_066A_D_LATEST_RANKING_SUMMARY.csv"

Write-Host "STAGE_ID=V21.066A"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_MUTATION=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.066A ranking-view summary was not created."
    }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally {
    Pop-Location
}
