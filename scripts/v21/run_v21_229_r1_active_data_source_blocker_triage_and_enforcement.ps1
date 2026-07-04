param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$V21229OutputDir = "",
    [switch]$DryRunPatches
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.229_R1_ACTIVE_DATA_SOURCE_BLOCKER_TRIAGE_AND_ENFORCEMENT"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_229_r1_active_data_source_blocker_triage_and_enforcement.py"),
    "--repo-root", $Root,
    "--output-dir", $OutputDir
)
if ($V21229OutputDir -ne "") { $ArgsList += @("--v21-229-output-dir", $V21229OutputDir) }
if ($DryRunPatches) { $ArgsList += "--dry-run-patches" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_229_r1_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
