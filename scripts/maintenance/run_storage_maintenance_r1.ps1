param(
    [switch]$Audit,
    [switch]$Migrate,
    [switch]$RetentionDryRun,
    [switch]$RetentionExecute,
    [switch]$Verify,
    [switch]$AllSafe
)
$ErrorActionPreference = 'Stop'

function Invoke-MaintenanceStep {
    param([string]$Name, [string[]]$StepArguments = @())
    $global:LASTEXITCODE = 0
    & (Join-Path $PSScriptRoot $Name) @StepArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Maintenance step failed: $Name (exit $LASTEXITCODE)"
    }
}

# Reject ambiguous calls before starting any step. AllSafe is read-only.
if ($AllSafe -and ($Migrate -or $RetentionExecute)) {
    throw 'AllSafe cannot be combined with Migrate or RetentionExecute.'
}

if ($Audit -or $AllSafe) {
    Invoke-MaintenanceStep 'run_audit_repo_size_r1.ps1'
}
if ($RetentionDryRun -or $AllSafe) {
    Invoke-MaintenanceStep 'run_enforce_retention_policy_r1.ps1'
}
if ($Verify) {
    Invoke-MaintenanceStep 'run_migrate_storage_layout_r1.ps1' @('-VerifyOnly')
}
if ($Migrate) {
    Invoke-MaintenanceStep 'run_migrate_storage_layout_r1.ps1' @('-Execute')
}
if ($RetentionExecute) {
    Invoke-MaintenanceStep 'run_enforce_retention_policy_r1.ps1' @('-Execute')
}
