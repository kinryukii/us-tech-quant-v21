[CmdletBinding()]
param([ValidateRange(1, 65535)][int]$Port = 8506)

$ErrorActionPreference = 'Stop'
$originalConsoleEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot 'scripts/common/storage_paths.ps1')
$paths = Get-UstqStoragePaths -RepoRoot $PSScriptRoot

Push-Location $PSScriptRoot
try {
    $result = $null
    & $paths.python_exe -B -m scripts.daily_recommendation --execute | ForEach-Object {
        $line = [string]$_
        if ($line -notmatch '^\s*\{') { Write-Host $line; return }
        try { $event = $line | ConvertFrom-Json -ErrorAction Stop }
        catch { Write-Host $line; return }
        if ($event.event -eq 'progress') { Write-Host $event.message }
        if ($event.event -eq 'result') { $result = $event.result }
    }
    $updateExitCode = $LASTEXITCODE
    if ($null -eq $result) { throw '更新没有返回结果，请检查运行日志。' }

    Write-Host $result.message
    Write-Host "数据日期：$($result.data_date)；更新时间：$($result.generated_at)"
    Write-Host "报告：$($result.report_path)"
    if ($result.status -ne 'READY' -or $updateExitCode -ne 0) {
        throw '今日推荐尚未生成；旧推荐不会作为当天结果展示。'
    }

    $coverage = $result.coverage
    Write-Host "股票池覆盖：$($coverage.eligible_count)/$($coverage.mapped_count) 可计算；$($coverage.excluded_count) 只因输入缺口排除。"
    $alternate = $result.acquisitions.alternate
    Write-Host "数据源：Moomoo $($result.acquisitions.moomoo.status)；备用行情 $($alternate.target_reached_symbols)/$($alternate.attempted_symbols) 只到达数据日期；公开数据 $($result.other_data.status)；基准行情到 $($result.benchmark_update.available_end_date)。"
    $massive = $result.acquisitions.massive
    if ($null -ne $massive) {
        $reached = @($massive.target_reached_tickers | Where-Object { $_ }).Count
        $missing = @($massive.issues | Where-Object { $_ }).Count
        Write-Host "MASSIVE：$reached/$($massive.selected_tickers) 只到达数据日期；$missing 只仍有缺口。"
        if ($missing -gt 0 -or $coverage.excluded_count -gt 0) {
            Write-Warning '数据源仍有缺口；本次推荐基于可验证的合格股票，不能视为全股票池完整覆盖。'
        }
    }

    Write-Host "最新 Top20 推荐："
    $result.rows | Select-Object rank,ticker,score,source | Format-Table -AutoSize | Out-String | Write-Host

    $selected = $result.selected_strategies_update
    if ($null -ne $selected) {
        if ($selected.status -in @('READY', 'PARTIAL') -and $selected.report_path) {
            $policies = Get-Content -LiteralPath $selected.report_path -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($name in @('HGB_DIAG_5', 'HGB_FACTOR_5')) {
                $policy = $policies.strategies.$name
                $application = $policy.application
                Write-Host "$($policy.label)：$($application.status)，信号日 $($application.signal_date)。"
                if ($null -eq $application.target_cash_weight) {
                    Write-Warning "当前目标方案不可用：$($application.reason)"
                    continue
                }
                Write-Host "空仓账户目标方案，目标现金 $([Math]::Round(100 * $application.target_cash_weight, 2))%；收盘目标、下一交易日开盘待执行。"
                $application.rows | Select-Object ticker,target_weight,action | Format-Table -AutoSize | Out-String | Write-Host
            }
        } else {
            Write-Warning "两项 HGB 策略更新未完成：$($selected.error)。原 A2 推荐保留，DEMO 显示各策略实际可用日期。"
        }
    }

    $sync = $result.performance_update
    if ($null -eq $sync -or $sync.status -notin @('READY', 'PARTIAL') -or
        $sync.ranking_end_date -ne $result.data_date) {
        throw '推荐已打印在终端，但 DEMO 尚未核验到同一天的新排名；请查看上面的报告和绩效更新状态。'
    }

    $publishedPath = Join-Path $paths.daily_root 'A2_updated_research/latest.json'
    $published = Get-Content -LiteralPath $publishedPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($published.run_id -ne $sync.run_id -or $published.ranking_end_date -ne $result.data_date) {
        throw 'DEMO 当前指向的排名并非本次更新结果；请查看报告。'
    }
    if ($sync.performance_end_date -ne $result.data_date -or
        $published.performance_end_date -ne $result.data_date) {
        throw "推荐已更新到 $($result.data_date)，但绩效曲线只到 $($published.performance_end_date)；本次更新未达到 DEMO 全部同步要求。"
    }

    Write-Host "DEMO 排名和绩效均已同步到 $($sync.ranking_end_date)。正在打开 http://127.0.0.1:$Port/"
    & (Join-Path $PSScriptRoot 'apps/demo_console/start.ps1') -Port $Port
} finally {
    [Console]::OutputEncoding = $originalConsoleEncoding
    Pop-Location
}
