Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
Push-Location $Root
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "run_v21_075_r1_position_sizing_policy_builder.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python (Join-Path $Dir "v21_075_r2_ranking_only_portfolio_backtest.py")
    exit $LASTEXITCODE
}
finally { Pop-Location }
