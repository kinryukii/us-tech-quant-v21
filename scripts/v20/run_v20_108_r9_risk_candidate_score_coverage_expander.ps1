$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r9_risk_candidate_score_coverage_expander.py"

Push-Location $RepoRoot
try {
    python $StageScript
}
finally {
    Pop-Location
}
