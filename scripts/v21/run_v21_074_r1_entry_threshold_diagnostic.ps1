Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
Push-Location $Root
try { python (Join-Path $Dir "v21_074_r1_entry_threshold_diagnostic.py"); exit $LASTEXITCODE }
finally { Pop-Location }
