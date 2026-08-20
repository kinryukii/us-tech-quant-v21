$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $repoRoot 'scripts\common\storage_paths.ps1')
& (Get-UstqPythonExecutable) (Join-Path $PSScriptRoot 'run_fast3_guard.py') @args
exit $LASTEXITCODE
