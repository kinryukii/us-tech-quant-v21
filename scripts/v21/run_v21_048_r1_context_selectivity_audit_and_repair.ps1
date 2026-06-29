Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_048_r1_context_selectivity_audit_and_repair.py"

Write-Host "STAGE_NAME=V21.048-R1_CONTEXT_SELECTIVITY_AUDIT_AND_REPAIR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_USE_ALLOWED=FALSE"
Write-Host "SHADOW_ADOPTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V21.048-R1 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
