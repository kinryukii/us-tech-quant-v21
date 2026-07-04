param(
    [string]$InputPath = "",
    [string]$OutputDir = "",
    [switch]$StagingMode,
    [switch]$DryRun,
    [switch]$ProductionWriteAllowed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Write-Host "PATCH_VERSION: V20.8"
Write-Host "PATCH_NAME: NORMALIZED_RESEARCH_DATASET_CONSTRUCTION"
Write-Host "REPORTING_ONLY: FALSE"
Write-Host "RESEARCH_DATASET_CONSTRUCTION: TRUE"
Write-Host "CREATES_NORMALIZED_ROWS: TRUE"
Write-Host "CREATES_FACTOR_EVIDENCE: FALSE"
Write-Host "CREATES_BACKTESTS: FALSE"
Write-Host "CREATES_DYNAMIC_WEIGHTING_ROWS: FALSE"
Write-Host "CREATES_TRADING_SIGNALS: FALSE"
Write-Host "CREATES_OFFICIAL_RECOMMENDATIONS: FALSE"
Write-Host "BROKER_API_USED: FALSE"
Write-Host "ORDER_EXECUTION_USED: FALSE"
Write-Host "V21_OUTPUTS_CREATED: FALSE"
Write-Host "V19_21_OUTPUTS_CREATED: FALSE"

$ArgsList = @("scripts/v20/v20_8_normalized_research_dataset_construction.py")
if ($InputPath) { $ArgsList += @("--input-path", $InputPath) }
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($StagingMode) { $ArgsList += "--staging-mode" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($ProductionWriteAllowed) { $ArgsList += "--production-write-allowed" }

Push-Location $RepoRoot
try {
    python @ArgsList
}
finally { Pop-Location }
