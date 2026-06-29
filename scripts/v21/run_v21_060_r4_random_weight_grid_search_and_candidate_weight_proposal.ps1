Set-StrictMode -Version Latest
$ErrorActionPreference="Stop"
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot=Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript=Join-Path $ScriptDir "v21_060_r4_random_weight_grid_search_and_candidate_weight_proposal.py"
$OutputDir=Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\random_backtests\weight_search"
$SummaryPath=Join-Path $OutputDir "V21_060_R4_SUMMARY.json"
Write-Host "STAGE_ID=V21.060-R4"; Write-Host "RESEARCH_ONLY=TRUE"; Write-Host "A0_REPLAYED=FALSE"; Write-Host "D_FORWARD_APPEND_ALLOWED=FALSE"
Push-Location $RepoRoot
try {
 New-Item -ItemType Directory -Force -Path $OutputDir|Out-Null
 python $StageScript; $Code=$LASTEXITCODE
 if(-not(Test-Path $SummaryPath)){throw "V21.060-R4 summary was not created."}
 $S=Get-Content $SummaryPath -Raw|ConvertFrom-Json
 Write-Host "FINAL_STATUS=$($S.FINAL_STATUS)"; Write-Host "DECISION=$($S.DECISION)"
 if($S.FINAL_STATUS -like "FAIL_*"){exit 1}; if($Code-ne 0){exit $Code}; exit 0
} finally {Pop-Location}
