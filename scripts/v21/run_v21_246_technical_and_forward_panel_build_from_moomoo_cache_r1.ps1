param(
  [string]$RepoRoot="D:\us-tech-quant",
  [switch]$Build,
  [string]$CacheRoot="D:\us-tech-quant-cache",
  [string]$V21245R1ARoot="outputs/v21/V21.245_R1A_MOOMOO_CACHE_CURRENTNESS_AND_FAILURE_TRIAGE",
  [string]$ExpectedLatestDate="2026-07-02",
  [switch]$UseQfq,
  [switch]$RespectExclusionList,
  [switch]$FailOnTooSparse,
  [int]$MinUsableTickerCount=250
)
$ErrorActionPreference="Stop"
Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_246_technical_and_forward_panel_build_from_moomoo_cache_r1.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot,"--cache-root",$CacheRoot,"--v21-245-r1a-root",$V21245R1ARoot,"--expected-latest-date",$ExpectedLatestDate,"--min-usable-ticker-count",[string]$MinUsableTickerCount,"--build")
if($UseQfq){$ArgsList+=@("--use-qfq")}
if($RespectExclusionList){$ArgsList+=@("--respect-exclusion-list")}
if($FailOnTooSparse){$ArgsList+=@("--fail-on-too-sparse")}
& $Python @ArgsList
exit $LASTEXITCODE
