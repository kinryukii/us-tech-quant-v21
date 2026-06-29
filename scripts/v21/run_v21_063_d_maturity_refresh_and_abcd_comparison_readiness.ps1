Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_063_d_maturity_refresh_and_abcd_comparison_readiness.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\d_weight_optimized\v21_063_maturity_refresh_and_abcd_comparison_readiness"
$SummaryPath = Join-Path $OutputDir "V21_063_D_MATURITY_REFRESH_SUMMARY.csv"

Write-Host "STAGE_ID=V21.063"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_USE=FALSE"
Write-Host "PREFERRED_POLICY_SELECTED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.063 D maturity refresh summary was not created."
    }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally {
    Pop-Location
}
