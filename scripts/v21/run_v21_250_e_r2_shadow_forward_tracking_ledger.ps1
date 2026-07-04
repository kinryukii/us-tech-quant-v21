param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_250_e_r2_shadow_forward_tracking_ledger.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.250 summary: $(Join-Path $out 'v21_250_summary.json')"
exit $code
