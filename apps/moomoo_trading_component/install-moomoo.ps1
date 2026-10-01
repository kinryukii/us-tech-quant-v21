$ErrorActionPreference = 'Stop'
$componentRepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $componentRepoRoot 'scripts/common/storage_paths.ps1')
$componentPython = (Get-UstqStoragePaths -RepoRoot $componentRepoRoot).python_exe
if (-not (Test-Path -LiteralPath $componentPython)) { throw '项目规范 Python 环境不可用。' }
& $componentPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-moomoo.txt')
if ($LASTEXITCODE -ne 0) { throw '安装 Moomoo SDK 失败' }
