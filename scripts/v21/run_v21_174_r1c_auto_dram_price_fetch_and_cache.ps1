$ErrorActionPreference = "Stop"

python scripts/v21/v21_174_r1c_auto_dram_price_fetch_and_cache.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$outDir = "outputs/v21/V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE"
$tmpDir = "$outDir/pytest_tmp"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$resolvedTmp = (Resolve-Path $tmpDir).Path
$env:TEMP = $resolvedTmp
$env:TMP = $resolvedTmp

python -m pytest scripts/v21/test_v21_174_r1c_auto_dram_price_fetch_and_cache.py -q --basetemp "$resolvedTmp"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "$outDir/V21.174_R1C_readable_report.txt"
Get-Content "$outDir/V21.174_R1C_summary.json"
