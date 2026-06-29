$ErrorActionPreference = "Stop"

python scripts/v21/v21_178_r1a_daily_dram_chain_execution_mode.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$outDir = "outputs/v21/V21.178_R1A_DAILY_DRAM_CHAIN_EXECUTION_MODE"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$tmpDir = "$outDir/pytest_tmp_$stamp"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$resolvedTmp = (Resolve-Path $tmpDir).Path
$env:TEMP = $resolvedTmp
$env:TMP = $resolvedTmp

python -m pytest scripts/v21/test_v21_178_r1a_daily_dram_chain_execution_mode.py -q --basetemp "$resolvedTmp"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "$outDir/V21.178_R1A_execution_mode_readable_report.txt"
Get-Content "$outDir/V21.178_R1A_execution_mode_summary.json"
