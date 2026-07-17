param(
    [switch]$DryRun,
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_046_daily_research_full_cycle_controller_r1.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.046_DAILY_RESEARCH_FULL_CYCLE_CONTROLLER_R1\v22_046_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

if ($DryRun -and $Execute) {
    throw "Use either -DryRun or -Execute, not both."
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($Execute) {
    $ArgsList += "--execute"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

Write-Output "final_summary_path=$SummaryPath"
Write-Output "summary_exists=$(Test-Path $SummaryPath)"
exit $PythonExit
