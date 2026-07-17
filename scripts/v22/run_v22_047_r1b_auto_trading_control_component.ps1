[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$MarketSnapshot,
    [string]$AccountSnapshot,
    [string]$StrategyPlugin,
    [switch]$Execute,
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v22\v22_047_r1b_auto_trading_control_component.py"
$Config = Join-Path $RepoRoot "config\v22_047_r1b_auto_trading_control.json"

if (-not (Test-Path $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path $Script)) { throw "Component script not found: $Script" }
if (-not $MarketSnapshot) { throw "-MarketSnapshot is required" }
if (-not $AccountSnapshot) { throw "-AccountSnapshot is required" }

$argsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--config-path", $Config,
    "--market-snapshot", $MarketSnapshot,
    "--account-snapshot", $AccountSnapshot
)
if ($StrategyPlugin) { $argsList += @("--strategy-plugin", $StrategyPlugin) }
if ($OutputDir) { $argsList += @("--output-dir", $OutputDir) }
if ($Execute) { $argsList += "--execute" }

& $Python @argsList
exit $LASTEXITCODE
