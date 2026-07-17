[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [switch]$QuoteProbe,
    [switch]$RequireTcp
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v22\v22_047_r1c_moomoo_opend_connection_profile.py"
$Profile = Join-Path $RepoRoot "config\moomoo_opend_connection.json"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1C_MOOMOO_OPEND_CONNECTION_PROFILE\v22_047_r1c_opend_preflight.json"

if (-not (Test-Path $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path $Script)) { throw "Profile script not found: $Script" }
if (-not (Test-Path $Profile)) { throw "Profile not found: $Profile" }

$ArgsList = @($Script, "--profile", $Profile, "--output", $Output)
if ($QuoteProbe) { $ArgsList += "--quote-probe" }
if ($RequireTcp) { $ArgsList += "--require-tcp" }

& $Python @ArgsList
exit $LASTEXITCODE
