$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$PythonScript = Join-Path $ScriptDir "v20_83_authoritative_official_current_ticker_level_ranking_export.py"
$ManifestPath = Join-Path $RepoRoot "outputs\v20\ops\V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json"

Write-Host "STAGE_NAME=V20.83_AUTHORITATIVE_OFFICIAL_CURRENT_TICKER_LEVEL_RANKING_EXPORT"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

try {
    $output = & python $PythonScript 2>&1
    $exitCode = $LASTEXITCODE
    if ($output) {
        $output | ForEach-Object { Write-Host $_ }
    }
    if (Test-Path $ManifestPath) {
        $manifest = Get-Content -Raw $ManifestPath | ConvertFrom-Json
        Write-Host $manifest.status
    }
    exit $exitCode
}
catch {
    Write-Host "BLOCKED_V20_83_WRAPPER_FAILURE"
    Write-Host $_.Exception.Message
    exit 1
}
