param([string]$RepoRoot="D:\us-tech-quant",[string]$OutputDir="")
$ErrorActionPreference="Stop"
Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_251_strategy_weight_governance_from_v21_255_and_current_regime_r1.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot)
if($OutputDir){$ArgsList+=@("--output-dir",$OutputDir)}
& $Python @ArgsList
exit $LASTEXITCODE
