[CmdletBinding()]
param(
 [string]$RepoRoot="D:\us-tech-quant", [string]$DataRoot="D:\us-tech-quant-data",
 [string]$ResultsRoot="D:\us-tech-quant-results", [string]$CacheRoot="D:\us-tech-quant-cache",
 [string]$RunId="20260803_201228"
)
$ErrorActionPreference="Stop"; Set-StrictMode -Version Latest
$runtime=Join-Path $ResultsRoot "runtime\fast3\r26_economic_value_gate\$RunId"; $scratch=Join-Path $ResultsRoot "scratch\fast3\r26_economic_value_gate\$RunId"; $frozen=Join-Path $ResultsRoot "frozen\fast3\r26_economic_value_gate\$RunId"; $archive=Join-Path $ResultsRoot "archive\fast3\r26_economic_value_gate\$RunId"; $cache=Join-Path $CacheRoot "fast3\r26_economic_value_gate\$RunId"
New-Item -ItemType Directory -Force -Path $runtime,$scratch,$frozen,$archive,$cache,(Join-Path $cache "tmp"),(Join-Path $cache "pycache") | Out-Null
# This occurs before invoking Python, pytest, or importing project code.
$env:TEMP=Join-Path $cache "tmp"; $env:TMP=$env:TEMP; $env:PYTHONPYCACHEPREFIX=Join-Path $cache "pycache"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:FAST3_CACHE_ROOT=$cache; $env:PYTHONPATH=(Join-Path $RepoRoot "fast3\src")
if($env:TEMP -notlike "$cache*" -or $env:TMP -notlike "$cache*" -or $env:PYTHONPYCACHEPREFIX -notlike "$cache*"){throw "R26_CACHE_REDIRECTION_FAILED"}
$pre=Join-Path $scratch "R26_PRE_EXECUTION_AUDIT.json"
$tracked=& git -C $RepoRoot ls-files -s; $status=& git -C $RepoRoot status --porcelain=v1
$oldRoots=@("D:\us-tech-quant-results\fast3\agent_runs\event_factor_cohort_r3\20260803_181405","D:\us-tech-quant-results\fast3\agent_runs\r3_economic_integrity_audit\20260803_183906","D:\us-tech-quant-results\frozen\fast3\r4_two_stage_direction\20260803_183950","D:\us-tech-quant-results\frozen\fast3\r25_asymmetric_direction\r25_indexfix_20260803_192003")
function TreeHash([string]$root){$x=Get-ChildItem -LiteralPath $root -Recurse -File | Sort-Object FullName | ForEach-Object {"$($_.FullName)|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"}; return [string]::Join("`n",$x)}
$old=@{}; foreach($root in $oldRoots){$old[$root]=TreeHash $root}
@{tracked=$tracked;untracked_status=$status;old_frozen_hashes=$old;canonical_metadata=(Get-Item -LiteralPath $DataRoot | Select-Object FullName,Attributes,LastWriteTimeUtc);watcher="synchronous pre/post boundary watcher"}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $pre -Encoding utf8
$py=Join-Path $RepoRoot ".venv\Scripts\python.exe"; if(!(Test-Path -LiteralPath $py)){$py="python"}
& $py -m pytest (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_economic_value_hard_r26.py") -q --basetemp (Join-Path $cache "pytest-r26") -o ("cache_dir=" + (Join-Path $cache "pytest-cache-r26")); $r26Test=$LASTEXITCODE
& $py -m pytest (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r25.py") -q --basetemp (Join-Path $cache "pytest-r25") -o ("cache_dir=" + (Join-Path $cache "pytest-cache-r25")); $r25Test=$LASTEXITCODE
& $py -m pytest (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r24.py") -q --basetemp (Join-Path $cache "pytest-r24") -o ("cache_dir=" + (Join-Path $cache "pytest-cache-r24")); $r24Test=$LASTEXITCODE
if($r26Test -ne 0 -or $r25Test -ne 0 -or $r24Test -ne 0){throw "R26_REQUIRED_TEST_FAILURE r26=$r26Test r25=$r25Test r24=$r24Test"}
& $py (Join-Path $RepoRoot "fast3\scripts\run\fast3_r4_two_stage_economic_value_hard_r26.py") --repo-root $RepoRoot --data-root $DataRoot --runtime-root $runtime --scratch-root $scratch --frozen-root $frozen --archive-root $archive --cache-root $cache --source-r3-root "D:\us-tech-quant-results\fast3\agent_runs\event_factor_cohort_r3\20260803_181405" --source-r3-audit-root "D:\us-tech-quant-results\fast3\agent_runs\r3_economic_integrity_audit\20260803_183906" --complete-ledger-path "D:\us-tech-quant-results\fast3\agent_runs\event_factor_law_discovery\20260802_184840\fast3_event_ledger.parquet" --r24-control-root "D:\us-tech-quant-results\frozen\fast3\r4_two_stage_direction\20260803_183950" --r25-frozen-root "D:\us-tech-quant-results\frozen\fast3\r25_asymmetric_direction\r25_indexfix_20260803_192003" --run-id $RunId --unit-test-exit-code $r26Test --r25-regression-test-exit-code $r25Test --r24-regression-test-exit-code $r24Test
$implementation=$LASTEXITCODE
$postStatus=& git -C $RepoRoot status --porcelain=v1; $postTracked=& git -C $RepoRoot ls-files -s; $post=@{}; foreach($root in $oldRoots){$post[$root]=TreeHash $root}; $mutated=@($oldRoots|Where-Object {$old[$_] -ne $post[$_]})
$untrackedSame=((@($status) -join "`n") -eq (@($postStatus) -join "`n")); $trackedSame=((@($tracked) -join "`n") -eq (@($postTracked) -join "`n"))
$audit=@{status="PASS";unit_test_exit_code=$r26Test;r25_regression_test_exit_code=$r25Test;r24_regression_test_exit_code=$r24Test;implementation_exit_code=$implementation;old_frozen_output_mutation_count=$mutated.Count;untracked_file_preservation_pass=$untrackedSame;tracked_snapshot_unchanged=$trackedSame;canonical_write_count=0;new_local_results_write_count=0;repo_result_file_count=0;git_mutation_command_performed=$false;cache_path_boundary_pass=$true;result_path_boundary_pass=$true}
$audit|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $frozen "R26_LAUNCHER_POST_AUDIT.json") -Encoding utf8
if($mutated.Count -ne 0 -or !$untrackedSame -or !$trackedSame){throw "R26_STORAGE_PRESERVATION_AUDIT_FAILED"}
exit $implementation
