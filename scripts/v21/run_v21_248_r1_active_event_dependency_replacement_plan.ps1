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
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.248_R1_ACTIVE_EVENT_DEPENDENCY_REPLACEMENT_PLAN" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_248_r1_active_event_dependency_replacement_plan.py" --repo-root $RepoRoot --output-dir $out
$code = $LASTEXITCODE
Write-Host "V21.248_R1 summary: $(Join-Path $out 'v21_248_r1_summary.json')"
exit $code
