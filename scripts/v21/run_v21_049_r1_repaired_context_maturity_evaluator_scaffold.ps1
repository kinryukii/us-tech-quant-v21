Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_049_r1_repaired_context_maturity_evaluator_scaffold.py"

Write-Host "STAGE_NAME=V21.049-R1_REPAIRED_CONTEXT_MATURITY_EVALUATOR_SCAFFOLD"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "MATURITY_EVALUATOR_SCAFFOLD_ONLY=TRUE"
Write-Host "SHADOW_ADOPTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_USE_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V21.049-R1 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
