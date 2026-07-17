[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [int]$OldPort = 11111,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v22\patch_v22_047_r1c_repo_opend_port_defaults.py"
$Profile = Join-Path $RepoRoot "config\moomoo_opend_connection.json"
$Report = Join-Path $RepoRoot "outputs\v22\V22.047_R1C_MOOMOO_OPEND_CONNECTION_PROFILE\v22_047_r1c_repo_port_patch_report.json"

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--profile", $Profile,
    "--old-port", [string]$OldPort,
    "--report", $Report
)
if ($Apply) { $ArgsList += "--apply" }

& $Python @ArgsList
exit $LASTEXITCODE
