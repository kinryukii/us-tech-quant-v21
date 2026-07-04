param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$Execute,
    [switch]$DryRun,
    [double]$MinTargetMB = 300,
    [int]$TopSize = 500,
    [switch]$AllowArchiveCompress,
    [switch]$AllowArchiveDuplicateDelete,
    [switch]$AllowQuarantineVerifiedDelete,
    [switch]$AllowCacheRetentionDelete,
    [double]$ArchiveCompressMinMB = 5,
    [int]$CacheRetentionDays = 14,
    [int]$QuarantineRetentionDays = 7
)

$ErrorActionPreference = "Stop"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.239_TOTAL_DISK_FOOTPRINT_GOVERNANCE"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_239_total_disk_footprint_governance.py"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--archive-root", $ArchiveRoot,
    "--cache-root", $CacheRoot,
    "--quarantine-root", $QuarantineRoot,
    "--output-dir", $OutputDir,
    "--min-target-mb", "$MinTargetMB",
    "--top-size", "$TopSize",
    "--archive-compress-min-mb", "$ArchiveCompressMinMB",
    "--cache-retention-days", "$CacheRetentionDays",
    "--quarantine-retention-days", "$QuarantineRetentionDays"
)

if ($Execute) { $ArgsList += "--execute" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($AllowArchiveCompress) { $ArgsList += "--allow-archive-compress" }
if ($AllowArchiveDuplicateDelete) { $ArgsList += "--allow-archive-duplicate-delete" }
if ($AllowQuarantineVerifiedDelete) { $ArgsList += "--allow-quarantine-verified-delete" }
if ($AllowCacheRetentionDelete) { $ArgsList += "--allow-cache-retention-delete" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_239_summary.json"
Write-Host "V21.239 summary: $SummaryPath"
exit $ExitCode
