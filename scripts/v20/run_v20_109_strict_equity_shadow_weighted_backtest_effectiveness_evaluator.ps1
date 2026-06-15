$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_109_strict_equity_shadow_weighted_backtest_effectiveness_evaluator.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
