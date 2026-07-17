[CmdletBinding()]
param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$repo = 'D:\us-tech-quant'
$dataRoot = 'D:\us-tech-quant-data'
$backtestsRoot = 'D:\us-tech-quant-backtests'
$dailyRoot = 'D:\us-tech-quant-daily'
$cacheRoot = 'D:\us-tech-quant-cache'
$archiveRoot = 'D:\us-tech-quant-archive'
$quarantineRoot = 'D:\us-tech-quant-quarantine'
$wrongMigrationRoot = 'D:\us-tech-quant-backtests_system_migrations'
$reportRoot = Join-Path $repo 'state\destructive_reset_r1'
$allowedRoots = @($repo,$dataRoot,$backtestsRoot,$dailyRoot,$cacheRoot,$archiveRoot,$quarantineRoot,$wrongMigrationRoot)

function Assert-AllowedPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    foreach ($root in $allowedRoots) {
        $safe = [System.IO.Path]::GetFullPath($root).TrimEnd('\')
        if ($full -eq $safe -or $full.StartsWith($safe + '\',[System.StringComparison]::OrdinalIgnoreCase)) { return $full }
    }
    throw "REFUSED_OUTSIDE_ALLOWED_ROOT: $full"
}

function Get-TreeStat([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @{size_before=0;file_count_before=0} }
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue)
    $sum = ($files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    return @{size_before=[int64]$sum;file_count_before=$files.Count}
}

$deleted = [System.Collections.Generic.List[object]]::new()
$failures = [System.Collections.Generic.List[object]]::new()
$totalDeleted = [int64]0
function Remove-Recorded([string]$Path,[string]$Reason) {
    $safe = Assert-AllowedPath $Path
    $stat = Get-TreeStat $safe
    $status = 'NOT_FOUND'
    if (Test-Path -LiteralPath $safe) {
        if (-not $Execute) { $status = 'WHATIF' }
        else {
            try {
                Remove-Item -LiteralPath $safe -Recurse -Force -ErrorAction Stop
                $status = 'DELETED'
                $script:totalDeleted += [int64]$stat.size_before
            } catch {
                $status = 'FAILED'
                $script:failures.Add(@{path=$safe;error=$_.Exception.Message})
            }
        }
    }
    $script:deleted.Add(@{path=$safe;reason=$Reason;size_before=[int64]$stat.size_before;file_count_before=[int]$stat.file_count_before;delete_status=$status;deleted_at=(Get-Date).ToUniversalTime().ToString('o')})
}

if (-not $Execute) { Write-Output 'WhatIf only. Pass -Execute for irreversible reset.'; exit 0 }
New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null

$dependencyExists = Test-Path -LiteralPath (Join-Path $repo 'requirements.lock.txt')
@{requirements_lock_exists=$dependencyExists;warning=if($dependencyExists){$null}else{'Dependency lock is incomplete; virtual environments were still removed by authorization.'}} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reportRoot 'dependency_warning.json') -Encoding UTF8

$stockValidationPath = Join-Path $reportRoot 'stock_validation.json'
if (-not (Test-Path -LiteralPath $stockValidationPath)) { throw 'stock_validation.json is required before destructive reset' }
$stockValidation = Get-Content -LiteralPath $stockValidationPath -Raw | ConvertFrom-Json
if (-not $stockValidation.preserve_stocks) { throw 'Fast stock validation did not authorize preservation; run the explicit data-redownload branch instead' }
@{missing_tickers=@();invalid_ticker_count=0} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reportRoot 'missing_tickers.json') -Encoding UTF8

# Remove stale repo state while preserving this reset record.
$stateRoot = Join-Path $repo 'state'
if (Test-Path -LiteralPath $stateRoot) {
    Get-ChildItem -LiteralPath $stateRoot -Force | Where-Object { $_.FullName -ne $reportRoot } | ForEach-Object { Remove-Recorded $_.FullName 'STALE_STATE_POINTER_OR_MANIFEST' }
}

