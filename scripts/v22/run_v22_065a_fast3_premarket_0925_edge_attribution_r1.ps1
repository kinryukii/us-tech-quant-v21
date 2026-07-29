param([switch]$Execute)
$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"
if (-not $Execute) { throw "The -Execute flag is required." }
$Python=".\.venv\Scripts\python.exe"
$Script=".\scripts\v22\v22_065a_fast3_premarket_0925_edge_attribution_r1.py"
$Test=".\scripts\v22\test_v22_065a_fast3_premarket_0925_edge_attribution_r1.py"
& $Python -m py_compile $Script $Test
if ($LASTEXITCODE -ne 0) { throw "PY_COMPILE failed" }
& $Python -m pytest $Test -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "TEST failed" }
& $Python $Script --execute
if ($LASTEXITCODE -ne 0) { throw "ATTRIBUTION failed" }
