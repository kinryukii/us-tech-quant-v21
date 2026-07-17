param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_013_factor_redundancy_cluster_audit.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT\v22_factor_redundancy_cluster_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

if (-not $Execute) {
    Write-Output "V22.013 wrapper dry run. Re-run with -Execute to create the factor redundancy cluster audit."
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
