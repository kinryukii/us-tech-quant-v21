param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [int]$MaxSingleFileMB = 1500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TimeStamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$ExportBase = Join-Path $RepoRoot "exports"
$BundleRoot = Join-Path $ExportBase "ABCDE_BACKTEST_BUNDLE_$TimeStamp"
$Payload    = Join-Path $BundleRoot "payload"

New-Item -ItemType Directory -Force -Path $Payload | Out-Null

Write-Host ""
Write-Host "=== ABCDE BACKTEST DATA EXPORT ==="
Write-Host "repo_root=$RepoRoot"
Write-Host "bundle_root=$BundleRoot"
Write-Host ""

# ============================================================
# 需要收集的输出文件
#
# 重点包括：
# 1. V21.231 Canonical / qfq / raw / price data
# 2. V21.233 ABCDE ranking master / Top20 / Top50 / overlap
# 3. V22.040 daily refresh summary and audit ledger
# 4. V22.041 ETF research layer
# 5. V22.042 direction gate
# 6. V22.043 forward outcomes
# 7. V22.045 archive-related raw files
# 8. 其他路径中名字包含 ABCDE / forward / canonical 的文件
# ============================================================

$OutputRegex = '(?i)' + (
    'abcde|' +
    'v21[._-]?231|' +
    'v21[._-]?233|' +
    'v22[._-]?040|' +
    'v22[._-]?041|' +
    'v22[._-]?042|' +
    'v22[._-]?043|' +
    'v22[._-]?045|' +
    'strategy[_-]?ranking[_-]?master|' +
    'ranking[_-]?history|' +
    'top20|' +
    'top50|' +
    'overlap[_-]?matrix|' +
    'forward[_-]?(outcome|return|label|panel)|' +
    'canonical|' +
    'qfq|' +
    'benchmark|' +
    'universe'
)

$AllowedOutputExtensions = @(
    ".csv",
    ".json",
    ".parquet",
    ".feather",
    ".pkl"
)

$ScriptRegex = '(?i)' + (
    'abcde|' +
    'v21[._-]?231|' +
    'v21[._-]?233|' +
    'v22[._-]?040|' +
    'v22[._-]?041|' +
    'v22[._-]?042|' +
    'v22[._-]?043|' +
    'forward|' +
    'ranking'
)

$AllowedScriptExtensions = @(
    ".py",
    ".ps1",
    ".json",
    ".yaml",
    ".yml",
    ".toml"
)

$SelectedFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
$SkippedFiles  = New-Object System.Collections.Generic.List[object]

# ============================================================
# 扫描 outputs
# ============================================================

$OutputsRoot = Join-Path $RepoRoot "outputs"

if (Test-Path $OutputsRoot) {
    Get-ChildItem -Path $OutputsRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            ($AllowedOutputExtensions -contains $_.Extension.ToLowerInvariant()) -and
            ($_.FullName -match $OutputRegex)
        } |
        ForEach-Object {
            $SelectedFiles.Add($_)
        }
}
else {
    Write-Warning "outputs directory not found: $OutputsRoot"
}

# ============================================================
# 扫描 scripts，保存回测逻辑和权重定义
# ============================================================

$ScriptsRoot = Join-Path $RepoRoot "scripts"

if (Test-Path $ScriptsRoot) {
    Get-ChildItem -Path $ScriptsRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            ($AllowedScriptExtensions -contains $_.Extension.ToLowerInvariant()) -and
            (
                $_.FullName -match $ScriptRegex -or
                $_.Name -match '(?i)(factor|weight|strategy|universe|forward)'
            )
        } |
        ForEach-Object {
            $SelectedFiles.Add($_)
        }
}
else {
    Write-Warning "scripts directory not found: $ScriptsRoot"
}

# 去重
$SelectedFiles = $SelectedFiles |
    Sort-Object FullName -Unique

# ============================================================
# 复制并保留原始目录结构
# ============================================================

$CopiedRecords = New-Object System.Collections.Generic.List[object]

