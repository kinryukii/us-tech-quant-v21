param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.248_R2_MOOMOO_ONLY_CHAIN_TEST_AND_EVENT_DISABLE_GATE" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_248_r2_moomoo_only_chain_test_and_event_disable_gate.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.248_R2 summary: $(Join-Path $out 'v21_248_r2_summary.json')"
exit $code
