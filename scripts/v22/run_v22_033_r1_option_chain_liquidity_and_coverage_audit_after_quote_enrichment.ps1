param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_033_r1_option_chain_liquidity_and_coverage_audit_after_quote_enrichment.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT\v22_option_chain_post_enrichment_summary.json"

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
