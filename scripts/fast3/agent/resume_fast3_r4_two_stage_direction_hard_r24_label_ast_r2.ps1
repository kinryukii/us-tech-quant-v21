[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$DataRoot = "D:\us-tech-quant-data",
    [string]$ResultsRoot = "D:\us-tech-quant-results",
    [string]$CacheRoot = "D:\us-tech-quant-cache",
    [string]$SourceR3Root = "",
    [string]$SourceR3AuditRoot = "",
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

function Get-OpaqueDirectoryState(
    [string]$Root,
    [string]$Path,
    [string]$SnapshotErrorType = $null,
    [string]$SnapshotErrorMessage = $null
) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $aclHash = $null
    $aclReadable = $false
    $sddl = $null
    $owner = $null
    try {
        $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
        $sddl = $acl.Sddl
        $owner = [string]$acl.Owner
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
        last_write_time_utc=$item.LastWriteTimeUtc.ToString("o")
        creation_time_utc=$item.CreationTimeUtc.ToString("o")
        attributes=[string]$item.Attributes
        object_type=if($item.PSIsContainer){"DIRECTORY"}else{"FILE"}
        reparse_point=[bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
        acl_readable=$aclReadable
        acl_sddl=$sddl
        acl_sddl_sha256=$aclHash
        owner=$owner
        snapshot_error_type=$SnapshotErrorType
        snapshot_error_message=$SnapshotErrorMessage
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
        try {
            $items = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)
        } catch [System.UnauthorizedAccessException] {
            if ((Full $dir) -eq (Full $Root)) {
                throw
            }
            $rel = Relative-To $Root $dir
            $opaque[$rel.ToLowerInvariant()] = Get-OpaqueDirectoryState `
                $Root $dir $_.Exception.GetType().FullName $_.Exception.Message
            continue
        }
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
        if ([string]$b.object_type -ne [string]$a.object_type -or
            [bool]$b.reparse_point -ne [bool]$a.reparse_point -or
            [long]$b.last_write_utc_ticks -ne [long]$a.last_write_utc_ticks -or
            [string]$b.last_write_time_utc -ne [string]$a.last_write_time_utc -or
            [string]$b.creation_time_utc -ne [string]$a.creation_time_utc -or
            [string]$b.attributes -ne [string]$a.attributes -or
            [bool]$b.acl_readable -ne [bool]$a.acl_readable -or
            [string]$b.acl_sddl_sha256 -ne [string]$a.acl_sddl_sha256 -or
            [string]$b.owner -ne [string]$a.owner -or
            [string]$b.snapshot_error_type -ne [string]$a.snapshot_error_type -or
            [string]$b.snapshot_error_message -ne [string]$a.snapshot_error_message) {
            $violations.Add("OPAQUE_METADATA_CHANGED:$key")
        }
    }
    return [string[]]$violations.ToArray()
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
    return [string[]]$violations.ToArray()
}

function Test-PathWithin([string]$Path,[string]$Root) {
    $fullPath = Full $Path; $fullRoot = Full $Root
    return ($fullPath -eq $fullRoot -or $fullPath.StartsWith($fullRoot + '\',[StringComparison]::OrdinalIgnoreCase))
}

function Get-CanonicalEffectiveAccess([string]$Path) {
    if ($null -eq ("Fast3CanonicalAccessProbe" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Fast3CanonicalAccessProbe {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern IntPtr CreateFileW(string n,uint a,uint s,IntPtr sa,uint c,uint f,IntPtr t);
 [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr h);
 static readonly IntPtr Invalid = new IntPtr(-1);
 public static bool CanOpen(string path,uint access,out int error) {
  IntPtr h=CreateFileW(path,access,7,IntPtr.Zero,3,0x02000000,IntPtr.Zero);
  error=Marshal.GetLastWin32Error(); if(h==Invalid) return false; CloseHandle(h); return true;
 }
}
'@
    }
    $checks = [ordered]@{ FILE_WRITE_DATA=0x2; FILE_APPEND_DATA=0x4; FILE_WRITE_ATTRIBUTES=0x100; FILE_WRITE_EA=0x10; DELETE=0x10000; WRITE_DAC=0x40000; WRITE_OWNER=0x80000 }
    $result = [ordered]@{}
    foreach ($name in $checks.Keys) {
        $error = 0; $allowed = [Fast3CanonicalAccessProbe]::CanOpen($Path,[uint32]$checks[$name],[ref]$error)
        if (-not $allowed -and $error -ne 5) { throw "CANONICAL_ACCESS_PROBE_UNDETERMINED:${name}:WIN32_$error" }
        $result[$name] = $allowed
    }
    return [ordered]@{
        file_write_data=[bool]$result.FILE_WRITE_DATA; file_append_data=[bool]$result.FILE_APPEND_DATA
        file_write_attributes=[bool]$result.FILE_WRITE_ATTRIBUTES; file_write_ea=[bool]$result.FILE_WRITE_EA
        delete=[bool]$result.DELETE; write_dac=[bool]$result.WRITE_DAC; write_owner=[bool]$result.WRITE_OWNER
        effective_write_access=([bool]$result.FILE_WRITE_DATA -or [bool]$result.FILE_APPEND_DATA -or [bool]$result.FILE_WRITE_ATTRIBUTES -or [bool]$result.FILE_WRITE_EA)
        effective_delete_access=[bool]$result.DELETE; effective_write_dac_access=[bool]$result.WRITE_DAC
    }
}

function Resolve-DeclaredReadOnlyRoot([string]$Name,[string]$Path,[string]$AllowedRoot) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "DECLARED_READ_ONLY_ROOT_MISSING:${Name}:$Path" }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) { throw "DECLARED_READ_ONLY_ROOT_NOT_DIRECTORY:${Name}:$Path" }
    if ([bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "DECLARED_READ_ONLY_ROOT_REPARSE_POINT:${Name}:$Path" }
    $resolved = Full ((Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath)
    if (-not (Test-PathWithin $resolved $AllowedRoot)) { throw "DECLARED_READ_ONLY_ROOT_ESCAPES_ALLOWED_ROOT:${Name}:$resolved" }
    return [ordered]@{ name=$Name; path=$resolved; allowed_root=(Full $AllowedRoot) }
}

function Resolve-R24DeclaredReadOnlyRoots([string]$Data,[string]$Results,[string]$SourceR3,[string]$SourceR3Audit) {
    $evidencePath = Join-Path $SourceR3Audit "FAST3_R3_POST_AUDIT_EVIDENCE.json"
    $evidence = Read-Json $evidencePath
    $files = @($evidence.canonical_execution_verification.canonical_partition_files_read)
    if ($files.Count -eq 0) { throw "R3_AUDIT_CANONICAL_PARTITION_EVIDENCE_MISSING" }
    $common = Split-Path -Parent ([string]$files[0])
    while (@($files | Where-Object { -not (Test-PathWithin ([string]$_) $common) }).Count -gt 0) {
        $parent = Split-Path -Parent $common
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $common) { throw "R3_AUDIT_CANONICAL_COMMON_ROOT_UNRESOLVED" }
        $common = $parent
    }
    return @( (Resolve-DeclaredReadOnlyRoot "r3_audit_canonical" $common $Data),
        (Resolve-DeclaredReadOnlyRoot "r3_source" $SourceR3 $Results),
        (Resolve-DeclaredReadOnlyRoot "r3_audit" $SourceR3Audit $Results) )
}

function Add-ScopedOpaqueState([object]$Opaque,[string]$Scope,[string]$Root,[string]$Path,[string]$ErrorType=$null,[string]$ErrorMessage=$null) {
    $state = Get-OpaqueDirectoryState $Root $Path $ErrorType $ErrorMessage
    $state["declared_root"] = $Scope
    $Opaque[($Scope + "\\" + [string]$state.relative_path).ToLowerInvariant()] = $state
}

function Snapshot-ReadOnlyRoots([object[]]$Roots,[ref]$OpaqueState) {
    $map = [ordered]@{}; $opaque = [ordered]@{}
    foreach ($root in $Roots) {
        $rootPath = [string]$root.path; $scope = [string]$root.name
        Add-ScopedOpaqueState $opaque $scope $rootPath $rootPath
        $stack = New-Object 'System.Collections.Generic.Stack[string]'; $stack.Push($rootPath)
        while ($stack.Count -gt 0) {
            $dir = $stack.Pop()
            try { $items = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop) }
            catch [System.UnauthorizedAccessException] { Add-ScopedOpaqueState $opaque $scope $rootPath $dir $_.Exception.GetType().FullName $_.Exception.Message; continue }
            foreach ($item in $items) {
                $fullPath = Full $item.FullName
                if ([bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Add-ScopedOpaqueState $opaque $scope $rootPath $fullPath "REPARSE_POINT" "REPARSE_POINT_NOT_TRAVERSED"; continue }
                if ($item.PSIsContainer) { $stack.Push($fullPath); continue }
                try { $hash=(Get-FileHash -LiteralPath $fullPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() }
                catch [System.UnauthorizedAccessException] { Add-ScopedOpaqueState $opaque $scope $rootPath $fullPath $_.Exception.GetType().FullName $_.Exception.Message; continue }
                $relative=Relative-To $rootPath $fullPath
                $map[($scope + "\\" + $relative).ToLowerInvariant()] = [ordered]@{ declared_root=$scope; relative_path=$relative; length=$item.Length; last_write_utc_ticks=$item.LastWriteTimeUtc.Ticks; sha256=$hash }
            }
        }
    }
    $OpaqueState.Value=$opaque; return $map
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
    return [string[]]$violations.ToArray()
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

function Ensure-External-R3([string]$Repo,[string]$Results,[string]$DeclaredR3,[string]$DeclaredAudit) {
    if (-not [string]::IsNullOrWhiteSpace($DeclaredR3) -or -not [string]::IsNullOrWhiteSpace($DeclaredAudit)) {
        if ([string]::IsNullOrWhiteSpace($DeclaredR3) -or [string]::IsNullOrWhiteSpace($DeclaredAudit)) {
            throw "R24_EXPLICIT_SOURCE_ROOTS_MUST_BE_PROVIDED_TOGETHER"
        }
        if (-not (Test-Path -LiteralPath $DeclaredR3 -PathType Container) -or -not (Test-Path -LiteralPath $DeclaredAudit -PathType Container)) {
            throw "R24_EXPLICIT_SOURCE_ROOT_MISSING"
        }
        return [ordered]@{ r3=(Full $DeclaredR3); audit=(Full $DeclaredAudit) }
    }
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
    if (-not (Test-Path -LiteralPath $env:FAST3_CACHE_ROOT -PathType Container)) {
        throw "MONITORED_PROCESS_CACHE_ROOT_MISSING"
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StdoutPath) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StderrPath) | Out-Null

    $wrapperName = "monitored_" + [Guid]::NewGuid().ToString("N") + ".cmd"
    $wrapperPath = Join-Path $env:FAST3_CACHE_ROOT $wrapperName
    $argumentText = (@($ArgumentList) -join " ")

    $batch = @"
@echo off
"$FilePath" $argumentText 1>"$StdoutPath" 2>"$StderrPath"
exit /b %ERRORLEVEL%
"@
    Set-Content -LiteralPath $wrapperPath -Value $batch -Encoding ASCII

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/d /s /c ""' + $wrapperPath + '""'
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    try {
        $started = $proc.Start()
        if (-not $started) {
            throw "MONITORED_PROCESS_START_RETURNED_FALSE"
        }

        while (-not $proc.HasExited) {
            Wait-Event -Timeout 0.20 | Out-Null
            Drain-WatcherEvents $AllowedFiles $AllowedDirs $RepoViolations $DataEvents $LocalEvents $ViolationReason $Repo $Data

            if (-not [string]::IsNullOrWhiteSpace([string]$ViolationReason.Value)) {
                Kill-Tree $proc.Id
                break
            }
            $proc.Refresh()
        }

        $proc.WaitForExit()
        $proc.Refresh()

        Start-Sleep -Milliseconds 300
        Drain-WatcherEvents $AllowedFiles $AllowedDirs $RepoViolations $DataEvents $LocalEvents $ViolationReason $Repo $Data

        if (-not $proc.HasExited) {
            throw "MONITORED_PROCESS_DID_NOT_EXIT"
        }

        [int]$capturedExitCode = $proc.ExitCode
        return $capturedExitCode
    }
    finally {
        try { $proc.Dispose() } catch {}
        Remove-Item -LiteralPath $wrapperPath -Force -ErrorAction SilentlyContinue
    }
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

$LimitsPath = Join-Path $RepoRoot "config\fast3\agent\FAST3_R4_TWO_STAGE_DIRECTION_HARD_R24_LIMITS.json"
$PromptPath = Join-Path $RepoRoot "docs\fast3\agent\FAST3_R4_TWO_STAGE_DIRECTION_HARD_R24_AGENT.md"
foreach ($p in @($LimitsPath,$PromptPath)) {
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
        throw "Required deployed control file missing: $p"
    }
}
$limits = Read-Json $LimitsPath

$expectedControlRefs = @(
    $LimitsPath,
    $PromptPath,
    (Join-Path $RepoRoot "scripts\fast3\agent\resume_fast3_r4_two_stage_direction_hard_r24_label_ast_r2.ps1"),
    (Join-Path $RepoRoot "scripts\fast3\agent\show_fast3_r4_two_stage_direction_hard_r24_status.ps1")
)
foreach ($controlRef in $expectedControlRefs) {
    if (-not (Test-Path -LiteralPath $controlRef -PathType Leaf)) {
        throw "R24_CONTROL_REFERENCE_SELFTEST_FAILED: $controlRef"
    }
}
Write-Host "R24_CONTROL_REFERENCE_SELFTEST_PASS=true"


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
$LockPath = Join-Path $StateRoot "active_hard_r24_label_ast_r2.lock.json"
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
$CollectionCardinalitySelfTestPass = $false
$ProcessExitcodeSelfTestPass = $false
$LabelSelfTestExit = $null
$LabelLineageSemanticSelfTestPass = $false
$LabelLineageAstAuditPass = $false
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
$CanonicalDataRoot = $null
$CanonicalAccessProbe = $null
$CanonicalAclGuardMode = "UNAVAILABLE_STOP"
$CanonicalAclMutationRequired = $false
$DeclaredReadOnlyRoots = @()
$DeclaredCanonicalRoots = @()
$BeforeReadOnlyOpaque = [ordered]@{}
$AfterReadOnlyOpaque = [ordered]@{}
$BeforeRepo = $null
$BeforeCanonical = $null
$BeforeLocal = $null
$AgentBackups = @()

try {
    Section "R4 hard-storage preflight"
    $emptyCollectionSelfTest = @(Compare-Metadata ([ordered]@{}) ([ordered]@{}))
    $singleCollectionSelfTest = @(Compare-Metadata ([ordered]@{}) ([ordered]@{
        "single" = [ordered]@{ length=1; last_write_utc_ticks=1 }
    }))
    $doubleCollectionSelfTest = @(Compare-Metadata ([ordered]@{}) ([ordered]@{
        "first" = [ordered]@{ length=1; last_write_utc_ticks=1 }
        "second" = [ordered]@{ length=2; last_write_utc_ticks=2 }
    }))
    if ($emptyCollectionSelfTest.Count -ne 0 -or
        $singleCollectionSelfTest.Count -ne 1 -or
        $doubleCollectionSelfTest.Count -ne 2) {
        throw "R24_COLLECTION_CARDINALITY_SELFTEST_FAILED"
    }
    $CollectionCardinalitySelfTestPass = $true
    Write-Host "R24_COLLECTION_CARDINALITY_SELFTEST_PASS=true"

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

    $sources = Ensure-External-R3 $RepoRoot $ResultsRoot $SourceR3Root $SourceR3AuditRoot
    $R3Root = [string]$sources.r3
    $R3AuditRoot = [string]$sources.audit
    if ([string]::IsNullOrWhiteSpace($R3Root) -or [string]::IsNullOrWhiteSpace($R3AuditRoot)) {
        throw "External R3 source or R3 post-audit evidence not found."
    }
    $DeclaredReadOnlyRoots = @(Resolve-R24DeclaredReadOnlyRoots `
        $DataRoot $ResultsRoot $R3Root $R3AuditRoot)
    $DeclaredCanonicalRoots = @($DeclaredReadOnlyRoots |
        Where-Object { [string]$_.name -eq "r3_audit_canonical" } |
        ForEach-Object { [string]$_.path })
    if ($DeclaredCanonicalRoots.Count -ne 1) {
        throw "DECLARED_CANONICAL_ROOT_CARDINALITY_INVALID:$($DeclaredCanonicalRoots.Count)"
    }
    $CanonicalDataRoot = $DeclaredCanonicalRoots[0]
    Write-Host "DECLARED_CANONICAL_ROOTS=$($DeclaredCanonicalRoots -join ';')"
    Write-Host "DECLARED_READ_ONLY_INPUT_ROOTS=$(($DeclaredReadOnlyRoots | ForEach-Object { $_.path }) -join ';')"

    $existingImplementationFiles = @()
    $missingImplementationFiles = @()

    foreach ($key in @($allowedFiles.Keys)) {
        $path = [string]$key
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $item = Get-Item -LiteralPath $path
            $existingImplementationFiles += [ordered]@{
                relative_path=(Relative-To $RepoRoot $path)
                source_path=$path
                length=$item.Length
                sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        } else {
            $missingImplementationFiles += $path
        }
    }

    if ($missingImplementationFiles.Count -gt 0) {
        throw "R24_EXISTING_IMPLEMENTATION_INCOMPLETE: $($missingImplementationFiles -join '; ')"
    }

    Write-Json ([ordered]@{
        run_id=$RunId
        status="FROZEN_EXISTING_IMPLEMENTATION"
        implementation_file_count=$existingImplementationFiles.Count
        implementation_files=$existingImplementationFiles
        codex_rerun_performed=$false
        existing_files_overwritten=$false
        model_or_factor_search_performed=$false
    }) (Join-Path $FrozenRoot "FAST3_R4_EXISTING_IMPLEMENTATION_FREEZE.json")

    Write-Host "R24_EXISTING_IMPLEMENTATION_FREEZE_PASS=true"
    Write-Host "R24_EXISTING_IMPLEMENTATION_FILE_COUNT=$($existingImplementationFiles.Count)"

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
    $BeforeCanonical = Snapshot-ReadOnlyRoots $DeclaredReadOnlyRoots ([ref]$BeforeReadOnlyOpaque)
    $localPath = Join-Path $RepoRoot ".local_results"
    if (Test-Path -LiteralPath $localPath -PathType Container) {
        $BeforeLocal = Snapshot-Metadata $localPath
    } else {
        $BeforeLocal = [ordered]@{}
    }

    # Normal research execution never mutates canonical ACLs; the access probe is non-destructive.
    $CanonicalAccessProbe = Get-CanonicalEffectiveAccess $CanonicalDataRoot
    if (-not $CanonicalAccessProbe.effective_write_access -and
        -not $CanonicalAccessProbe.effective_delete_access -and
        -not $CanonicalAccessProbe.effective_write_dac_access -and
        -not $CanonicalAccessProbe.write_owner) {
        $AclGuardActive = $true
        $CanonicalAclGuardMode = "EXISTING_READ_ONLY_ACL"
    } else {
        $CanonicalAclMutationRequired = $true
        $CanonicalAclGuardMode = "UNAVAILABLE_STOP"
        $FinalDecision = "STOP_CANONICAL_WRITE_GUARD_UNAVAILABLE"
        throw "CANONICAL_WRITE_GUARD_UNAVAILABLE: use the separate elevated hardening tool; normal launcher will not call Set-Acl"
    }
    Write-Host "CANONICAL_ACL_GUARD_ACTIVE=true"
    Write-Host "CANONICAL_ACL_GUARD_MODE=$CanonicalAclGuardMode"

    $RepoWatcher = New-Object System.IO.FileSystemWatcher
    $RepoWatcher.Path = $RepoRoot
    $RepoWatcher.IncludeSubdirectories = $true
    $RepoWatcher.NotifyFilter = [IO.NotifyFilters]'FileName, DirectoryName, LastWrite, Size, Security'
    $RepoWatcher.EnableRaisingEvents = $true

    $DataWatcher = New-Object System.IO.FileSystemWatcher
    $DataWatcher.Path = $CanonicalDataRoot
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
    $env:FAST3_DATA_ROOT = $CanonicalDataRoot
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
$env:PYTHONPATH = (Join-Path $RepoRoot "fast3\src")
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
        data_root=$CanonicalDataRoot
        declared_canonical_roots=$DeclaredCanonicalRoots
        declared_read_only_input_roots=@($DeclaredReadOnlyRoots | ForEach-Object { $_.path })
        runtime_root=$RuntimeRoot
        scratch_root=$ScratchRoot
        frozen_root=$FrozenRoot
        archive_root=$ArchiveRunRoot
        cache_root=$RunCacheRoot
        canonical_acl_guard_active=$AclGuardActive
        canonical_acl_guard_mode=$CanonicalAclGuardMode
        canonical_effective_write_access=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_write_access}
        canonical_effective_delete_access=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_delete_access}
        canonical_effective_write_dac_access=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_write_dac_access}
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

    # Validate the new process runner before executing tests or research.
    Section "R24 process exit-code self-test"
    $exitZeroScript = Join-Path $RunCacheRoot "exit_zero.ps1"
    $exitSevenScript = Join-Path $RunCacheRoot "exit_seven.ps1"
    Set-Content -LiteralPath $exitZeroScript -Value "exit 0" -Encoding ASCII
    Set-Content -LiteralPath $exitSevenScript -Value "exit 7" -Encoding ASCII

    $exitZero = Run-MonitoredProcess `
        "powershell.exe" `
        @("-NoProfile","-ExecutionPolicy","Bypass","-File",('"{0}"' -f $exitZeroScript)) `
        $RepoRoot `
        (Join-Path $RuntimeRoot "process_selftest_zero_stdout.log") `
        (Join-Path $RuntimeRoot "process_selftest_zero_stderr.log") `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    $exitSeven = Run-MonitoredProcess `
        "powershell.exe" `
        @("-NoProfile","-ExecutionPolicy","Bypass","-File",('"{0}"' -f $exitSevenScript)) `
        $RepoRoot `
        (Join-Path $RuntimeRoot "process_selftest_seven_stdout.log") `
        (Join-Path $RuntimeRoot "process_selftest_seven_stderr.log") `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    if ($exitZero -ne 0 -or $exitSeven -ne 7) {
        throw "R24_PROCESS_EXITCODE_SELFTEST_FAILED: zero=$exitZero seven=$exitSeven"
    }
    $ProcessExitcodeSelfTestPass = $true
    Write-Host "R24_PROCESS_EXITCODE_SELFTEST_PASS=true"

    Section "R24 label-lineage semantic self-test"
    $labelSelfTest = Join-Path $RunCacheRoot "validate_r24_label_lineage_semantics.py"
    @'
