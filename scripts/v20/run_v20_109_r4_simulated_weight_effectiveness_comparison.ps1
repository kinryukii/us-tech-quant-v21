$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Runner = Join-Path $ScriptDir "v20_109_r4_simulated_weight_effectiveness_comparison.py"

python $Runner
