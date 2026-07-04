param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.253_COEFFICIENT_GUIDED_E_R3_WEIGHT_RECALIBRATION" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_253_coefficient_guided_e_r3_weight_recalibration.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.253 summary: $(Join-Path $out 'v21_253_summary.json')"
exit $code
