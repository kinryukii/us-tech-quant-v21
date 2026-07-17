param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_036_r3a_moomoo_quote_context_import_and_log_permission_diagnostic_research_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DefaultOutputDir = Join-Path $RepoRoot "outputs\v22\V22.036_R3A_MOOMOO_QUOTE_CONTEXT_IMPORT_AND_LOG_PERMISSION_DIAGNOSTIC_RESEARCH_ONLY"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir -ne "") {
    $ArgsList += @("--output-dir", $OutputDir)
    $SummaryPath = Join-Path $OutputDir "v22_036_r3a_summary.json"
} else {
    $SummaryPath = Join-Path $DefaultOutputDir "v22_036_r3a_summary.json"
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
