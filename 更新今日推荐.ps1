[CmdletBinding()]
param([ValidateRange(1, 65535)][int]$Port = 8506, [switch]$RefreshData, [string]$FiniteCaAdmissionRef)

$ErrorActionPreference = 'Stop'
$originalConsoleEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot 'scripts/common/storage_paths.ps1')
$paths = Get-UstqStoragePaths -RepoRoot $PSScriptRoot
$finiteCaRef = $null
$finiteCaJson = $null
if ($FiniteCaAdmissionRef) {
    $finiteCaRef = $FiniteCaAdmissionRef | ConvertFrom-Json -ErrorAction Stop
    if (@($finiteCaRef.PSObject.Properties.Name).Count -ne 2 -or
        $finiteCaRef.path -isnot [string] -or [string]::IsNullOrWhiteSpace($finiteCaRef.path) -or
        $finiteCaRef.sha256 -isnot [string] -or $finiteCaRef.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw '有限 MAIN CA admission 必须是精确 JSON {path,sha256}；原默认资格不变。'
    }
    $finiteCaJson = $finiteCaRef | ConvertTo-Json -Compress
}

function Invoke-UstqDailyAction {
    param([string[]]$Arguments)
    # One streaming presentation adapter for the existing finite daily actions.
    # Preserve native exit codes, progress and the original terminal-result rules.
    $result = $null
    & $paths.python_exe @Arguments | ForEach-Object {
        $line = [string]$_
        if ($line -notmatch '^\s*\{') { Write-Host $line; return }
        try { $event = $line | ConvertFrom-Json -ErrorAction Stop }
        catch { Write-Host $line; return }
        if ($event.event -eq 'progress') { Write-Host $event.message }
        if ($event.event -eq 'result') { $result = $event.result }
    }
    return [pscustomobject]@{ result = $result; exit_code = $LASTEXITCODE }
}

function Read-UstqBoundedJson {
    param([IO.Stream]$Stream, [Threading.CancellationToken]$CancellationToken = [Threading.CancellationToken]::None)
    $limit = 4 * 1024 * 1024
    $buffer = New-Object byte[] 8192
    $payload = [IO.MemoryStream]::new()
    try {
        while ($true) {
            $read = $Stream.ReadAsync($buffer, 0, [Math]::Min($buffer.Length, $limit + 1 - [int]$payload.Length), $CancellationToken).GetAwaiter().GetResult()
            if ($read -eq 0) { break }
            $payload.Write($buffer, 0, $read)
            if ($payload.Length -gt $limit) { throw '模拟组件摘要超过 4 MiB；未读取完整历史。' }
        }
        return [Text.UTF8Encoding]::new($false, $true).GetString($payload.ToArray()) | ConvertFrom-Json
    } finally { $payload.Dispose() }
}

