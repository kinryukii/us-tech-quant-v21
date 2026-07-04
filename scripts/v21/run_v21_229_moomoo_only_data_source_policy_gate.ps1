param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$V21228OutputDir = "",
    [switch]$IncludeV20,
    [switch]$FailOnActiveBlockers
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$OutputDir = Join-Path $Root "outputs\v21\V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_229_moomoo_only_data_source_policy_gate.py"),
    "--repo-root", $Root,
    "--output-dir", $OutputDir
)
if ($V21228OutputDir -ne "") { $ArgsList += @("--v21-228-output-dir", $V21228OutputDir) }
if ($IncludeV20) { $ArgsList += "--include-v20" }
if ($FailOnActiveBlockers) { $ArgsList += "--fail-on-active-blockers" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_229_summary.json"
Write-Host "final_summary_path=$SummaryPath"
exit $ExitCode
