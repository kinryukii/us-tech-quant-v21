param(
  [string]$RepoRoot="D:\us-tech-quant",
  [switch]$AuditOnly,
  [string]$CacheRoot="D:\us-tech-quant-cache",
  [string]$V21245Root="outputs/v21/V21.245_MOOMOO_HISTORICAL_BACKFILL_TO_LOCAL_CACHE_R1",
  [string]$ExpectedLatestDate="2026-07-03",
  [int]$MinimumUsableTickerCount=250,
  [switch]$WriteExclusionList,
  [switch]$FailOnNotReady
)
$ErrorActionPreference="Stop"
Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_245_r1a_moomoo_cache_currentness_and_failure_triage.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot,"--cache-root",$CacheRoot,"--v21-245-root",$V21245Root,"--expected-latest-date",$ExpectedLatestDate,"--minimum-usable-ticker-count",[string]$MinimumUsableTickerCount,"--audit-only")
if($WriteExclusionList){$ArgsList+=@("--write-exclusion-list")}
if($FailOnNotReady){$ArgsList+=@("--fail-on-not-ready")}
& $Python @ArgsList
exit $LASTEXITCODE
