param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_033_option_chain_liquidity_and_coverage_audit.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT\v22_option_chain_liquidity_coverage_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Set-Location $RepoRoot
if ($Execute) {
    & $Python $Script --repo-root $RepoRoot --execute
} else {
    & $Python $Script --repo-root $RepoRoot
}
$PythonExit = $LASTEXITCODE
if ($PythonExit -ne 0) {
    exit $PythonExit
}

Write-Output "final_summary_path=$SummaryPath"
exit 0
