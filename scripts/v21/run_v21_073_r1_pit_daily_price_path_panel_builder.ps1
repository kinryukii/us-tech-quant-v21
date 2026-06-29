Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Push-Location $RepoRoot
try {
    python (Join-Path $ScriptDir "v21_073_r1_pit_daily_price_path_panel_builder.py")
    exit $LASTEXITCODE
}
finally { Pop-Location }
