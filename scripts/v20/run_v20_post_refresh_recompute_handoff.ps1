param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$ScriptPath = Join-Path $ScriptDir "v20_post_refresh_recompute_handoff.py"

Push-Location $RepoRoot
try {
    & $Python $ScriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "V20 post-refresh recompute handoff failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
