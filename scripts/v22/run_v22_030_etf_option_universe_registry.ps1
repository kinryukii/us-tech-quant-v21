param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_030_etf_option_universe_registry.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.030_ETF_OPTION_UNIVERSE_REGISTRY\v22_etf_option_universe_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

if (-not $Execute) {
    Write-Output "V22.030 wrapper dry run. Re-run with -Execute to create the ETF option universe registry."
    Write-Output "summary_path=$SummaryPath"
    exit 0
}

Set-Location $RepoRoot
& $Python $Script --repo-root $RepoRoot
$PythonExit = $LASTEXITCODE
if ($PythonExit -ne 0) {
    exit $PythonExit
}

Write-Output "final_summary_path=$SummaryPath"
exit 0
