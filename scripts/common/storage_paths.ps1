function Get-UstqStoragePaths {
    param([string]$RepoRoot = (Get-Location).Path)
    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $cfg = Get-Content (Join-Path $repo 'config\storage_paths.json') -Raw | ConvertFrom-Json
    $keys = 'repo_root','data_root','cache_root','daily_root','backtest_root','results_root','envs_root'
    $out = @{}
    foreach ($key in $keys) { $envName = 'USTQ_' + $key.ToUpper(); $out[$key] = if ([Environment]::GetEnvironmentVariable($envName)) {[Environment]::GetEnvironmentVariable($envName)} else {$cfg.$key} }
    $preferred = Join-Path $out['envs_root'] 'daily-python312\Scripts\python.exe'
    $out['python_exe'] = if ($env:USTQ_PYTHON_EXE) {$env:USTQ_PYTHON_EXE} elseif(Test-Path $preferred){$preferred} else {(Join-Path $out['envs_root'] '.venv\Scripts\python.exe')}
    return $out
}
function Get-UstqRepoRoot { (Get-UstqStoragePaths).repo_root }
function Get-UstqDataRoot { (Get-UstqStoragePaths).data_root }
function Get-UstqCacheRoot { (Get-UstqStoragePaths).cache_root }
function Get-UstqDailyRoot { (Get-UstqStoragePaths).daily_root }
function Get-UstqBacktestRoot { (Get-UstqStoragePaths).backtest_root }
function Get-UstqResultsRoot { (Get-UstqStoragePaths).results_root }
function Get-UstqEnvsRoot { (Get-UstqStoragePaths).envs_root }
function Get-UstqPythonExecutable { (Get-UstqStoragePaths).python_exe }
function Assert-UstqExternalPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $repo = ([IO.Path]::GetFullPath((Get-UstqRepoRoot))).TrimEnd('\') + '\'
    if($full.StartsWith($repo,[StringComparison]::OrdinalIgnoreCase)){throw "REPO_PATH_REJECTED:$Path"}
}
function Show-UstqStorageConfiguration { Get-UstqStoragePaths }
