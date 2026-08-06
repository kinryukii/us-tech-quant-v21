[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$DataRoot = "D:\us-tech-quant-data",
    [string]$ResultsRoot = "D:\us-tech-quant-results",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$Model = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host (" " + $Text)
    Write-Host ("=" * 80)
}

function Read-Json([string]$Path) {
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Write-Json([object]$Value,[string]$Path) {
    $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Full([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Relative-To([string]$Root,[string]$Path) {
    $rootFull = (Full $Root) + '\'
    $pathFull = [IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull,[StringComparison]::OrdinalIgnoreCase)) {
        return $pathFull
    }
    return $pathFull.Substring($rootFull.Length).Replace('/','\')
}

function Kill-Tree([int]$Pid) {
    try { & taskkill.exe /PID $Pid /T /F 2>$null | Out-Null } catch {}
}

function Test-PathUnderPrefix([string]$Path,[string[]]$Prefixes) {
    $fullPath = Full $Path
    foreach ($prefix in $Prefixes) {
        $p = Full $prefix
        if ($fullPath -eq $p -or
            $fullPath.StartsWith($p + '\',[StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-OpaqueDirectoryState([string]$Root,[string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $aclHash = $null
    $aclReadable = $false
    try {
        $sddl = (Get-Acl -LiteralPath $Path -ErrorAction Stop).Sddl
        $bytes = [Text.Encoding]::UTF8.GetBytes($sddl)
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $aclHash = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-","").ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }
        $aclReadable = $true
    } catch {
        $aclHash = "UNREADABLE"
    }
    return [ordered]@{
        relative_path=(Relative-To $Root $Path)
        last_write_utc_ticks=$item.LastWriteTimeUtc.Ticks
        attributes=[string]$item.Attributes
        acl_readable=$aclReadable
        acl_sddl_sha256=$aclHash
    }
}

function Snapshot-Repo(
    [string]$Root,
    [string[]]$SkipPrefixes,
    [string[]]$OpaqueDirectoryNames,
    [ref]$OpaqueState
) {
    $map = [ordered]@{}
    $opaque = [ordered]@{}
    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push((Full $Root))

    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        $items = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)
        foreach ($item in $items) {
            $fullPath = Full $item.FullName
            if (Test-PathUnderPrefix $fullPath $SkipPrefixes) {
                continue
            }

            if ($item.PSIsContainer) {
                $isOpaque = $false
                foreach ($name in $OpaqueDirectoryNames) {
                    if ($item.Name.Equals($name,[StringComparison]::OrdinalIgnoreCase)) {
                        $isOpaque = $true
                        break
                    }
                }
                if ($isOpaque) {
                    $rel = Relative-To $Root $fullPath
                    $opaque[$rel.ToLowerInvariant()] = Get-OpaqueDirectoryState $Root $fullPath
                    continue
                }
                $stack.Push($fullPath)
                continue
            }

            $rel = Relative-To $Root $fullPath
            $map[$rel.ToLowerInvariant()] = [ordered]@{
                relative_path=$rel
                length=$item.Length
                last_write_utc_ticks=$item.LastWriteTimeUtc.Ticks
                sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }

    $OpaqueState.Value = $opaque
    return $map
}

function Compare-OpaqueDirectoryStates([object]$Before,[object]$After) {
    $violations = New-Object System.Collections.Generic.List[string]
    $beforeNames = @($Before.Keys)
    $afterNames = @($After.Keys)
    $allNames = @($beforeNames + $afterNames | Sort-Object -Unique)

    foreach ($key in $allNames) {
        $hasBefore = $Before.Contains($key)
        $hasAfter = $After.Contains($key)
        if (-not $hasBefore) {
            $violations.Add("OPAQUE_CREATED:$key")
            continue
        }
        if (-not $hasAfter) {
            $violations.Add("OPAQUE_DELETED:$key")
            continue
        }

        $b = $Before[$key]
        $a = $After[$key]
        if ([long]$b.last_write_utc_ticks -ne [long]$a.last_write_utc_ticks -or
            [string]$b.attributes -ne [string]$a.attributes -or
            [string]$b.acl_sddl_sha256 -ne [string]$a.acl_sddl_sha256) {
            $violations.Add("OPAQUE_METADATA_CHANGED:$key")
        }
    }
    return ,([string[]]$violations.ToArray())
}

function Snapshot-Metadata([string]$Root) {
    $map = [ordered]@{}
    foreach ($f in Get-ChildItem -LiteralPath $Root -Force -File -Recurse -ErrorAction Stop) {
        $rel = Relative-To $Root $f.FullName
        $map[$rel.ToLowerInvariant()] = [ordered]@{
            relative_path=$rel
            length=$f.Length
            last_write_utc_ticks=$f.LastWriteTimeUtc.Ticks
        }
    }
    return $map
}

function Compare-Snapshots([object]$Before,[object]$After,[hashtable]$AllowedChanges) {
    $violations = New-Object System.Collections.Generic.List[string]
    $beforeNames = @($Before.Keys)
    $afterNames = @($After.Keys)
    $allNames = @($beforeNames + $afterNames | Sort-Object -Unique)
    foreach ($key in $allNames) {
        if ($AllowedChanges.ContainsKey(([string]$key).ToLowerInvariant())) { continue }
        $hasBefore = $Before.Contains($key)
        $hasAfter = $After.Contains($key)
        if (-not $hasBefore) {
            $violations.Add("CREATED:$key")
            continue
        }
        if (-not $hasAfter) {
            $violations.Add("DELETED:$key")
            continue
        }
        $b = $Before[$key]
        $a = $After[$key]
        if ([string]$b.sha256 -ne [string]$a.sha256 -or
            [long]$b.length -ne [long]$a.length) {
            $violations.Add("MODIFIED:$key")
        }
    }
    return ,([string[]]$violations.ToArray())
}

function Compare-Metadata([object]$Before,[object]$After) {
    $violations = New-Object System.Collections.Generic.List[string]
    $beforeNames = @($Before.Keys)
    $afterNames = @($After.Keys)
    $allNames = @($beforeNames + $afterNames | Sort-Object -Unique)
    foreach ($key in $allNames) {
        $hasBefore = $Before.Contains($key)
        $hasAfter = $After.Contains($key)
        if (-not $hasBefore) { $violations.Add("CREATED:$key"); continue }
        if (-not $hasAfter) { $violations.Add("DELETED:$key"); continue }
        $b = $Before[$key]
        $a = $After[$key]
        if ([long]$b.length -ne [long]$a.length -or
            [long]$b.last_write_utc_ticks -ne [long]$a.last_write_utc_ticks) {
            $violations.Add("METADATA_CHANGED:$key")
        }
    }
    return ,([string[]]$violations.ToArray())
}

function Find-SummaryRoot([string]$SearchRoot,[string]$FileName,[scriptblock]$Predicate) {
    foreach ($f in Get-ChildItem -LiteralPath $SearchRoot -Filter $FileName -File -Recurse -ErrorAction SilentlyContinue) {
        try {
            $j = Read-Json $f.FullName
            if (& $Predicate $j) {
                return $f.Directory.FullName
            }
        } catch {}
    }
    return $null
}

function Ensure-External-R3([string]$Repo,[string]$Results) {
    $r3 = Find-SummaryRoot $Results "fast3_event_factor_r3_summary.json" {
        param($j)
        ([string]$j.RUN_ID -eq "20260802_211307" -and
         [string]$j.FINAL_DECISION -eq "STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY")
    }
    $audit = Find-SummaryRoot $Results "fast3_r3_post_audit_summary.json" {
        param($j)
        ([string]$j.SOURCE_R3_RUN_ID -eq "20260802_211307" -and
         [string]$j.FINAL_DECISION -eq "PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN")
    }

    $migrationRoot = Join-Path $Results "archive\fast3\legacy_migration"
    if ($null -eq $r3) {
        $legacyR3 = Join-Path $Repo ".local_results\fast3\event_factor_cohort_r3\20260802_211307"
        if (Test-Path -LiteralPath $legacyR3 -PathType Container) {
            $dst = Join-Path $migrationRoot "event_factor_cohort_r3\20260802_211307"
            if (-not (Test-Path -LiteralPath $dst -PathType Container)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
                Copy-Item -LiteralPath $legacyR3 -Destination $dst -Recurse -Force
            }
            $r3 = $dst
        }
    }
    if ($null -eq $audit) {
        $legacyAuditCandidates = @(
            (Join-Path $Repo ".local_results\fast3\r3_economic_integrity_audit\20260802_230000"),
            (Join-Path $Repo ".local_results\fast3\r3_economic_integrity_audit\20260802_225457")
        )
        foreach ($legacyAudit in $legacyAuditCandidates) {
            if (Test-Path -LiteralPath $legacyAudit -PathType Container) {
                $dst = Join-Path $migrationRoot ("r3_economic_integrity_audit\" + (Split-Path -Leaf $legacyAudit))
                if (-not (Test-Path -LiteralPath $dst -PathType Container)) {
                    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
                    Copy-Item -LiteralPath $legacyAudit -Destination $dst -Recurse -Force
                }
                $audit = $dst
                break
            }
        }
    }
    return [ordered]@{ r3=$r3; audit=$audit }
}

function Restore-AclSddl([string]$Path,[string]$Sddl) {
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm($Sddl)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Drain-WatcherEvents(
    [hashtable]$AllowedFiles,
    [hashtable]$AllowedDirs,
    [System.Collections.Generic.List[string]]$RepoViolations,
    [System.Collections.Generic.List[string]]$DataEvents,
    [System.Collections.Generic.List[string]]$LocalEvents,
    [ref]$ViolationReason,
    [string]$Repo,
    [string]$Data
) {
    $events = @(Get-Event -ErrorAction SilentlyContinue)
    foreach ($evt in $events) {
        $source = [string]$evt.SourceIdentifier
        $ea = $evt.SourceEventArgs
        try {
            if ($source.StartsWith("R4Data_")) {
                $detail = $source
                if ($null -ne $ea -and $ea.PSObject.Properties.Name -contains "FullPath") {
                    $detail += ":" + [string]$ea.FullPath
                }
                $DataEvents.Add($detail)
                $ViolationReason.Value = "CANONICAL_FILESYSTEM_EVENT"
            } elseif ($source.StartsWith("R4Repo_")) {
                if ($source.EndsWith("_Error")) {
                    $RepoViolations.Add("WATCHER_ERROR")
                    $ViolationReason.Value = "REPOSITORY_WATCHER_ERROR"
                } elseif ($null -ne $ea -and $ea.PSObject.Properties.Name -contains "FullPath") {
                    $paths = @([string]$ea.FullPath)
                    if ($ea.PSObject.Properties.Name -contains "OldFullPath") {
                        $paths += [string]$ea.OldFullPath
                    }
                    foreach ($path in $paths) {
                        if ([string]::IsNullOrWhiteSpace($path)) { continue }
                        $fullPath = [IO.Path]::GetFullPath($path).TrimEnd('\')
                        $lower = $fullPath.ToLowerInvariant()
                        $gitRoot = (Full (Join-Path $Repo ".git")).ToLowerInvariant()
                        $localRoot = (Full (Join-Path $Repo ".local_results")).ToLowerInvariant()

                        if ($lower -eq $gitRoot -or $lower.StartsWith($gitRoot + '\')) {
                            $RepoViolations.Add("GIT_WRITE:$fullPath")
                            $ViolationReason.Value = "GIT_DIRECTORY_WRITE"
                            continue
                        }
                        if ($lower -eq $localRoot -or $lower.StartsWith($localRoot + '\')) {
                            $LocalEvents.Add($fullPath)
                            $ViolationReason.Value = "LOCAL_RESULTS_WRITE"
                            continue
                        }
                        if ($AllowedFiles.ContainsKey($lower) -or $AllowedDirs.ContainsKey($lower)) {
                            continue
                        }

                        $tempAllowed = $false
                        foreach ($allowedKey in @($AllowedFiles.Keys)) {
                            $allowedPath = [string]$allowedKey
                            $allowedDir = [IO.Path]::GetDirectoryName($allowedPath)
                            $allowedName = [IO.Path]::GetFileName($allowedPath)
                            if ([IO.Path]::GetDirectoryName($lower) -eq $allowedDir) {
                                $name = [IO.Path]::GetFileName($lower)
                                if (($name.StartsWith("." + $allowedName) -or $name.StartsWith($allowedName + ".")) -and
                                    ($name.EndsWith(".tmp") -or $name.EndsWith(".temp") -or $name.EndsWith("~"))) {
                                    $tempAllowed = $true
                                    break
                                }
                            }
                        }
                        if (-not $tempAllowed) {
                            $RepoViolations.Add("UNAUTHORIZED_REPO_EVENT:$fullPath")
                            $ViolationReason.Value = "UNAUTHORIZED_REPOSITORY_WRITE"
                        }
                    }
                }
            }
        } finally {
            Remove-Event -EventIdentifier $evt.EventIdentifier -ErrorAction SilentlyContinue
        }
    }
}

function Run-MonitoredProcess(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$StdoutPath,
    [string]$StderrPath,
    [hashtable]$AllowedFiles,
    [hashtable]$AllowedDirs,
    [System.Collections.Generic.List[string]]$RepoViolations,
    [System.Collections.Generic.List[string]]$DataEvents,
    [System.Collections.Generic.List[string]]$LocalEvents,
    [ref]$ViolationReason,
    [string]$Repo,
    [string]$Data
) {
    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath -PassThru

    while (-not $proc.HasExited) {
        Wait-Event -Timeout 0.20 | Out-Null
        Drain-WatcherEvents $AllowedFiles $AllowedDirs $RepoViolations $DataEvents $LocalEvents $ViolationReason $Repo $Data
        if (-not [string]::IsNullOrWhiteSpace([string]$ViolationReason.Value)) {
            Kill-Tree $proc.Id
            break
        }
        $proc.Refresh()
    }
    try { $proc.WaitForExit() } catch {}
    Start-Sleep -Milliseconds 500
    Drain-WatcherEvents $AllowedFiles $AllowedDirs $RepoViolations $DataEvents $LocalEvents $ViolationReason $Repo $Data
    return $proc.ExitCode
}

$RepoRoot = Full $RepoRoot
$DataRoot = Full $DataRoot
$ResultsRoot = Full $ResultsRoot
$CacheRoot = Full $CacheRoot

foreach ($p in @($RepoRoot,$DataRoot,$ResultsRoot,$CacheRoot)) {
    if (-not (Test-Path -LiteralPath $p -PathType Container)) {
        throw "Required root missing: $p"
    }
}
$repoPrefix = $RepoRoot.TrimEnd('\') + '\'
if ($ResultsRoot.StartsWith($repoPrefix,[StringComparison]::OrdinalIgnoreCase) -or
    $CacheRoot.StartsWith($repoPrefix,[StringComparison]::OrdinalIgnoreCase) -or
    $DataRoot.StartsWith($repoPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw "Data, results and cache roots must be outside the repository."
}

$LimitsPath = Join-Path $RepoRoot "config\fast3\agent\FAST3_R4_TWO_STAGE_DIRECTION_HARD_R23_LIMITS.json"
$PromptPath = Join-Path $RepoRoot "docs\fast3\agent\FAST3_R4_TWO_STAGE_DIRECTION_HARD_R23_AGENT.md"
foreach ($p in @($LimitsPath,$PromptPath)) {
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
        throw "Required deployed control file missing: $p"
    }
}
$limits = Read-Json $LimitsPath

$expectedControlRefs = @(
    $LimitsPath,
    $PromptPath,
    (Join-Path $RepoRoot "scripts\fast3\agent\run_fast3_r4_two_stage_direction_hard_r23_agent.ps1"),
    (Join-Path $RepoRoot "scripts\fast3\agent\show_fast3_r4_two_stage_direction_hard_r23_status.ps1")
)
foreach ($controlRef in $expectedControlRefs) {
    if (-not (Test-Path -LiteralPath $controlRef -PathType Leaf)) {
        throw "R23_CONTROL_REFERENCE_SELFTEST_FAILED: $controlRef"
    }
}
Write-Host "R23_CONTROL_REFERENCE_SELFTEST_PASS=true"


$RunId = (Get-Date).ToString("yyyyMMdd_HHmmss")
$RuntimeRoot = Join-Path $ResultsRoot "runtime\fast3\r4_two_stage_direction\$RunId"
$ScratchRoot = Join-Path $ResultsRoot "scratch\fast3\r4_two_stage_direction\$RunId"
$FrozenRoot = Join-Path $ResultsRoot "frozen\fast3\r4_two_stage_direction\$RunId"
$ArchiveRunRoot = Join-Path $ResultsRoot "archive\fast3\r4_two_stage_direction\$RunId"
$RunCacheRoot = Join-Path $CacheRoot "fast3\r4_two_stage_direction\$RunId"
foreach ($p in @($RuntimeRoot,$ScratchRoot,$FrozenRoot,$RunCacheRoot)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}

$StateRoot = Join-Path $ResultsRoot "runtime\fast3\r4_two_stage_direction\state"
New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
$LockPath = Join-Path $StateRoot "active_hard_r23.lock.json"
if (Test-Path -LiteralPath $LockPath -PathType Leaf) {
    try {
        $old = Read-Json $LockPath
        if (Get-Process -Id ([int]$old.pid) -ErrorAction SilentlyContinue) {
            throw "R4 hard-storage Agent is already running. PID=$($old.pid)"
        }
    } catch {
        if ($_.Exception.Message -like "R4 hard-storage Agent is already running*") { throw }
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}
Write-Json ([ordered]@{
    pid=$PID
    run_id=$RunId
    started_at=(Get-Date).ToString("o")
    runtime_root=$RuntimeRoot
    scratch_root=$ScratchRoot
    frozen_root=$FrozenRoot
}) $LockPath

$allowedFiles = @{}
$allowedDirs = @{}
foreach ($rel in @($limits.agent_repo_write_allowlist)) {
    $fullPath = Full (Join-Path $RepoRoot ([string]$rel).Replace('/','\'))
    $allowedFiles[$fullPath.ToLowerInvariant()] = $true
    $dir = [IO.Path]::GetDirectoryName($fullPath)
    while ($dir -and $dir.StartsWith($RepoRoot,[StringComparison]::OrdinalIgnoreCase)) {
        $allowedDirs[(Full $dir).ToLowerInvariant()] = $true
        if ((Full $dir) -eq $RepoRoot) { break }
        $dir = [IO.Path]::GetDirectoryName($dir)
    }
}
$allowedDirs[$RepoRoot.ToLowerInvariant()] = $true

$RepoWatcher = $null
$DataWatcher = $null
$EventSubscriptions = @()
$OriginalDataSddl = $null
$AclGuardActive = $false
$RepoViolations = New-Object System.Collections.Generic.List[string]
$DataEvents = New-Object System.Collections.Generic.List[string]
$LocalEvents = New-Object System.Collections.Generic.List[string]
$ViolationReason = ""
$ImplementationExit = $null
$TestExit = $null
$ResearchExit = $null
$ArchiveFinalized = $false
$FinalDecision = "STOP_R4_HARD_STORAGE_PREFLIGHT_FAILED"
$SummaryReadable = $false
$RequiredArtifactsPresent = $false
$RepoSnapshotViolations = @()
$RepoOpaqueSnapshotViolations = @()
$CanonicalSnapshotViolations = @()
$BeforeRepoOpaque = [ordered]@{}
$AfterRepoOpaque = [ordered]@{}
$R3Root = $null
$R3AuditRoot = $null
$BeforeRepo = $null
$BeforeCanonical = $null
$BeforeLocal = $null
$AgentBackups = @()

try {
    Section "R4 hard-storage preflight"
    $emptyCollectionSelfTest = @(Compare-Metadata ([ordered]@{}) ([ordered]@{}))
    if (@($emptyCollectionSelfTest).Count -ne 0) {
        throw "R23_EMPTY_COLLECTION_SELFTEST_FAILED"
    }
    Write-Host "R23_EMPTY_COLLECTION_SELFTEST_PASS=true"

    Write-Host "RUN_ID=$RunId"
    Write-Host "REPO_ROOT=$RepoRoot"
    Write-Host "DATA_ROOT=$DataRoot"
    Write-Host "RUNTIME_ROOT=$RuntimeRoot"
    Write-Host "SCRATCH_ROOT=$ScratchRoot"
    Write-Host "FROZEN_ROOT=$FrozenRoot"
    Write-Host "ARCHIVE_RUN_ROOT=$ArchiveRunRoot"
    Write-Host "CACHE_ROOT=$RunCacheRoot"
    Write-Host "GIT_MUTATION_ALLOWED=false"
    Write-Host "PRESERVE_EXISTING_UNTRACKED_FILES=true"

    $sources = Ensure-External-R3 $RepoRoot $ResultsRoot
    $R3Root = [string]$sources.r3
    $R3AuditRoot = [string]$sources.audit
    if ([string]::IsNullOrWhiteSpace($R3Root) -or [string]::IsNullOrWhiteSpace($R3AuditRoot)) {
        throw "External R3 source or R3 post-audit evidence not found."
    }

    $preexistingAgentTargets = @()
    foreach ($key in @($allowedFiles.Keys)) {
        $path = [string]$key
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $preexistingAgentTargets += [ordered]@{
                relative_path=(Relative-To $RepoRoot $path)
                source_path=$path
                sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    Write-Json ([ordered]@{
        run_id=$RunId
        preexisting_agent_target_count=$preexistingAgentTargets.Count
        preexisting_agent_targets=$preexistingAgentTargets
        existing_files_overwritten=$false
        unrelated_files_will_not_be_modified=$true
    }) (Join-Path $FrozenRoot "FAST3_R4_PREEXISTING_SOURCE_BACKUP_MANIFEST.json")
    if ($preexistingAgentTargets.Count -gt 0) {
        throw "R4 hard-R2.2 implementation target already exists. It was preserved and not overwritten. Use a clean new target version or inspect the existing implementation."
    }

    $skipPrefixes = @((Join-Path $RepoRoot ".git"),(Join-Path $RepoRoot ".local_results"))
    $opaqueDirectoryNames = @(
        ".pytest_cache",
        ".venv",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "__pycache__",
        ".tox"
    )
    $BeforeRepo = Snapshot-Repo $RepoRoot $skipPrefixes $opaqueDirectoryNames ([ref]$BeforeRepoOpaque)
    $BeforeCanonical = Snapshot-Metadata $DataRoot
    $localPath = Join-Path $RepoRoot ".local_results"
    if (Test-Path -LiteralPath $localPath -PathType Container) {
        $BeforeLocal = Snapshot-Metadata $localPath
    } else {
        $BeforeLocal = [ordered]@{}
    }

    # Install a fail-closed inheritable deny-write ACL on canonical data.
    $dataAcl = Get-Acl -LiteralPath $DataRoot
    $OriginalDataSddl = $dataAcl.Sddl
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $sid = $identity.User
    $rights = [System.Security.AccessControl.FileSystemRights]::CreateFiles `
        -bor [System.Security.AccessControl.FileSystemRights]::CreateDirectories `
        -bor [System.Security.AccessControl.FileSystemRights]::WriteData `
        -bor [System.Security.AccessControl.FileSystemRights]::AppendData `
        -bor [System.Security.AccessControl.FileSystemRights]::WriteAttributes `
        -bor [System.Security.AccessControl.FileSystemRights]::WriteExtendedAttributes `
        -bor [System.Security.AccessControl.FileSystemRights]::Delete `
        -bor [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    $denyRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        $rights,
        [System.Security.AccessControl.InheritanceFlags]"ContainerInherit,ObjectInherit",
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Deny
    )
    [void]$dataAcl.AddAccessRule($denyRule)
    Set-Acl -LiteralPath $DataRoot -AclObject $dataAcl

    $verified = $false
    foreach ($ace in (Get-Acl -LiteralPath $DataRoot).Access) {
        try {
            $aceSid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier])
            if ($aceSid.Value -eq $sid.Value -and
                $ace.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny -and
                (($ace.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::WriteData) -ne 0)) {
                $verified = $true
                break
            }
        } catch {}
    }
    if (-not $verified) {
        throw "Canonical deny-write ACL could not be verified."
    }
    $AclGuardActive = $true
    Write-Host "CANONICAL_ACL_GUARD_ACTIVE=true"

    $RepoWatcher = New-Object System.IO.FileSystemWatcher
    $RepoWatcher.Path = $RepoRoot
    $RepoWatcher.IncludeSubdirectories = $true
    $RepoWatcher.NotifyFilter = [IO.NotifyFilters]'FileName, DirectoryName, LastWrite, Size, Security'
    $RepoWatcher.EnableRaisingEvents = $true

    $DataWatcher = New-Object System.IO.FileSystemWatcher
    $DataWatcher.Path = $DataRoot
    $DataWatcher.IncludeSubdirectories = $true
    $DataWatcher.NotifyFilter = [IO.NotifyFilters]'FileName, DirectoryName, LastWrite, Size, Security'
    $DataWatcher.EnableRaisingEvents = $true

    foreach ($name in @("Changed","Created","Deleted","Renamed","Error")) {
        $EventSubscriptions += Register-ObjectEvent -InputObject $RepoWatcher -EventName $name -SourceIdentifier ("R4Repo_" + $name)
        $EventSubscriptions += Register-ObjectEvent -InputObject $DataWatcher -EventName $name -SourceIdentifier ("R4Data_" + $name)
    }

    $tempRoot = Join-Path $RunCacheRoot "temp"
    $pycache = Join-Path $RunCacheRoot "pycache"
    $pytestCache = Join-Path $RunCacheRoot "pytest_cache"
    $pytestTemp = Join-Path $RunCacheRoot "pytest_temp"
    $joblibTemp = Join-Path $RunCacheRoot "joblib"
    $mplCache = Join-Path $RunCacheRoot "matplotlib"
    $numbaCache = Join-Path $RunCacheRoot "numba"
    foreach ($p in @($tempRoot,$pycache,$pytestCache,$pytestTemp,$joblibTemp,$mplCache,$numbaCache)) {
        New-Item -ItemType Directory -Force -Path $p | Out-Null
    }

    $env:FAST3_REPO_ROOT = $RepoRoot
    $env:FAST3_DATA_ROOT = $DataRoot
    $env:FAST3_RESULTS_ROOT = $ResultsRoot
    $env:FAST3_RUNTIME_ROOT = $RuntimeRoot
    $env:FAST3_SCRATCH_ROOT = $ScratchRoot
    $env:FAST3_FROZEN_ROOT = $FrozenRoot
    $env:FAST3_ARCHIVE_ROOT = $ArchiveRunRoot
    $env:FAST3_CACHE_ROOT = $RunCacheRoot
    $env:FAST3_AGENT_RUN_ID = $RunId
    $env:FAST3_AGENT_LIMITS_PATH = $LimitsPath
    $env:FAST3_R3_SOURCE_ROOT = $R3Root
    $env:FAST3_R3_AUDIT_ROOT = $R3AuditRoot
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHONPYCACHEPREFIX = $pycache
    $env:PYTEST_ADDOPTS = "-o cache_dir=$pytestCache --basetemp=$pytestTemp"
    $env:JOBLIB_TEMP_FOLDER = $joblibTemp
    $env:MPLCONFIGDIR = $mplCache
    $env:NUMBA_CACHE_DIR = $numbaCache
    $env:XDG_CACHE_HOME = $RunCacheRoot
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $env:LOKY_MAX_CPU_COUNT = "2"
    $env:GIT_OPTIONAL_LOCKS = "0"

    $blockedBin = Join-Path $RunCacheRoot "blocked_bin"
    New-Item -ItemType Directory -Force -Path $blockedBin | Out-Null
    $gitBlocker = Join-Path $blockedBin "git.cmd"
    @"
@echo off
echo FAST3_R4_GIT_COMMAND_BLOCKED 1>&2
exit /b 97
"@ | Set-Content -LiteralPath $gitBlocker -Encoding ASCII
    $env:PATH = $blockedBin + ";" + $env:PATH
    $env:FAST3_GIT_COMMAND_BLOCKER_ACTIVE = "1"


    $preflight = [ordered]@{
        run_id=$RunId
        storage_contract="FAST3_STORAGE_CONTRACT_R1"
        repo_root=$RepoRoot
        data_root=$DataRoot
        runtime_root=$RuntimeRoot
        scratch_root=$ScratchRoot
        frozen_root=$FrozenRoot
        archive_root=$ArchiveRunRoot
        cache_root=$RunCacheRoot
        canonical_acl_guard_active=$AclGuardActive
        r3_source_root=$R3Root
        r3_audit_root=$R3AuditRoot
        local_results_existing=(Test-Path -LiteralPath $localPath -PathType Container)
        local_results_read_only_preserved=$true
        git_mutation_allowed=$false
        existing_untracked_files_preserved=$true
        status="PASS"
    }
    Write-Json $preflight (Join-Path $FrozenRoot "FAST3_R4_HARD_STORAGE_PREFLIGHT.json")

    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -eq $codex) { throw "Codex CLI not found." }

    $python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $pyCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pyCmd) { throw "Python executable not found." }
        $python = $pyCmd.Source
    }

    # Phase 1: one bounded Codex implementation pass. No full research.
    $agentInput = Join-Path $RuntimeRoot "implementation_agent_input.md"
    $agentStdout = Join-Path $RuntimeRoot "implementation_codex_stdout.jsonl"
    $agentStderr = Join-Path $RuntimeRoot "implementation_codex_stderr.log"
    $agentFinal = Join-Path $RuntimeRoot "implementation_codex_final.md"
    $agentWrapper = Join-Path $RunCacheRoot "invoke_codex_implementation.ps1"

    $instruction = @"
Implement and unit-test FAST3 R4 hard-storage R2.3.

Do not run the full R4 historical study. The outer launcher will run it exactly once.

Write source only to the exact allowlist in FAST3_AGENT_LIMITS_PATH. Do not touch any other repository file, .git or .local_results. Do not execute Git commands.

Use existing FAST3 modules read-only where possible. Build the fixed direct-versus-two-stage comparison, leakage controls, deterministic eight-block schedule, development early stop, internal holdout, nulls, economic diagnostics, frozen artifacts and prospective model freeze described in the contract.

All tests and temporary files must use FAST3_CACHE_ROOT.
"@
    $contract = Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8
    Set-Content -LiteralPath $agentInput -Value ($instruction + "`r`n`r`n--- CONTRACT ---`r`n" + $contract) -Encoding UTF8

    $wrapperText = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Push-Location $env:FAST3_REPO_ROOT
try {
    $args = @(
        "--ask-for-approval","never",
        "exec","--json",
        "--sandbox","workspace-write",
        "--add-dir",$env:FAST3_CACHE_ROOT,
        "--output-last-message",$env:FAST3_CODEX_FINAL_MESSAGE
    )
    if (-not [string]::IsNullOrWhiteSpace($env:FAST3_CODEX_MODEL)) {
        $args += @("--model",$env:FAST3_CODEX_MODEL)
    }
    $args += "-"
    Get-Content -LiteralPath $env:FAST3_CODEX_INPUT -Raw -Encoding UTF8 |
        & $env:FAST3_CODEX_PATH @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
'@
    Set-Content -LiteralPath $agentWrapper -Value $wrapperText -Encoding UTF8
    $env:FAST3_CODEX_INPUT = $agentInput
    $env:FAST3_CODEX_FINAL_MESSAGE = $agentFinal
    $env:FAST3_CODEX_PATH = $codex.Source
    $env:FAST3_CODEX_MODEL = $Model

    Section "Phase 1: bounded R4 implementation"
    $ImplementationExit = Run-MonitoredProcess `
        "powershell.exe" `
        @("-NoProfile","-ExecutionPolicy","Bypass","-File",('"{0}"' -f $agentWrapper)) `
        $RepoRoot $agentStdout $agentStderr `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    if (-not [string]::IsNullOrWhiteSpace($ViolationReason)) {
        $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
        throw "Storage violation during implementation: $ViolationReason"
    }
    if ($ImplementationExit -ne 0) {
        $FinalDecision = "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED"
        throw "Codex implementation failed with exit code $ImplementationExit."
    }

    foreach ($key in @($allowedFiles.Keys)) {
        if (-not (Test-Path -LiteralPath ([string]$key) -PathType Leaf)) {
            # Only the two prospective files are optional until a pass.
            $leaf = [IO.Path]::GetFileName([string]$key)
            if ($leaf -notlike "*prospective_shadow*") {
                $FinalDecision = "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED"
                throw "Required implementation file missing: $key"
            }
        }
    }

    # Phase 2: exact unit tests, outside Codex.
    $testFile = Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r23.py"
    $testStdout = Join-Path $RuntimeRoot "pytest_stdout.log"
    $testStderr = Join-Path $RuntimeRoot "pytest_stderr.log"
    $testWrapper = Join-Path $RunCacheRoot "invoke_pytest.ps1"
    $env:FAST3_PYTHON_PATH = $python
    $env:FAST3_TEST_FILE = $testFile
    Set-Content -LiteralPath $testWrapper -Encoding UTF8 -Value @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Push-Location $env:FAST3_REPO_ROOT
try {
    & $env:FAST3_PYTHON_PATH -m pytest $env:FAST3_TEST_FILE -q
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
'@

    Section "Phase 2: unit tests"
    $TestExit = Run-MonitoredProcess `
        "powershell.exe" `
        @("-NoProfile","-ExecutionPolicy","Bypass","-File",('"{0}"' -f $testWrapper)) `
        $RepoRoot $testStdout $testStderr `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    if (-not [string]::IsNullOrWhiteSpace($ViolationReason)) {
        $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
        throw "Storage violation during tests: $ViolationReason"
    }
    if ($TestExit -ne 0) {
        $FinalDecision = "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED"
        throw "R4 unit tests failed with exit code $TestExit."
    }

    # Phase 3: run the full historical architecture study exactly once.
    $researchScript = Join-Path $RepoRoot "fast3\scripts\run\fast3_r4_two_stage_direction_hard_r23.py"
    if (-not (Test-Path -LiteralPath $researchScript -PathType Leaf)) {
        $FinalDecision = "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED"
        throw "Research entrypoint missing: $researchScript"
    }

    $researchStdout = Join-Path $RuntimeRoot "research_stdout.log"
    $researchStderr = Join-Path $RuntimeRoot "research_stderr.log"
    $researchWrapper = Join-Path $RunCacheRoot "invoke_research.ps1"
    $env:FAST3_RESEARCH_SCRIPT = $researchScript
    Set-Content -LiteralPath $researchWrapper -Encoding UTF8 -Value @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Push-Location $env:FAST3_REPO_ROOT
try {
    & $env:FAST3_PYTHON_PATH $env:FAST3_RESEARCH_SCRIPT `
        --repo-root $env:FAST3_REPO_ROOT `
        --data-root $env:FAST3_DATA_ROOT `
        --runtime-root $env:FAST3_RUNTIME_ROOT `
        --scratch-root $env:FAST3_SCRATCH_ROOT `
        --frozen-root $env:FAST3_FROZEN_ROOT `
        --cache-root $env:FAST3_CACHE_ROOT `
        --source-r3-root $env:FAST3_R3_SOURCE_ROOT `
        --source-r3-audit-root $env:FAST3_R3_AUDIT_ROOT `
        --limits $env:FAST3_AGENT_LIMITS_PATH `
        --run-id $env:FAST3_AGENT_RUN_ID
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
'@

    Section "Phase 3: one bounded R4 historical run"
    $ResearchExit = Run-MonitoredProcess `
        "powershell.exe" `
        @("-NoProfile","-ExecutionPolicy","Bypass","-File",('"{0}"' -f $researchWrapper)) `
        $RepoRoot $researchStdout $researchStderr `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    if (-not [string]::IsNullOrWhiteSpace($ViolationReason)) {
        $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
        throw "Storage violation during research: $ViolationReason"
    }

    $summaryPath = Join-Path $FrozenRoot "fast3_r4_two_stage_direction_summary.json"
    if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
        try {
            $summary = Read-Json $summaryPath
            $candidateDecision = [string]$summary.FINAL_DECISION
            if (@($limits.decisions) -contains $candidateDecision) {
                $FinalDecision = $candidateDecision
                $SummaryReadable = $true
            }
        } catch {}
    }

    if ($ResearchExit -ne 0 -and -not $SummaryReadable) {
        $FinalDecision = "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED"
        throw "Research runner failed without a readable terminal summary. Exit=$ResearchExit"
    }

    $artifactState = [ordered]@{}
    foreach ($name in @($limits.required_frozen_artifacts)) {
        $artifactState[$name] = Test-Path -LiteralPath (Join-Path $FrozenRoot ([string]$name)) -PathType Leaf
    }
    $RequiredArtifactsPresent = -not ($artifactState.Values -contains $false)
}
catch {
    $errorText = $_ | Out-String
    Set-Content -LiteralPath (Join-Path $RuntimeRoot "launcher_exception.log") -Value $errorText -Encoding UTF8
}
finally {
    # Drain and stop watchers before ACL restoration.
    try {
        Drain-WatcherEvents $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents ([ref]$ViolationReason) $RepoRoot $DataRoot
    } catch {}

    foreach ($sub in $EventSubscriptions) {
        try { Unregister-Event -SourceIdentifier $sub.Name -ErrorAction SilentlyContinue } catch {}
    }
    try { Get-Event | Remove-Event -ErrorAction SilentlyContinue } catch {}
    if ($null -ne $RepoWatcher) { try { $RepoWatcher.Dispose() } catch {} }
    if ($null -ne $DataWatcher) { try { $DataWatcher.Dispose() } catch {} }

    if ($AclGuardActive -and -not [string]::IsNullOrWhiteSpace($OriginalDataSddl)) {
        try {
            Restore-AclSddl $DataRoot $OriginalDataSddl
        } catch {
            $ViolationReason = "CANONICAL_ACL_RESTORE_FAILED"
            $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
        }
    }

    # Post-run repository and canonical audits.
    try {
        $afterRepo = Snapshot-Repo `
            $RepoRoot `
            @((Join-Path $RepoRoot ".git"),(Join-Path $RepoRoot ".local_results")) `
            $opaqueDirectoryNames `
            ([ref]$AfterRepoOpaque)
        $relativeAllowed = @{}
        foreach ($key in @($allowedFiles.Keys)) {
            $relativeAllowed[(Relative-To $RepoRoot ([string]$key)).ToLowerInvariant()] = $true
        }
        $RepoSnapshotViolations = @(Compare-Snapshots $BeforeRepo $afterRepo $relativeAllowed)
        $RepoOpaqueSnapshotViolations = @(Compare-OpaqueDirectoryStates $BeforeRepoOpaque $AfterRepoOpaque)

        $afterCanonical = Snapshot-Metadata $DataRoot
        $CanonicalSnapshotViolations = @(Compare-Metadata $BeforeCanonical $afterCanonical)

        $localPath = Join-Path $RepoRoot ".local_results"
        if (Test-Path -LiteralPath $localPath -PathType Container) {
            $afterLocal = Snapshot-Metadata $localPath
        } else {
            $afterLocal = [ordered]@{}
        }
        $localSnapshotViolations = @(Compare-Metadata $BeforeLocal $afterLocal)
        foreach ($v in $localSnapshotViolations) { $LocalEvents.Add("POST_SNAPSHOT:$v") }
    } catch {
        [void]$RepoViolations.Add("POSTRUN_SNAPSHOT_AUDIT_FAILED:" + $_.Exception.Message)
        if ($null -eq $RepoSnapshotViolations) { $RepoSnapshotViolations = @() }
        if ($null -eq $RepoOpaqueSnapshotViolations) { $RepoOpaqueSnapshotViolations = @() }
        if ($null -eq $CanonicalSnapshotViolations) { $CanonicalSnapshotViolations = @() }
    }

    $RepoSnapshotViolationCount = @($RepoSnapshotViolations).Count
    $RepoOpaqueSnapshotViolationCount = @($RepoOpaqueSnapshotViolations).Count
    $CanonicalSnapshotViolationCount = @($CanonicalSnapshotViolations).Count
    $RepoWatchViolationCount = @($RepoViolations).Count
    $CanonicalWatchEventCount = @($DataEvents).Count
    $LocalResultsEventCount = @($LocalEvents).Count

    if ($RepoSnapshotViolationCount -gt 0 -or
        $RepoOpaqueSnapshotViolationCount -gt 0 -or
        $CanonicalSnapshotViolationCount -gt 0 -or
        $RepoWatchViolationCount -gt 0 -or
        $CanonicalWatchEventCount -gt 0 -or
        $LocalResultsEventCount -gt 0 -or
        -not [string]::IsNullOrWhiteSpace($ViolationReason)) {
        $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
    }

    $storagePass = (
        $AclGuardActive -and
        $RepoSnapshotViolationCount -eq 0 -and
        $RepoOpaqueSnapshotViolationCount -eq 0 -and
        $CanonicalSnapshotViolationCount -eq 0 -and
        $RepoWatchViolationCount -eq 0 -and
        $CanonicalWatchEventCount -eq 0 -and
        $LocalResultsEventCount -eq 0 -and
        [string]::IsNullOrWhiteSpace($ViolationReason)
    )

    $audit = [ordered]@{
        run_id=$RunId
        storage_contract="FAST3_STORAGE_CONTRACT_R1"
        final_decision=$FinalDecision
        canonical_acl_guard_active_during_run=$AclGuardActive
        canonical_acl_restored=([string]::IsNullOrWhiteSpace($ViolationReason) -or $ViolationReason -ne "CANONICAL_ACL_RESTORE_FAILED")
        canonical_watch_event_count=$CanonicalWatchEventCount
        canonical_watch_events=@($DataEvents)
        canonical_snapshot_violation_count=$CanonicalSnapshotViolationCount
        canonical_snapshot_violations=$CanonicalSnapshotViolations
        repo_watch_violation_count=$RepoWatchViolationCount
        repo_watch_violations=@($RepoViolations)
        repo_snapshot_violation_count=$RepoSnapshotViolationCount
        repo_snapshot_violations=$RepoSnapshotViolations
        repo_opaque_snapshot_violation_count=$RepoOpaqueSnapshotViolationCount
        repo_opaque_snapshot_violations=$RepoOpaqueSnapshotViolations
        repo_opaque_directories_before=$BeforeRepoOpaque
        repo_opaque_directories_after=$AfterRepoOpaque
        new_local_results_write_count=$LocalResultsEventCount
        local_results_events=@($LocalEvents)
        git_mutation_performed=$false
        forbidden_git_commands_executed=$false
        preexisting_untracked_files_preserved=($RepoSnapshotViolationCount -eq 0 -and $LocalResultsEventCount -eq 0)
        canonical_write_count=if($CanonicalSnapshotViolationCount -eq 0 -and $CanonicalWatchEventCount -eq 0){0}else{$CanonicalSnapshotViolationCount + $CanonicalWatchEventCount}
        repo_result_write_count=if($RepoSnapshotViolationCount -eq 0 -and $RepoWatchViolationCount -eq 0){0}else{$RepoSnapshotViolationCount + $RepoWatchViolationCount}
        implementation_exit_code=$ImplementationExit
        test_exit_code=$TestExit
        research_exit_code=$ResearchExit
        summary_readable=$SummaryReadable
        required_artifacts_present=$RequiredArtifactsPresent
        storage_contract_pass=$storagePass
        runtime_root=$RuntimeRoot
        scratch_root=$ScratchRoot
        frozen_root=$FrozenRoot
        archive_root=$ArchiveRunRoot
        cache_root=$RunCacheRoot
        r3_source_root=$R3Root
        r3_audit_root=$R3AuditRoot
        checked_at=(Get-Date).ToString("o")
    }
    Write-Json $audit (Join-Path $FrozenRoot "FAST3_R4_HARD_STORAGE_LAUNCHER_AUDIT.json")

    $launcherSummary = [ordered]@{
        RUN_ID=$RunId
        FINAL_DECISION=$FinalDecision
        STORAGE_CONTRACT_PASS=$storagePass
        CANONICAL_ACL_GUARD_ACTIVE_DURING_RUN=$AclGuardActive
        CANONICAL_WATCH_EVENT_COUNT=$CanonicalWatchEventCount
        REPO_WATCH_VIOLATION_COUNT=$RepoWatchViolationCount
        NEW_LOCAL_RESULTS_WRITE_COUNT=$LocalResultsEventCount
        REPO_SNAPSHOT_VIOLATION_COUNT=$RepoSnapshotViolationCount
        REPO_OPAQUE_SNAPSHOT_VIOLATION_COUNT=$RepoOpaqueSnapshotViolationCount
        CANONICAL_SNAPSHOT_VIOLATION_COUNT=$CanonicalSnapshotViolationCount
        PREEXISTING_UNTRACKED_FILES_PRESERVED=($RepoSnapshotViolationCount -eq 0 -and $LocalResultsEventCount -eq 0)
        IMPLEMENTATION_EXIT_CODE=$ImplementationExit
        TEST_EXIT_CODE=$TestExit
        RESEARCH_EXIT_CODE=$ResearchExit
        SUMMARY_READABLE=$SummaryReadable
        ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT=$RequiredArtifactsPresent
        ARCHIVE_FINALIZED=$false
        FROZEN_ROOT=$FrozenRoot
        RUNTIME_ROOT=$RuntimeRoot
        SCRATCH_ROOT=$ScratchRoot
        ARCHIVE_ROOT=$ArchiveRunRoot
    }
    Write-Json $launcherSummary (Join-Path $FrozenRoot "FAST3_R4_HARD_STORAGE_LAUNCHER_SUMMARY.json")

    # Completed runtime and scratch are moved to archive; frozen evidence remains.
    try {
        New-Item -ItemType Directory -Force -Path $ArchiveRunRoot | Out-Null
        $runtimeArchive = Join-Path $ArchiveRunRoot "runtime"
        $scratchArchive = Join-Path $ArchiveRunRoot "scratch"
        if (Test-Path -LiteralPath $RuntimeRoot -PathType Container) {
            Move-Item -LiteralPath $RuntimeRoot -Destination $runtimeArchive -Force
        }
        if (Test-Path -LiteralPath $ScratchRoot -PathType Container) {
            Move-Item -LiteralPath $ScratchRoot -Destination $scratchArchive -Force
        }
        $ArchiveFinalized = $true
        $archivePointer = [ordered]@{
            run_id=$RunId
            archive_finalized=$true
            runtime_archive=$runtimeArchive
            scratch_archive=$scratchArchive
            frozen_root=$FrozenRoot
            completed_at=(Get-Date).ToString("o")
        }
        Write-Json $archivePointer (Join-Path $FrozenRoot "FAST3_R4_ARCHIVE_POINTER.json")

        $launcherSummary.ARCHIVE_FINALIZED = $true
        $launcherSummary.RUNTIME_ROOT = $runtimeArchive
        $launcherSummary.SCRATCH_ROOT = $scratchArchive
        Write-Json $launcherSummary (Join-Path $FrozenRoot "FAST3_R4_HARD_STORAGE_LAUNCHER_SUMMARY.json")
    } catch {
        $ArchiveFinalized = $false
        $storagePass = $false
        $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
        Write-Json ([ordered]@{
            run_id=$RunId
            archive_finalized=$false
            error=$_.Exception.Message
        }) (Join-Path $FrozenRoot "FAST3_R4_ARCHIVE_POINTER.json")
        $launcherSummary.FINAL_DECISION = $FinalDecision
        $launcherSummary.STORAGE_CONTRACT_PASS = $false
        $launcherSummary.ARCHIVE_FINALIZED = $false
        Write-Json $launcherSummary (Join-Path $FrozenRoot "FAST3_R4_HARD_STORAGE_LAUNCHER_SUMMARY.json")
    }

    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue

    Section "R4 hard-storage collection"
    Write-Host "FINAL_DECISION=$FinalDecision"
    Write-Host "STORAGE_CONTRACT_PASS=$($storagePass.ToString().ToLowerInvariant())"
    Write-Host "CANONICAL_ACL_GUARD_ACTIVE_DURING_RUN=$($AclGuardActive.ToString().ToLowerInvariant())"
    Write-Host "CANONICAL_WATCH_EVENT_COUNT=$($CanonicalWatchEventCount)"
    Write-Host "REPO_WATCH_VIOLATION_COUNT=$($RepoWatchViolationCount)"
    Write-Host "NEW_LOCAL_RESULTS_WRITE_COUNT=$($LocalResultsEventCount)"
    Write-Host "REPO_SNAPSHOT_VIOLATION_COUNT=$($RepoSnapshotViolationCount)"
    Write-Host "REPO_OPAQUE_SNAPSHOT_VIOLATION_COUNT=$($RepoOpaqueSnapshotViolationCount)"
    Write-Host "CANONICAL_SNAPSHOT_VIOLATION_COUNT=$($CanonicalSnapshotViolationCount)"
    Write-Host "PREEXISTING_UNTRACKED_FILES_PRESERVED=$(($RepoSnapshotViolationCount -eq 0 -and $LocalResultsEventCount -eq 0).ToString().ToLowerInvariant())"
    Write-Host "IMPLEMENTATION_EXIT_CODE=$ImplementationExit"
    Write-Host "TEST_EXIT_CODE=$TestExit"
    Write-Host "RESEARCH_EXIT_CODE=$ResearchExit"
    Write-Host "SUMMARY_READABLE=$($SummaryReadable.ToString().ToLowerInvariant())"
    Write-Host "ALL_REQUIRED_FROZEN_ARTIFACTS_PRESENT=$($RequiredArtifactsPresent.ToString().ToLowerInvariant())"
    Write-Host "ARCHIVE_FINALIZED=$($ArchiveFinalized.ToString().ToLowerInvariant())"
    Write-Host "FROZEN_ROOT=$FrozenRoot"
    Write-Host "ARCHIVE_ROOT=$ArchiveRunRoot"

    if (-not $storagePass) { exit 4 }
    if ($ImplementationExit -ne 0 -or $TestExit -ne 0) { exit 3 }
    if (-not $SummaryReadable -or -not $RequiredArtifactsPresent) { exit 3 }
    if (-not $ArchiveFinalized) { exit 5 }
    exit 0
}
