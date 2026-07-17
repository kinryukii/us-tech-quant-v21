[CmdletBinding(DefaultParameterSetName="Show")]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [Parameter(ParameterSetName="Set", Mandatory=$true)]
    [ValidateSet("OFF", "SHADOW", "PAPER", "LIVE", "FLATTEN_ONLY")]
    [string]$Mode,
    [Parameter(ParameterSetName="Set")]
    [string]$Note = "",
    [Parameter(ParameterSetName="Set")]
    [switch]$ConfirmLive,
    [Parameter(ParameterSetName="Show")]
    [switch]$Show
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v22\v22_047_r1b_auto_trading_control_component.py"

if (-not (Test-Path $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path $Script)) { throw "Component script not found: $Script" }

if ($PSCmdlet.ParameterSetName -eq "Set") {
    $argsList = @($Script, "--repo-root", $RepoRoot, "--set-switch", $Mode, "--switch-note", $Note)
    if ($ConfirmLive) { $argsList += "--confirm-live" }
    & $Python @argsList
} else {
    & $Python $Script --repo-root $RepoRoot --show-switch
}
exit $LASTEXITCODE
