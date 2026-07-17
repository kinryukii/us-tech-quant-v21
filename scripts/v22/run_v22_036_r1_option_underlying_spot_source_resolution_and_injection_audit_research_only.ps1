param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_036_r1_option_underlying_spot_source_resolution_and_injection_audit_research_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DefaultOutputDir = Join-Path $RepoRoot "outputs\v22\V22.036_R1_OPTION_UNDERLYING_SPOT_SOURCE_RESOLUTION_AND_INJECTION_AUDIT_RESEARCH_ONLY"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir -ne "") {
    $ArgsList += @("--output-dir", $OutputDir)
    $SummaryPath = Join-Path $OutputDir "v22_036_r1_summary.json"
} else {
    $SummaryPath = Join-Path $DefaultOutputDir "v22_036_r1_summary.json"
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
