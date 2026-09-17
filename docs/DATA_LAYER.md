# 数据层开发入口

本数据层沿用项目的外部存储根与 per-ticker Parquet。`DataStore` 负责统一读取，SQLite catalog 负责记录所选文件、覆盖日期和来源。证券身份、13F 成员资格、研究冻结与策略采用仍由原有契约决定。

本说明描述接口与维护流程；实际已恢复数量、最新日期、缺失源与网络状态以本次交付报告和 `status` 的输出为准。新增来源须经校验、登记后才能从 catalog 读取；代码安装和数据登记也不等于原有冻结消费端已经切换。

## 存储位置

根路径统一由 `config/storage_paths.json` 和 `scripts/common/storage_paths.py` 解析。

| 责任 | 默认位置 |
| --- | --- |
| 源码、测试、小型配置 | `D:/us-tech-quant` |
| 数据文件 | `D:/us-tech-quant-data` |
| 下载缓存、可重建目录 | `D:/us-tech-quant-cache` |
| 日常运行状态 | `D:/us-tech-quant-daily` |
| 回测记录 | `D:/us-tech-quant-backtests` |
| 报告与补数计划 | `D:/us-tech-quant-results` |
| Python 环境 | `D:/us-tech-quant-envs` |

使用的 Python 是 `D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe`。数据、缓存、结果、环境根必须互不嵌套，并位于代码仓库之外。测试或暂存交付可通过 `USTQ_DATA_ROOT`、`USTQ_CACHE_ROOT`、`USTQ_RESULTS_ROOT` 等环境变量，或工具明确提供的根路径参数，指向独立目录。

当前文件组织为：

```text
data_root/
  stocks/<编码后的ticker>/
    daily_raw.parquet                   # 旧布局，保留
    daily_qfq.parquet                   # 旧布局，保留
    metadata.json                      # 旧来源元数据，保留
    versions/
      daily_raw_<内容hash前缀>.parquet
      daily_qfq_<内容hash前缀>.parquet
  providers/yahoo/stocks/<编码后的ticker>/versions/
    daily_split_adjusted_<内容hash前缀>.parquet
    actions_<内容hash前缀>.parquet
  providers/massive/grouped_daily/versions/<采集契约hash>/<编码后的ticker>/
    daily_raw.parquet
  reference/market_quality/versions/
    <质量记录或明确过滤后的内容hash版本>.parquet
cache_root/
  derived/data_catalog/catalog.sqlite3
  <显式指定的采集目录>/intervals/        # 下载结果及其校验记录
results_root/
  <显式指定的计划与报告目录>/
```

带 `/` 的证券代码通过安全编码的目录和 catalog 映射访问；不要把它直接拼接成文件路径。新 Parquet 按内容生成版本文件，保留原始源和旧版本。不要按“最新文件名”猜当前文件。

## 查询

从包含 `scripts` 的代码目录运行：

```python
from scripts.storage.storage_r2a import DataStore

store = DataStore()
tickers = store.list_tickers(adjustment="qfq")
bars = store.daily(
    "AAPL", "qfq", start_date="2026-09-01", end_date="2026-09-04",
    columns=["ticker", "date", "open", "high", "low", "close", "volume"],
)
metadata = store.metadata("prices_daily", "AAPL", "qfq")
print(metadata["path"], metadata.get("vintage_id"), metadata["lineage"])
```

行情日期边界包含首尾。日期和 ticker 条件在 Arrow 扫描阶段应用，再转换成 pandas；指定 `columns` 可减少读取量。日期列可以是 ISO 字符串、Arrow date 或 timestamp；timestamp 查询边界的时区必须与存储一致。

旧函数 `load_ticker_daily`、`load_ticker_intraday`、`scan_universe_daily` 保留。开发新代码优先使用 `DataStore`。只有 catalog 完全不存在时，默认 Moomoo 日线读取才回到旧 `stocks/<ticker>/daily_*.parquet`。catalog 已存在但缺项、目标文件消失、版本不支持或 current 选择重复，都会明确报错，不隐藏数据故障。Yahoo 读取始终要求明确的 catalog 记录。

### 显式选择补充行情来源

`daily()` 默认 `provider="moomoo"`，沿用 `prices_daily` 的 raw／QFQ。Yahoo 保存在独立的 `prices_daily_yahoo`，调用时必须同时明确 provider 和复权含义：

```python
yahoo_bars = store.daily(
    "AAPL", adjustment="split_adjusted", provider="yahoo",
    start_date="2026-09-01", end_date="2026-09-11",
    columns=["ticker", "date", "open", "high", "low", "close", "volume",
             "adjusted_close", "provider_code", "source_id", "observed_at"],
)
yahoo_metadata = store.metadata("prices_daily_yahoo", "AAPL", "split_adjusted")
actions = store.read("corporate_actions_yahoo", "AAPL",
                     start_date="2026-01-01", end_date="2026-09-11")
```

Massive 的原始日线使用独立的 `prices_daily_massive`：

```python
massive_bars = store.daily(
    "AAPL", adjustment="raw", provider="massive",
    start_date="2026-09-01", end_date="2026-09-11",
)
```

来源缺失或失败时明确报错；默认 Moomoo 读取不会尝试其他来源，各来源不会自动拼接或互相补值。`manage_data prices` 仍使用默认 Moomoo 入口。新增 provider 必须增加明确契约和测试，不能只靠改一个来源名称接入。

Yahoo 的 `open/high/low/close` 保留 chart 返回的拆股调整价格，标记 `split_adjusted`；它不等于 Moomoo QFQ，也不标记为 Moomoo raw。单列 `adjusted_close` 保留供应商额外调整后的收盘价，允许缺失；它不替代 `close`，不用于隐式重算 OHLC。公司行动独立保留事件类别、事件 ID、纽约日期、原事件 JSON 和同一原始响应的来源 hash。公司行动记录属于请求区间内的供应商快照；没有登记该数据集或没有返回某事件，不能据此证明该证券从未发生过公司行动。

每个 Yahoo 日线版本记录真实返回的 `provider_symbol`、`currency=USD`、`exchange_timezone=America/New_York`、原始 HTTP 响应路径与 SHA256、请求窗口及抓取时间。逐行 `source=YAHOO_CHART`，`provider_code` 等于真实返回的 symbol，`source_id` 是原始响应 SHA256；`observed_at` 必须是带时区的实际抓取时间。lineage 的 `vintage_semantics=CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT` 表示当前抓取版本，不能将其回填成历史时点已知数据。

读取前检查明确的 schema 与 lineage 契约，即使只请求 `close` 也要求完整必要列。完整验收另外逐行检查 OHLCV、重复 `(ticker,date)`、来源及运输代码、`adjusted_close`、时区和源文件 hash；Yahoo 覆盖单列在 `supplemental_price_datasets` 中，不计入 Moomoo raw／QFQ 双腿完整性。供应商当前运输代码验证不授予 CUSIP／CIK 历史身份、生命周期或策略资格。

命令行查看覆盖与少量行情：

```powershell
$pythonExe = 'D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe'
& $pythonExe -B -m scripts.storage.manage_data status
& $pythonExe -B -m scripts.storage.manage_data prices --ticker AAPL --adjustment raw --start 2026-09-01 --end 2026-09-04 --limit 10
```

`manage_data` 的 `--catalog`、`--data-root`、`--cache-root`、`--results-root` 等全局参数放在子命令前。`prices` 输出 CSV，`status` 输出 JSON。

## 基本面与 13F 独立读取

市场行情、SEC 基本面、13F 披露、证券身份和交易日历保留独立数据集，不合并成一张含义不清的宽表。索引程序只注册实际存在的来源；具体名称和覆盖看 `status`。

构建入口支持以下目录名称；实际注册数量取决于源文件是否存在，缺源时不会伪造空文件或冒充已补齐：

| dataset | 内容 | 日期使用注意 |
| --- | --- | --- |
| `prices_daily` | 每 ticker、raw／QFQ 日线 | `date` 是交易日期 |
| `prices_daily_yahoo` | Yahoo 独立拆股调整日线与辅助 `adjusted_close` | `date` 是纽约交易日期；当前抓取 vintage，不是历史 PIT |
| `prices_daily_massive` | Massive 独立未复权日线 | `date` 是请求的交易所日期；保留供应商原始时间戳 |
| `corporate_actions_yahoo` | Yahoo 请求窗口内的原始公司行动记录 | `date` 是纽约事件日期；原事件 JSON 和响应来源保留 |
| `market_symbol_aliases` | 有发行人依据的代码变更与股类运输格式 | 当前运输参考；读取不会自动改写历史代码 |
| `market_data_quality_events` | 零成交量、隔离、内部缺日等质量记录 | `date`；保留原值、原因和来源 |
| `market_provider_comparison_events` | 跨来源价格或成交量差异 | `date`；超过阈值不自动决定哪个来源正确 |
| `market_legacy_lifecycle_events` | 旧代码终止、结算和临时交易窗口的官方依据 | 区分已发生、计划和仍未知的事件；按实际列选择日期 |
| `prices_intraday_1m` | 每 ETF 的现存一分钟分片快照 | `timestamp_utc` 有明确时区；保留原全时段 session 与 raw 来源 |
| `prices_intraday_1m_incremental` | 与旧历史存在冲突、单独保留的新分钟来源 | 独立 vintage，不能直接和主分钟快照拼接 |
| `13f_universe_legacy` | 保留的旧动态 13F 股票池 | 生效日期不等于报告季度末；旧口径独立保留 |
| `13f_holdings_legacy` | 保留的旧选定机构持仓 | 按原始 accession 和披露时点解释 |
| `13f_identity` | 已有身份／运输映射 | 不能将当前 ticker 映射回填为历史事实 |
| `trading_calendar` | 当前所选 XNYS 正常交易时段日历 | `trade_date`；检查版本、范围及实际登记来源 |
| `trading_calendar_provider_legacy` | 保留的原 Moomoo 日历 | 保留旧范围，不覆盖生成日历的 current |
| `sec_submissions_pre2026` | 恢复的 2026 年以前 SEC 提交记录 | `filed_date`；实际接受时点分别保留 |
| `sec_facts_pre2026` | 恢复的 2026 年以前 SEC XBRL 事实 | `filed_date_fact`；保留单位、accession 与修订 |
| `sec_feature_states_pre2026` | 既有算法恢复的基本面状态 | `feature_effective_date`；依赖原有特征与 PIT 契约 |
| `sec_companyfacts_2026_snapshot` | 现有 SEC 快照内的 2026 年事实 | `filed_date`；快照范围不等于目标日期完整覆盖 |
| `sec_submissions_2026_snapshot` | 现有 SEC 快照内的 2026 年提交记录 | `filed_date`；报告期与接受时点独立 |
| `sec_companyfacts_incremental` | 后续增量 SEC 事实 | `filed_date`；保留独立快照和来源 |
| `sec_submissions_incremental` | 后续增量 SEC 提交记录 | `filed_date`；不能直接覆盖旧快照 |
| `sec_companyfacts_2026` | 基线与增量的统一 2026 年事实查询副本 | 保留单位、期间、frame、修订和所有源行；不按 ticker／year 聚合 |
| `sec_submissions_2026` | 基线、增量及显式时点例外的统一提交查询副本 | `(cik, accession)` 唯一；按有时区的 `accepted_at` 查询 |
| `13f_universe_external25` | 外部 25 家口径的动态股票池 | `effective_date`；独立于原 authoritative 口径 |
| `13f_quarter_external25` | 外部 25 家口径的季度股票池 | `effective_date`；季度末不等于可用日期 |
| `13f_filings_external25` | 外部 25 家口径的提交记录 | `filed_date`；核对 accession 与接受时点 |
| `13f_holdings_external25` | 外部 25 家口径的选定持仓 | 不假定存在统一日期列，依原始 filing 关联 |
| `security_onboarding_external25` | 外部 25 家季度证券的数据接入待审队列 | `effective_date`；只是已有 CUSIP 映射及覆盖提示，不授予身份或策略资格 |
| `vix_cboe_daily` | 官方 Cboe VIX 日线与市场日历对照标记 | `DATE`；保留官方原值，XNYS 仅是跨市场对照，非 Cboe 日历权威 |
| `bls_release_calendar_legacy` | 原有 BLS 历史发布日历的保真 Parquet 副本 | `release_date`；只有发布时间安排，不是 CPI 等宏观数值 |
| `bls_release_calendar` | 成功获取后才注册的新 BLS 官方发布日历 | 此轮获取失败，不能视为已有 2026 覆盖 |
| `fred_release_calendar` | FRED 官方五类主要宏观发布安排 | `release_date`；计划时间不是实际发布或历史可用时点 |

