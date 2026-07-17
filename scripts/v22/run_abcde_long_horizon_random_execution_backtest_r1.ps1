param(
    [string]$Python = "",
    [string]$OutputDir = "outputs/v22/ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_R1"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $RepoRoot ".venv/Scripts/python.exe"
}
& $Python (Join-Path $PSScriptRoot "abcde_long_horizon_random_execution_backtest_r1.py") --repo-root $RepoRoot --output-dir $OutputDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

