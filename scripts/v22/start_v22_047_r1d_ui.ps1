[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [switch]$Foreground)
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1d_live_market_account_bridge.py"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
$Runtime = Join-Path $Output "runtime"
$Logs = Join-Path $Output "logs"
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
New-Item -ItemType Directory -Path $Logs -Force | Out-Null
if ($Foreground) { & $Python $Main ui --repo-root $RepoRoot; exit $LASTEXITCODE }
$UiInfo = New-Object System.Diagnostics.ProcessStartInfo
$UiInfo.FileName = $Python
$UiInfo.Arguments = "`"$Main`" ui --repo-root `"$RepoRoot`""
$UiInfo.WorkingDirectory = $RepoRoot
$UiInfo.UseShellExecute = $true
$UiInfo.WindowStyle = "Hidden"
$Ui = [System.Diagnostics.Process]::Start($UiInfo)
Set-Content -LiteralPath (Join-Path $Runtime "ui.pid") -Value $Ui.Id -Encoding ascii
Write-Output "ui_status=PASS_R1D_UI_STARTED"
Write-Output "ui_url=http://127.0.0.1:8765"
Write-Output "engine_dependency=False"
