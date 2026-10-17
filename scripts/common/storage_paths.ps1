function Resolve-UstqStoragePath {
    param([string]$Path, [int]$Depth = 0)
    if ($Depth -gt 128) { throw "STORAGE_LINK_CYCLE:$Path" }
    $full = [IO.Path]::GetFullPath($Path)
    $parent = [IO.Path]::GetDirectoryName($full.TrimEnd('\','/'))
    if (-not $parent) { return $full }
    $physicalParent = Resolve-UstqStoragePath -Path $parent -Depth ($Depth + 1)
    $candidate = Join-Path $physicalParent ([IO.Path]::GetFileName($full.TrimEnd('\','/')))
    try { $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return $candidate }
        throw
    }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $targets = @($item.Target)
        if ($targets.Count -ne 1 -or -not $targets[0]) { throw "STORAGE_LINK_TARGET_UNKNOWN:$candidate" }
        $target = [string]$targets[0]
        if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path $physicalParent $target }
        return Resolve-UstqStoragePath -Path $target -Depth ($Depth + 1)
    }
    return $candidate
}
function Test-UstqPathWithin([string]$Path, [string]$Root) {
    $base = $Root.TrimEnd('\','/')
    return $Path.Equals($base, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
function Get-UstqStoragePaths {
    param([string]$RepoRoot = $(if ($env:USTQ_REPO_ROOT) { $env:USTQ_REPO_ROOT } else { (Get-Location).Path }))
    $repo = Resolve-UstqStoragePath $RepoRoot
    $cfg = Get-Content -LiteralPath (Join-Path $repo 'config\storage_paths.json') -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
    $keys = 'repo_root','data_root','cache_root','daily_root','backtest_root','results_root','envs_root'
    $out = @{}
    foreach ($key in $keys) {
        $envName = 'USTQ_' + $key.ToUpper()
        $value = [Environment]::GetEnvironmentVariable($envName)
        if (-not $value) { $value = $cfg.$key }
        $out[$key] = Resolve-UstqStoragePath $value
    }
    # An explicitly selected checkout takes precedence over stale copied routing.
    if ($PSBoundParameters.ContainsKey('RepoRoot')) { $out['repo_root'] = $repo }
    $roots = @($keys | Where-Object { $_ -ne 'repo_root' })
    foreach ($key in $roots) {
        if ((Test-UstqPathWithin $out[$key] $out.repo_root) -or (Test-UstqPathWithin $out.repo_root $out[$key])) {
            throw "STORAGE_ROOT_NESTS_REPO:$key"
        }
        foreach ($other in $roots) {
            if ($key -ne $other -and (Test-UstqPathWithin $out[$key] $out[$other])) {
                throw "STORAGE_ROOTS_ALIAS_OR_NEST:$key/$other"
            }
        }
    }
    $canonical = Join-Path $out['envs_root'] 'us-tech-quant-main\Scripts\python.exe'
    $out['python_exe'] = Resolve-UstqStoragePath $(if ($env:USTQ_PYTHON_EXE) {$env:USTQ_PYTHON_EXE} else {$canonical})
    if (Test-UstqPathWithin $out.python_exe $out.repo_root) { throw 'PYTHON_EXECUTABLE_MUST_BE_EXTERNAL' }
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
function Assert-UstqExternalPath([string]$Path, [string]$Kind = '') {
    $paths = Get-UstqStoragePaths
    $full = Resolve-UstqStoragePath $Path
    if (Test-UstqPathWithin $full $paths.repo_root) { throw "REPO_PATH_REJECTED:$Path" }
    if (Test-UstqPathWithin $full $paths.data_root) { throw "CANONICAL_DATA_OUTPUT_REJECTED:$Path" }
    $kinds = 'cache','daily','backtest','results'
    if ($Kind) {
        if ($Kind -notin $kinds) { throw "UNSUPPORTED_OUTPUT_KIND:$Kind" }
        $kinds = @($Kind)
    }
    foreach ($item in $kinds) {
        if (Test-UstqPathWithin $full $paths[$item + '_root']) { return }
    }
    throw "OUTPUT_OUTSIDE_CONFIGURED_ROOT:$Path"
}
function Show-UstqStorageConfiguration { Get-UstqStoragePaths }
