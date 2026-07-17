
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$StartDate = "2022-01-01",
    [string]$EndDate = "2026-07-13",
    [string]$TopK = "5,10,20,50",
    [int]$LagDays = 1,
    [double]$CostBps = 5.0,
    [string]$PanelPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $RepoRoot "scripts\v22\abcde_local_effectiveness_backtest_r1.py"

if (-not (Test-Path $PythonExe)) {
    throw "Python venv not found: $PythonExe"
}
if (-not (Test-Path $ScriptPath)) {
    throw "Backtest script not found: $ScriptPath"
}

Write-Host "=== INSTALL/CHECK DEPENDENCIES ==="
& $PythonExe -m pip install duckdb pandas numpy pyarrow
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

$ArgsList = @(
    $ScriptPath,
    "--repo-root", $RepoRoot,
    "--start-date", $StartDate,
    "--end-date", $EndDate,
    "--topk", $TopK,
    "--lag-days", "$LagDays",
    "--cost-bps", "$CostBps"
)

if ($PanelPath -ne "") {
    $ArgsList += @("--panel-path", $PanelPath)
}

Write-Host ""
Write-Host "=== RUN LOCAL ABCDE BACKTEST ==="
& $PythonExe @ArgsList

if ($LASTEXITCODE -ne 0) {
    throw "Backtest failed with exit code $LASTEXITCODE"
}
