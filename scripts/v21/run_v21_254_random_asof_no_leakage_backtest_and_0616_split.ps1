param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = "",
  [int]$SeedCount = 20,
  [int]$TrialsPerSeed = 100
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.254_RANDOM_ASOF_NO_LEAKAGE_BACKTEST_AND_0616_SPLIT" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
& $python "scripts\v21\v21_254_random_asof_no_leakage_backtest_and_0616_split.py" --repo-root $RepoRoot --output-dir $out --seed-count $SeedCount --trials-per-seed $TrialsPerSeed
$code = $LASTEXITCODE
Write-Host "V21.254 summary: $(Join-Path $out 'v21_254_summary.json')"
exit $code