$repoTargets = @(
    '.venv','.venv_moomoo_py312','outputs','exports','backups','data','inputs','__pycache__','.pytest_cache','.pytest_tmp',
    '.mypy_cache','.ruff_cache','htmlcov','dist','build','.tmp','tmp','unused','us-tech-quanttmppytest','x','.agents'
)
foreach ($relative in $repoTargets) { Remove-Recorded (Join-Path $repo $relative) 'REPO_GENERATED_OR_REBUILDABLE' }

# Remove nested interpreter/test caches and egg-info with verified repo-contained paths.
Get-ChildItem -LiteralPath $repo -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "$repo\.git*" -and ($_.Name -eq '__pycache__' -or $_.Name -eq '.pytest_cache' -or $_.Name -like '*.egg-info') } |
    Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { if (Test-Path -LiteralPath $_.FullName) { Remove-Recorded $_.FullName 'NESTED_CACHE_OR_EGG_INFO' } }

# Remove data/report binaries from the repo, preserving small test fixtures and config assets.
$binaryExtensions = @('.csv','.parquet','.arrow','.feather','.duckdb','.sqlite','.db','.zip','.gz','.log','.pdf','.png','.jpg','.jpeg','.gif','.webp')
$binaryFiles = @(Get-ChildItem -LiteralPath $repo -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object {
    $_.FullName -notlike "$repo\.git*" -and
    $_.FullName -notlike "$reportRoot*" -and
    $binaryExtensions -contains $_.Extension.ToLowerInvariant() -and
    -not ($_.Length -le 5MB -and ($_.FullName -like "$repo\tests\*" -or $_.FullName -like "$repo\config\*" -or $_.FullName -like "$repo\configs\*"))
})
foreach ($file in $binaryFiles) { Remove-Recorded $file.FullName 'REPO_BINARY_DATA_OR_REPORT' }
Remove-Recorded (Join-Path $repo 'large_files_over_50mb.txt') 'STALE_STORAGE_REPORT'

# Data root: stocks is the only permanent dataset.
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
Get-ChildItem -LiteralPath $dataRoot -Force | Where-Object { $_.Name -ne 'stocks' -and $_.Name -notlike 'README*' -and $_.Name -notin @('data_inventory.json','missing_tickers.json') } |
    ForEach-Object { Remove-Recorded $_.FullName 'NON_STOCK_PERMANENT_DATA_REMOVED' }

# Recreate empty external result/cache roots.
Remove-Recorded $backtestsRoot 'ALL_BACKTESTS_AND_STRATEGY_HISTORY'
New-Item -ItemType Directory -Path $backtestsRoot -Force | Out-Null
@'
Backtests are external and disposable by explicit user policy.
Each future backtest must create an independent run directory, must not copy market data, and must never write into the repository.
'@ | Set-Content -LiteralPath (Join-Path $backtestsRoot 'README_BACKTESTS_EXTERNAL.txt') -Encoding UTF8

Remove-Recorded $dailyRoot 'ALL_DAILY_OUTPUTS'
New-Item -ItemType Directory -Path $dailyRoot -Force | Out-Null
@'
Daily outputs must be written externally under a dated, unique run directory. This root is intentionally empty after reset.
'@ | Set-Content -LiteralPath (Join-Path $dailyRoot 'README_DAILY_OUTPUTS_EXTERNAL.txt') -Encoding UTF8

Remove-Recorded $cacheRoot 'ALL_LEGACY_CACHE'
New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
foreach ($name in @('temporary','derived','downloads','testing')) { New-Item -ItemType Directory -Path (Join-Path $cacheRoot $name) -Force | Out-Null }
@'
This entire cache may be deleted at any time.
It must never contain unique data. Maximum size: 2 GB. TTL: 7 days. Use LRU cleanup above the limit.
Permanent prices belong only in D:\us-tech-quant-data\stocks.
Backtests belong only in D:\us-tech-quant-backtests. Daily outputs belong only in D:\us-tech-quant-daily.
'@ | Set-Content -LiteralPath (Join-Path $cacheRoot 'README_CACHE_DISPOSABLE.txt') -Encoding UTF8

