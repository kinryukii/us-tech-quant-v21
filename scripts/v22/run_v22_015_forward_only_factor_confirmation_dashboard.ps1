param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_015_forward_only_factor_confirmation_dashboard.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD\v22_forward_only_factor_confirmation_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

if (-not $Execute) {
    Write-Output "V22.015 wrapper dry run. Re-run with -Execute to create the forward-only factor confirmation dashboard."
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
