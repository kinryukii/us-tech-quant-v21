param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_002_v21_active_deprecated_output_manifest.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST\v21_output_manifest_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

if (-not $Execute) {
    Write-Output "V22.002 wrapper dry run. Re-run with -Execute to create the read-only V21 output manifest."
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