`external25` 数据集保留自己的明确口径，不替换 `pit_13f_reconstruction_r1.py` 的原有 authoritative 机构配置。历史与增量事实也分别注册；合并消费时必须显式决定来源顺序、accession 去重和信息时点，不能只按最新文件拼表。

### 2026 年 SEC 统一查询

新开发代码可直接读 `sec_companyfacts_2026` 与 `sec_submissions_2026`，不必手工拼接基线、增量和例外三个输入。统一查询副本仍与 `sec_*_pre2026` 分开，保留原基线／增量／例外数据集供来源审计：

```python
facts = store.read("sec_companyfacts_2026", start_date="2026-09-01", end_date="2026-09-11",
                   date_column="filed_date",
                   columns=["cik", "accession", "taxonomy", "concept", "unit", "raw_value",
                            "start_date", "end_date", "frame", "accepted_at", "input_file_sha256"])
submissions = store.read("sec_submissions_2026", start_date="2026-09-01T04:00:00Z",
                         end_date="2026-09-12T03:59:59.999999Z", date_column="accepted_at")
```

维护入口使用明确的源 manifest 并前后校验 hash：

```powershell
& $pythonExe -B -m scripts.storage.materialize_sec_2026 --baseline-manifest D:/us-tech-quant-data/sec/recovery_20260913/sec_restore_manifest.json --incremental-manifest D:/us-tech-quant-data/sec/incremental_20260913/incremental_manifest.json --exception-manifest D:/us-tech-quant-data/sec/incremental_20260913/acceptance_exceptions_manifest.json --output-root D:/us-tech-quant-data/sec/unified_2026 --as-of 2026-09-11
```

该入口输出 `versions/<contract hash>/companyfacts.parquet`、`submissions.parquet` 与 `sec_2026_manifest.json`，由维护程序把其中两个 `catalog_records` 在同一事务内传给 `register_file`。工具自身不更新 catalog，不覆盖原始源。每行新增 `input_file_sha256`、`input_manifest_sha256`、`input_dataset_role`；原来的 ZIP／member、URL、fetch 时间、单位和事实列全部保留，不同来源没有的列保留 null。

此轮已生成并注册的统一版本位于 `data_root/sec/unified_2026/versions/50888a20f844ba77c39b9501/`，含 1,173,431 条事实与 140,433 条唯一提交记录。数量是记录行数，不是证券数量或完整企业覆盖承诺。

提交记录要求 `(cik, accession)` 唯一，已知 `accepted_at` 按纽约日历日期划入 2026 年窗口；此轮两条 `filed_date=2025-12-31`、但 2026 年正式接收的记录仍保留真实日期。上例提交查询的 UTC 边界对应纽约 9 月 1 日至 11 日；不同季节必须按当时夏令时转换，不能全年写死 UTC 偏移。接收时间未知的记录仅按 `filed_date` 进入待核对数据，时间继续保留 null；按 `accepted_at` 过滤不会返回这些未知记录，需要单独检查 `acceptance_status`。

事实保留原文件中的所有行，包括同一 accession 下不同概念、单位、frame、期间或原有重复事实；任何跨输入 accession 重叠都会明确停止，等待有依据的修订对账，不用 `drop_duplicates` 或任意最新优先级处理。事实的 `filed_date` 过滤只限制申报日期；消费者仍要按实际 `accepted_at` 和决策时点执行信息可用性规则。合并成功仅证明这些明确输入的可追踪联合，不保证所有企业和概念都已齐备。

### 交易日历更新