function Invoke-UstqComponentRequest {
    param([ValidateSet('/api/health', '/api/applied/view', '/api/applied/showcase-roster', '/api/token', '/api/applied/reconcile', '/api/applied/prepare-current', '/api/applied/charts-update', '/api/applied/maintenance-begin', '/api/applied/maintenance-status', '/api/applied/maintenance-end')][string]$Path,
          [ValidateSet('GET', 'POST')][string]$Method = 'GET', [hashtable]$Body, [string]$Token)
    # Fixed same-origin routes, no redirects, no order/start/authorization endpoints.
    if (($Method -eq 'POST') -ne ($Path -cin @('/api/applied/reconcile', '/api/applied/prepare-current', '/api/applied/charts-update', '/api/applied/maintenance-begin', '/api/applied/maintenance-end'))) { throw '模拟组件请求路径或方法不匹配。' }
    Add-Type -AssemblyName System.Net.Http
    $origin = 'http://127.0.0.1:8766'
    $handler = [Net.Http.HttpClientHandler]::new(); $handler.AllowAutoRedirect = $false; $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler); $client.Timeout = [Threading.Timeout]::InfiniteTimeSpan
    # Original owner maximum call counts, not a guessed short mutation deadline.
    # GET retains the existing 15s/4MiB bound; timed-out POST is never repeated.
    $seconds = switch ($Path) {
        '/api/applied/maintenance-begin' { 330 }
        '/api/applied/prepare-current' { 4500 }
        '/api/applied/charts-update' { 660 }
        '/api/applied/maintenance-end' { 660 }
        default { 15 }
    }
    $deadline = [Threading.CancellationTokenSource]::new($seconds * 1000)
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($Method), ($origin + $Path))
    $response = $null; $stream = $null
    try {
        $request.Headers.Add('Origin', $origin)
        if ($Method -eq 'POST') {
            if (-not $Token) { throw '模拟组件授权令牌缺失。' }
            $request.Headers.Add('X-CSRF-Token', $Token)
            $request.Content = [Net.Http.StringContent]::new(($Body | ConvertTo-Json -Compress), [Text.Encoding]::UTF8, 'application/json')
        }
        $response = $client.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $deadline.Token).GetAwaiter().GetResult()
        if ($response.Content.Headers.ContentLength -gt 4 * 1024 * 1024) { throw '模拟组件摘要超过 4 MiB。' }
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $value = Read-UstqBoundedJson -Stream $stream -CancellationToken $deadline.Token
        if (-not $response.IsSuccessStatusCode -or $value.ok -isnot [bool] -or -not $value.ok) {
            throw "模拟组件未接受请求（HTTP $([int]$response.StatusCode)）：$($value.error)"
        }
        return $value
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose(); $deadline.Dispose(); $client.Dispose(); $handler.Dispose()
    }
}

function Get-UstqSimulationView {
    $health = Invoke-UstqComponentRequest -Path '/api/health'
    if ($health.data.component -cne 'moomoo-trading-component' -or
        $health.data.live_execution_enabled -isnot [bool] -or $health.data.live_execution_enabled) {
        throw '8766 未通过原模拟组件健康校验；保留该端口的现有进程。'
    }
    if ($health.data.manual_data_updates -isnot [bool] -or -not $health.data.manual_data_updates) {
        throw '原模拟组件未启用 ManualDataUpdates；保留现有进程，须按原入口切换手动更新模式。'
    }
    $view = Invoke-UstqComponentRequest -Path '/api/applied/view'
    if ($view.display.status -cne 'CURRENT' -or $view.display.owner_busy -isnot [bool] -or $view.display.owner_busy) {
        throw '模拟组件正在处理原任务，当前摘要为旧快照；未准备或更改启停状态。'
    }
    if ($view.data.manual_data_updates -isnot [bool] -or -not $view.data.manual_data_updates -or
        $view.data.broker.manual_data_updates -isnot [bool] -or -not $view.data.broker.manual_data_updates) {
        throw '原模拟组件未启用 ManualDataUpdates；保留现有进程，须按原入口切换手动更新模式。'
    }
    return $view
}