import ast
import math
from pathlib import Path

import pandas as pd
from fast3.models.two_stage_direction_hard_r24 import R4ContractError, prepare_cohort

features = [f"f{i}" for i in range(20)]
labels = ["UP_FIRST"]
base = {
    **{name: [0.0] for name in features},
    "label": labels,
    "timestamp_et": [pd.Timestamp("2024-01-02T10:00:00Z")],
    "entry_timestamp_et": [pd.Timestamp("2024-01-02T10:01:00Z")],
    "horizon_timestamp_et": [pd.Timestamp("2024-01-03T10:00:00Z")],
    "hit_timestamp_et": [pd.Timestamp("2024-01-02T12:00:00Z")],
    "touch_minutes": [119.0],
    "underlying": ["QQQ"],
    "uniqueness_weight": [1.0] * len(labels),
}

def assert_valid_uniqueness_weight_fixture(frame: pd.DataFrame) -> None:
    assert "uniqueness_weight" in frame.columns
    weights = pd.to_numeric(frame["uniqueness_weight"], errors="coerce")
    assert len(weights) == len(frame)
    assert weights.notna().all()
    assert weights.map(math.isfinite).all()


def assert_label_lineage_ast_audit() -> None:
    source = Path("fast3/src/fast3/models/two_stage_direction_hard_r24.py")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_cohort"
    )
    literals = {
        node.value for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "horizon_timestamp_et" in literals
    assert "label_end_timestamp_et" in literals
    assert "LABEL_HORIZON_AFTER_24H_DEADLINE" in literals
    assert "EVENT_HIT_OUTSIDE_OBSERVED_LABEL_PATH" in literals
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_r22"
        and node.func.attr == "prepare_cohort"
        for node in ast.walk(function)
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Timedelta"
        and any(
            keyword.arg == "hours"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == 24
            for keyword in node.keywords
        )
        for node in ast.walk(function)
    )


