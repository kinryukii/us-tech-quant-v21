param([string]$RepoRoot="D:\us-tech-quant",[string]$OutputDir="")
$ErrorActionPreference="Stop"; Set-Location $RepoRoot
$Python=Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script=Join-Path $RepoRoot "scripts\v21\v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py"
$ArgsList=@($Script,"--repo-root",$RepoRoot); if($OutputDir){$ArgsList+=@("--output-dir",$OutputDir)}
& $Python @ArgsList
exit $LASTEXITCODE
