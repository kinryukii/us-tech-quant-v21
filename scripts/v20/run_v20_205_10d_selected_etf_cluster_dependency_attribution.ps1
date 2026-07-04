$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_205_10d_selected_etf_cluster_dependency_attribution.py"

python $Runner
