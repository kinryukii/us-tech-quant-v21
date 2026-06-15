$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_109_r3_research_only_simulated_weight_strict_equity_rerank_runner.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
