param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.249_SHADOW_CANDIDATE_SELECTION_AND_FORWARD_TRACKING_GATE" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_249_shadow_candidate_selection_and_forward_tracking_gate.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.249 summary: $(Join-Path $out 'v21_249_summary.json')"
exit $code
