param(
    [switch]$Execute,
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_032_moomoo_etf_option_chain_snapshot.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT\v22_moomoo_etf_option_chain_snapshot_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Set-Location $RepoRoot
if ($Execute) {
    & $Python $Script --repo-root $RepoRoot --execute --host $MoomooHost --port $Port
} else {
    & $Python $Script --repo-root $RepoRoot --host $MoomooHost --port $Port
}
$PythonExit = $LASTEXITCODE
if ($PythonExit -ne 0) {
    exit $PythonExit
}

Write-Output "final_summary_path=$SummaryPath"
exit 0
