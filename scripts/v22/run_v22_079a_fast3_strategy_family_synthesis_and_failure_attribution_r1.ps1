$ErrorActionPreference='Stop';$root=(Resolve-Path "$PSScriptRoot\..\..").Path;Set-Location $root
python -m py_compile scripts/v22/v22_079a_fast3_strategy_family_synthesis_and_failure_attribution_r1.py
python -m pytest scripts/v22/test_v22_079a_fast3_strategy_family_synthesis_and_failure_attribution_r1.py -q
python scripts/v22/v22_079a_fast3_strategy_family_synthesis_and_failure_attribution_r1.py
