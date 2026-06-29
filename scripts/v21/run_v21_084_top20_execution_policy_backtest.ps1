param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$OutputDir = ""
)

$script = Join-Path $Root "scripts\v21\v21_084_top20_execution_policy_backtest.py"
if ($OutputDir -ne "") {
    python $script --root $Root --output-dir $OutputDir
} else {
    python $script --root $Root
}
