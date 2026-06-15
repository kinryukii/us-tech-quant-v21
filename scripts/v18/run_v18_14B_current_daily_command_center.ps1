param(
    [switch]$UseYFinance,
    [switch]$FullDaily,
    [switch]$ReadCenterRefreshOnly,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$Root = "D:\us-tech-quant"
$Current = Join-Path $Root "scripts\v18\run_v18_current_daily_command_center.ps1"
if (-not (Test-Path $Current)) {
    throw "Missing current daily command center wrapper: $Current"
}

$Args = @()
if ($UseYFinance) { $Args += "-UseYFinance" }
if ($FullDaily) { $Args += "-FullDaily" }
if ($ReadCenterRefreshOnly) { $Args += "-ReadCenterRefreshOnly" }
if ($ValidateOnly) { $Args += "-ValidateOnly" }

& powershell -NoProfile -ExecutionPolicy Bypass -File $Current @Args
exit $LASTEXITCODE
