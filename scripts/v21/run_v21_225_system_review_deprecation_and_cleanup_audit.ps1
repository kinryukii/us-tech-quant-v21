param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$V21224OutputDir = "",
    [switch]$IncludeV20
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.225_SYSTEM_REVIEW_DEPRECATION_AND_CLEANUP_AUDIT"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_225_system_review_deprecation_and_cleanup_audit.py"),
    "--repo-root",
    $Root,
    "--output-dir",
    $OutputDir
)

if ($V21224OutputDir -ne "") {
    $ArgsList += @("--v21-224-output-dir", $V21224OutputDir)
}
if ($IncludeV20) {
    $ArgsList += "--include-v20"
}

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_225_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
