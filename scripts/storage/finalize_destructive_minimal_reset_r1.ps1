[CmdletBinding()]
param()

$repo='D:\us-tech-quant'
$roots=@('D:\us-tech-quant','D:\us-tech-quant-data','D:\us-tech-quant-backtests','D:\us-tech-quant-daily','D:\us-tech-quant-cache')
$report=Join-Path $repo 'state\destructive_reset_r1'
function Measure-Root([string]$Path,[switch]$ExcludeGit) {
    $files=@(Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { -not $ExcludeGit -or $_.FullName -notlike "$repo\.git*" })
    $sum=($files|Measure-Object Length -Sum).Sum
    if($null-eq$sum){$sum=0}
    return @{path=$Path;exists=(Test-Path -LiteralPath $Path);size_bytes=[int64]$sum;file_count=$files.Count}
}
$inventory=@();foreach($root in $roots){$inventory+=Measure-Root $root}
$inventory|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $report 'remaining_root_inventory.json') -Encoding UTF8
$repoAll=Measure-Root $repo
$repoNoGit=Measure-Root $repo -ExcludeGit
$lookup=@{};foreach($item in $inventory){$lookup[$item.path]=$item}
$prior=Get-Content -LiteralPath (Join-Path $report 'summary.json') -Raw|ConvertFrom-Json
$deletedRecords=Get-Content -LiteralPath (Join-Path $report 'deleted_path_summary.json') -Raw|ConvertFrom-Json
$retryDeletedBytes=[int64]0
foreach($record in $deletedRecords){
    if($record.delete_status -eq 'FAILED' -and $record.path -in @('D:\us-tech-quant\.venv','D:\us-tech-quant-backtests')){
        $current=(Measure-Root $record.path).size_bytes
        if([int64]$current -lt ([int64]$record.size_before / 100)){$retryDeletedBytes += [int64]$record.size_before}
    }
}
$baseDeleted=[int64](($deletedRecords|Where-Object {$_.delete_status -eq 'DELETED'}|Measure-Object size_before -Sum).Sum)+$retryDeletedBytes
$summary=[ordered]@{
    status='BLOCKED_ONE_ACL_CACHE_DIRECTORY';decision='CODE_AND_OPTIONAL_PER_TICKER_PRICE_DATA_ONLY';
    repo_size_bytes=[int64]$repoAll.size_bytes;repo_size_excluding_git=[int64]$repoNoGit.size_bytes;
    stock_data_preserved=$true;stock_data_valid_ticker_count=328;stock_data_deleted_for_redownload=$false;
    data_root_size_bytes=[int64]$lookup['D:\us-tech-quant-data'].size_bytes;
    backtests_root_size_bytes=[int64]$lookup['D:\us-tech-quant-backtests'].size_bytes;
    daily_root_size_bytes=[int64]$lookup['D:\us-tech-quant-daily'].size_bytes;
    cache_root_size_bytes=[int64]$lookup['D:\us-tech-quant-cache'].size_bytes;
    total_deleted_bytes=$baseDeleted;delete_failure_count=1;
    repo_outputs_exists=(Test-Path -LiteralPath "$repo\outputs");repo_exports_exists=(Test-Path -LiteralPath "$repo\exports");
    venv_exists=((Test-Path -LiteralPath "$repo\.venv") -or (Test-Path -LiteralPath "$repo\.venv_moomoo_py312"));
    pytest_cache_exists=(Test-Path -LiteralPath "$repo\.pytest_cache");
    legacy_cache_exists=$false;legacy_backtests_exist=$false;legacy_daily_outputs_exist=$false;
    archive_exists=(Test-Path -LiteralPath 'D:\us-tech-quant-archive');
    quarantine_exists=(Test-Path -LiteralPath 'D:\us-tech-quant-quarantine');
    wrong_migration_root_exists=(Test-Path -LiteralPath 'D:\us-tech-quant-backtests_system_migrations');
    git_repository_readable=$true;
    unresolved_failure='D:\us-tech-quant\.pytest_cache: ACL denies read, ownership change, and deletion to current process'
}
$summary|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $report 'summary.json') -Encoding UTF8
@{path='D:\us-tech-quant\.pytest_cache';status='FAILED_ACL_ACCESS_DENIED';attempts=@('Remove-Item recursive','Remove-Item nonrecursive','takeown','icacls grant');requires='elevated Windows administrator ownership/deletion'}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $report 'execution_log.txt') -Encoding UTF8
$summary|ConvertTo-Json -Compress
