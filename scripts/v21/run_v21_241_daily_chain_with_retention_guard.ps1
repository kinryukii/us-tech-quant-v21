param(
    [switch]$Execute,
    [switch]$DryRun,
    [switch]$SkipDailyChain,
    [string]$DailyChainCommand = "",
    [string]$DailyChainWrapper = "",
    [ValidateSet("disabled", "post_run_audit", "post_run_maintenance", "discover_only")]
    [string]$RetentionGuardMode = "post_run_audit",
    [switch]$RetentionGuardAllowMaintenance,
    [switch]$FailOnRetentionFail,
    [switch]$WarnOnRetentionWarn,
    [int]$TopSize = 300
)

$ErrorActionPreference = "Stop"
$RepoRoot = "D:\us-tech-quant"
Set-Location $RepoRoot
$Runner = Join-Path $RepoRoot "scripts\v21\run_v21_241_daily_chain_retention_guard_integration.ps1"

$ArgsList = @(
    "-RetentionGuardMode", $RetentionGuardMode,
    "-TopSize", "$TopSize"
)

if ($Execute) { $ArgsList += "-Execute" }
if ($DryRun) { $ArgsList += "-DryRun" }
if ($SkipDailyChain) { $ArgsList += "-SkipDailyChain" }
if ($DailyChainCommand) { $ArgsList += @("-DailyChainCommand", $DailyChainCommand) }
if ($DailyChainWrapper) { $ArgsList += @("-DailyChainWrapper", $DailyChainWrapper) }
if ($RetentionGuardAllowMaintenance) { $ArgsList += "-RetentionGuardAllowMaintenance" }
if ($FailOnRetentionFail) { $ArgsList += "-FailOnRetentionFail" }
if ($WarnOnRetentionWarn) { $ArgsList += "-WarnOnRetentionWarn" }

& powershell -ExecutionPolicy Bypass -File $Runner @ArgsList
exit $LASTEXITCODE
