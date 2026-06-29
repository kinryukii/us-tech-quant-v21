param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$venvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$audit = Join-Path $Root "scripts\v21\v21_085_r1_technical_feature_enrichment_audit.py"
$test = Join-Path $Root "scripts\v21\test_v21_085_r1_technical_feature_enrichment_audit.py"

python $audit --root $Root
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python $test
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "V21.085-R1 technical feature enrichment audit complete."
