param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$Execute,
    [switch]$DryRun,
    [double]$MinTargetMB = 400,
    [int]$TopSize = 300,
    [switch]$AllowRecentAuditCsvArchive,
    [switch]$AllowCanonicalBackupPrune,
    [int]$CanonicalBackupRetainCount = 2
)

$ErrorActionPreference = "Stop"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.237_RECENT_BLOCKER_REVIEW_AND_COMPRESSED_ARCHIVE_MOVE"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_237_recent_blocker_review_and_compressed_archive_move.py"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--archive-root", $ArchiveRoot,
    "--cache-root", $CacheRoot,
    "--quarantine-root", $QuarantineRoot,
    "--output-dir", $OutputDir,
    "--min-target-mb", "$MinTargetMB",
    "--top-size", "$TopSize",
    "--canonical-backup-retain-count", "$CanonicalBackupRetainCount"
)

if ($Execute) { $ArgsList += "--execute" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($AllowRecentAuditCsvArchive) { $ArgsList += "--allow-recent-audit-csv-archive" }
if ($AllowCanonicalBackupPrune) { $ArgsList += "--allow-canonical-backup-prune" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_237_summary.json"
Write-Host "V21.237 summary: $SummaryPath"
exit $ExitCode