function Ensure-UstqSimulationService {
    $componentPort = 8766
    $listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    if ($listeners | Where-Object { $_.Port -eq $componentPort }) {
        $view = Get-UstqSimulationView
        Write-Host '模拟组件已在线；沿用原账户、历史与当前启停状态。'
        return $view
    }
    $launcher = Join-Path $PSScriptRoot 'apps/moomoo_trading_component/start.ps1'
    $shellExe = Join-Path $PSHOME 'pwsh.exe'
    if (-not (Test-Path -LiteralPath $shellExe)) { $shellExe = Join-Path $PSHOME 'powershell.exe' }
    $logRoot = Join-Path $paths.daily_root 'moomoo_trading_component/logs'
    Assert-UstqExternalPath -Path $logRoot -Kind daily | Out-Null
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')
    $launchArgs = @('-NoProfile', '-File', ('"{0}"' -f $launcher), '-Port', "$componentPort",
        '-ManualDataUpdates', '-WithMoomooBest', '-ExecutionDelayMinutes', '25',
        '-ExecutionWindowSeconds', '1500', '-BrokerExecutionWindowSeconds', '1500')
    $started = Start-Process -FilePath $shellExe -ArgumentList $launchArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot ("daily-launch-$stamp.log")) `
        -RedirectStandardError (Join-Path $logRoot ("daily-launch-$stamp.err.log"))
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if ($started.HasExited) { break }
        try {
            $view = Get-UstqSimulationView
            if ($view.data.running -is [bool] -and -not $view.data.running -and
                $view.data.broker.running -is [bool] -and -not $view.data.broker.running) {
                Write-Host '已启动原组件的手动数据模式，五本与原 SIM 保持暂停。'
                return $view
            }
            throw '新模拟组件未处于双暂停；未改变其状态。'
        } catch { $lastFailure = [string]$_.Exception.Message }
    }
    throw "原模拟组件尚未就绪；$lastFailure；日志：$logRoot"
}

function Get-UstqActiveStrategyIds {
    # Reuse the accepted roster owner; a failed read never falls back locally.
    $metadata = (Invoke-UstqComponentRequest -Path '/api/applied/showcase-roster').data
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $idsJson = ($metadata | ConvertTo-Json -Depth 32 -Compress) | & $paths.python_exe -X utf8 -B -c 'import json,sys; from apps.moomoo_trading_component.moomoo_component.showcase import validate_state_projection; state=json.load(sys.stdin); projection=validate_state_projection(state); (state.get("metadata_only") is True and state.get("books")=={} and state.get("active_strategy_ids")==projection["showcase_ids"]) or sys.exit("SHOWCASE_ROSTER_METADATA_STATE_CHANGED"); print(json.dumps(projection["showcase_ids"]))'
    if ($LASTEXITCODE -ne 0) { throw '原活动名单元数据未通过核验；不回退旧名单。' }
    return @($idsJson | Out-String | ConvertFrom-Json)
}

function Get-UstqMaintenanceStatus {
    param($Context)
    $value = (Invoke-UstqComponentRequest -Path '/api/applied/maintenance-status').data
    if ($value.schema -cne 'MANUAL_DAILY_MAINTENANCE_V1' -or
        $value.maintenance_id -cne $Context.maintenance_id -or
        $value.original_running.cohort -isnot [bool] -or $value.original_running.broker -isnot [bool] -or
        $value.original_running.cohort -ne $value.original_running.broker -or
        $value.active -isnot [bool] -or $value.restore_requested -isnot [bool] -or
        $value.operation_active -isnot [bool] -or $value.job_active -isnot [bool] -or
        $value.workers_drained -isnot [bool] -or $value.cleanup_verified -isnot [bool]) {
        throw '原维护状态身份或控制回执未知；保持暂停，不重发操作。'
    }
    if ($null -ne $Context.original_running -and
        ($value.original_running.cohort -ne $Context.original_running.cohort -or
         $value.original_running.broker -ne $Context.original_running.broker)) {
        throw '原维护启停意图绑定改变；保持暂停，不恢复。'
    }
    return $value
}

function Wait-UstqMaintenance {
    param($Context, [string[]]$Phases, [int]$Seconds)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        $state = Get-UstqMaintenanceStatus -Context $Context
        if (-not $state.operation_active -and -not $state.job_active -and $state.phase -cin $Phases) { return $state }
        if ($state.phase -cin @('FAILED', 'CANCELLED') -and -not $state.operation_active -and -not $state.job_active) {
            throw "原维护阶段失败：$($state.reason)；保持暂停。"
        }
        if ($watch.Elapsed.TotalSeconds -ge $Seconds) { throw '原维护状态仍未确定；保持暂停，不重发操作或恢复运行。' }
        Start-Sleep -Seconds 2
    } while ($true)
}

function Invoke-UstqMaintenanceOperation {
    param($Context, [string]$Path, [hashtable]$Body, [string[]]$Phases, [int]$Seconds)
    try {
        $null = Invoke-UstqComponentRequest -Path $Path -Method POST -Token $Context.token -Body $Body
    } catch {
        # Transport failure says nothing about whether the original owner accepted
        # the operation. Only fresh scalar status of this exact ID can settle it.
        Write-Warning '原维护操作未收到完整回执；只核验同一维护记录，不重复提交。'
    }
    return Wait-UstqMaintenance -Context $Context -Phases $Phases -Seconds $Seconds
}

function Begin-UstqDailyMaintenance {
    $view = Ensure-UstqSimulationService
    $token = (Invoke-UstqComponentRequest -Path '/api/token').data.token
    $context = [pscustomobject]@{maintenance_id=('daily_' + [Guid]::NewGuid().ToString('N')); token=$token; end_submitted=$false;original_running=$null}
    # A new paused service needs its original read-only account connection first.
    # This display hint only selects a read request; reconcile itself checks fresh
    # paused/account/budget identity. It cannot authorise a pause or resume.
    if ($view.data.running -is [bool] -and -not $view.data.running -and
        $view.data.broker.running -is [bool] -and -not $view.data.broker.running) {
        $null = Invoke-UstqComponentRequest -Path '/api/applied/reconcile' -Method POST -Token $token -Body @{}
    }
    $script:dailyMaintenanceContext = $context
    $state = Invoke-UstqMaintenanceOperation -Context $context -Path '/api/applied/maintenance-begin' `
        -Body @{maintenance_id=$context.maintenance_id} -Phases @('PAUSED') -Seconds 330
    if (-not $state.workers_drained -or -not $state.cleanup_verified -or -not $state.active) {
        throw '原维护未确认安全暂停和清理；未执行日更。'
    }
    $context.original_running = [pscustomobject]@{cohort=$state.original_running.cohort;broker=$state.original_running.broker}
    return $context
}

