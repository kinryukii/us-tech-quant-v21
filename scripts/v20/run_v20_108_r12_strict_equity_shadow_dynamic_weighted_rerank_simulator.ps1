$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r12_strict_equity_shadow_dynamic_weighted_rerank_simulator.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