ok_frame = pd.DataFrame(base)
assert_valid_uniqueness_weight_fixture(ok_frame)
ok = prepare_cohort(ok_frame, features)
assert len(ok) == 1
assert ok["label_observed_span_minutes"].iloc[0] == 1439.0
assert ok["label_end_timestamp_et"].iloc[0] == pd.Timestamp("2024-01-03T10:01:00Z")

late = pd.DataFrame(base)
late["horizon_timestamp_et"] = [pd.Timestamp("2024-01-03T10:02:00Z")]
assert_valid_uniqueness_weight_fixture(late)
try:
    prepare_cohort(late, features)
except R4ContractError as exc:
    assert str(exc) == "LABEL_HORIZON_AFTER_24H_DEADLINE"
else:
    raise AssertionError("late observed horizon was not rejected")

bad_hit = pd.DataFrame(base)
bad_hit["hit_timestamp_et"] = [pd.Timestamp("2024-01-03T10:01:00Z")]
assert_valid_uniqueness_weight_fixture(bad_hit)
try:
    prepare_cohort(bad_hit, features)
except R4ContractError as exc:
    assert str(exc) == "EVENT_HIT_OUTSIDE_OBSERVED_LABEL_PATH"
else:
    raise AssertionError("out-of-path event hit was not rejected")

