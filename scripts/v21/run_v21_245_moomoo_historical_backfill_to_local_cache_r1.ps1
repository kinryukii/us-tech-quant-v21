param(
  [string]$RepoRoot="D:\us-tech-quant",
  [string]$OutputDir="",
  [string]$CacheRoot="D:\us-tech-quant-cache",
  [switch]$Execute,
  [switch]$DryRun,
  [string]$StartDate="2018-01-01",
  [string]$EndDate="latest_completed",
  [string]$UniverseSource="auto",
  [string]$PriceTypes="raw,qfq",
  [switch]$Resume,
  [int]$TopN=0,
  [switch]$FailOnAllFetchFailed,
  [switch]$AllowMoomooProviderFetch
)
$ErrorActionPreference="Stop"
Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_245_moomoo_historical_backfill_to_local_cache_r1.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot,"--cache-root",$CacheRoot,"--start-date",$StartDate,"--end-date",$EndDate,"--universe-source",$UniverseSource,"--price-types",$PriceTypes)
if($OutputDir){$ArgsList+=@("--output-dir",$OutputDir)}
if($Execute){$ArgsList+=@("--execute")} else {$ArgsList+=@("--dry-run")}
if($Resume){$ArgsList+=@("--resume")}
if($TopN -gt 0){$ArgsList+=@("--top-n",[string]$TopN)}
if($FailOnAllFetchFailed){$ArgsList+=@("--fail-on-all-fetch-failed")}
if($AllowMoomooProviderFetch){$ArgsList+=@("--allow-moomoo-provider-fetch")}
& $Python @ArgsList
exit $LASTEXITCODE
