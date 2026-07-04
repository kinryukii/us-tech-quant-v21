param(
  [string]$RepoRoot = "D:\us-tech-quant",
  [string]$OutputDir = "",
  [string]$CanonicalQfqPath = "",
  [int]$SeedCount = 20,
  [int]$TrialsPerSeed = 100
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$out = if ($OutputDir) { $OutputDir } else { Join-Path $RepoRoot "outputs\v21\V21.254_R1_MOOMOO_PRE0616_HISTORICAL_RANDOM_ASOF_BACKTEST" }
New-Item -ItemType Directory -Force -Path $out | Out-Null
$argsList = @("scripts\v21\v21_254_r1_moomoo_pre0616_historical_random_asof_backtest.py", "--repo-root", $RepoRoot, "--output-dir", $out, "--seed-count", "$SeedCount", "--trials-per-seed", "$TrialsPerSeed")
if ($CanonicalQfqPath) { $argsList += @("--canonical-qfq-path", $CanonicalQfqPath) }
& $python @argsList
$code = $LASTEXITCODE
Write-Host "V21.254_R1 summary: $(Join-Path $out 'v21_254_r1_summary.json')"
exit $code
