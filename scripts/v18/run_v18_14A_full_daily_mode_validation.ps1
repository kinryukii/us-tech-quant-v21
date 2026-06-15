$ErrorActionPreference = "Stop"

$Root = "D:\us-tech-quant"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Validator = Join-Path $Root "scripts\v18\v18_14A_full_daily_mode_validation.py"

if (-not (Test-Path $Python)) {
    throw "Missing Python executable: $Python"
}
if (-not (Test-Path $Validator)) {
    throw "Missing Python validator: $Validator"
}

& $Python $Validator --root $Root
exit $LASTEXITCODE
