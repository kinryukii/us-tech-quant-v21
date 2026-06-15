param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r6a_r1_fundamental_source_contract_and_import_gate.py"

Write-Host "STAGE_NAME=V20.108-R6A-R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "IS_OFFICIAL_RANKING=FALSE"
Write-Host "IS_OFFICIAL_WEIGHT=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.108-R6A-R1 fundamental source contract and import gate failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE_CREATED") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R6A_R1_FUNDAMENTAL_IMPORT_GATE_WAITING_FOR_LOCAL_INPUT") -or
        ($Output -contains "PASS_V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_VALIDATED")
    if (-not $Passed) {
        throw "V20.108-R6A-R1 import gate did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
