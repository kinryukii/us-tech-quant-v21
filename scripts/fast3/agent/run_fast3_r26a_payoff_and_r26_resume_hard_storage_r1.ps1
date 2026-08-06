[CmdletBinding()]
param(
 [string]$RepoRoot="D:\us-tech-quant", [string]$DataRoot="D:\us-tech-quant-data",
 [string]$ResultsRoot="D:\us-tech-quant-results", [string]$CacheRoot="D:\us-tech-quant-cache",
 [string]$RunId=(Get-Date -Format "yyyyMMdd_HHmmss")
)
$ErrorActionPreference="Stop"; Set-StrictMode -Version Latest
$runtime=Join-Path $ResultsRoot "runtime\fast3\r26a_executable_payoff_ledger\$RunId"; $scratch=Join-Path $ResultsRoot "scratch\fast3\r26a_executable_payoff_ledger\$RunId"; $frozen=Join-Path $ResultsRoot "frozen\fast3\r26a_executable_payoff_ledger\$RunId"; $archive=Join-Path $ResultsRoot "archive\fast3\r26a_executable_payoff_ledger\$RunId"; $cache=Join-Path $CacheRoot "fast3\r26a_executable_payoff_ledger\$RunId"
New-Item -ItemType Directory -Force -Path $runtime,$scratch,$frozen,$archive,$cache,(Join-Path $cache "tmp"),(Join-Path $cache "pycache") | Out-Null
$env:TEMP=Join-Path $cache "tmp"; $env:TMP=$env:TEMP; $env:PYTHONPYCACHEPREFIX=Join-Path $cache "pycache"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:FAST3_CACHE_ROOT=$cache; $env:PYTHONPATH=Join-Path $RepoRoot "fast3\src"
if($env:TEMP -notlike "$cache*" -or $env:TMP -notlike "$cache*" -or $env:PYTHONPYCACHEPREFIX -notlike "$cache*"){throw "R26A_CACHE_REDIRECTION_FAILED"}
$py=Join-Path $RepoRoot ".venv\Scripts\python.exe"; if(!(Test-Path -LiteralPath $py)){$py="python"}
& $py -m pytest (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r26a_executable_payoff_ledger.py") -q --basetemp (Join-Path $cache "pytest-r26a") -o ("cache_dir="+(Join-Path $cache "pytest-cache-r26a")); if($LASTEXITCODE -ne 0){throw "R26A_TARGETED_TEST_FAILURE"}
& $py -m pytest (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r26a_executable_payoff_ledger.py") (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_economic_value_hard_r26.py") -q --basetemp (Join-Path $cache "pytest-combined") -o ("cache_dir="+(Join-Path $cache "pytest-cache-combined")); if($LASTEXITCODE -ne 0){throw "R26A_FULL_TEST_FAILURE"}
& $py (Join-Path $RepoRoot "fast3\scripts\run\fast3_r26a_executable_payoff_ledger.py") --repo-root $RepoRoot --data-root $DataRoot --runtime-root $runtime --scratch-root $scratch --frozen-root $frozen --archive-root $archive --cache-root $cache --source-r3-root "D:\us-tech-quant-results\fast3\agent_runs\event_factor_cohort_r3\20260803_181405" --source-r3-audit-root "D:\us-tech-quant-results\fast3\agent_runs\r3_economic_integrity_audit\20260803_183906" --complete-ledger-path "D:\us-tech-quant-results\fast3\agent_runs\event_factor_law_discovery\20260802_184840\fast3_event_ledger.parquet" --r24-control-root "D:\us-tech-quant-results\frozen\fast3\r4_two_stage_direction\20260803_183950" --r25-frozen-root "D:\us-tech-quant-results\frozen\fast3\r25_asymmetric_direction\r25_indexfix_20260803_192003" --r26-failed-frozen-root "D:\us-tech-quant-results\frozen\fast3\r26_economic_value_gate\20260803_201228_r3" --run-id $RunId
exit $LASTEXITCODE
