param()
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repoRoot 'scripts\common\storage_paths.ps1')
& (Get-UstqPythonExecutable) "$PSScriptRoot\repo_write_guard_r2a.py"
exit $LASTEXITCODE
