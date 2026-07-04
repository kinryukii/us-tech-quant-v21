param(
  [string]$RepoRoot="D:\us-tech-quant",
  [string]$InputRoot="outputs/v21/V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1",
  [string]$OutputDir=""
)
$ErrorActionPreference="Stop"
Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_247_technical_subfactor_effectiveness_pit_lite_audit.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot,"--input-root",$InputRoot)
if($OutputDir){$ArgsList+=@("--output-dir",$OutputDir)}
& $Python @ArgsList
exit $LASTEXITCODE
