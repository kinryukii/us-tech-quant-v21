$ErrorActionPreference = "Stop"

python scripts/v21/v21_177_r1a_staleness_semantic_repair.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$outDir = "outputs/v21/V21.177_R1A_STALENESS_SEMANTIC_REPAIR"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$tmpDir = "$outDir/pytest_tmp_$stamp"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$resolvedTmp = (Resolve-Path $tmpDir).Path
$env:TEMP = $resolvedTmp
$env:TMP = $resolvedTmp

python -m pytest scripts/v21/test_v21_177_r1a_staleness_semantic_repair.py -q --basetemp "$resolvedTmp"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "$outDir/V21.177_R1A_readable_report.txt"
Get-Content "$outDir/V21.177_R1A_summary.json"