assert_label_lineage_ast_audit()
print("R24_LABEL_LINEAGE_AST_AUDIT_PASS=true")
print("R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_PASS=true")
'@ | Set-Content -LiteralPath $labelSelfTest -Encoding UTF8

    $LabelSelfTestExit = Run-MonitoredProcess `
        $python `
        @('"{0}"' -f $labelSelfTest) `
        $RepoRoot `
        (Join-Path $RuntimeRoot "label_lineage_selftest_stdout.log") `
        (Join-Path $RuntimeRoot "label_lineage_selftest_stderr.log") `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    if ($LabelSelfTestExit -ne 0) {
        throw "R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_FAILED: exit=$LabelSelfTestExit"
    }
    $LabelLineageSemanticSelfTestPass = $true
    $LabelLineageAstAuditPass = $true
    if (-not $CollectionCardinalitySelfTestPass -or
        -not $ProcessExitcodeSelfTestPass -or
        -not $LabelLineageSemanticSelfTestPass -or
        -not $LabelLineageAstAuditPass -or
        -not [string]::IsNullOrWhiteSpace($ViolationReason)) {
        throw "R24_PRE_IMPLEMENTATION_GATE_FAILED"
    }
    Write-Host "R24_LABEL_LINEAGE_AST_AUDIT_PASS=true"
    Write-Host "R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_PASS=true"

    # Phase 1 resume: validate the already-frozen R24 implementation. Do not rerun Codex.
    Section "Phase 1 resume: validate existing R24 implementation"
    $ImplementationExit = 0

    $requiredImplementationPaths = @(
        (Join-Path $RepoRoot "fast3\src\fast3\models\two_stage_direction_hard_r24.py"),
        (Join-Path $RepoRoot "fast3\scripts\run\fast3_r4_two_stage_direction_hard_r24.py"),
        (Join-Path $RepoRoot "fast3\scripts\run\fast3_r4_prospective_shadow_hard_r24.py"),
        (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r24.py"),
        (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_prospective_shadow_hard_r24.py"),
        (Join-Path $RepoRoot "fast3\docs\architecture\FAST3_R4_TWO_STAGE_DIRECTION_HARD_R24.md")
    )
    foreach ($path in $requiredImplementationPaths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "R24_EXISTING_IMPLEMENTATION_REQUIRED_FILE_MISSING: $path"
        }
    }

    $syntaxScript = Join-Path $RunCacheRoot "validate_existing_r24.py"
    @'
from pathlib import Path

paths = [
    Path(r"__REPO_ROOT__\fast3\src\fast3\models\two_stage_direction_hard_r24.py"),
    Path(r"__REPO_ROOT__\fast3\scripts\run\fast3_r4_two_stage_direction_hard_r24.py"),
    Path(r"__REPO_ROOT__\fast3\scripts\run\fast3_r4_prospective_shadow_hard_r24.py"),
    Path(r"__REPO_ROOT__\fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r24.py"),
    Path(r"__REPO_ROOT__\fast3\tests\unit\test_fast3_r4_prospective_shadow_hard_r24.py"),
]
for path in paths:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("R24_EXISTING_IMPLEMENTATION_SYNTAX_PASS=true")
'@.Replace("__REPO_ROOT__", $RepoRoot) | Set-Content -LiteralPath $syntaxScript -Encoding UTF8

    $ImplementationExit = Run-MonitoredProcess `
        $python `
        @('"{0}"' -f $syntaxScript) `
        $RepoRoot `
        (Join-Path $RuntimeRoot "implementation_syntax_stdout.log") `
        (Join-Path $RuntimeRoot "implementation_syntax_stderr.log") `
        $allowedFiles $allowedDirs $RepoViolations $DataEvents $LocalEvents `
        ([ref]$ViolationReason) $RepoRoot $DataRoot

    if (-not [string]::IsNullOrWhiteSpace($ViolationReason)) {
        $FinalDecision = "STOP_R4_STORAGE_CONTRACT_VIOLATION"
        throw "Storage violation during implementation validation: $ViolationReason"
    }
    if ($ImplementationExit -ne 0) {
        $FinalDecision = "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED"
        throw "R24 syntax validation failed. Exit=$ImplementationExit"
    }

    # Phase 2: exact unit tests, outside Codex.
    $testFiles = @(
        (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_two_stage_direction_hard_r24.py"),
        (Join-Path $RepoRoot "fast3\tests\unit\test_fast3_r4_prospective_shadow_hard_r24.py")
    )
    $testStdout = Join-Path $RuntimeRoot "pytest_stdout.log"
    $testStderr = Join-Path $RuntimeRoot "pytest_stderr.log"
    $testWrapper = Join-Path $RunCacheRoot "invoke_pytest.ps1"
    $env:FAST3_PYTHON_PATH = $python
    $env:FAST3_TEST_FILES = ($testFiles -join [IO.Path]::PathSeparator)
    Set-Content -LiteralPath $testWrapper -Encoding UTF8 -Value @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Push-Location $env:FAST3_REPO_ROOT
try {
    $testFiles = $env:FAST3_TEST_FILES -split [IO.Path]::PathSeparator
    & $env:FAST3_PYTHON_PATH -m pytest @testFiles -q -p no:cacheprovider
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
'@

    Section "Phase 2: outer unit tests on frozen R24 implementation"
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
    $researchScript = Join-Path $RepoRoot "fast3\scripts\run\fast3_r4_two_stage_direction_hard_r24.py"
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

    Section "Phase 3: one bounded R24 historical run"
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
            if ((@($limits.decisions) -contains $candidateDecision) -or
                $candidateDecision.StartsWith("STOP_R4_",[StringComparison]::Ordinal)) {
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
            Restore-AclSddl $CanonicalDataRoot $OriginalDataSddl
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

        $implementationHashViolations = @()
        foreach ($entry in $existingImplementationFiles) {
            if (-not (Test-Path -LiteralPath $entry.source_path -PathType Leaf)) {
                $implementationHashViolations += "DELETED:$($entry.relative_path)"
                continue
            }
            $afterHash = (Get-FileHash -LiteralPath $entry.source_path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($afterHash -ne $entry.sha256) {
                $implementationHashViolations += "MODIFIED:$($entry.relative_path)"
            }
        }
        foreach ($violation in $implementationHashViolations) {
            $RepoSnapshotViolations += "R24_IMPLEMENTATION_$violation"
        }

        $afterCanonical = Snapshot-ReadOnlyRoots $DeclaredReadOnlyRoots ([ref]$AfterReadOnlyOpaque)
        $CanonicalSnapshotViolations = @(Compare-Metadata $BeforeCanonical $afterCanonical)
        $CanonicalSnapshotViolations += @(Compare-OpaqueDirectoryStates $BeforeReadOnlyOpaque $AfterReadOnlyOpaque)

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
        snapshot_scope_implementation_changed=$true
        declared_canonical_roots=$DeclaredCanonicalRoots
        declared_read_only_input_roots=@($DeclaredReadOnlyRoots | ForEach-Object { $_.path })
        undeclared_input_access_count=0
        canonical_acl_guard_active_during_run=$AclGuardActive
        canonical_acl_guard_mode=$CanonicalAclGuardMode
        canonical_acl_mutation_required=$CanonicalAclMutationRequired
        canonical_effective_write_access=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_write_access}
        canonical_effective_delete_access=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_delete_access}
        canonical_effective_write_dac_access=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_write_dac_access}
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
        resume_existing_implementation=$true
        label_lineage_ast_repair_r2=$true
        snapshot_implementation_changed=$true
        r24_collection_cardinality_selftest_pass=$CollectionCardinalitySelfTestPass
        r24_process_exitcode_selftest_pass=$ProcessExitcodeSelfTestPass
        r24_label_lineage_semantic_selftest_exit_code=$LabelSelfTestExit
        r24_label_lineage_semantic_selftest_pass=$LabelLineageSemanticSelfTestPass
        r24_label_lineage_ast_audit_pass=$LabelLineageAstAuditPass
        codex_rerun_performed=$false
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
        SNAPSHOT_SCOPE_IMPLEMENTATION_CHANGED=$true
        DECLARED_CANONICAL_ROOTS=$DeclaredCanonicalRoots
        DECLARED_READ_ONLY_INPUT_ROOTS=@($DeclaredReadOnlyRoots | ForEach-Object { $_.path })
        UNDECLARED_INPUT_ACCESS_COUNT=0
        STORAGE_CONTRACT_PASS=$storagePass
        CANONICAL_ACL_GUARD_MODE=$CanonicalAclGuardMode
        CANONICAL_ACL_MUTATION_REQUIRED=$CanonicalAclMutationRequired
        CANONICAL_EFFECTIVE_WRITE_ACCESS=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_write_access}
        CANONICAL_EFFECTIVE_DELETE_ACCESS=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_delete_access}
        CANONICAL_EFFECTIVE_WRITE_DAC_ACCESS=if($null -eq $CanonicalAccessProbe){$null}else{$CanonicalAccessProbe.effective_write_dac_access}
        CANONICAL_ACL_GUARD_ACTIVE_DURING_RUN=$AclGuardActive
        CANONICAL_WATCH_EVENT_COUNT=$CanonicalWatchEventCount
        REPO_WATCH_VIOLATION_COUNT=$RepoWatchViolationCount
        NEW_LOCAL_RESULTS_WRITE_COUNT=$LocalResultsEventCount
        REPO_SNAPSHOT_VIOLATION_COUNT=$RepoSnapshotViolationCount
        REPO_OPAQUE_SNAPSHOT_VIOLATION_COUNT=$RepoOpaqueSnapshotViolationCount
        CANONICAL_SNAPSHOT_VIOLATION_COUNT=$CanonicalSnapshotViolationCount
        PREEXISTING_UNTRACKED_FILES_PRESERVED=($RepoSnapshotViolationCount -eq 0 -and $LocalResultsEventCount -eq 0)
        RESUME_EXISTING_IMPLEMENTATION=$true
        LABEL_LINEAGE_AST_REPAIR_R2=$true
        SNAPSHOT_IMPLEMENTATION_CHANGED=$true
        R24_COLLECTION_CARDINALITY_SELFTEST_PASS=$CollectionCardinalitySelfTestPass
        R24_PROCESS_EXITCODE_SELFTEST_PASS=$ProcessExitcodeSelfTestPass
        R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_EXIT_CODE=$LabelSelfTestExit
        R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_PASS=$LabelLineageSemanticSelfTestPass
        R24_LABEL_LINEAGE_AST_AUDIT_PASS=$LabelLineageAstAuditPass
        CODEX_RERUN_PERFORMED=$false
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
    Write-Host "R24_COLLECTION_CARDINALITY_SELFTEST_PASS=$($CollectionCardinalitySelfTestPass.ToString().ToLowerInvariant())"
    Write-Host "R24_PROCESS_EXITCODE_SELFTEST_PASS=$($ProcessExitcodeSelfTestPass.ToString().ToLowerInvariant())"
    Write-Host "R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_EXIT_CODE=$LabelSelfTestExit"
    Write-Host "R24_LABEL_LINEAGE_SEMANTIC_SELFTEST_PASS=$($LabelLineageSemanticSelfTestPass.ToString().ToLowerInvariant())"
    Write-Host "R24_LABEL_LINEAGE_AST_AUDIT_PASS=$($LabelLineageAstAuditPass.ToString().ToLowerInvariant())"
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
