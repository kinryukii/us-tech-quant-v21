param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_034_r1_option_iv_greeks_oi_missing_source_and_alternative_data_strategy_audit.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DefaultOutputDir = Join-Path $RepoRoot "outputs\v22\V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir -ne "") {
    $ArgsList += @("--output-dir", $OutputDir)
    $SummaryPath = Join-Path $OutputDir "v22_034_r1_summary.json"
} else {
    $SummaryPath = Join-Path $DefaultOutputDir "v22_034_r1_summary.json"
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
