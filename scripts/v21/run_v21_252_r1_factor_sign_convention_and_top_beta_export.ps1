param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.252_R1_FACTOR_SIGN_CONVENTION_AND_TOP_BETA_EXPORT" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_252_r1_factor_sign_convention_and_top_beta_export.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.252_R1 summary: $(Join-Path $out 'v21_252_r1_summary.json')"
exit $code
