param([string]$RepoRoot="D:\us-tech-quant",[string]$OutputDir="")
$ErrorActionPreference="Stop"
Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_248_technical_signal_failure_attribution_and_repair_spec_r1.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot)
if($OutputDir){$ArgsList+=@("--output-dir",$OutputDir)}
& $Python @ArgsList
exit $LASTEXITCODE
