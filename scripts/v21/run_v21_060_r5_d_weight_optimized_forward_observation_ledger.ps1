Set-StrictMode -Version Latest
$ErrorActionPreference="Stop"
$D=Split-Path -Parent $MyInvocation.MyCommand.Path;$R=Resolve-Path(Join-Path $D "..\..");$S=Join-Path $D "v21_060_r5_d_weight_optimized_forward_observation_ledger.py";$O=Join-Path $R "outputs\v21\experiments\momentum_dynamic\d_weight_optimized";$J=Join-Path $O "V21_060_R5_SUMMARY.json"
Write-Host "STAGE_ID=V21.060-R5";Write-Host "RESEARCH_ONLY=TRUE";Write-Host "D_VARIANT_OFFICIAL=FALSE"
Push-Location $R
try{New-Item -ItemType Directory -Force -Path $O|Out-Null;python $S;$C=$LASTEXITCODE;if(-not(Test-Path $J)){throw "V21.060-R5 summary missing"};$X=Get-Content $J -Raw|ConvertFrom-Json;Write-Host "FINAL_STATUS=$($X.FINAL_STATUS)";Write-Host "DECISION=$($X.DECISION)";if($X.FINAL_STATUS-like"FAIL_*"){exit 1};if($C-ne 0){exit $C};exit 0}finally{Pop-Location}
