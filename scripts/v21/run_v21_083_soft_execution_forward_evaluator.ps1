param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$OutputDir = ""
)

$script = Join-Path $Root "scripts\v21\v21_083_soft_execution_forward_evaluator.py"
if ($OutputDir -ne "") {
    python $script --root $Root --output-dir $OutputDir
} else {
    python $script --root $Root
}