function Assert-UstqPreparedReceipt {
    param($Receipt, [string]$SignalDate)
    $parsed = [DateTime]::MinValue; $execution = [DateTime]::MinValue
    if (-not [DateTime]::TryParseExact($SignalDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$parsed) -or $parsed.Year -ne 2026 -or
        $Receipt.action -cne 'PREPARE_CURRENT_PUBLISHED_INPUTS' -or $Receipt.signal_date -cne $SignalDate -or
        ($Receipt.orders_created -isnot [int] -and $Receipt.orders_created -isnot [long]) -or $Receipt.orders_created -ne 0 -or
        $Receipt.running -isnot [bool] -or $Receipt.running -or $Receipt.status -cnotin @('READY', 'PARTIAL') -or
        -not [DateTime]::TryParseExact($Receipt.execution_date, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$execution) -or $execution.Year -ne 2026 -or $execution -le $parsed) {
        throw '原模拟准备回执日期或零委托／暂停证明不匹配。'
    }
    $ids = @(Get-UstqActiveStrategyIds); $bookIds = @($Receipt.books.PSObject.Properties.Name)
    if ($ids.Count -ne 5 -or $bookIds.Count -ne $ids.Count -or @($bookIds | Where-Object { $_ -cnotin $ids }).Count) {
        throw '原准备回执的五套活动策略身份不匹配。'
    }
    foreach ($sid in $ids) {
        $book = $Receipt.books.$sid
        if ($book.signal_date -cne $SignalDate -or $book.execution_date -cne $Receipt.execution_date -or
            $book.status -cnotin @('READY', 'BLOCKED')) { throw '原准备回执的策略日期或状态不匹配。' }
    }
    $broker = $Receipt.broker
    if ($null -eq $broker -or $broker.action -cne 'PREPARE_CURRENT_PUBLISHED_INPUTS' -or
        $broker.signal_date -cne $SignalDate -or $broker.execution_date -cne $Receipt.execution_date -or
        $broker.strategy_id -cnotin $ids -or $broker.prepared -isnot [bool] -or
        ($broker.orders_created -isnot [int] -and $broker.orders_created -isnot [long]) -or $broker.orders_created -ne 0 -or
        $broker.running -isnot [bool] -or $broker.running) { throw '原 SIM 准备回执不匹配。' }
    if ($Receipt.status -ceq 'READY' -and (@($ids | Where-Object { $Receipt.books.$_.status -cne 'READY' }).Count -or
        -not $broker.prepared -or $broker.status -cne 'READY')) { throw '原准备回执的 READY 与分项状态不一致。' }
}

