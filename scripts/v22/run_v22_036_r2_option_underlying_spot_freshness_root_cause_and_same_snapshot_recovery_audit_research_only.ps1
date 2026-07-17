param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_036_r2_option_underlying_spot_freshness_root_cause_and_same_snapshot_recovery_audit_research_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DefaultOutputDir = Join-Path $RepoRoot "outputs\v22\V22.036_R2_OPTION_UNDERLYING_SPOT_FRESHNESS_ROOT_CAUSE_AND_SAME_SNAPSHOT_RECOVERY_AUDIT_RESEARCH_ONLY"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir -ne "") {
    $ArgsList += @("--output-dir", $OutputDir)
    $SummaryPath = Join-Path $OutputDir "v22_036_r2_summary.json"
} else {
    $SummaryPath = Join-Path $DefaultOutputDir "v22_036_r2_summary.json"
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
