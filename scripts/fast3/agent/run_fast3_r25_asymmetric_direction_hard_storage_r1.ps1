[CmdletBinding()]
param(
 [string]$RepoRoot="D:\us-tech-quant", [string]$DataRoot="D:\us-tech-quant-data",
 [string]$ResultsRoot="D:\us-tech-quant-results", [string]$CacheRoot="D:\us-tech-quant-cache",
 [string]$RunId=(Get-Date -Format "yyyyMMdd_HHmmss")
)
$ErrorActionPreference="Stop"; Set-StrictMode -Version Latest
$runtime=Join-Path $ResultsRoot "runtime\fast3\r25_asymmetric_direction\$RunId"; $scratch=Join-Path $ResultsRoot "scratch\fast3\r25_asymmetric_direction\$RunId"; $frozen=Join-Path $ResultsRoot "frozen\fast3\r25_asymmetric_direction\$RunId"; $archive=Join-Path $ResultsRoot "archive\fast3\r25_asymmetric_direction\$RunId"; $cache=Join-Path $CacheRoot "fast3\r25_asymmetric_direction\$RunId"
New-Item -ItemType Directory -Force -Path $runtime,$scratch,$frozen,$archive,$cache,(Join-Path $cache "tmp"),(Join-Path $cache "pycache")|Out-Null
$env:TEMP=Join-Path $cache "tmp"; $env:TMP=$env:TEMP; $env:PYTHONPYCACHEPREFIX=Join-Path $cache "pycache"; $env:FAST3_CACHE_ROOT=$cache; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH=(Join-Path $RepoRoot "fast3\src")
$py=Join-Path $RepoRoot ".venv\Scripts\python.exe"; if(!(Test-Path -LiteralPath $py)){$py="python"}
& $py -m pytest (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r25.py") -q --basetemp (Join-Path $cache "pytest") -o cache_dir=(Join-Path $cache "pytest-cache")
$test=$LASTEXITCODE
& $py (Join-Path $RepoRoot "fast3\scripts\run\fast3_r4_two_stage_direction_hard_r25.py") --repo-root $RepoRoot --data-root $DataRoot --runtime-root $runtime --scratch-root $scratch --frozen-root $frozen --archive-root $archive --cache-root $cache --source-r3-root "D:\us-tech-quant-results\fast3\agent_runs\event_factor_cohort_r3\20260803_181405" --source-r3-audit-root "D:\us-tech-quant-results\fast3\agent_runs\r3_economic_integrity_audit\20260803_183906" --complete-ledger-path "D:\us-tech-quant-results\fast3\agent_runs\event_factor_law_discovery\20260802_184840\fast3_event_ledger.parquet" --r24-control-root "D:\us-tech-quant-results\frozen\fast3\r4_two_stage_direction\20260803_183950" --run-id $RunId
exit $LASTEXITCODE
