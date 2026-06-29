$ErrorActionPreference = "Stop"

python scripts/v21/v21_178_daily_dram_plan_chain_orchestrator_r1.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$outDir = "outputs/v21/V21.178_DAILY_DRAM_PLAN_CHAIN_ORCHESTRATOR_R1"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$tmpDir = "$outDir/pytest_tmp_$stamp"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$resolvedTmp = (Resolve-Path $tmpDir).Path
$env:TEMP = $resolvedTmp
$env:TMP = $resolvedTmp

python -m pytest scripts/v21/test_v21_178_daily_dram_plan_chain_orchestrator_r1.py -q --basetemp "$resolvedTmp"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "$outDir/V21.178_daily_dram_orchestrator_readable_report.txt"
Get-Content "$outDir/V21.178_daily_dram_orchestrator_summary.json"
