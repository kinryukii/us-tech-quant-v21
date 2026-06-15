$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_109_r1_shadow_underperformance_decomposition_and_weight_repair_plan.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
