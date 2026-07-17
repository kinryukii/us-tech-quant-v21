param(
    [switch]$Execute,
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441,
    [int]$MaxContracts = 2000,
    [int]$BatchSize = 200,
    [string]$UnderlyingFilter = "",
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_032_r1_option_quote_enrichment_from_moomoo_read_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY\v22_option_quote_enrichment_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot, "--host", $MoomooHost, "--port", $Port, "--max-contracts", $MaxContracts, "--batch-size", $BatchSize)
if ($UnderlyingFilter -ne "") {
    $ArgsList += @("--underlying-filter", $UnderlyingFilter)
}
if ($Execute) {
    $ArgsList += "--execute"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE
if ($PythonExit -ne 0) {
    exit $PythonExit
}

Write-Output "final_summary_path=$SummaryPath"
exit 0
