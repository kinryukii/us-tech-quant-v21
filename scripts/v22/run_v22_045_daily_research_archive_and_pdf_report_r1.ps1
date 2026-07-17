param(
    [switch]$DryRun,
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_045_daily_research_archive_and_pdf_report_r1.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.045_DAILY_RESEARCH_ARCHIVE_AND_PDF_REPORT_R1\v22_045_summary.json"

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
