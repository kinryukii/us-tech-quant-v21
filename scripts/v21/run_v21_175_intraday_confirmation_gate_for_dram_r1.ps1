$ErrorActionPreference = "Stop"

python scripts/v21/v21_175_intraday_confirmation_gate_for_dram_r1.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$outDir = "outputs/v21/V21.175_INTRADAY_CONFIRMATION_GATE_FOR_DRAM_R1"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$tmpDir = "$outDir/pytest_tmp_$stamp"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$resolvedTmp = (Resolve-Path $tmpDir).Path
$env:TEMP = $resolvedTmp
$env:TMP = $resolvedTmp

python -m pytest scripts/v21/test_v21_175_intraday_confirmation_gate_for_dram_r1.py -q --basetemp "$resolvedTmp"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "$outDir/V21.175_readable_report.txt"
Get-Content "$outDir/V21.175_summary.json"