foreach ($File in $SelectedFiles) {
    $SizeMB = [math]::Round($File.Length / 1MB, 3)

    if ($SizeMB -gt $MaxSingleFileMB) {
        $SkippedFiles.Add(
            [pscustomobject]@{
                FullPath      = $File.FullName
                SizeMB        = $SizeMB
                Reason        = "FILE_EXCEEDS_MAX_SINGLE_FILE_MB"
                LastWriteTime = $File.LastWriteTime
            }
        )
        continue
    }

    $RelativePath = $File.FullName.Substring($RepoRoot.Length).TrimStart("\")
    $Destination  = Join-Path $Payload $RelativePath
    $DestDir      = Split-Path $Destination -Parent

    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Destination -Force

    $Hash = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash

    $CopiedRecords.Add(
        [pscustomobject]@{
            RelativePath  = $RelativePath
            SourcePath    = $File.FullName
            SizeBytes     = $File.Length
            SizeMB        = $SizeMB
            LastWriteTime = $File.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            SHA256        = $Hash
        }
    )
}

# ============================================================
# 清单与统计
# ============================================================

$ManifestPath = Join-Path $BundleRoot "MANIFEST.csv"
$CopiedRecords |
    Sort-Object RelativePath |
    Export-Csv -Path $ManifestPath -NoTypeInformation -Encoding UTF8

$SkippedPath = Join-Path $BundleRoot "SKIPPED_FILES.csv"
$SkippedFiles |
    Export-Csv -Path $SkippedPath -NoTypeInformation -Encoding UTF8

$TotalBytes = ($CopiedRecords | Measure-Object -Property SizeBytes -Sum).Sum
if ($null -eq $TotalBytes) {
    $TotalBytes = 0
}

$Summary = [ordered]@{
    export_timestamp            = (Get-Date).ToString("o")
    repo_root                   = $RepoRoot
    bundle_root                 = $BundleRoot
    copied_file_count           = $CopiedRecords.Count
    skipped_file_count          = $SkippedFiles.Count
    total_size_mb               = [math]::Round($TotalBytes / 1MB, 3)
    max_single_file_mb          = $MaxSingleFileMB
    contains_csv                = @($CopiedRecords | Where-Object {$_.RelativePath -match '\.csv$'}).Count
    contains_json               = @($CopiedRecords | Where-Object {$_.RelativePath -match '\.json$'}).Count
    contains_parquet            = @($CopiedRecords | Where-Object {$_.RelativePath -match '\.parquet$'}).Count
    contains_strategy_code      = @($CopiedRecords | Where-Object {$_.RelativePath -match '\.(py|ps1)$'}).Count
}

$Summary |
    ConvertTo-Json -Depth 5 |
    Set-Content -Path (Join-Path $BundleRoot "EXPORT_SUMMARY.json") -Encoding UTF8

# ============================================================
# 输出关键文件定位表
# ============================================================

$KeyPatterns = [ordered]@{
    abcde_ranking_master = 'abcde_strategy_ranking_master'
    abcde_top20          = 'abcde_top20'
    abcde_top50          = 'abcde_top50'
    abcde_overlap        = 'abcde_strategy_overlap'
    v21_233_summary      = 'v21_233_summary'
    v22_040_summary      = 'v22_040_summary'
    v22_040_ledger       = 'v22_040_stage_ledger'
    forward_outcome      = 'forward.*(outcome|return|label|panel)'
    canonical_price      = 'canonical.*(price|daily|panel)|qfq'
    universe             = 'universe'
}

$KeyFileRows = foreach ($Entry in $KeyPatterns.GetEnumerator()) {
    $Matches = $CopiedRecords |
        Where-Object {$_.RelativePath -match "(?i)$($Entry.Value)"} |
        Sort-Object LastWriteTime -Descending

    if ($Matches.Count -gt 0) {
        foreach ($Match in $Matches | Select-Object -First 10) {
            [pscustomobject]@{
                Category      = $Entry.Key
                RelativePath  = $Match.RelativePath
                SizeMB        = $Match.SizeMB
                LastWriteTime = $Match.LastWriteTime
            }
        }
    }
    else {
        [pscustomobject]@{
            Category      = $Entry.Key
            RelativePath  = "NOT_FOUND"
            SizeMB        = 0
            LastWriteTime = ""
        }
    }
}

$KeyFileRows |
    Export-Csv -Path (Join-Path $BundleRoot "KEY_FILES.csv") `
    -NoTypeInformation `
    -Encoding UTF8

# ============================================================
# 保存 Git 状态
# ============================================================

$GitInfoPath = Join-Path $BundleRoot "GIT_STATE.txt"

try {
    Push-Location $RepoRoot

    "=== GIT COMMIT ===" |
        Set-Content -Path $GitInfoPath -Encoding UTF8

    git rev-parse HEAD 2>&1 |
        Add-Content -Path $GitInfoPath -Encoding UTF8

    "`n=== GIT STATUS --SHORT ===" |
        Add-Content -Path $GitInfoPath -Encoding UTF8

    git status --short 2>&1 |
        Add-Content -Path $GitInfoPath -Encoding UTF8
}
catch {
    "Git information unavailable: $($_.Exception.Message)" |
        Set-Content -Path $GitInfoPath -Encoding UTF8
}
finally {
    Pop-Location
}

# ============================================================
# 保存 Python环境
# ============================================================

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (Test-Path $PythonExe) {
    try {
        & $PythonExe -m pip freeze |
            Set-Content `
                -Path (Join-Path $BundleRoot "PYTHON_REQUIREMENTS_SNAPSHOT.txt") `
                -Encoding UTF8
    }
    catch {
        Write-Warning "Failed to capture pip freeze."
    }
}

# ============================================================
# 生成说明
# ============================================================

$Readme = @"
ABCDE BACKTEST BUNDLE

Created:
$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Purpose:
- Compare A1 / B / C / D / E strategy effectiveness
- Reconstruct historical daily rankings
- Join rankings with canonical adjusted prices
- Run lagged Top-K portfolio backtests
- Measure turnover, drawdown, IC, hit rate and benchmark excess return

Important:
- Do not include broker credentials, API keys or account identifiers.
- Rankings must be shifted by at least one tradable bar/day before simulated execution.
- Canonical qfq prices should be used for return calculations when available.

Files:
- MANIFEST.csv
- KEY_FILES.csv
- EXPORT_SUMMARY.json
- SKIPPED_FILES.csv
- GIT_STATE.txt
- payload\
"@

$Readme |
    Set-Content -Path (Join-Path $BundleRoot "README_BACKTEST.txt") -Encoding UTF8

# ============================================================
# 压缩
# ============================================================

$ZipPath = "$BundleRoot.zip"

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Compress-Archive `
    -Path "$BundleRoot\*" `
    -DestinationPath $ZipPath `
    -CompressionLevel Optimal

Write-Host ""
Write-Host "=== EXPORT COMPLETE ==="
Write-Host "copied_file_count=$($CopiedRecords.Count)"
Write-Host "skipped_file_count=$($SkippedFiles.Count)"
Write-Host "total_size_mb=$([math]::Round($TotalBytes / 1MB, 3))"
Write-Host "bundle_folder=$BundleRoot"
Write-Host "bundle_zip=$ZipPath"
Write-Host "manifest=$ManifestPath"
Write-Host "key_files=$(Join-Path $BundleRoot 'KEY_FILES.csv')"
Write-Host ""
