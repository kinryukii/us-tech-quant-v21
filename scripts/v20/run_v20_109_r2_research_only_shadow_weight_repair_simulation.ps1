$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_109_r2_research_only_shadow_weight_repair_simulation.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
