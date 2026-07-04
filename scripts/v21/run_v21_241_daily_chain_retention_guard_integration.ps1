param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ArchiveRoot = "D:\us-tech-quant-archive",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$QuarantineRoot = "D:\us-tech-quant-quarantine",
    [switch]$Execute,
    [switch]$DryRun,
    [switch]$AuditOnly,
    [switch]$DiscoverOnly,
    [switch]$SkipDailyChain,
    [string]$DailyChainCommand = "",
    [string]$DailyChainWrapper = "",
    [ValidateSet("disabled", "post_run_audit", "post_run_maintenance", "discover_only")]
    [string]$RetentionGuardMode = "post_run_audit",
    [string]$RetentionGuardPs1 = "",
    [string]$RetentionGuardPython = "",
    [switch]$RetentionGuardAllowMaintenance,
    [switch]$FailOnRetentionFail,
    [switch]$WarnOnRetentionWarn,
    [int]$TopSize = 300
)

$ErrorActionPreference = "Stop"
$OutputDir = Join-Path $RepoRoot "outputs\v21\V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_241_daily_chain_retention_guard_integration.py"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--archive-root", $ArchiveRoot,
    "--cache-root", $CacheRoot,
    "--quarantine-root", $QuarantineRoot,
    "--output-dir", $OutputDir,
    "--retention-guard-mode", $RetentionGuardMode,
    "--top-size", "$TopSize"
)

if ($Execute) { $ArgsList += "--execute" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($AuditOnly) { $ArgsList += "--audit-only" }
if ($DiscoverOnly) { $ArgsList += "--discover-only" }
if ($SkipDailyChain) { $ArgsList += "--skip-daily-chain" }
if ($DailyChainCommand) { $ArgsList += @("--daily-chain-command", $DailyChainCommand) }
if ($DailyChainWrapper) { $ArgsList += @("--daily-chain-wrapper", $DailyChainWrapper) }
if ($RetentionGuardPs1) { $ArgsList += @("--retention-guard-ps1", $RetentionGuardPs1) }
if ($RetentionGuardPython) { $ArgsList += @("--retention-guard-python", $RetentionGuardPython) }
if ($RetentionGuardAllowMaintenance) { $ArgsList += "--retention-guard-allow-maintenance" }
if ($FailOnRetentionFail) { $ArgsList += "--fail-on-retention-fail" }
if ($WarnOnRetentionWarn) { $ArgsList += "--warn-on-retention-warn" }

& $Python @ArgsList
$ExitCode = $LASTEXITCODE
$SummaryPath = Join-Path $OutputDir "v21_241_summary.json"
Write-Host "V21.241 summary: $SummaryPath"
exit $ExitCode
