param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ApprovalPhrase = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_216_aggressive_compact_and_delete_expanded_outputs_after_approval.py"),
    "--repo-root",
    $Root
)
if ($ApprovalPhrase -ne "") {
    $ArgsList += @("--approval-phrase", $ApprovalPhrase)
}

& $Python @ArgsList
exit $LASTEXITCODE
