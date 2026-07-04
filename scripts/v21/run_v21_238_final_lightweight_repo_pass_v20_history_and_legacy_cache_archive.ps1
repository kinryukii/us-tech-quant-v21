param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$Execute,
    [switch]$DryRun,
    [double]$MinTargetMB = 150,
    [int]$TopSize = 300,
    [switch]$AllowV21229ExtraInventoryArchive,
    [switch]$AllowV20HistoryArchive,
    [switch]$AllowLegacyStateCacheArchive,
    [double]$LegacyCacheMinMB = 1,
    [double]$V20HistoryMinMB = 3
)

$ErrorActionPreference = "Stop"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.238_FINAL_LIGHTWEIGHT_REPO_PASS_V20_HISTORY_AND_LEGACY_CACHE_ARCHIVE"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_238_final_lightweight_repo_pass_v20_history_and_legacy_cache_archive.py"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--archive-root", $ArchiveRoot,
    "--cache-root", $CacheRoot,
    "--quarantine-root", $QuarantineRoot,
    "--output-dir", $OutputDir,
    "--min-target-mb", "$MinTargetMB",
    "--top-size", "$TopSize",
    "--legacy-cache-min-mb", "$LegacyCacheMinMB",
    "--v20-history-min-mb", "$V20HistoryMinMB"
)

if ($Execute) { $ArgsList += "--execute" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($AllowV21229ExtraInventoryArchive) { $ArgsList += "--allow-v21-229-extra-inventory-archive" }
if ($AllowV20HistoryArchive) { $ArgsList += "--allow-v20-history-archive" }
if ($AllowLegacyStateCacheArchive) { $ArgsList += "--allow-legacy-state-cache-archive" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_238_summary.json"
Write-Host "V21.238 summary: $SummaryPath"
exit $ExitCode
