param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$Execute,
    [switch]$DryRun,
    [double]$MinTargetMB = 500,
    [int]$TopSize = 300,
    [switch]$AllowTransientDelete,
    [switch]$AllowVerifiedDuplicateDelete,
    [switch]$AllowArchiveMove
)

$ErrorActionPreference = "Stop"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.236_FAST_REPO_SLIM_STAGE2_TRANSIENT_DUPLICATE_AND_HISTORICAL_OUTPUT_PURGE"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_236_fast_repo_slim_stage2_transient_duplicate_and_historical_output_purge.py"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--archive-root", $ArchiveRoot,
    "--cache-root", $CacheRoot,
    "--quarantine-root", $QuarantineRoot,
    "--output-dir", $OutputDir,
    "--min-target-mb", "$MinTargetMB",
    "--top-size", "$TopSize"
)

if ($Execute) { $ArgsList += "--execute" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($AllowTransientDelete) { $ArgsList += "--allow-transient-delete" }
if ($AllowVerifiedDuplicateDelete) { $ArgsList += "--allow-verified-duplicate-delete" }
if ($AllowArchiveMove) { $ArgsList += "--allow-archive-move" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_236_summary.json"
Write-Host "V21.236 summary: $SummaryPath"
exit $ExitCode
