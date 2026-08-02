$ErrorActionPreference='Stop'
Set-Location (Resolve-Path "$PSScriptRoot\..\..").Path
$out='D:\us-tech-quant-results\v22\V22.080B_FAST3_ONE_PERCENT_MOVE_PREDICTABILITY_PREFLIGHT_R1'
python -m py_compile scripts/v22/v22_080b_fast3_one_percent_move_predictability_preflight_r1.py
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
python -m pytest scripts/v22/test_v22_080b_fast3_one_percent_move_predictability_preflight_r1.py -q
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
if(Test-Path $out){Remove-Item -LiteralPath $out -Recurse -Force}
python scripts/v22/v22_080b_fast3_one_percent_move_predictability_preflight_r1.py --output-dir $out
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
$s=Get-Content "$out\v22_080b_summary.json" -Raw|ConvertFrom-Json
"FINAL_STATUS=$($s.final_status)";"FINAL_DECISION=$($s.final_decision)";"SUMMARY_PATH=$out\v22_080b_summary.json"