Remove-Recorded $archiveRoot 'ALL_ARCHIVES_REMOVED_BY_USER'
Remove-Recorded $quarantineRoot 'ALL_QUARANTINE_REMOVED_BY_USER'
Remove-Recorded $wrongMigrationRoot 'MALFORMED_MIGRATION_ROOT'

$stocksRoot = Join-Path $dataRoot 'stocks'
$stockFiles = @(Get-ChildItem -LiteralPath $stocksRoot -Recurse -File -Force -ErrorAction SilentlyContinue)
$stockBytes = ($stockFiles | Measure-Object Length -Sum).Sum
if ($null -eq $stockBytes) { $stockBytes = 0 }
$inventory = @{generated_at=(Get-Date).ToUniversalTime().ToString('o');ticker_count=[int]$stockValidation.ticker_count;valid_ticker_count=[int]$stockValidation.valid_ticker_count;file_count=$stockFiles.Count;size_bytes=[int64]$stockBytes}
$inventory | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $dataRoot 'data_inventory.json') -Encoding UTF8
@{missing_tickers=@()} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataRoot 'missing_tickers.json') -Encoding UTF8

function Get-RootInventory([string]$Path) {
    $stat = Get-TreeStat $Path
    return @{path=$Path;exists=(Test-Path -LiteralPath $Path);size_bytes=[int64]$stat.size_before;file_count=[int]$stat.file_count_before}
}
$remaining = @(
    Get-RootInventory $repo
    Get-RootInventory $dataRoot
    Get-RootInventory $backtestsRoot
    Get-RootInventory $dailyRoot
    Get-RootInventory $cacheRoot
)
$remaining | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'remaining_root_inventory.json') -Encoding UTF8
$deleted | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'deleted_path_summary.json') -Encoding UTF8

$gitReadable = $false
try { Push-Location $repo; git rev-parse --is-inside-work-tree | Out-Null; $gitReadable = ($LASTEXITCODE -eq 0) } finally { Pop-Location }
$repoWithoutGit = Get-ChildItem -LiteralPath $repo -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "$repo\.git*" } | Measure-Object Length -Sum
$summary = @{
    status='PASS_DESTRUCTIVE_MINIMAL_RESET_R1';decision='CODE_AND_OPTIONAL_PER_TICKER_PRICE_DATA_ONLY';
    stock_data_preserved=$true;stock_data_valid_ticker_count=[int]$stockValidation.valid_ticker_count;stock_data_deleted_for_redownload=$false;
    total_deleted_bytes=$totalDeleted;delete_failure_count=$failures.Count;git_repository_readable=$gitReadable;
    repo_size_excluding_git=[int64]$repoWithoutGit.Sum;
    repo_outputs_exists=(Test-Path -LiteralPath (Join-Path $repo 'outputs'));repo_exports_exists=(Test-Path -LiteralPath (Join-Path $repo 'exports'));
    venv_exists=((Test-Path -LiteralPath (Join-Path $repo '.venv')) -or (Test-Path -LiteralPath (Join-Path $repo '.venv_moomoo_py312')));
    legacy_cache_exists=$false;legacy_backtests_exist=$false;legacy_daily_outputs_exist=$false;
    archive_exists=(Test-Path -LiteralPath $archiveRoot);quarantine_exists=(Test-Path -LiteralPath $quarantineRoot);wrong_migration_root_exists=(Test-Path -LiteralPath $wrongMigrationRoot)
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'summary.json') -Encoding UTF8
$failures | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reportRoot 'execution_log.txt') -Encoding UTF8
if ($failures.Count -gt 0) { throw "RESET_COMPLETED_WITH_$($failures.Count)_DELETE_FAILURES" }
Write-Output ($summary | ConvertTo-Json -Compress)