`scripts/storage/refresh_trading_calendar.py` 从已安装的 `exchange_calendars` 生成 XNYS 正常现金股票交易时段，不手写工作日／节假日规则。生成文件包含 `trade_date`、UTC 开收盘时间、纽约时区和提前收市标记；manifest 记录包版本、规则模块 hash、生成时间、所需日期范围及实际首尾交易日。库的来源是 [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars)，交易所参考是 [NYSE 交易时段与节假日](https://www.nyse.com/trade/hours-calendars)。

```powershell
& $pythonExe -B -m scripts.storage.refresh_trading_calendar --start 2016-01-01 --end 2026-09-11 --data-root D:/us-tech-quant-data
```

新版本位于 `data_root/reference/trading_calendar/XNYS/versions/`，保留 `moomoo/source/trading_calendar/us_trading_calendar.parquet` 的原始字节。生成器完全不写 catalog；在其他目录构建任务结束后，通过构建器的 `--calendar-manifest` 登记生成器返回的明确 manifest 路径：

```powershell
& $pythonExe -B -m scripts.storage.build_data_catalog --index-only --target-date 2026-09-11 --calendar-manifest D:/us-tech-quant-data/reference/trading_calendar/XNYS/versions/xnys_sessions_f61c8f8d47cd94ae4b75.manifest.json --report D:/us-tech-quant-results/data_management/calendar_index_report.json
```

构建器核对日历文件 hash，登记为当前 `trading_calendar`；原 provider 日历单独索引为 `trading_calendar_provider_legacy`，后续构建不会把它覆盖回生成日历的 current。已生成并登记的此版本从 2016-01-04 至 2026-09-11，共 2,688 个交易日、21 个提前收市日，来源版本为 `exchange_calendars 4.13.2`。规则日历不是 broker 行情数据，也不覆盖美股所有场所或盘前／盘后时段；未来临时休市或规则修订需要记录新版本。

通用读取可以先查看登记的日期列，再限制读取区间：

```python
metadata = store.metadata("sec_facts_pre2026")
date_column = metadata["lineage"]["date_column"]
facts = store.read(
    "sec_facts_pre2026", start_date="2025-01-01", end_date="2025-12-31",
    date_column=date_column,
)
```

对 Hive 分区 Parquet 目录传 `partitioning="hive"`。没有可用日期列的数据集不能使用日期过滤；先检查其 schema 与原有契约。SEC 事实按披露时间过滤仍不自动等于可用特征，消费者还需处理实际接受时间、修订关系、计量单位和信息可用时间。

### 分片行情快照

`prices_intraday_1m` 使用 `format=parquet_manifest`。catalog 所选文件是一个不可变 JSON 清单，记录各 Parquet 分片的绝对路径、SHA256、行数、时间范围与共同 schema；原分片不复制、不改写。`DataStore` 核对清单及分片后，用显式文件列表构造 Arrow dataset，再做时点谓词过滤：

```python
minute = store.read(
    "prices_intraday_1m", "QQQ", "raw",
    start_date="2026-08-07T13:30:00Z", end_date="2026-08-07T13:35:00Z",
    date_column="timestamp_utc", columns=["symbol", "timestamp_utc", "close", "session"],
)
```

清单读取不使用 Hive 推断，不能传 `partitioning="hive"`。`symbol` 是这类原始分片里的证券列。时间边界必须与存储同为有时区或无时区，纳秒边界保留精度；不得猜测无时区字符串是纽约时间还是 UTC。混合 schema 仅允许 string／large_string 与同一时区 timestamp 的单位提升；不同字段、时区、数值类型明确拒绝。保留原 `source=moomoo_opend`、`adjustment_type=NONE` 和全时段数据含义，不把盘前／盘后硬套成 XNYS 正常交易时段。

准备单一 ETF 的清单示例：

```powershell
& $pythonExe -B -m scripts.storage.build_parquet_manifest --input-root D:/us-tech-quant-data/fast3/moomoo_24h_1m/canonical/symbol=QQQ --output-root D:/us-tech-quant-cache/derived/data_catalog/manifests --dataset prices_intraday_1m --ticker QQQ --adjustment raw --date-column timestamp_utc --ticker-column symbol --source MOOMOO_OPEND --expected-value symbol=QQQ --expected-value code=US.QQQ --expected-value source=moomoo_opend --expected-value adjustment_type=NONE
```

该命令只准备清单。输出的 `catalog_record` 由维护程序在一个写事务内传给既有 `register_file(connection, **catalog_record)`；`format` 必须保留 `parquet_manifest`。新增数据可以通过 `--extra-fragment` 追加明确文件，并用 `--supporting-manifest` 固定采集及重叠核对证据。清单拒绝重复路径及时间范围重叠；先比较新旧重叠行情、生成仅新时间段的分片，再创建新清单版本，不通过简单 glob 拼接制造重复 bars。旧清单和旧分片继续保留。

读取会前后核对所选清单及分片 hash，因此比普通单文件查询多出完整性检查成本。验收器对此格式执行 footer、hash、schema、显式来源／证券与不重叠范围核对；它不逐行判断 OHLCV、不证明分片内部每一分钟或每交易日完整。六 ETF 旧清单的物理记录合计 14,226,752 行、588 片；截至 2026-08-08 00:00 UTC 的旧范围与后续新增范围，应按各清单版本及实际交付报告区分。

此轮新增分钟数据中，QQQ、TQQQ、SQQQ、SOXL、SOXS 的重叠 OHLC 一致，但成交量／成交额有供应商修订；保留旧历史及修订核对报告，只追加新时间段。SOXX 最初因一条 open 从 539.41 修订为 539.78 而阻断，新增来源先单列 `prices_intraday_1m_incremental`。随后第二次正式接口请求的同日 1,440 行与新增来源完全一致，确认该价格修订及成交量／成交额变化后，主 `prices_intraday_1m` 采用新来源替换 5,521 条重叠记录并追加 34,560 条新记录，保留旧分片前缀 1,680 条，形成 41,761 条的替换分片，覆盖至纽约 9 月 11 日。旧数据、旧清单及首次阻断证据继续保留；新清单固定二次核验依据，不把这一已核对的来源修订推广为自动接受其他冲突的规则。行级抓取时间仍使用各自真实下载时间，不能当作供应商发布修订的时间。

`scripts/storage/restore_sec_data.py` 负责从明确的 SEC 压缩包与 CIK 映射恢复数据，分开保存 historical 与 current 产物，并生成来源/hash/覆盖清单。恢复历史产物只有 hash 与原冻结记录相符，才能称为字节一致。新一轮源压缩包使用独立的恢复输出目录；该工具拒绝把不同恢复契约混入同一目录。不要直接运行包含训练流程的旧 SEC 研究脚本 `main()` 来完成数据维护。

## 13F 原始初报与修订的重新获取

2026-09-14 使用个人 Gmail 作为 SEC 请求联系标识，重新核对现有 external25 的 25 家机构最新 submissions，并获取 2026Q2 的 25 份初报及 1 份修订。公开下载不需要 Gmail 登录，本次没有修改持久邮箱配置。报告期仍为 2026-06-30，抓取日不等于持仓日。

`13f_filings_external25` 更新为新核对的 25 条初报元数据；新增 `13f_raw_filings_external25`（26 条）与 `13f_raw_holdings_external25`（49,631 条，初报 33,509＋修订 16,122）。通过 `store.read(dataset, date_column="filed_date", start_date=..., end_date=...)` 读取。原始表保留 accession、form、接受时间、实际抓取时间、来源 hash、修订类型／序号、原信息表 XML 及质量状态。

Citadel `0001104659-26-104387` 是序号 1 的 `RESTATEMENT`；其 16,122 条与初报为不同版本，不能跨版本直接加总，也未合并进旧的初报选股产物。25 份初报哈希及全部 33,509 条关键字段与旧数据一致。旧股票池、选定持仓、身份映射及独立的 24 家权威机构契约保留。

Duquesne 与 Himalaya 初报存在源内金额汇总差异，明细减封面分别为 −4 与 +1 个申报单位。共 103 条明细保留所属申报的 `SOURCE_VALUE_TOTAL_MISMATCH`，不补值、不猜测单位修正。这些 raw 数据的登记不代表已通过所有研究质量门槛。SEC 接受时间也不自动证明某历史交易决策时刻已完成公开传播。

原始资料在 `cache_root/13f_intake/13f_personal_contact_20260914/`，标准化表在 `data_root/13f/13f_personal_contact_20260914/`，来源、核验、发布回执在 `results_root/13f_intake/13f_personal_contact_20260914/`。旧版本和首次异常停止证据保留。完整说明见 [本次报告](D:/us-tech-quant-results/13f_intake/13f_personal_contact_20260914/final_report.md)。

## 追加股票与更新流程

新增股票通过数据订阅登记，不需要修改 Python 股票列表，也不会自动加入策略池。以下 AAPL 是命令格式示例；按实际要添加的股票填写明确的 provider code 和历史区间。

新季度 13F 可先生成数据接入待审队列，复用已有精确 CUSIP 映射：

```powershell
& $pythonExe -B -m scripts.storage.prepare_security_onboarding --quarter-root D:/us-tech-quant-data/13f/recovery_20260913 --identity-path D:/us-tech-quant-results/13f_pit_v1/data/universe/security_identity_v17c_transport.parquet --historical-universe D:/us-tech-quant-results/13f_pit_v1/data/universe/13f_dynamic_universe.parquet
```

输出 `security_onboarding.parquet` 并注册 `security_onboarding_external25`，旧派生版本按 hash 保留。此轮队列有 639 条证券记录，其中 53 个 CUSIP 未出现在所给历史集合；57 条待身份核对，另 2 条存在同一 provider code 对应同时期多 CUSIP 的冲突。已有映射也保留生命周期复核要求，不自动通过身份审查；该队列不写订阅、不下载、不改变策略股票池。核对运输代码与身份依据后，再用下列 `add-stock` 显式登记。

```powershell
& $pythonExe -B -m scripts.storage.manage_data add-stock --provider-code US.AAPL --ticker AAPL --start 2019-01-01 --target 2026-09-11 --identity-source unknown
```

`provider-code`、`ticker`、`start`、`target`、`identity-source` 都必须显式给出。未知身份写入 `PENDING_IDENTITY`；给出来源后也仅为 `REQUESTED_IDENTITY_REVIEW`，不自动授予 PIT 身份。重复登记同一 provider code 可更新所需区间，但不能静默改绑到另一 ticker。

生成补数计划：

```powershell
& $pythonExe -B -m scripts.storage.manage_data plan --tickers AAPL --start 2019-01-01 --target 2026-09-11 --output D:/us-tech-quant-results/data_management/fetch_plan.csv
```

不指定 `--tickers` 时，计划覆盖当前目录内股票与订阅股票的并集。`--start`／`--target` 是本次计划的明确区间。计划检查 raw／QFQ 文件缺失以及日期范围前后的缺口，标记 `MISSING_FILE`、`MISSING_DATA`、`PREFIX_GAP`、`TAIL_GAP`。它不会依据最早／最晚日期推断内部交易日已经齐全。

纯字母数字 ticker 使用既有下载器的 `US.<ticker>` 运输规则。含点、横杠或斜杠的 ticker 必须有明确订阅映射；缺映射或同 ticker 对应多个 provider code 时，计划标记 `BLOCKED_*`。该运输规则不构成证券历史身份验证。

计划没有待补行时跳过下载。有待补行时，先确认所有待下载行均有明确 provider code，再调用 Moomoo 下载入口：

```powershell
& $pythonExe -B -m scripts.storage.refresh_market_data --repo-root D:/us-tech-quant --work-root D:/us-tech-quant-cache/data_management/market_acquisition --universe-csv D:/us-tech-quant-results/data_management/fetch_plan.csv --start 2019-01-01 --end 2026-09-11 --adjustments raw qfq

& $pythonExe -B -m scripts.storage.refresh_market_data --repo-root D:/us-tech-quant --work-root D:/us-tech-quant-cache/data_management/market_acquisition --universe-csv D:/us-tech-quant-results/data_management/fetch_plan.csv --start 2019-01-01 --end 2026-09-11 --adjustments raw qfq --execute
```

第一条生成 dry-run；第二条才请求历史行情。下载器复用既有 Moomoo fetcher、配额检查与重试逻辑，不打开交易上下文。它使用命令行全局 `--start`／`--end`，不会逐行执行计划 CSV 的不同日期区间。需要精细增量时按相同日期区间拆分计划。QFQ 更新必须带足够重叠历史用于一致性核对；首次追加股票需覆盖完整的所需历史。

随后将下载产物纳入统一索引：

```powershell
& $pythonExe -B -m scripts.storage.build_data_catalog --target-date 2026-09-11 --extra-market-root D:/us-tech-quant-cache/data_management/market_acquisition --report D:/us-tech-quant-results/data_management/catalog_build_report.json
& $pythonExe -B -m scripts.storage.manage_data status
```

`--extra-market-root` 指向下载器的 work root，构建器通过 `intervals/*.json` 的路径与 hash 验证下载结果，不按任意 CSV 文件名推断来源。将该采集目录作为长期可发现的维护输入；后续构建也应传入它。构建器先验证并采用 catalog 当前文件作为基底，不会因为旧原始目录未被再次发现而退回较短历史。无新增数据时保留行级 `source_id` 和原文件版本；当前文件缺失、hash 改变，或更早 cutoff 会截断既有历史时明确停止。

日常快速追加可在同一构建命令上加 `--updates-only`，只读取已验证 current 与显式新行情 interval，省去再次扫描所有旧来源；它保留既有历史与来源记录，不是清空后仅用增量重建。首次恢复仍使用完整发现流程。

历史来源记录仍保留原路径和 hash，记录存在不等于源文件仍可访问；保留归档义务仍适用。构建前后比较每股票的覆盖区间、来源和异常，不仅比较文件数量。

SEC 恢复输出通过构建器的 `--sec-root` 纳入索引，分别读取其 `historical/` 与 `current/` 子目录。`--incremental-sec-root` 注册后续增量事实／提交记录；`--quarter-root` 注册外部 25 家口径的季度扩展文件。指定 `--source-data-root`、`--source-cache-root`、`--source-results-root` 可以从原有根读取，在其他明确的输出根恢复。构建器保留旧文件与旧快照指针；现有依赖合并 CSV 的消费端仍需显式兼容导出／迁移，不能把 catalog 就绪当作全系统切换完成。

### Yahoo 补充采集与追加股票

`refresh_free_market.py` 是独立的 Yahoo chart 采集入口，使用现有 `requests`，不要求安装额外 SDK。通过 `--tickers` 显式追加所需股票，无需改代码中的名单；省略时取 catalog 当前全部已支持日线来源与明确订阅股票的并集，不写订阅表或策略池。默认使用 ticker 本身作为 Yahoo 运输代码，要求返回的 symbol 完全相等。异名或特殊股类可通过 `--symbol-map` 给出 JSON 对象：每个项目 ticker 对应一个对象，严格包含 `provider_symbol` 和 `evidence_url` 两个字段；前者是已核对的 Yahoo 代码，后者是支持映射的明确 HTTPS 证据页面。映射文件需事先核对，不自动把点、横杠或斜杠互换，也不因为提供 URL 就授予历史身份资格。

```powershell
& $pythonExe -B -m scripts.storage.refresh_free_market --tickers AAPL MSFT --start 2018-01-01 --end 2026-09-11 --work-root D:/us-tech-quant-cache/data_acquisition/yahoo_supplement --workers 2
& $pythonExe -B -m scripts.storage.refresh_free_market --tickers AAPL MSFT --start 2018-01-01 --end 2026-09-11 --work-root D:/us-tech-quant-cache/data_acquisition/yahoo_supplement --workers 2 --execute
```

需要显式别名时，在同一命令上增加 `--symbol-map`，指向已经核对的映射 JSON。项目 ticker 继续用于 catalog 键，真实返回的 provider symbol 与映射证据保留在采集契约及 lineage 中。

第一条仅显示计划，第二条才请求数据；结束日期必须已完成。缓存目录必须位于配置的 cache root 内，保存原始响应与逐股票 checkpoint，数据根保存按输出内容 hash 命名的版本文件。同一明确请求契约可复用已校验的成功结果；`--retry-transient-failures` 只重试已缓存的网络／HTTP 5xx 故障并保留旧尝试记录。访问拒绝或限流会停止继续请求，不更换身份绕过。无效原始 OHLCV 行进入 `rejected_rows`，不插值或伪造交易日。

采集完成产生 `acquisition_report.json`。维护程序先核对原始响应及规范化文件的 hash，只将 `SUCCESS` 且通过来源质量复核的项目，通过其中的 `catalog_record` 和已有 `actions_catalog_record` 调用 `register_file` 登记，并保留 `source_files` 原始响应记录；这些记录使用独立 dataset，不改变 Moomoo 的 current。仅有少量有效 OHLCV、其余大量原始行无效的异常稀疏结果，先隔离待核对，不能把采集 `SUCCESS` 直接等同于可靠行情。采集 CLI 自身不写 catalog，也不接受 `build_data_catalog --extra-market-root` 的 Moomoo interval 格式。完成登记后运行 `validate_data_catalog`，检查 Yahoo 的独立覆盖、缺口、来源与实际最大日期后再供开发使用。公司行动必须按自身请求窗口解释，不能将不同窗口的 current 当作完整历史并集。

### Massive 免费日线采集

`refresh_massive_market.run_acquisition(api_key=..., start_date=..., end_date=..., work_root=...)` 接收调用方从安全凭据来源取得的内存密钥，按现有目录与订阅并集、已登记的交易日历请求 [Massive Daily Market Summary](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary)。免费 Basic 的历史范围为最近两年；本实现只请求已结束的纽约日期，固定 `adjusted=false`、`include_otc=false`，至少间隔 12.5 秒，认证或限流错误明确停止。密钥通过官方域名的 Authorization 头发送，不放入 URL、报告或命令行。没有密钥时不要使用虚构值或重置现有凭据。

每个交易日保存完整原始响应、SHA256 和真实抓取时间，再筛选明确的股票代码。没有返回某股票就记录缺口，不生成零值行情。按请求的交易所日期登记 `date`，另保留原始 `source_timestamp_ms`、`vwap` 与成交笔数 `transactions`。OHLC 标记 `raw`；供应商未报告的 `turnover` 保留 null，不用 VWAP 乘成交量推算。原始未复权价格不能直接与 Yahoo 拆股调整价格的跨拆股历史比较。

输出 `acquisition_summary.json` 指向不可变 `acquisition_manifest.json`，内含候选 `catalog_records`、逐股票缺失交易日和拒绝记录。按原始输入与输出 hash 核验后，在统一索引事务中登记 `prices_daily_massive` 和原始 `source_files`，不改变 Moomoo 或 Yahoo 的选择。同一契约的逐日 checkpoint 可校验后复用；多个进程不能共用同一采集目录写入。后续采集不得把短窗口无条件替代已有长历史，需先证明日期保留及重叠数据相容，或明确保留为独立候选。

较长的 Massive 批次可用 `compact_acquisition_manifest(acquisition_manifest=..., output_root=...)` 离线整理重复来源元数据，沿用原 Parquet 的路径与字节。catalog schema 仍为 1，旧 `lineage.inputs` 继续兼容；共享模式改用互斥的 `lineage.inputs_manifest={"path": ..., "sha256": ..., "indexes": [...]}`。共享 JSON 严格包含 `schema_version: 1`、`role: "RAW_INPUT_MANIFEST"`、`provider: "MASSIVE_GROUPED"` 和按日期排序的叶子 `inputs`；每项只有原始 `path`、`sha256`、`date`、带明确时区的 `observed_at`。省略 `indexes` 表示全部来源，提供时表示非空、升序且不重复的精确子集，不能把其他股票有记录的日期误算为该股票有行情。清单不递归引用其他清单，不接受越界路径或重复日期、路径、SHA。

日常 `metadata()` 检查共享清单的 SHA、结构与叶子路径边界；`daily()` 另外在读取前后检查所选 Parquet 的 SHA，仍把日期和列过滤交给 Arrow。两者不逐份 hash 可能很大的全市场原始响应。需要深检时可调用 `store.resolve_price_inputs(metadata, verify_raw=True)` 检查所选叶子，或运行完整 `validate_data_catalog`：它核对所选原始文件和 `source_files`，每份 raw 在同一轮验收中只 hash 一次，并检查价格 `source_id` 集合、交易日、真实抓取时间与清单的精确对应关系。此性能边界不代表日常查询已经完成原始响应全量验收；共享清单也不改变当前抓取 vintage 的非历史 PIT 语义。

`DataStore` 实例建立时固定允许访问的数据根的规范路径；实际文件路径每次访问仍重新解析并检查边界，避免同一规范路径被重复解析。若有意更换数据根配置，应重新建立实例。此优化不跨请求缓存原始响应或共享清单，也不省略读取前后的 SHA 检查。

需要重做已取得的明确运输映射时，`normalize_cached(acquisition_manifest=..., checkpoint_root=..., symbol_map=..., output_root=...)` 是完全离线入口：它没有密钥或 HTTP 参数，先核对完整原 manifest、逐日 checkpoint 与全部原始响应，再生成独立版本。它拒绝把已经属于另一 catalog ticker 的供应商代码复制成第二份行情。比如 SQ 已于 2025-01-21 更名为 XYZ，原目录也已含 XYZ；此轮将 SQ→XYZ 登记在 `market_symbol_aliases`，不复制 Yahoo 已按 XYZ 返回的相同补充历史。Massive 在更名前按 SQ 实际返回的历史行情仍属于独立、有真实日期的原始记录，须保留；旧 Moomoo 历史运输代码也不因此被自动改写。

`store.read("market_symbol_aliases")` 返回可查询的显式别名和股类运输格式。消费者先按 `provider` 与 `alias_ticker` 查找 `canonical_ticker`，再明确调用 `daily()`；reader 不静默重写代码。表中生效日期、发行人依据和当前运输语义必须保留，不能把它当成跨所有历史时点的证券身份主表。

**历史代码不能自动当作恒定证券身份。** `daily()` 提供供应商运输代码的原始历史；相同代码可能跨越不同发行人或已注销／重发的权益。此次官方核查已确认：MNTN 的现发行人于 2025-05-22 首次交易，此前同代码属于 Everest Consolidator；FIG 的现发行人 Figma 于 2025-07-31 首次交易，此前同代码属于 Simplify Macro Strategy ETF。研究现发行人时必须同时限制身份和日期，不能使用这些起点之前的同代码数据。VRM 的旧权益于 2025-01-14 注销，2025-02-20 为重组后新股复牌，不能把旧股、OTC 的 VRMMQ 与新股拼成同一连续证券价格。

JBS 的 2025-06-11／12 在其实际 NYSE 首交易日 6 月 13 日之前；SHAZ 的 13 个潜在缺日和 BMNR 的 2025-04-24 处于各自 Nasdaq／NYSE American 挂牌前的 OTC 阶段，不能仅按 XNYS 日历判为交易所漏采。SHAZ／BMNR 的逐日 OTC 无 bar 原因仍未确认，SHEL 2021-05-05 也仍缺可靠来源。完整日期、官方依据与身份边界见 [历史缺日核查](D:/us-tech-quant-results/data_layer/20260913/history_gap_lifecycle_review.json)。覆盖报告中的 `identity_key` 只是按已确认 SQ→XYZ 改名去重后的统计键，不认证其他代码的历史身份连续性；已观察区间日历覆盖完整也不代表证券全历史数据完整。原始行情保留作证据，未把旧 ETF、SPAC、注销权益或 ADR 的价格复制为当前公司行情。

追加尚未包含在原批次股票名单中的代码，可使用完全离线的 `normalize_cached_tickers(acquisition_manifest, checkpoint_root, tickers, symbol_map=None, *, output_root)`。它复用已保存的全市场逐日响应，验证原清单、checkpoint、原始 SHA 后生成独立候选；不写订阅、catalog 或策略股票池。`tickers` 必须显式非空；真实运输符号与项目 ticker 不同时须给出映射依据，也不能复制已经归属于另一原 ticker 的 provider symbol。新入口的 `scope_source.mode` 为 `EXPLICIT_SYMBOLS`；缺少真实行情时继续报告空缺。

这个入口允许映射带 `effective_from`／`effective_to`，只提取已明确范围内的运输代码；仍保存完整请求交易日与原始输入清单。比如 FI 在 2025-11-11 改回 FISV，同一普通股 CUSIP 的变更由 Nasdaq 公告和发行人年报确认：

```python
from scripts.storage.refresh_massive_market import normalize_cached_tickers

candidate = normalize_cached_tickers(
    acquisition_manifest=completed_manifest_path,
    checkpoint_root=completed_checkpoint_root,
    tickers=["FI"],
    symbol_map={"FI": {"provider_symbol": "FI", "effective_to": "2025-11-10",
                       "evidence_url": "https://www.nasdaqtrader.com/TraderNews.aspx?id=DTN2025-32"}},
    output_root="D:/us-tech-quant-data/providers/massive/cached_symbols",
)
```

完成核验与登记后，可用 `store.daily("FI", "raw", provider="massive", end_date="2025-11-10")` 读取旧运输段，使用 FISV 读取此次转板后的段。FI 是已确认改名的历史段，不能算作新增证券；后续计划应读取 `lineage.provider_mapping` 的有效期及别名参考。默认采集并集会发现这类已登记历史代码，调用方应明确区间或股票范围；结束后的无行情日期不补零。两个文件保持独立，读取不会自动拼接或重标历史代码。

价格与来源按不可变版本保存。相同输出路径已有不同清单字节时，采集器明确停止并保留旧文件，不静默覆盖；相同内容可幂等复用。代码升级后重新规范化旧批次若触发此保护，应保留原清单并明确准备新的版本，不能删除旧证据来规避冲突。

### 查询数据质量记录

`market_data_quality_events` 是共享质量文件，catalog 键的 ticker 为空；先限制日期读取，再按行内 ticker 筛选：

```python
quality = store.read("market_data_quality_events", start_date="2026-09-01", end_date="2026-09-11")
nfe_quality = quality.loc[quality["ticker"].eq("NFE")]
```

零成交量、内部疑似缺日和运输代码检查是质量线索，不能单独证明停牌、退市或错误。此轮按发行人／SEC 公告隔离 EA、NUVL、OLPX、TALK 的异常稀疏 Yahoo 快照；按 Nasdaq 正式停牌公告，从 NFE 的可读 Yahoo 日线排除 2026-09-11 零成交量记录，保留原始响应、原行及排除依据。HLXC 等缺乏可靠停牌证据的零成交量记录保留并标记。生命周期事件必须按实际生效时间判断，不能要求已停止交易的证券补出最新日行情。

`market_provider_comparison_events` 采用相同的共享文件读取方式，保存多来源 OHLC／成交量超过明确阈值的差异，以及 Massive 无 bar 而 Yahoo 返回零成交量平价记录的对照。每行包括双方原值、阈值、日期与来源 SHA；这类标记不会自动决定哪个来源正确。Massive 与其他源的成交量、可计入成交规则或后续修订可能不同，跨源比较须先核对拆股与日期口径。

`market_legacy_lifecycle_events` 保存 SEC、交易所与发行人对旧代码的可核查证据，区分普通股、SPAC 单位、到期股权单位与临时交易代码。已完成的证券终止与仅公告的未来计划使用不同状态；不能把合并已完成自动推定为单位代码最后实际成交日。后续缺口计算应引用明确状态与生效日期，保留仍未确认的情况，也不能用继承公司的普通股直接补进原证券历史。

### 官方 VIX 与宏观发布日历

`scripts/storage/refresh_public_sources.py` 复用已有官方源下载及解析器，`--execute` 才实际采集，并输出本次 `acquisition_report.json`。构建器的 `--public-sources-report` 接受该明确报告路径；逐项只登记 `SUCCESS` 的 `vix_cboe_daily` 或 `bls_release_calendar`，先核对规范化输出与官方原始文件 hash，保留 URL、抓取时间和 vintage 语义。失败来源留在报告中，不注册成伪造的完整数据。

此轮 VIX 当前选择含日历对照标记的副本，9,271 行截至 2026-09-11；官方日期和价格原值均保留，已知非 XNYS 日期及官方 open 超出 high／low 的情况保留为标记，不按股票日线规则删改。历史 BLS 文件转为 `bls_release_calendar_legacy` 后保留 183 条原记录；本次新 BLS 获取失败，2026 发布日历仍是明确缺口。原有 VIX 派生特征不随原始源更新自动重算，也不因此取得新 PIT 资格。

免费替代来源 `fred_release_calendar` 保存圣路易斯联储官方 FRED 页面中五类主要发布日历（Employment Situation、CPI、JOLTS、Employment Cost Index、PPI）。本轮原始 2025 年页面列出 47 条安排，2026 年全年页面列出 53 条；规范化到 2026-09-11 后，两年合计 87 条（2025 年 47 条、2026 年 40 条）。只保留官方实际列出的日期，不按每月十二次猜填。它补充主要发布安排，不能冒充完整 BLS 官方日历。`store.read("fred_release_calendar", start_date="2026-09-01", end_date="2026-09-11", date_column="release_date")` 按 `release_date` 查询。

FRED 页面明确使用 US Central，离线 `refresh_public_sources.normalize_fred_calendar(download_manifest, output_root, target_date, repo=...)` 复用现有 FAST6 解析器并指定 `America/Chicago`，分别保留中部／纽约计划时间和 UTC；夏令时按日期转换。解析严格核对页面标题、canonical release ID／年份、广告行数、时区与重复事件，保留原始 HTML hash 和实际抓取时间。页面 Updated 标记、计划发布日期都不等于实际发布时间或历史数据可用时点。

该入口也支持明确的跨年份下载清单。多个年份或显式 `source_years` 模式要求每年五个 release ID 都齐全；URL 年份必须是唯一的合法整数且不超过目标年，并与 HTML 年份一致。同年重复 release ID、缺页或年份混搭会停止规范化。原单年调用保持兼容，跨年版本另外记录 `source_years` 与每年来源，保留已有年度候选和原始页面。

## 旧 CSV 消费端的候选导出

`scripts/storage/publish_data_snapshot.py` 提供既有列结构的 raw／QFQ 合并 CSV、来源清单与候选指针。**默认只准备候选，不读取或修改旧 current JSON／CSV 指针**：

```powershell
& $pythonExe -B -m scripts.storage.publish_data_snapshot --target-date 2026-09-11 --report-root D:/us-tech-quant-results/data_management/legacy_export
```

CSV 写入 `data_root/canonical/moomoo_ohlcv/snapshot_id=.../`，内容与来源 hash 确定快照身份；报告目录包含 `candidate_canonical_pointer.json` 和 `publication_report.json`。默认报告的 `mode` 为 `PREPARED_ONLY`、`pointer_changed` 为 `false`。准备成功表示这些候选文件可供开发核查，不表示原有失效指针已修复。

导出只接受规范化入口已验证的 `MOOMOO_OPEND` 与 `MOOMOO` 来源标签，并保留各行原标签；manifest 另列 `source_labels`。其中 `MOOMOO` 可来自明确的 `provider=MOOMOO` 与 `price_type=RAW_DAILY/QFQ_DAILY` 输入，不被静默改写成 `MOOMOO_OPEND`。未知或其他来源仍拒绝导出。

默认候选采用 catalog 中同时具有 raw／QFQ 的 provider symbols，分别计算截止日期之后实际导出的股票集合与目标日覆盖。该集合不是策略股票池。某些旧消费端会直接把 CSV 中全部股票送入横截面排名，因此不能将全 catalog 候选直接当作原策略输入。

显式 `--publish-pointer` 仅接受旧 current 同目录已有的 `abcde_expected_universe.csv`，并要求 current 声明的 expected count 与名单一致、名单股票双腿齐备且目标日覆盖完整。缺少这一单一旧范围契约时拒绝发布；不会用 catalog 交集、临时新名单或排除缺失股票来制造完整覆盖。该路径只复用既有范围，不恢复或选择新研究股票池。

发布时按已捕获的绝对数据路径读出并前后核对 hash，避免读取中重新选择 current；旧 JSON／CSV 指针均保存精确字节备份。切换前检查旧指针与范围名单是否变化，切换后读取校验；失败仅回滚本次仍拥有的字节，不覆盖已观察到的其他写入。这个比较检查与原子文件替换不是整个旧日常链的全局写锁，显式切换应避免与其他指针生产者同时运行。

兼容指针保留 `canonical_as_of_date`，完整时填写 `canonical_complete_universe_date`，manifest 同步填写 `latest_date`。`model_safe_count` 保持未知，不推断研究可用性。本次若只交付候选，旧 current 仍按交付报告作为明确的 legacy 阻断保留；新开发通过 `DataStore` 访问已恢复文件。

## 数据含义与验收

- raw 与 QFQ 是两个独立 adjustment。不得用未标记的单列价格替代它们，或将两者混合拼接。
- QFQ 可因公司行动或供应商修订变化。重叠价格冲突时不拼接两个 vintage；只有新来源覆盖既有全部日期并延长历史时，才整段替换所选来源。无重叠片段先保留待核对，出现兼容桥接后有限重试。
- 合并保留每行 `source_id`，最终 `lineage.inputs` 只列实际采用的来源路径与 SHA256。`issues` 可能包含已解决的合并事件；结合 `unbridged_interval_count` 和实际覆盖判断当前缺口。
- `vintage_id` 标识所选文件版本，`source_sha256` 在 catalog 行中是该文件的内容 hash。它们不自动证明某历史决策日已能看到该 vintage。`observed_at` 缺失就保留未知，不能用重建时间补成历史观察时间。
- catalog 的 `is_current=1` 只表示构建器当前选择的文件，不代表该股票全历史完整、全股票池完整、身份已核实、基本面已齐备、研究已接受或策略已采用。
- min／max 日期和 row_count 只是覆盖摘要。完整验收还应核对交易日内部缺口、上市退市区间、raw／QFQ 双腿、13F 机构与 accession 完整性、SEC 身份映射及实际披露可用时间。
- 日期筛选不等于 PIT 授权。沿用项目原有训练截止、标签成熟、冻结、已暴露持出区间与前瞻评估边界；数据维护不运行模型或改变这些规则。

相关测试位于 `tests/storage/test_data_store.py`、`test_manage_data.py`、`test_catalog_integration.py`、`test_publish_data_snapshot.py`、`test_refresh_trading_calendar.py`、`test_prepare_security_onboarding.py`、`test_parquet_manifest.py`、`test_materialize_sec_2026.py` 及构建器自己的单元测试。它们使用合成数据验证接口、过滤、来源选择与追加流程；通过测试不替代对实际数据覆盖和来源的验收。


## FINRA 与美国财政部历史研究资料

新增入口 `scripts/storage/refresh_official_research_data.py` 复用现有 storage resolver、FAST6 原始文件获取器、`register_file` 和 `DataStore`；它只承担两个明确官方来源的格式校验与接入，没有新的 catalog 或证券身份映射。

| dataset | 范围与含义 |
| --- | --- |
| `finra_cnms_short_volume_pre2026` | FINRA Consolidated NMS 场外公开报告成交量；保留 `provider_symbol`、`short_volume`、`short_exempt_volume`、`total_volume`、`reporting_facilities` 与 `short_volume_share` |
| `treasury_nominal_par_yields_pre2026` | 财政部名义 par yield，长表 `date/provider_field/tenor_months/yield_percent` |
| `treasury_real_par_yields_pre2026` | 财政部实际 par yield，单位同上，允许负实际收益率和官方 null |

FINRA 的 ShortVolume **已经包含** ShortExemptVolume，不能重复相加；其占比的分母是同份 CNMS 文件的 TotalVolume，不是全市场成交量。该数据不是 short interest、借券余额或净做空资金流，也不与单独 TRF 文件重复汇总。原供应商 symbol 不授予历史证券身份或原股票池资格。历史模式仅接受 2026 年以前的整数股数格式。显式指定 `--as-of` 后使用独立的 `*_current` 数据集，FINRA 三个成交量列以 `decimal128(24,6)` 保留 2026-02-23 起的六位小数股数；原 `*_pre2026` 数据集和原始文件不变。

所有行保留原始来源 hash、实际 `observed_at_utc`、`vintage_semantics=CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT`，历史 `available_at_utc` 保持 null。FINRA 通常在成交当日美东 18:00 前发布，但可能随后修订；财政部的报价采集时间约美东 15:30，与实际网站发布时间不同。Treasury XML 的 updated 字段保留为 `feed_updated_at_utc`，不得回填为历史发布日期。免费官方历史快照可供明确标注的条件研究，不自动成为未经修订的历史 PIT 认证。

名义收益率减实际收益率可作为通胀补偿相关研究量，但不是纯通胀预期；必须保留期限、日期和曲线类型，也不能把收益率的百分数单位误作小数。

```powershell
# 不加 --execute 只显示请求计划。显式登记仅涉及这三个新增 dataset。
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_official_research_data --run-id official_free_20260914_pre2026 --finra-start 2023-01-01 --finra-end 2025-12-31 --first-year 2020 --last-year 2025 --execute --register
```

原始文件：`cache_root/official_research_intake/<run-id>/raw`；标准化版本：`data_root/reference/official_research/versions/<contract hash>`；请求清单、manifest 与报告：`results_root/official_research_intake/<run-id>`。重试复用同一 run-id 已校验的原始字节；要观察供应商新修订，使用新的显式 run-id 保留独立 vintage。任何下载/解析失败都不发布不完整的数据；已有更广日期覆盖不能被较窄范围覆盖。各研究规格仍需做证券身份、时点、全样本支持和披露延迟验证。

```python
from scripts.storage.storage_r2a import DataStore
store = DataStore()
short = store.read("finra_cnms_short_volume_pre2026", start_date="2025-12-01", end_date="2025-12-31")
aapl_provider_rows = short.loc[short.provider_symbol.eq("AAPL")]  # 仅原供应商代码查询
nominal = store.read("treasury_nominal_par_yields_pre2026", start_date="2025-01-01", end_date="2025-12-31")
real = store.read("treasury_real_par_yields_pre2026", start_date="2025-01-01", end_date="2025-12-31")
# 研究冻结应绑定 metadata 中的版本路径/hash 和 manifest；current 只是当前目录选择。
```

当前快照例子（必须同时给出请求终点与 `--as-of`；后者是上界，不会自动延长默认请求范围）：

```powershell
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_official_research_data --run-id official_free_20260914_current --finra-start 2023-01-01 --finra-end 2026-09-11 --first-year 2020 --last-year 2026 --as-of 2026-09-14 --reuse-manifest D:/us-tech-quant-results/official_research_intake/official_free_20260914_pre2026/manifest.json --execute --register
```

当前数据集分别为 `finra_cnms_short_volume_current`、`treasury_nominal_par_yields_current`、`treasury_real_par_yields_current`，同样由 `DataStore.read` 读取。下一次补数据使用新的明确 run-id，并核实官方实际已发布的最新日期。当前年度的财政部年度文件会重新获取；历史 raw 可以按旧 manifest 的 URL/hash 复用而不复制。重复使用同一 run-id 是恢复同一次获取，并不刷新供应商修订。2026+ 数据获取和完整性检查不授予训练、调参或回测授权。

来源：[FINRA 下载与时点说明](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files)、[FINRA 数据解释](https://www.finra.org/rules-guidance/notices/information-notice-051019)、[Treasury 官方 XML 接口](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)。

## BLS、纽约联储与美联储 H.10 官方数据

2026-09-14 在完成 FINRA／Treasury 当前快照后，新增以下三个 dataset，并通过既有 `register_file` 登记到同一 catalog。它们直接获取官方免费数据，本次未使用 API key 或付费服务。接口生成快照与 catalog 登记是两个动作；`current` 只表示当前选择的文件。

| dataset | 本次范围 | 官方最新可得观测 |
| --- | --- | --- |
| `bls_economic_observations_current` | 40 个月度序列，7,996 行；2010-01 起，包括 CPI、PPI、就业、工时、工资、失业及 JOLTS | 36 个序列到 2026-08，4 个 JOLTS 序列到 2026-07；逐序列核对 API 的 latest 标记 |
| `nyfed_reference_rates_current` | EFFR、OBFR、TGCR、BGCR、SOFR、SOFRAI 六类；90,816 个长表指标行，各类型起点不同，最早 2010-01-04 | 五类隔夜利率有效日到 2026-09-10；SOFRAI 到 2026-09-11，与官方 latest 全记录核对 |
| `frb_h10_daily_current` | 23 个货币汇率与 3 个美元指数，45,318 行；2020-01-01 起 | 2026-09-08 官方周报中观测到 2026-09-04；采集时 9 月 14 日周报尚未发布 |

`as_of` 是获取与过滤上界，不能把月度参考期、利率有效日或上周汇率改写为该日期。BLS 的 `date` 为参考期第一天，并保留参考期末；纽约联储 `date` 为有效日。所有来源保留原始响应、来源 URL/hash、实际抓取时间和当前修订版本语义，历史 `available_at_utc` 未经证实时保持 null。既有 2026+ 观察、训练截止与持出区间约束继续生效。

```powershell
# 在 D:/us-tech-quant 内执行；下一次刷新必须换成新的显式 run-id。
# BLS / NYFed 不加 --execute 只准备计划。
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_bls_observations --run-id official_expansion_20260914 --as-of 2026-09-14 --start-year 2010 --execute
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_nyfed_reference_rates --run-id official_expansion_20260914 --as-of 2026-09-14 --execute
# H.10 入口直接采集，不使用 --execute 参数。
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_frb_h10 --run-id official_expansion_20260914 --as-of 2026-09-14 --start-date 2020-01-01
```

上述命令准备和验证版本；NYFed 另支持显式 `--register`，BLS 与 H.10 的本次登记在独立完整性核验后复用既有 `register_file` 完成，命令本身不会自动登记。不要把快照生成成功当作目录已更新。每次实际发布都应核对 manifest、raw／Parquet hash、逐序列最新日期与旧 catalog 保留情况。重复 run-id 恢复已有采集，并不观察新的供应商修订。

原始响应放在 `cache_root/official_research_intake/<run-id>/raw/`，Parquet 版本放在 `data_root/reference/official_research/` 下，manifest、请求清单、核验与发布回执放在 `results_root/official_research_intake/<run-id>/`。本次统一验收入口为 `D:/us-tech-quant-results/official_research_intake/official_expansion_20260914/verification_receipt.json`。

```python
from scripts.storage.storage_r2a import DataStore
store = DataStore()
macro = store.read("bls_economic_observations_current", start_date="2026-01-01", end_date="2026-08-31")
funding = store.read("nyfed_reference_rates_current", start_date="2026-09-01", end_date="2026-09-11")
fx = store.read("frb_h10_daily_current", start_date="2026-09-01", end_date="2026-09-04")
```

BLS 保留原值字符串、单位、季调、footnotes、source_latest 与参考期。2025-10 官方缺失的 16 行保留缺失及拨款中断说明，不补零。此次 BLS 生成器源码 hash 与发布核验器 hash 不同：生成后修复 JSON 重读时序列排序导致的请求 hash 核验问题，数据和原 manifest 未改写；catalog lineage 分别保存 `generation_adapter_sha256` 与 `publication_verifier_sha256`。

NYFed 的百分数利率、美元十亿元成交量与指数分列标明单位，保留修订、脚注与 EFFR 2016 年前的方法变化；24 个官方 `NA` 指标保留 null 及原值 JSON。H.10 保留 1,898 个官方 `ND`，汇率方向按序列标记；3 个美元指数的 XML 基期标签与当前发布页冲突，保留原标签、官方当前解释及冲突标记。委内瑞拉货币代码／币制变化也保留待核对标记，不自动拼成可直接计算收益的同币种序列。

这些序列提供宏观、融资和汇率维度，不代表同等数量的独立因子。涉及发布反应的研究须先补可验证的历史发布时间／版本信息，不能把今天回取的修订数据对齐到历史参考期开始直接回测。

来源：[BLS API FAQ](https://www.bls.gov/developers/api_faqs.htm)、[BLS API 条款](https://www.bls.gov/developers/termsOfService.htm)、[纽约联储 Markets API](https://markets.newyorkfed.org/static/docs/markets-api.html)、[参考利率说明](https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates)、[H.10 官方发布页](https://www.federalreserve.gov/releases/h10/current/)、[H.10 官方历史数据](https://www.federalreserve.gov/releases/h10/data/FRB_h10_xml.zip)。

BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov.

New York Fed reference rates are subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not responsible for publication of these reference rates by US Tech Quant, does not endorse this republication, and has no liability for your use. See [Terms of Use](https://www.newyorkfed.org/privacy/termsofuse).

## 显式仓库路径与迁移

Python 的 `resolve(repo_root=...)` 与 PowerShell 的 `Get-UstqStoragePaths -RepoRoot ...`，均以显式指定的仓库目录读取配置并返回该仓库位置；它优先于继承的 `USTQ_REPO_ROOT` 和复制配置中的旧 `repo_root`。其他外部根的参数、环境变量和配置优先级保持原有行为。

路径解析本身不搬动文件。迁移具体组件时，应在旧位置不可用的隔离环境验证新入口，核对调用方、内容哈希及冻结契约，再处理旧副本。带源码哈希冻结的读取器优先使用既有路径参数；不能直接替换冻结源码中的文字。
## 财报原文、内部人、受益所有权、分部指标与基金持仓

2026-09-14 的 `factor_sources_20260914` 接入沿用现有 storage resolver、FAST6 原始缓存、`register_file` 和 `DataStore`。新获取的原始响应主要在 `cache_root/official_research_intake/<run-id>/raw/`；N-PORT 季度 ZIP 位于同一 run-id 下的 `sec_nport/raw/<quarter>_nport.zip`。既有 Form 4 季度原件按明确路径和 hash 复用，保留原存储位置。规范化版本在 `data_root/reference/official_research/`，计划、来源凭据、校验和发布回执在 `results_root/official_research_intake/<run-id>/`。最终覆盖、实际行数及未取得的资料以该目录 `final_report.md` 和各 manifest 为准；生成快照本身不等于已登记 catalog。

| 数据集 | 保留内容 | `DataStore.read` 日期列 |
| --- | --- | --- |
| `sec_event_filings`、`sec_earnings_documents` | 2024 年以来既定 CIK 范围内的 8-K／8-K/A Item 2.02、EX-99 附件、完整提交原文定位、披露接受时间和提取状态 | `filed_date` |
| `sec_beneficial_ownership_documents`、`sec_beneficial_ownership_fields` | 当前季度 13D／13G 及修订原文；XML 叶节点原值、路径、属性和重复报告人 | `filed_date` |
| `sec_form4_<table>_current` | 八张 Form 4 原表，包括申报、报告人、衍生／非衍生交易及持有、脚注、签名；2020 年起季度包加当前季度原文 | `filing_date` |
| `sec_financial_notes_<table>_current` | SUB、NUM、TXT、REN、PRE、CAL、TAG、DIM 八表；2020 年起季度／月份包中既定 CIK 的自定义、维度和文本事实 | 六张事实／展示表用 `filing_date`；TAG／DIM 用 `archive_period_end` |
| `finra_consolidated_short_interest_current` | FINRA 半月空头持仓全字段及明确解释的数字列；208 份公开文件，2017-12-29 至 2026-08-14 | `date` |
| `sec_nport_filings_current`、`sec_nport_holdings_current`、`sec_nport_identifiers_current`、`sec_nport_securities_lending_current`、`sec_nport_explanatory_notes_current` | N-PORT 基金申报、持仓、标识、证券出借及附注；2024Q1 至 2026Q2 官方公开季度包 | `filing_date` |

`<table>` 使用原表名的小写，例如 `sec_form4_nonderiv_trans_current`、`sec_financial_notes_num_current`。日期列必须显式传给通用 `DataStore.read`；catalog lineage 中记录日期列并不会自动替代调用参数。

```python
from scripts.storage.storage_r2a import DataStore
store = DataStore()
earnings = store.read("sec_earnings_documents", start_date="2025-10-01",
                      end_date="2025-12-31", date_column="filed_date")
insiders = store.read("sec_form4_nonderiv_trans_current", start_date="2025-10-01",
                      end_date="2025-12-31", date_column="filing_date")
```

2026 年以后仅获授权做获取与数据完整性核查，不用于训练、调参、因子筛选或回测。以上固定 CIK 来自既有身份范围，并非历史时点股票池。原始字节、抓取时间、源 URL／SHA、季度、行号和修订申报均保留；今天回取的修订版本不自动取得历史 PIT 资格。来源申报时间与批量数据实际发布时间是不同字段，未知的历史可用时间保持 null。

**实际更新边界。** 当天 SEC 日内补充使用一次有明确 feed anchor 的官方 all-form Atom 快照，并验证已翻页到前一天；该时点之后的申报不属于此次完整性声明。财报附注最新公开包是 2026 年 8 月。N-PORT 最新公开批量包是 2026Q2，其中最新报告期为 2026-05-31；本批不包含季度结束后的逐份申报。FINRA 公开索引止于 8 月 14 日，按官方日历应发布的 8 月 31 日结算数据尚未取得；此源保持 `PARTIAL_SOURCE_COVERAGE`，不能称为已完整更新到今天。

**原文与交易含义。** 财报范围是 Item 2.02 相关提交，不保证涵盖发行人网站所有独立指引。`guidance_term_candidate` 只是词语命中，不是已解释的管理层指引；HTML 表格边界与 PDF 提取状态均显式保留，数值抽取仍需语义核对。13D/G 的 discovery CIK 不自动认作目标发行人；主体身份应来自原披露。Form 4 的买卖、赠与、期权行权、扣税等交易代码不混成净买入；衍生与非衍生证券分表，脚注价格不填零，4/A 不静默覆盖原申报。

**财报维度。** NUM/TXT 保留原值字符串、`dimh`、`iprx`、期间及精度字段；字典按每个来源包完整保留。连接必须包括 `source_period + source_sha256 + provider key`，不能跨季度任取同名自定义标签；官方 DIM 字段 `dimhash` 另外提供显式 `dimh` 别名。源 TAG 字典缺项保留并列入核验记录。各包的引号解析模式根据原文件结构推断并记录；两种有效解释导致不同行界时拒绝解析，不猜测字段或丢行。平衡的字面引号与 CSV 包裹无法仅靠语法可靠区分，原件保留供核对。源数值本身已受供应商小数舍入、日期舍入及文本截断等限制，不能从规范化结果恢复已丢失的精度或文本。

**空头持仓与基金持仓。** FINRA 半月余额不等于每日 short volume、借券费率或净做空流量；`999.99` 的 days-to-cover 哨兵／上限值不作为精确数值使用。历史文件在今天索引中存在，不证明其当时已按当前范围发布。N-PORT 的 `CURRENCY_VALUE` 已是美元金额，不按 `CURRENCY_CODE` 再换汇；原值另提供精确 Decimal 别名。`percent_net_assets=5.27` 表示 5.27%，`balance_numeric` 的单位由原 `UNIT` 决定。`IS_LAST_FILING` 指基金预计不再提交 N-PORT，不能拿来选择最新修订。修订与缺失 series ID 保留；即使 `report_date` 在 2026 年前，2026 年提交的修订仍属于 2026 年信息。

刷新使用 `scripts/storage/refresh_sec_event_originals.py`、`refresh_sec_insider_data.py`、`refresh_sec_financial_notes.py`、`refresh_finra_short_interest.py`、`refresh_sec_nport.py` 的显式计划和 run-id。先查看对应 `--help`，核对范围后获取，再验证和登记。原 run-id 只恢复同一次获取；需要观察新修订时创建新的明确版本。网络超时可按凭据限定恢复次数，HTTP 拒绝不通过换入口重试；失败记录和未取得的文件列表不删除。

来源：[SEC 申报访问说明](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)、[SEC 内部人数据](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets)、[财报附注数据](https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets)、[FINRA 空头持仓文件](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files)、[N-PORT 数据](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets)。

### 同日纽约联储新发布版本

本轮执行跨过纽约联储 2026-09-14 美国早间发布窗口，随后以新 run-id `nyfed_release_20260914_1300z` 刷新并登记 `nyfed_reference_rates_current`。此版本共 90,852 条长表指标，相对早间版新增 36 条，既有记录语义变化及删除均为 0；六类利率分别做最新日期读取验收。EFFR、OBFR、TGCR、BGCR、SOFR 有效日至 2026-09-11，SOFRAI 至 2026-09-14。旧版保留，当前 catalog 指向新版；日期列仍为 `date`。完整凭据位于 `results_root/official_research_intake/nyfed_release_20260914_1300z/nyfed/`。

## 2026-09-14 官方数据扩展与 FINRA 账户进度

本轮 `official_extension_20260914_1415z` 继续复用现有 storage resolver、原件归档、`register_file` 与 `DataStore`。接入结果与独立校验凭据见 `results_root/official_research_intake/official_extension_20260914_1415z/final_report.md`。数据仅用于本次授权的获取和完整性检查；2026 年以后不用于训练、调参、因子筛选或回测。

| dataset | 新增内容 | 本轮覆盖 |
| --- | --- | --- |
| `cboe_vvix_daily_current` | VIX 的波动率指数 | 2006-03-06 至 2026-09-11，5,102 行 |
| `cboe_vix9d_daily_current` | 9 日期权隐含波动率指数 | 2011-01-04 至 2026-09-11，3,945 行 |
| `cboe_ovx_daily_current` | 原油 ETF 波动率指数 | 2009-09-18 至 2026-09-11，4,269 行 |
| `cboe_gvz_daily_current` | 黄金 ETF 波动率指数 | 2009-09-18 至 2026-09-11，4,269 行 |
| `cboe_vxapl_daily_current` | 苹果波动率指数 | 2011-01-07 至 2026-09-11，3,938 行 |
| `cboe_vxazn_daily_current` | 亚马逊波动率指数，保留 Cboe 的 VXAZN 编码 | 2011-01-07 至 2026-09-11，3,938 行 |
| `cboe_vxeem_daily_current` | 新兴市场 ETF 波动率指数 | 2011-03-16 至 2026-09-11，3,892 行 |
| `nyfed_primary_dealer_current` | 28 条交易商净持仓、回购/逆回购融资、证券交收失败系列 | 18,714 行；26 条自 2013-04-03、2 条自 2022-01-05，最新均为 2026-09-02 |
| `chicago_fed_nfci_weekly_current` | NFCI、ANFCI、Risk、Credit、Leverage、Nonfinancial_Leverage 六个指数 | 1971-01-08 至 2026-09-04，2,905 周 |

以上数据均使用 `date` 查询，按各自官方观测频率解释。Cboe 的 `close` 等数值保留官方指数点位，不除以 100，也不视为可直接交易的股票或期货价格。7 份 CSV 来自官方历史页明确列出的下载链接，原文值和真实行号保留；官方回算或修订历史不取得历史 PIT 资格。复用 `scripts/storage/refresh_public_sources.py`，正式 CLI 使用模块方式：

```powershell
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_public_sources --sources cboe_indices --work-root D:/us-tech-quant-results/official_research_intake/<new-run-id> --target-date <as-of-date> --execute
```

这仍是生成待验收快照的命令，不会自动登记目录。当前 Cboe 原件在 `cache_root/official_research_intake/official_extension_20260914_1415z/20260914T142438799644Z/raw/cboe_indices/`；版本在 `data_root/reference/official_research/cboe_indices/5228ef8dd7a13f91481d1dc6/`；manifest 与验收回执在本轮结果目录 `20260914T142438799644Z/cboe_indices/`。确切规范化代码 SHA 及测试副本保存在 `code_snapshot/cboe/`，后续扩展不改变该历史版本身份。

纽约联储的薄适配器是 `scripts/storage/refresh_nyfed_primary_dealer.py`，只取固定 28 个官方系列，不下载全部系列、不拼接旧编号。原件在本轮缓存 `raw/nyfed_primary_dealer/`，Parquet 在 `data_root/reference/official_research/nyfed_primary_dealer/<version>/`。值的单位是百万美元；净持仓可为负数，融资是总额口径，交收失败是报告期累计金额，不能解释成唯一失败交易数或日均值。339 个官方 `*` 保留原文并置数值为 null，未猜测其含义。保留 `seriesbreak`、当前定义及其适用范围；当前定义不自动证明旧问卷期间的历史含义。官方日期表混有其他频率，独立验收按 FR 2004 周三报告频率验证各系列有效范围完整性。

```powershell
& D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe -B -m scripts.storage.refresh_nyfed_primary_dealer --run-id <new-run-id> --as-of <as-of-date> --execute
```

芝加哥联储当前历史每周可能随新数据、历史修订及估计权重变化。六列是指数值，不是分项对 NFCI 的贡献。周五观测日期、官方 HTTP Last-Modified 与历史实际可用时点分别保留，不能互换。沿用 `refresh_public_sources.normalize_nfci` 从已校验的官方原件离线生成快照；原件位于 `cache_root/official_research_intake/official_extension_20260914_1415z/nfci/raw/nfci/`，Parquet 位于 `data_root/reference/official_research/nfci/6250ef2f4528d930a63bc21d/`。精确获取清单、版本路径及独立核验见本轮 `nfci/` 凭据。三类来源均保留版权、署名与使用范围说明，公开下载不代表获得再分发或商业数据授权。

FINRA 个人账户已使用用户指定的罗马字姓名及个人 Gmail 注册；公开 API 的认证和分页捕获已接入既有 `refresh_finra_short_interest.py`。凭据只从 `FINRA_API_CLIENT_ID`、`FINRA_API_CLIENT_SECRET` 环境变量读取，令牌仅存内存，禁止重定向转发认证头，失败不会自动反复认证。实际启用仍须完成账户密码激活和 Public API 凭据申请；本轮没有取得生产 API 数据。当前已登记空头余额仍至 2026-08-14，2026-08-31 结算期缺口未关闭，不能标记 latest complete。

此前 4 个 SEC 所有权原件缺口本轮仅再作一次已确认官方索引请求，仍为 HTTP 503，随即停止。新证据在 `results_root/official_research_intake/sec_event_corrections_20260914_1415z/official_link_recovery/`；旧原件、4 张数据表、manifest 与规范化代码保持不变。


## 2026-09-15 GitHub 线索对应的官方免费数据入库

`github_official_expansion_20260915` 新登记 6 套、172,829 行，catalog 4276→4282；主代理原件全字段/Decimal/状态核验及 DataStore 最新期读取通过。实际数据继续直接落入配置中的 data_root/reference/official_research，原件进 cache_root/official_research_intake；没有新增包或另一套目录。

| 数据集 | 行数 | 实际覆盖 | 最新期说明 |
| --- | ---: | --- | --- |
| CFTC TFF：18 个金融期货合约 | 14,075 | 2010-07-27～2026-09-08 | 官方 9 月 11 日更新的 9 月 8 日持仓；各合约起点不同 |
| BIS：12 个经济体政策利率 | 125,751 | 1990-01-01 起，最晚至 2026-09-08 | 印度 7/23、韩国 8/28、澳洲 9/3、加拿大/英国 9/7，其余 9/8 |
| BIS：12 个经济体实际有效汇率 | 4,692 | 1994-01～2026-07 | 2020=100、月度、未季调；date 为月初标签，另留 period_end |
| 财政部 Operating Cash Balance | 16,602 | 2005-10-03～2026-09-10 | 按 account_type 区分财政账户余额、收款及付款 |
| 财政部 Debt to the Penny | 6,700 | 2000-01-03～2026-09-10 | 美元；包含公众持有、政府内部及总债务 |
| 财政部 Average Interest Rates | 5,009 | 2001-01-31～2026-08-31 | 百分数；存量债务平均利率，不是市场收益率曲线 |

数据集名称为 `cftc_tff_futures_only_major_financial_current`、`bis_central_bank_policy_rates_daily_current`、`bis_real_effective_exchange_rates_monthly_current`，及 `treasury_fiscaldata_{operating_cash_balance,debt_to_penny,avg_interest_rates}_current`。全部为当前修订版本；原缺失值、源标记、历史方法及代理利率说明保留，available_at_utc 为 null。月度 BIS date 是月初标签，period_end 另存。2026+ 本次仅补数/完整性观察，无策略训练、筛选或回测授权。

源码入口是 `scripts/storage/refresh_cftc_cot.py`、`refresh_bis_statistics.py`、`refresh_fiscaldata.py`，均复用既有存储/归档/目录。GitHub 参考 moshejs/commitments-of-traders、bis-med-it/pysdmx、fedspendingtransparency/fiscal-data，实际数据均从官方 API 获取；代码开源许可不替代数据条款。

专项 68 项及默认 261 项合成测试通过。整体预检仍受两个既有不可读临时目录的 ANTI_BLOAT_ACCOUNTING_INCOMPLETE 阻塞，不视作整体功能验收通过，未绕过权限。FINRA 凭据已 Active 但本机 API 密码仍未收到，8/31 期尚缺；OFR HFM 目录不一致及 HTTP400 候选未登记。

本轮完整报告、5 个 manifest/目录事务、原件 QC 和恢复凭据：[final_report.md](D:/us-tech-quant-results/official_research_intake/github_official_expansion_20260915/final_report.md)。财政部 3 次 ReadTimeout 各一次恢复，原失败及计划保持不变。


## 2026-09-15 第二轮官方免费数据追加

`additional_official_expansion_20260915` 新登记 4 类、5 套数据，33,292 行；catalog 4282→4287。原件/缓存沿用配置中的 cache_root，规范 Parquet 使用 data_root/reference/official_research，计划、字段定义、原件对照和目录事务回执使用 results_root/official_research_intake/<run-id>。数据通过现有 DataStore 读取，日期列均显式使用 `date`。

| dataset | 行数 | 本轮实际覆盖及含义 |
| --- | ---: | --- |
| `treasury_fiscaldata_auctions_query_current` | 7,864 | 2000-01-03～2026-09-15；7,861 条已有结果，已出结果最新为9/14；另外两条9/15公告及一条2001-09-11原始无结果记录不冒充结果 |
| `cftc_bank_participation_financial_futures_current` | 1,695 | 2024-09-03～2026-09-01；25份月报、23个固定金融市场原标签，US/NON_US/TOTAL银行组；历史有市场缺席，不补值 |
| `frb_g17_technology_industry_monthly_current` | 10,536 | 1990-01-31～2026-07-31；24系列各439个月：制造业/机械/计算机电子/半导体等产出、产能及利用率；date为源月份末标签 |
| `treasury_tic_foreign_us_long_term_holdings_current` | 8,892 | 2020-01～2026-06；114个来源实体/汇总标签、持仓、净交易和估值变化 |
| `treasury_tic_long_term_gross_transactions_current` | 4,305 | 2023-02～2026-06；105个来源实体/汇总标签、美国及外国长期证券总买卖额 |

TIC 的 `date` 为月初标签，`source_period` 与 `period_end` 另存；金额单位为百万美元。其全部 13,197 行、250,461 原字段单元格与官方 HTML 对照一致，n.a. 保留 null、原文 -0 保留，不混加国家/地区/全球/Of Which 重叠汇总。托管或居住地不等于最终受益人国籍。交易及估值新口径始于2023-02，未拼接旧 Form S 或回推 CSLT。官方6月数据于8/17发布，7月数据计划9/16发布，本批尚未到期。

拍卖保留114原字段，并为20个核心金额/倍数增加精确 Decimal 别名；`date=auction_date`，公告日、发行日、record_date 另存，未来发行日不是未来已知的拍卖结果。第12页API附加了10个与拍卖无关的字典字段；已保存完整原字典，并仅在实际记录均不含这些字段且原114项定义/格式不变时排除它们。原失败和父计划保留，前12页未重复请求。

BPR 保留458个保密银行计数空白，不推算小组人数；它是银行报告头寸，不能视作银行身份、资金流量或全体银行资产。原行1,130个空白OI保留，另列 `market_open_interest` 明确记录源组别OI。官方索引仅保留最近25个月，不宣称2008年以来完整。

G.17 当前发布为8/18、观测至7月，下一计划发布9/18。IP以2017平均产出=100；CAP按2017实际产出标度，不是平均容量=100；CAPUTL是百分数。所有10,536点与官方TXT和SDMX双向逐值一致，当前发布页17条系列132个显示点做舍入一致性核对。当前NAICS、r/p标记、XML重复展示系列别名及秋季2026拟换基期说明保留。

入口为 `scripts/storage/refresh_fiscaldata.py --tables auctions_query`、`refresh_cftc_bpr.py`、`refresh_frb_g17.py`、`refresh_treasury_tic.py`；使用模块方式和新的显式run-id/as-of，具体执行开关见各 `--help`。脚本生成待验收版本，登记仍复用既有目录流程。本批没有安装额外包、申请付费服务或新建平行存储框架。GitHub仅参考免费接口/版本方法，实际观测均来自官方发布。

专项101项、项目默认261项合成测试通过；原件字段、Parquet哈希及DataStore最新期读取通过。数据仍是当前回取版本，历史可用时点未知保持null；2026+仅获取与完整性观察，不做训练、调参、因子筛选或回测。已有整体预检权限阻塞没有绕过；本轮Git状态读取还遇到dubious ownership，未修改safe.directory，不宣称整体治理验收通过。FINRA 2026-08-31期仍未取得，未将其计入本轮新增。

来源：[财政部拍卖查询](https://www.treasurydirect.gov/auctions/auction-query/)、[CFTC BPR说明](https://www.cftc.gov/MarketReports/BankParticipationReports/ExplanatoryNotes/index.htm)、[美联储G.17](https://www.federalreserve.gov/releases/g17/Current/default.htm)、[TIC 6月公告](https://home.treasury.gov/news/press-releases/sb0606)。完整证据与本轮恢复说明：[final_report.md](D:/us-tech-quant-results/official_research_intake/additional_official_expansion_20260915/final_report.md)。