function Prepare-UstqSimulationCurrent {
    param([string]$SignalDate, $Context)
    $parsed = [DateTime]::MinValue
    if (-not [DateTime]::TryParseExact($SignalDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$parsed) -or $parsed.Year -ne 2026) {
        throw '更新返回的信号日期不在原 2026 观测边界；未提交准备。'
    }
    $control = Get-UstqMaintenanceStatus -Context $Context
    if ($control.phase -cne 'PAUSED' -or $control.operation_active -or $control.job_active -or
        -not $control.cleanup_verified -or -not $control.workers_drained) {
        throw '原维护尚未处于安全暂停；未提交准备。'
    }
    $null = Invoke-UstqComponentRequest -Path '/api/applied/reconcile' -Method POST -Token $Context.token -Body @{}
    $state = Invoke-UstqMaintenanceOperation -Context $Context -Path '/api/applied/prepare-current' `
        -Body @{maintenance_id=$Context.maintenance_id;expected_signal_date=$SignalDate} -Phases @('PAUSED', 'FAILED') -Seconds 4500
    if ($null -eq $state.prepare_receipt) { throw "原准备未返回合格回执：$($state.reason)；保持暂停。" }
    Assert-UstqPreparedReceipt -Receipt $state.prepare_receipt -SignalDate $SignalDate
    return $state.prepare_receipt
}

function Update-UstqMainCharts {
    param([string]$SignalDate, $Context, $FiniteCaAdmission)
    # The original Cohort registers and supervises its original job. No separate
    # PS Python actor, ref resolver, model loop or process-local lease is created.
    $body = @{maintenance_id=$Context.maintenance_id;expected_signal_date=$SignalDate}
    if ($null -ne $FiniteCaAdmission) { $body.finite_ca_admission_ref = $FiniteCaAdmission }
    $state = Invoke-UstqMaintenanceOperation -Context $Context -Path '/api/applied/charts-update' `
        -Body $body -Phases @('READY', 'CHARTS_FINISHED', 'FAILED', 'CANCELLED') -Seconds 3930
    if (-not $state.cleanup_verified -or -not $state.workers_drained) {
        throw '原 MAIN 子树尚未确认清理；保持暂停。'
    }
    if ($state.phase -ceq 'CHARTS_FINISHED' -and $state.main_status -ceq 'AWAITING_OWNER_RECEIPT') {
        # A zero child exit is not publication qualification. The original end
        # operation must still verify the actual same-day immutable owner receipt.
        return [pscustomobject]@{status='AWAITING_OWNER_RECEIPT'}
    }
    if ($state.phase -cne 'READY' -or $state.main_status -cne 'READY' -or $state.main_end -cne $SignalDate) {
        throw "原 MAIN 图表未核验到 $SignalDate：$($state.reason)；旧合格曲线与暂停状态保留。"
    }
    return [pscustomobject]@{status='READY';end=$state.main_end}
}

