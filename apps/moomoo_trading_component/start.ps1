param([int]$Port = 8766, [switch]$ActivateStrategies, [switch]$WithMoomooBest, [switch]$Offline,
      [ValidateRange(0,180)][int]$ExecutionDelayMinutes = 0,
      [ValidateRange(1,600)][int]$ExecutionWindowSeconds = 600,
      [ValidateRange(1,3600)][int]$BrokerExecutionWindowSeconds = 3600)
$ErrorActionPreference = 'Stop'
$componentRepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $componentRepoRoot 'scripts/common/storage_paths.ps1')
$componentPaths = Get-UstqStoragePaths -RepoRoot $componentRepoRoot
$componentPython = $componentPaths.python_exe
if (-not (Test-Path -LiteralPath $componentPython)) { throw '项目规范 Python 环境不可用。' }
Set-Location -LiteralPath $componentRepoRoot
$componentState = Join-Path $componentPaths.daily_root 'moomoo_trading_component'
$componentArgs = @('-X', 'utf8', '-B', '-m', 'apps.moomoo_trading_component.moomoo_component', '--port', "$Port", '--repo-root', $componentRepoRoot)
if (-not $Offline) {
    $componentArgs += @('--applied-strategies', '--data-dir', (Join-Path $componentState 'applied'))
    $componentArgs += @('--execution-delay-minutes', "$ExecutionDelayMinutes")
    $componentArgs += @('--execution-window-seconds', "$ExecutionWindowSeconds", '--qualified-quotes-only')
    if ($WithMoomooBest) { $componentArgs += @('--moomoo-best', '--broker-execution-window-seconds', "$BrokerExecutionWindowSeconds") }
    if ($ActivateStrategies) { $componentArgs += '--activate-applied' }
} elseif ($ActivateStrategies -or $WithMoomooBest) {
    throw 'Offline不能启用三策略或券商模拟自动执行。'
} else {
    $componentArgs += @('--data-dir', (Join-Path $componentState 'manual'))
}
& $componentPython @componentArgs
