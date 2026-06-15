$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r13_strict_equity_shadow_rerank_delta_and_effectiveness_readiness_auditor.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
