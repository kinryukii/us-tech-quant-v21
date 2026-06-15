param(
    [string]$Root = "D:\us-tech-quant",
    [Alias("UseYFinance")]
    [switch]$UseYFinanceForFullUniverseRecompute,
    [switch]$ApplyFullUniverseRecomputedCandidates
)

$ErrorActionPreference = "Stop"

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Script = Join-Path $Root "scripts\v18\v18_35D_full_universe_factor_technical_recompute.py"
$ReadFirst = Join-Path $Root "outputs\v18\ops\V18_35D_READ_FIRST.txt"

Write-Host "=== START V18.35D FULL UNIVERSE FACTOR TECHNICAL RECOMPUTE ==="
Write-Host "ROOT: $Root"
Write-Host "USE_YFINANCE_FOR_FULL_UNIVERSE_RECOMPUTE: $UseYFinanceForFullUniverseRecompute"
Write-Host "APPLY_FULL_UNIVERSE_RECOMPUTED_CANDIDATES: $ApplyFullUniverseRecomputedCandidates"
Write-Host "AUTO_TRADE: DISABLED"
Write-Host "AUTO_SELL: DISABLED"
Write-Host "OFFICIAL_DECISION_IMPACT: NONE"

if (-not (Test-Path $Script)) {
    Write-Host "STATUS: FAIL_V18_35D_FULL_UNIVERSE_RECOMPUTE_FAILED"
    throw "Missing script: $Script"
}

$Args35D = @("--root", $Root)
if ($UseYFinanceForFullUniverseRecompute) { $Args35D += "--use-yfinance-for-full-universe-recompute" }
if ($ApplyFullUniverseRecomputedCandidates) { $Args35D += "--apply-full-universe-recomputed-candidates" }

& $Python $Script @Args35D
$ExitCode = $LASTEXITCODE

if (Test-Path $ReadFirst) {
    Write-Host "--- V18.35D READ_FIRST ---"
    Get-Content -Path $ReadFirst | ForEach-Object { Write-Host $_ }
}

Write-Host "=== DONE V18.35D FULL UNIVERSE FACTOR TECHNICAL RECOMPUTE ==="
Write-Host "READ_FIRST: $ReadFirst"

if ($ExitCode -ne 0) {
    exit $ExitCode
}

if (Test-Path $ReadFirst) {
    $StatusLine = Select-String -Path $ReadFirst -Pattern '^STATUS:\s*FAIL_' -SimpleMatch:$false
    if ($StatusLine) { exit 1 }
}

exit 0
