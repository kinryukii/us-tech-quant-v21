param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [string]$Underlying = "QQQ"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_036_r3_option_read_only_underlying_quote_snapshot_refresh_and_injection_research_only.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DefaultOutputDir = Join-Path $RepoRoot "outputs\v22\V22.036_R3_OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$ArgsList = @($Script, "--repo-root", $RepoRoot, "--underlying", $Underlying)
if ($OutputDir -ne "") {
    $ArgsList += @("--output-dir", $OutputDir)
    $SummaryPath = Join-Path $OutputDir "v22_036_r3_summary.json"
} else {
    $SummaryPath = Join-Path $DefaultOutputDir "v22_036_r3_summary.json"
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
