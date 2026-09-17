param([int]$Port = 8501)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. (Join-Path $repo 'scripts/common/storage_paths.ps1')
$paths = Get-UstqStoragePaths -RepoRoot $repo
$demoPython = Join-Path $paths.envs_root 'demo-console/Scripts/python.exe'
$originalPythonPath = $env:PYTHONPATH
$originalBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = $repo
    $env:PYTHONDONTWRITEBYTECODE = '1'
    Push-Location $repo
    try {
        & $demoPython -B -m streamlit run apps/demo_console/app.py --server.address 127.0.0.1 --server.port $Port --server.headless true --server.fileWatcherType none --client.showErrorDetails false
        if ($LASTEXITCODE -ne 0) { throw "Streamlit could not start (exit $LASTEXITCODE). See apps/demo_console/README.md." }
    } finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $originalPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $originalBytecode
}
