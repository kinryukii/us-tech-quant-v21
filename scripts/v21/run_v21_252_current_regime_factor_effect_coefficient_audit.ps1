param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.252_CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_252_current_regime_factor_effect_coefficient_audit.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.252 summary: $(Join-Path $out 'v21_252_summary.json')"
exit $code
