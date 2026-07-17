[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1d_live_market_account_bridge.py"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path -LiteralPath $Main)) { throw "R1D module not found: $Main" }
@("runtime", "logs", "runtime\moomoo_appdata") | ForEach-Object {
    New-Item -ItemType Directory -Path (Join-Path $Output $_) -Force | Out-Null
}
& $Python -m py_compile $Main
if ($LASTEXITCODE -ne 0) { throw "R1D Python compile check failed" }
& $Python -c "import pandas, pytest; print('python_dependencies=READY')"
if ($LASTEXITCODE -ne 0) { throw "Required Python dependencies are unavailable" }
$PreviousAppData = $env:appdata
$env:appdata = Join-Path $Output "runtime\moomoo_appdata"
& $Python -c "import moomoo; print('moomoo_sdk=READY')"
$env:appdata = $PreviousAppData
if ($LASTEXITCODE -ne 0) { throw "Moomoo SDK is unavailable" }
Write-Output "install_status=PASS_R1D_LOCAL_RUNTIME_READY"
Write-Output "output_dir=$Output"
Write-Output "auto_start_enabled=False"
Write-Output "live_enabled=False"

