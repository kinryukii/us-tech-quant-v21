param([ValidateRange(1, 65535)][int]$Port = 8501, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$url = "http://127.0.0.1:$Port/"
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if ($listeners | Where-Object { $_.Port -eq $Port }) {
    $ready = $false
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri ($url + '_stcore/health') -TimeoutSec 3 -MaximumRedirection 0
        $page = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3 -MaximumRedirection 0
        $ready = $health.StatusCode -eq 200 -and $health.Content.Trim() -ceq 'ok' -and
            $page.StatusCode -eq 200 -and $page.Content -match '<title>Streamlit</title>'
    } catch { $ready = $false }
    if (-not $ready) {
        throw "Port $Port is occupied, but no healthy Streamlit page was verified. Retry after startup, or select another -Port. The existing process was left running."
    }
    Write-Host "A healthy Streamlit service is already available at $url"
    if (-not $NoBrowser) {
        try { Start-Process -FilePath $url }
        catch { Write-Warning "Could not open the browser automatically. Open $url manually." }
    }
    return
}
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
        $headless = $NoBrowser.IsPresent.ToString().ToLowerInvariant()
        Write-Host "Starting DEMO at $url. Keep this terminal open while using it."
        & $demoPython -B -m streamlit run apps/demo_console/app.py --server.address 127.0.0.1 --server.port $Port --server.headless $headless --server.fileWatcherType none --client.showErrorDetails false
        if ($LASTEXITCODE -ne 0) { throw "Streamlit could not start (exit $LASTEXITCODE). See apps/demo_console/README.md." }
    } finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $originalPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $originalBytecode
}
