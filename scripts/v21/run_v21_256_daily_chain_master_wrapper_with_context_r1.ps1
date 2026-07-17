param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [switch]$AuditOnly,
    [switch]$Execute
)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModuleRepo = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
if (-not $RepoRoot) { $RepoRoot = $ModuleRepo }
$RepoRoot = (Resolve-Path $RepoRoot).Path
. (Join-Path $ModuleRepo "scripts\common\storage_paths.ps1")
$PythonExe = Get-UstqPythonExecutable
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "External Python executable not found: $PythonExe" }
$ResolvedPython=(Resolve-Path -LiteralPath $PythonExe).Path
$RepoPrefix=([IO.Path]::GetFullPath([string]$RepoRoot)).TrimEnd('\')+'\'
if($ResolvedPython.StartsWith($RepoPrefix,[System.StringComparison]::OrdinalIgnoreCase)){throw "Python executable must be outside repo: $ResolvedPython"}
Set-Location $RepoRoot
$Script = Join-Path $RepoRoot "scripts\v21\v21_256_daily_chain_master_wrapper_with_context_r1.py"
$RunMode = "AuditOnly"
if ($Execute) { $RunMode = "Execute" }
$OutRoot = if($OutputDir){$OutputDir}else{Join-Path (Get-UstqDailyRoot) "current\V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"}
Assert-UstqExternalPath $OutRoot
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
$ArgsList = @($Script, "--repo-root", $RepoRoot, "--run-mode", $RunMode)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
$env:USTQ_REPO_ROOT=$RepoRoot; $env:USTQ_DATA_ROOT=(Get-UstqDataRoot); $env:USTQ_CACHE_ROOT=(Get-UstqCacheRoot); $env:USTQ_DAILY_ROOT=(Get-UstqDailyRoot); $env:USTQ_RESULTS_ROOT=(Get-UstqResultsRoot); $env:USTQ_ENVS_ROOT=(Get-UstqEnvsRoot); $env:USTQ_PYTHON_EXE=$ResolvedPython
& $ResolvedPython @ArgsList *> (Join-Path $OutRoot "v21_256_wrapper_stdout.log")
$ExitCode = $LASTEXITCODE
Get-Content -Path (Join-Path $OutRoot "v21_256_wrapper_stdout.log")
exit $ExitCode
