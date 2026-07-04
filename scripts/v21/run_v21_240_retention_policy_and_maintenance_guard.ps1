param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$Execute,
    [switch]$DryRun,
    [switch]$AuditOnly,
    [int]$TopSize = 500,
    [double]$RepoWarningMB = 800,
    [double]$RepoHardMB = 1000,
    [double]$TotalWarningMB = 2000,
    [double]$TotalHardMB = 2500,
    [double]$ArchiveWarningMB = 800,
    [double]$ArchiveHardMB = 1200,
    [double]$CacheWarningMB = 700,
    [double]$CacheHardMB = 1000,
    [double]$QuarantineWarningMB = 100,
    [double]$QuarantineHardMB = 300,
    [switch]$AllowArchiveCompress,
    [switch]$AllowArchiveDuplicateDelete,
    [switch]$AllowQuarantineVerifiedDelete,
    [switch]$AllowCacheRetentionDelete,
    [double]$ArchiveCompressMinMB = 5,
    [double]$RepoLargeFileWarningMB = 10,
    [double]$RepoLargeFileHardMB = 50,
    [int]$CacheRetentionDays = 14,
    [int]$QuarantineRetentionDays = 7,
    [double]$RecentFileProtectionHours = 24
)

$ErrorActionPreference = "Stop"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.240_RETENTION_POLICY_AND_MAINTENANCE_GUARD"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_240_retention_policy_and_maintenance_guard.py"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--archive-root", $ArchiveRoot,
    "--cache-root", $CacheRoot,
    "--quarantine-root", $QuarantineRoot,
    "--output-dir", $OutputDir,
    "--top-size", "$TopSize",
    "--repo-warning-mb", "$RepoWarningMB",
    "--repo-hard-mb", "$RepoHardMB",
    "--total-warning-mb", "$TotalWarningMB",
    "--total-hard-mb", "$TotalHardMB",
    "--archive-warning-mb", "$ArchiveWarningMB",
    "--archive-hard-mb", "$ArchiveHardMB",
    "--cache-warning-mb", "$CacheWarningMB",
    "--cache-hard-mb", "$CacheHardMB",
    "--quarantine-warning-mb", "$QuarantineWarningMB",
    "--quarantine-hard-mb", "$QuarantineHardMB",
    "--archive-compress-min-mb", "$ArchiveCompressMinMB",
    "--repo-large-file-warning-mb", "$RepoLargeFileWarningMB",
    "--repo-large-file-hard-mb", "$RepoLargeFileHardMB",
    "--cache-retention-days", "$CacheRetentionDays",
    "--quarantine-retention-days", "$QuarantineRetentionDays",
    "--recent-file-protection-hours", "$RecentFileProtectionHours"
)

if ($Execute) { $ArgsList += "--execute" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($AuditOnly) { $ArgsList += "--audit-only" }
if ($AllowArchiveCompress) { $ArgsList += "--allow-archive-compress" }
if ($AllowArchiveDuplicateDelete) { $ArgsList += "--allow-archive-duplicate-delete" }
if ($AllowQuarantineVerifiedDelete) { $ArgsList += "--allow-quarantine-verified-delete" }
if ($AllowCacheRetentionDelete) { $ArgsList += "--allow-cache-retention-delete" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_240_summary.json"
Write-Host "V21.240 summary: $SummaryPath"
exit $ExitCode
