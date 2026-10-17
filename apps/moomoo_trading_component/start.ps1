param([int]$Port = 8766, [switch]$ActivateStrategies, [switch]$WithMoomooBest, [switch]$Offline, [switch]$ManualDataUpdates,
      [ValidateRange(0,180)][int]$ExecutionDelayMinutes = 25,
      [ValidateScript({ ($_ -ge 1 -and $_ -le 600) -or $_ -eq 1500 })][int]$ExecutionWindowSeconds = 1500,
      [ValidateRange(1,3600)][int]$BrokerExecutionWindowSeconds = 1500)
$ErrorActionPreference = 'Stop'
if ($ExecutionDelayMinutes -ne 25) {
    if (-not $PSBoundParameters.ContainsKey('ExecutionWindowSeconds')) { $ExecutionWindowSeconds = 600 }
    if (-not $PSBoundParameters.ContainsKey('BrokerExecutionWindowSeconds')) { $BrokerExecutionWindowSeconds = 600 }
}
if ($ExecutionWindowSeconds -eq 1500 -and $ExecutionDelayMinutes -ne 25) {
    throw '纸面1500秒窗口仅允许开盘后25分钟延迟。'
}
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
    if ($ManualDataUpdates) { $componentArgs += '--manual-data-updates' }
    if ($ActivateStrategies) { $componentArgs += '--activate-applied' }
} elseif ($ActivateStrategies -or $WithMoomooBest -or $ManualDataUpdates) {
    throw 'Offline不能启用三策略或券商模拟自动执行。'
} else {
    $componentArgs += @('--data-dir', (Join-Path $componentState 'manual'))
}
& $componentPython @componentArgs