function End-UstqDailyMaintenance {
    param($Context, [switch]$Abort, [string]$SignalDate)
    if ($Context.end_submitted) { throw '结束操作已经提交；仅核验同一维护状态，不重复提交。' }
    $Context.end_submitted = $true
    $body = @{maintenance_id=$Context.maintenance_id}
    if ($Abort) { $body.abort = $true }
    $state = Invoke-UstqMaintenanceOperation -Context $Context -Path '/api/applied/maintenance-end' `
        -Body $body -Phases @('FINISHED') -Seconds 660
    if ($state.active -or $state.cleanup_verified_before_resume -isnot [bool] -or
        -not $state.cleanup_verified_before_resume -or $state.operation_active -or $state.job_active -or
        $state.resumed -isnot [bool] -or $state.current_running.cohort -isnot [bool] -or
        $state.current_running.broker -isnot [bool] -or
        ($state.resumed -and ($Abort -or -not $state.original_running.cohort -or -not $state.restore_requested)) -or
        (-not $Abort -and $state.original_running.cohort -and $state.restore_requested -and -not $state.resumed)) {
        throw '原维护清理或最终启停回执未知；不重复提交或推断已恢复。'
    }
    if (-not $Abort -and ($state.main_status -cne 'READY' -or $state.main_end -cne $SignalDate)) {
        throw '原维护结束未确认同日 MAIN 发布；不推断更新完成。'
    }
    # resumed records the completed maintenance action; current_running is the
    # fresh current state and may reflect a later explicit stop/start.
    return $state
}

Push-Location $PSScriptRoot
try {
    $script:dailyMaintenanceContext = $null
    $maintenance = Begin-UstqDailyMaintenance
    $result = $null
    $updateArgs = @('-X', 'utf8', '-B', '-m', 'scripts.daily_recommendation', '--execute', '--compact-output')
    if ($RefreshData) { $updateArgs += '--refresh-data' }
    $updateAction = Invoke-UstqDailyAction -Arguments $updateArgs
    $result = $updateAction.result
    $updateExitCode = $updateAction.exit_code
    if ($null -eq $result) { throw '更新没有返回结果，请检查运行日志。' }

    Write-Host $result.message
    Write-Host "数据日期：$($result.data_date)；更新时间：$($result.generated_at)"
    Write-Host "原推荐报告：$($result.report_path)"
    if ($result.recovery.report_path) { Write-Host "本次恢复报告：$($result.recovery.report_path)" }
    if ($result.status -ne 'READY') {
        throw '今日推荐尚未生成；旧推荐不会作为当天结果展示。'
    }

    $coverage = $result.coverage
    Write-Host "股票池覆盖：$($coverage.eligible_count)/$($coverage.mapped_count) 可计算；$($coverage.excluded_count) 只因输入缺口排除。"
    $alternate = $result.acquisitions.alternate
    Write-Host "数据源：Moomoo $($result.acquisitions.moomoo.status)；备用行情 $($alternate.target_reached_symbols)/$($alternate.attempted_symbols) 只到达数据日期；公开数据 $($result.other_data.status)；基准行情到 $($result.benchmark_update.available_end_date)。"
    $massive = $result.acquisitions.massive
    if ($null -ne $massive) {
        $reached = if ($null -ne $massive.target_reached_count) { $massive.target_reached_count } else { @($massive.target_reached_tickers | Where-Object { $_ }).Count }
        $missing = if ($null -ne $massive.issue_count) { $massive.issue_count } else { @($massive.issues | Where-Object { $_ }).Count }
        Write-Host "MASSIVE：$reached/$($massive.selected_tickers) 只到达数据日期；$missing 只仍有缺口。"
        if ($missing -gt 0 -or $coverage.excluded_count -gt 0) {
            Write-Warning '数据源仍有缺口；本次推荐基于可验证的合格股票，不能视为全股票池完整覆盖。'
        }
    }

    Write-Host "最新 Top20 推荐："
    $result.rows | Select-Object rank,ticker,score,source | Format-Table -AutoSize | Out-String | Write-Host

    # Finish a previously blocked first publication in a fresh process after
    # the large daily producer has exited. Ordinary recovery stays reuse-only.
    $paperInputsReady = ($result.consensus_paper_inputs.status -ceq 'READY' -and
        $result.consensus_paper_inputs.paper_current_status -ceq 'READY')
    if (-not $paperInputsReady) {
        $inputSource = $result.accepted_source
        if (-not $inputSource.path -or $inputSource.sha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw '策略输入续接缺少原已接受来源，保持暂停。'
        }
        Write-Host '使用已发布日更来源，在独立进程中补齐策略输入；复用已接受的同日输入。'
        $inputResult = $null
        $inputArgs = @('-X', 'utf8', '-B', '-m', 'scripts.daily_recommendation', '--prepare-current-inputs',
            '--expected-signal-date', $result.data_date, '--source-report', $inputSource.path,
            '--source-sha256', $inputSource.sha256)
        $inputAction = Invoke-UstqDailyAction -Arguments $inputArgs
        $inputResult = $inputAction.result
        $inputExitCode = $inputAction.exit_code
        $inputCountersValid = $null -ne $inputResult
        if ($inputCountersValid) {
            foreach ($counterName in @('acquisition_calls', 'raw_inference_calls', 'model_fit_calls', 'trade_requests')) {
                $counter = $inputResult.PSObject.Properties[$counterName]
                if ($null -eq $counter -or ($counter.Value -isnot [int] -and $counter.Value -isnot [long]) -or
                    $counter.Value -ne 0) { $inputCountersValid = $false }
            }
        }
        if ($null -eq $inputResult -or $inputResult.action -cne 'PREPARE_CURRENT_INPUTS' -or
            $inputResult.target_date -cne $result.data_date -or -not $inputCountersValid -or
            $inputResult.source_report.path -cne $inputSource.path -or
            $inputResult.source_report.sha256 -cne $inputSource.sha256 -or
            $inputResult.broker_action_allowed -isnot [bool] -or $inputResult.broker_action_allowed -or
            $inputResult.status -cnotin @('READY', 'BLOCKED') -or
            ($inputResult.status -ceq 'READY' -and $inputExitCode -ne 0)) {
            throw '策略输入续接未返回匹配的原来源回执；保持暂停，不启动账户操作。'
        }
        $paperInputsReady = $inputResult.status -ceq 'READY'
        if ($paperInputsReady) {
            Write-Host "策略输入已核验到 $($result.data_date)；接下来由原账户组件检查目标。"
        } else {
            Write-Warning "部分策略输入尚未就绪：$($inputResult.reason) $($inputResult.error)；继续由原组件核验各账户，保持暂停。"
        }
    }

    # Plan qualification is owned by prepare-current, separately from research charts.
    $preparation = Prepare-UstqSimulationCurrent -SignalDate $result.data_date -Context $maintenance
    $currentTargetsReady = $preparation.status -ceq 'READY'
    if ($currentTargetsReady) {
        Write-Host "五套 PAPER 与原 SIM 已准备信号 $($preparation.signal_date) → 执行 $($preparation.execution_date)，保持暂停，新增委托为 0。"
    } else { Write-Warning "模拟目标尚未全部准备：$($preparation.status) $($preparation.reason)；原启停意图和历史保留。" }
    # Both accepted statuses are fresh owner receipts: controls remained paused
    # and no order cycle ran. A per-account PARTIAL must not block independent
    # MAIN qualification; it still prevents overall delivery READY.
    $main = if ($preparation.status -cin @('READY', 'PARTIAL')) {
        # Only this explicit manual entry can request missing native CA responses.
        # This stage grants no MAIN source/account admission; charts requalify.
        $caResult = $null
        $caArgs = @('-X', 'utf8', '-B', '-m', 'scripts.daily_recommendation', '--prepare-main-ca', '--expected-signal-date', $result.data_date)
        if ($null -ne $finiteCaRef) { $caArgs += @('--finite-ca-admission-ref', $finiteCaJson) }
        $caAction = Invoke-UstqDailyAction -Arguments $caArgs
        $caResult = $caAction.result
        $caExitCode = $caAction.exit_code
        $caCountersValid = $null -ne $caResult
        if ($caCountersValid) {
            foreach ($counterName in @('history_requests', 'trade_requests', 'model_fit_calls', 'models_loaded', 'account_replays')) {
                $counterProperty = $caResult.PSObject.Properties[$counterName]
                if ($null -eq $counterProperty -or
                    ($counterProperty.Value -isnot [int] -and $counterProperty.Value -isnot [long]) -or
                    $counterProperty.Value -ne 0) { $caCountersValid = $false }
            }
            $rehabProperty = $caResult.PSObject.Properties['rehab_requests']
            if ($null -eq $rehabProperty -or
                ($rehabProperty.Value -isnot [int] -and $rehabProperty.Value -isnot [long]) -or
                $rehabProperty.Value -lt 0) { $caCountersValid = $false }
        }
        if ($caExitCode -ne 0 -or $null -eq $caResult -or $caResult.action -cne 'PREPARE_MAIN_CA' -or
            $caResult.status -cne 'READY' -or $caResult.target_date -cne $result.data_date -or
            -not $caCountersValid -or
            $caResult.broker_action_allowed -isnot [bool] -or $caResult.broker_action_allowed -or
            $caResult.main_qualification_ready -isnot [bool] -or $caResult.main_qualification_ready) {
            throw "MAIN 原来源 CA 准备未获核验：$($caResult.status) $($caResult.reason) $($caResult.error)；合格数据和目标保留，继续暂停。"
        }
        Write-Host "MAIN 当期 CA 来源回执已核验，新增 get_rehab 查询 $($caResult.rehab_requests)；接下来仍由原 MAIN 独立资格门核验。"
        if ($null -ne $finiteCaRef -and ($null -eq $caResult.finite_ca_admission_ref -or
            $caResult.finite_ca_admission_ref.path -cne $finiteCaRef.path -or
            $caResult.finite_ca_admission_ref.sha256 -cne $finiteCaRef.sha256)) {
            throw '有限 MAIN CA admission 回执身份与显式请求不一致；保持暂停。'
        }
        Update-UstqMainCharts -SignalDate $result.data_date -Context $maintenance -FiniteCaAdmission $finiteCaRef
    }
        else { [pscustomobject]@{status='NOT_UPDATED';reason='原安全暂停准备未获核验；未启动新的 MAIN 图表任务。'} }

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
    if ($sync.performance_end_date -lt $result.data_date -or
        $published.performance_end_date -lt $result.data_date) {
        throw "推荐已更新到 $($result.data_date)，但绩效曲线只到 $($published.performance_end_date)；本次更新未达到 DEMO 全部同步要求。"
    }

    if (-not $paperInputsReady -or -not $currentTargetsReady -or $main.status -cnotin @('READY', 'AWAITING_OWNER_RECEIPT') -or $updateExitCode -ne 0 -or $null -eq $result.completion -or $result.completion.status -cne 'READY') {
        throw '推荐和合格模拟目标已保留；模拟目标、Raw／HGB／MAIN 图表或基准尚未全部核验，查看报告 completion 的失败分支。重跑同一入口可恢复未完成步骤。'
    }
    $finished = End-UstqDailyMaintenance -Context $maintenance -SignalDate $result.data_date
    $script:dailyMaintenanceContext = $null
    Write-Host "原维护已结束；当前 PAPER 运行=$($finished.current_running.cohort)，原 SIM 运行=$($finished.current_running.broker)。启停以原 owner 回执为准。"
    Write-Host "DEMO 五套目标、排名、Raw／HGB／MAIN 图表和基准已核验到完成交易日 $($result.data_date)。实际模拟成交另见账户状态。正在打开 http://127.0.0.1:$Port/"
    & (Join-Path $PSScriptRoot 'apps/demo_console/start.ps1') -Port $Port
} catch {
    $failure = $_
    if ($null -ne $script:dailyMaintenanceContext) {
        try {
            $control = Get-UstqMaintenanceStatus -Context $script:dailyMaintenanceContext
            if ($control.active -and -not $script:dailyMaintenanceContext.end_submitted) {
                $null = End-UstqDailyMaintenance -Context $script:dailyMaintenanceContext -Abort
                Write-Warning '本次日更未完成；原维护已清理，账户继续暂停。'
            } else {
                Write-Warning '本次日更未完成；仅核验原维护记录，实际启停状态以 owner 回执为准。'
            }
        } catch { Write-Warning '本次日更或维护结果未知；保持暂停，仅核验原维护状态，不重复提交或恢复。' }
    }
    throw $failure
} finally {
    [Console]::OutputEncoding = $originalConsoleEncoding
    Pop-Location
}
