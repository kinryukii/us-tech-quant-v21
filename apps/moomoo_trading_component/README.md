# Moomoo 策略执行组件



活动源码位于 `D:/us-tech-quant/apps/moomoo_trading_component`。所有账户、冻结执行计划、幂等记录、恢复状态与日常日志，均由项目共享 resolver 路由到 `daily_root/moomoo_trading_component`；默认是 `D:/us-tech-quant-daily/moomoo_trading_component`。C 盘原源码与原 runtime 保留为迁移前恢复证据，原启动入口只转发到本目录。迁移记录见每日状态根下的 `migration_20261001.json`，7 个 SQLite 数据库已用合法 backup 合并 WAL，逐表行内容与完整性验证通过；未改写旧成交。



当前活动策略为五套：`RAW_A2`、`HGB_DIAG_5`、`R10_DIRECT_MEAN4_ELASTICNET_MID`、`R10_DIRECT_H5_RIDGE_MID`、`R7_GROSS_LINEAR`。原 `HGB_FACTOR_5` 暂停并保留历史入口、账本与全部成交。已有账户保留原账期；新增三套各有独立的 10,000 USD 本地纸面账户。原唯一美国股票 SIMULATE 账户通过显式审计绑定 `R10_DIRECT_H5_RIDGE_MID`，预算仍为 10,000 USD，按原持仓和资金差额调仓。

五套成员通过停止状态下的 POST `/api/applied/strategy-membership` 绑定原控制库前置 SHA；原 SIM 的 POST `/api/applied/broker-strategy-binding` 要求新鲜资金持仓对账、原账户/预算、无未完成委托和绑定前置 SHA。两个接口只准备绑定。`/api/applied/start` 与 `/api/applied/broker-start` 才恢复各自调度；启动器复用持久化身份，不自动迁移或清仓。旧计划、权限、COMMITTED repair 和历史保留原字节与审计来源，旧双 HGB 临时/长期权限不移交给新策略。

### 原 SIM 对齐当期完整发布目标

POST `/api/applied/broker-published-target-alignment` 复用原 `BestBroker` 和同一 SIMULATE 账户，面向当前已绑定且仍活动的策略。请求只引用该策略 owner 已发布的完整 READY 计划，不接受自定义股票、权重或任意目标。它准备差额调仓计划，不提交订单；账户身份、10,000 USD 独立预算、旧委托/成交与幂等历史不重建。正权重目标全部保留；原持仓在完整目标外时追加 SELL / 0%，不保留旧 HOLD 来覆盖新目标。本次 R7 例为 20 个正权重目标（各 5%、现金 0）及 15 个原持仓退出项；数量由当期目标和实际持仓集合产生，不写死为通用规则。

可复用调用顺序为停止调度、POST `/api/applied/reconcile` 核实原账户资金/持仓和旧订单，再 GET `/api/applied/view` 取得当前身份与前置值。对齐前必须已停止且 worker 退出、对账仍新鲜（60 秒以内）、无挂单/未知订单、原独立预算一致、本信号无已提交订单或执行进度；原信号收盘时钟、来源 SHA、目标 SHA 和严格执行窗口继续校验。请求正文严格只有以下六个字符串字段：

| 字段 | 当期来源 |
| --- | --- |
| `alignment_id` | 本次唯一请求身份；相同正文可幂等重试，变更请求不得复用 |
| `requested_at` | 带时区的真实请求时间，不得晚于服务当前时钟 |
| `expected_strategy_id` | `broker.strategy_id`，必须属于当前活动成员 |
| `signal_date` | 该策略当前 owner 计划的完整信号日 |
| `expected_target_sha256` | `books[expected_strategy_id].published_target_sha256` |
| `expected_precondition_sha256` | `broker.published_target_alignment_precondition_sha256` |

`published_target_sha256` 由后端对完整 owner 计划生成，不能重算轻量展示投影来替代。前置 SHA 绑定原账户、策略、预算、现金、持仓、原计划/进度和上次对齐身份；读取与写入间发生变化即拒绝。服务端重新核对同源目标、原信号时钟和账户后，以 `PUBLISHED_TARGET_ALIGNED` 审计收据保存旧设置与新计划。新对齐请求在同一 SQLite 事务保存完整计划与 `ACTIVE` 持仓转换授权审计。普通启动只恢复已签当前计划；持续转换尚未完成时，新合格信号从 cohort 当期已冻结 owner 目标准备差额调仓，在原正常窗口执行，完成后恢复所选策略常规调仓。原既有 alignment 记录不自动升级为持续转换授权，旧策略权限也不移交。

原已有对齐记录需要明确 POST `/api/applied/broker-published-target-conversion` 授权持续转换；正文严格只有 `conversion_id`、`alignment_id`、`requested_at`、`expected_precondition_sha256` 四个字符串，不接受自定义股票/权重、账户或预算。服务端核对原对齐审计与当前前置状态，只保存授权记录，不改写原收据、订单或历史，也不在此请求中下单。

POST `/api/applied/broker-published-target-manual-completion` 只接受 `manual_id`、`requested_at`、`deadline_utc`、`expected_strategy_id`、`signal_date`、`expected_target_sha256`、`expected_precondition_sha256` 七个字符串，为原已发布目标的剩余差额准备本次有限补单授权；不接受任意股票或权重。原执行段与恢复段分别保存在 owner 审计中，原订单和成交历史保留；接口保存授权回执，实际执行仍由原 `broker-start` 接续。该次截止与常规开盘窗口独立，原行情、资金、库存等门禁继续适用。

POST `/api/applied/broker-published-target-alignment-rollback` 只接受 `alignment_id` 和当前 `expected_precondition_sha256`，仅在原停止/新鲜对账门禁与尚未开始本期执行等校验通过时恢复保留设置，不删除对齐审计。对齐或回滚本身均不下单；需要执行时再明确调用原启动接口。所有 mutation 继续要求同源 JSON 与本服务进程的 `X-CSRF-Token`，不提供 REAL 下单能力。

### 当前展示与统计范围

`/paper` 与 DEMO `/paper-trading` 共用一套展示组件。原券商模拟账户是主区，目标持仓、当前核验持仓和显式 SELL / 0% 退出项分区，另显示目标内持有与目标外剩余数；缺少已返回持仓市值时权重及差值保持未知，不自行推算执行股数。行情检查未通过项只对应原 skipped 记录，完整目标/现仓范围由对照表展示；五本 PAPER 账本及 NAV 是随后总览。纽约/JST 窗口从同一实际计划起止时间动态格式化。完整规则可展开，当前活动成员中的对角 HGB 沿用自己的自动接续权限，其他四本及当前 Ridge SIM 的常规执行使用严格纽约 09:55–10:20 窗口；下文旧双 HGB 授权片段仍是原历史契约，不代表权限已扩大到新增策略。

券商卡片只读 `broker.published_target_conversion`：有效 owner 记录为 `ACTIVE` 时说明尚未完成统一持仓，后续合格信号在正常执行窗口按当期已冻结目标继续差额调仓；`COMPLETED` 表示 owner 已依据真实账户对账与本期 BUY 完成状态确认转换结束，此后恢复所选策略常规调仓。缺失、未知或与当前策略不符的记录显示待核验，不凭旧 alignment 记录假定持续转换已启用。页面不预测完成时间/股数，不增加写入按钮，原账户与审计历史保留。 余现金说明只有当期 owner 完成状态才切换为整数股与资金规则留下的余款；未完成或仅有旧期完成记录时不据此宣称本期已完成。

本次手动补单只读取 `broker.published_target_manual_completion`（`OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1`）；`ACTIVE` / `EXPIRED` / `COMPLETED` 分别显示“授权有效”/“已截止”/“本次补单已执行”。常规窗口优先读取冻结元数据的 `ordinary_execution_time_utc` / `ordinary_execution_deadline_utc`，手动窗口读取 `authorized_at_utc` / `deadline_utc`，补单记录编号来自 `manual_id`。授权窗口与常规开盘窗口分开展示：常规纽约 09:55–10:20 窗口与历史记录各按自身时钟展示，另显示该次有限授权的起止时间、状态和补单记录身份。手动窗口不标作“开盘后 0–10 分钟”，也不推算完成时刻或股数；原目标、实际差额、合格行情和资金/库存等门禁继续适用，不借此扩大其他信号或策略权限。页面仅只读解释 owner 记录，没有任意下单按钮；授权或窗口开放均不能当作已成交证明。

GET `/api/applied/view` 是固定只读、有界展示投影（最多 4 MiB）；完整审计快照和原 GET `/api/applied/state` 保留。纸面 NAV 最多返回 1,000 条，券商委托接口当前只返回最近最多 100 笔，因此“最近委托 / 其中已成交”及展开表的显示范围不能解释为完整历史总量。待确认委托保持单独状态。目标对齐与启动只证明计划已准备/调度已启用，全部成交须以实际券商对账和原账本为依据；本段不声明本期全成交或研究图表已经更新至当前目标日。

账户状态视图只读刷新采用单个在途 GET，请求结束后再等待 15 秒安排下一次；GET 最多 15 秒，失败保留上次记录并明确标注最近成功读取时间及待更新状态。操作完成后的核验排队串行执行，过早发出的旧响应不覆盖新核验。刷新控制不会自动重发 POST，也不改变下单或报价规则。

三套新增策略只对原固定 TOP100 consensus 输入应用已冻结模型，不重训、不搜索、不修改原研究选择。日更保存 Raw32 数学输入，并由同一来源 owner 校验原池、当前身份、特征/模型 SHA 和真实收盘时钟；每本计划按自身收盘持仓、现金、精确 HOLD 股数和 R7 前次请求 G 独立准备。来源不合格时该策略明确 BLOCKED，其他合格账本独立运行。`PAPER_CURRENT_IDS` 只列已接通的当前纸面消费者，新增 `R6_DURATION_TREE` 复用原 `duration_tree_2025` 和原生 `p_failure` 解码；它不扩大原 MAIN 三套、v1 五本或券商权限。Duration 仅显式读取 `A2_consensus_paper/duration_latest.json` 指向的候选 sidecar，绑定原 `latest.json` 的 publication、相同 flags/池和真实 probe 观测时钟；同日补齐不重写原三套输入、旧来源或历史资格。同日恢复通过同一组件续接已接受来源；`reuse_only` 缓存未命中时直接阻断该可选阶段，不触发原输入重建。缓存命中延迟导入特征与排名模块；阶段切换释放临时对象并归还 Arrow 空闲页。读表限制为一批预取、按列转换，保留原数值和类型。Duration 复用原无标签持仓状态取前驱键，省去重复构造；输出仅保留必要历史键、当前日和类型见证，原状态计算及审计仍完整执行，时钟与 1.5GiB/8GiB 门槛不变。来源、成熟 probe 或冻结身份不合格仅使 Duration BLOCKED，原三套先独立发布；没有真实成熟来源时不补造 READY。现行普通执行为纽约 09:55–10:20（开盘后延迟 25 分钟、1500 秒窗口），资金/整数股/报价/价差门禁继续适用。

页面只读取轻量发布包和账户状态；历史 NAV 最多一次返回 1,000 条，完整 SQLite 历史不删。新增模型在原单 worker 中逐头加载、释放后弱引用核验，不设全局模型缓存，并记录实测内存。当前输入与运行状态位于 `daily_root/A2_consensus_paper` 和 `daily_root/moomoo_trading_component/applied`；纸面数据库实际位于 `applied/books/books/<strategy_id>/state.sqlite3`，共用控制库为 `applied/books/cohort.sqlite3`。缓存、报告和模型仍由原共享 resolver 路由到各自 D 盘根。



```powershell

# 打开控制台及原有模拟账户，调度保持停止

& "D:/us-tech-quant/apps/moomoo_trading_component/start.ps1" -WithMoomooBest

# 启动已绑定的五策略调度及原有模拟账户

& "D:/us-tech-quant/apps/moomoo_trading_component/start.ps1" -WithMoomooBest -ActivateStrategies

```



地址为 <http://127.0.0.1:8766/paper>；正式 DEMO <http://127.0.0.1:8506/paper-trading> 嵌入同一组件。`/manual` 保留手动工作台，`/live` 仅提供明确操作后的实盘只读查询。`-Offline` 使用隔离的本地合成行情演示，不能同时启用策略或券商模拟。所有启动使用项目规范 Python 环境，不创建仓库内 `.venv`。



HGB 计划跟随 `config/research_governance/selected_hgb_policy.json` 的活动策略。旧方案 `RAW_TOP20_FROZEN_LEGACY` 复用原冻结优化器，以 Raw A2 Top20 为新建仓候选，已有持仓按旧优化器管理；沿用原账户并按差额调仓。政策切换后，已成交的本期冻结计划和权限保留，下一期有效收盘信号才生成所选政策的新计划。`HGB_TOP20_RISK_R1` 使用 Raw Top40 内的 HGB Top20 作为买入候选，由对角／因子收缩风控决定权重和现金；候选外旧持仓只能减仓。正常日更时，PAPER 与原券商 SIM 均按各自真实收盘持仓和现金生成计划，不能用 DEMO 空仓目标替代；只有新计划的 `policy_id`、信号日期和来源 SHA 已持久保存才证明账户采纳，配置切换不改写旧成交。



用户明确要求重启时，POST `/api/applied/reset-hgb` 仅接受绑定策略、信号日期、活动策略 ID、包 SHA、请求时间及 reset_id 的请求；调度须停止。两本 HGB 纸面账本经完整性检查和归档后，各以 10,000 虚拟 USD 初始化，Raw A2 账本保持原记录并暂停。原 MOOMOO SIMULATE 账户、独立预算及历史委托成交均保留；下一交易日先将原持仓全部卖出，只有确认实际空仓且无未完成订单，才以清仓后的实际策略现金重买 HGB_DIAG_5。重启目标明确标为 `POST_LIQUIDATION_ASSUMPTION`，不冒充真实历史收盘估值；新账期有独立幂等身份，归档或重启失败时不自动执行。新计划仍使用已冻结的 HGB_TOP20_RISK_R1 模型和参数。



同一组件进程中的纸面仓与券商模拟共享科学计算 worker 锁，每次最多启动一个模型子进程；日常状态与页面读取复用轻量缓存，避免两套调度同时加载模型。此限制不管理其它任务的进程。

DEMO 与嵌入工作台使用只读 `/api/applied/view`：当前计划、持仓、成交、NAV 和已暂停账本按展示用途投影，来源只返回路径/SHA，响应上限 4 MiB。原 `/api/applied/state` 与数据库继续保留完整来源和历史审计，展示接口不更改计划、权限或调度。



2026-10-04 用户随后撤销了 MOOMOO 的全卖重买计划，要求继续用原模拟持仓自动调仓到现行 HGB 对角风险目标。POST `/api/applied/broker-cancel-reset` 仅接受原 `reset_id`，在调度停止、重置仍为 ARMED、未提交任何该重置委托且无未完成订单时，归档撤销证据并解除重置计划；持仓、现金、预算和历史委托成交保持原账本。此次按用户指定的当前页面已发布 10 月 2 日 HGB_DIAG_5 权重准备一次性 `REBALANCE_EXISTING_POSITIONS` 差额调仓；标明 `USER_REQUESTED_PUBLISHED_TARGET_REBALANCE`，不将现金起点目标冒充原账户收盘优化结果。执行使用原账户实际资金、持仓与窗口内合格报价，仅调整至目标股数，不要求全账户空仓、不生成新现金账期；下一信号仍走原实际账户收盘估值路径。已完成的两本本地 HGB 纸面账期重启继续保留，各自从 10,000 虚拟美元运行。



补齐实际行情使同一尚未执行信号的排名和 HGB 目标变化时，POST `/api/applied/revise-targets` 仅接受原 `reset_id` 和新的 `expected_package_sha256`。纸面及原券商模拟调度都须停止，信号日期、执行日期、冻结日历、策略、账户和开盘窗口保持一致；只允许开盘前且尚无该目标成交或已提交委托的修订。两本 HGB 纸面账期仍是原账期，原 10,000 美元空仓、旧重启档案、原券商资金持仓和全部历史成交均保留。现行 DailySource 为新包建立独立且不可覆写的目标模板档案，修订收据绑定原账期和新模板；原目标及来源保存在修订历史中。接口仅准备目标，失败时保持停止，重试同一包幂等；全部目标验收后才通过原启动接口恢复执行。



## 收盘信号与模拟执行

本次手动补单结束后，常规每交易日默认窗口为 **纽约 09:55–10:20（America/New_York）**，即官方开盘后延迟 **25 分钟**、窗口 **1500 秒**；原五本纸面账户、原 SIM、启动器和原日更恢复入口共用此默认。显式旧延迟（包括 0 / 30 分钟）及窗口覆盖继续有效，单次手动补单授权仍最多 **600 秒**；原策略、账户预算、既有订单及历史时钟和授权记录保留。以下 2026-10-16 及更早日期段保留当时契约，新默认接续其后的常规信号。

新 schema2 常规执行仅在美东 **09:55–10:20** 内自动续查，**10:20 为硬截止**；之后的剩余目标须另获单次手动授权（仍最多 600 秒），不自动延长至收盘。旧 schema1 及 2026-10-09 等带日期授权保留各自原记录和时钟。

2026-10-16 用户将普通模拟下单起点改为纽约时间 **10:00**，保留原 **600 秒**窗口，即 **10:00–10:10 America/New_York**。原五套纸面账户及当前绑定的 Ridge 券商模拟共用此时钟，随纽约夏令时转换。历史研究回放继续使用其原开盘执行口径。启动器与原日更恢复入口使用 30 分钟延迟；打开页面及日更仍保留原启停状态。

显式暂停准备时，只对官方开盘前、无执行尝试及同信号人工许可绑定的普通五本目标更新执行时间；计划内容、来源与官方开盘时间保留。旧订单、成交、reset 和人工窗口不改写，也不将原 HGB 自动接续权限移交给 Ridge 等其它策略。

以下日期段落保留历史时钟与授权沿革。



2026-10-01 用户明确将默认执行延迟从开盘后 150 分钟改为 **0 分钟**。使用最新已完成美股交易日的收盘信号，在下一交易日开盘后第一份合格实时报价上执行。接近开盘及执行窗口内按约 1 秒检查；数据读取、网络与券商处理仍有实际延迟，记录真实报价时间、委托时间和成交时间，不倒签到 09:30。开盘前 5 分钟仅验证证券及预订阅，不取得可执行价格、不下单。



2026-10-02 用户确认默认执行时间为开盘至开盘后十分钟：本地三套纸面账户和券商模拟统一 **0 分钟延迟、600 秒窗口**。当时的 `start.ps1` 与三策略 CLI 省略时均使用该默认，不继承旧的 3,600 秒默认窗口；可用 `-ExecutionWindowSeconds` 与 `-BrokerExecutionWindowSeconds` 明确覆盖。旧信号已有订单时保留原到期约束，修改时钟不会重发历史成交或过期买单。未获得报价或窗口错过时显示等待/错过及具体原因，不使用昨日收盘价或补造开盘价。



2026-10-09 用户另行授权了**每日自动接续**：原两本 HGB 纸面仓和原唯一 SIM 账户优先在 09:30–09:40 执行；剩余目标沿同一冻结计划自动处理至交易日历收盘前 10 分钟，提前收盘日也按日历计算。通常价差仍不超过 50bp；超过 50bp 仅允许真实报价的最小价格单位 `price_tick` 一档内，且总价差不超过 200bp。30 秒报价、2% 价格偏离、原资金、整数股、原目标及真实成交时间门禁保留。停牌、无合格行情、未知订单或真实资金不足不能伪造完成。

长期授权只有原 Cohort settings 一个权威，各原账户保存审计投影；一次通过 POST `/api/applied/automatic-completion-policy` 明确保存 `{"enabled":true,"close_buffer_seconds":600,"one_tick_spread":true}`，不在日更时续签人工许可。启用要求原调度停止、原账户已对账且无挂单/未知订单；从授权后的下一纽约日期生效，沿用本项目 2026 评价边界。服务启动从原 SQLite 恢复，旧许可和旧成交不改写。无新 worker、账本或逐日授权目录，原日更入口及原启动器继续复用。

已确认终结的失败余单按原代次、冷却和券商实成交数量重试，未知或未终结订单先对账；已解析股数持久保存，不因下午报价重算加码。纸面资金不足时保留真实部分成交和未到达目标，只补固定目标的剩余股数。截止后停止新发送，保留真实未完成原因及已发订单的对账。其它策略、旧计划及未启用长期授权的账户保留原期限规则。

三本本地纸面账户另提供明确授权后的同日补执行入口 `Cohort.authorize_catchup(execution_date=..., deadline_utc=..., now=...)`。仅在调度停止、当前轮和 worker 已退出、原开盘窗口已结束后，逐本核对原批次、账户身份、冻结计划 SHA、来源和已核验的原下单权益；同一纽约交易日的正常时段内，授权截止不得超过当前时刻后 600 秒或当日收盘。授权与审计持久保存，默认延迟和原窗口不变；恢复仍走原逐证券纸面账本，只补尚未处理的目标，已处理证券不重复。报价继续按真实时间、30 秒新鲜度和 50bp 价差门禁检查，买入 ask、卖出 bid、先卖后买、整数股及单边 5bp 费用不变，不补造开盘成交。期限到达或身份、来源、计划变化即拒绝补执行，未来交易日不继承本次授权。



券商模拟的同日余单补执行使用 POST `/api/applied/broker-catchup`，旧模式正文仅接受 `execution_date` 与带时区的 `deadline_utc`；须先停止并通过原 `/api/applied/reconcile` 核实原 SIMULATE 账户、全部旧订单终态及独立预算。授权最多 600 秒且限同一纽约交易日，绑定完整原冻结计划、来源、原 BUY 股数和既有 SELL 证据；延期卖出后恢复 BUY 继承同一 SELL 目标，不因新报价反向回买。授权本身不启动执行；POST `/api/applied/broker-start` 的空正文只恢复券商模拟 worker，本地三策略仍可保持暂停，防止已完成账本的估值请求竞争行情额度。原报价、资金、幂等、截止和实盘隔离保护保持生效，未来信号不继承本次授权。



用户明确要求按当前时价补完余单时，上述券商接口可额外接受严格布尔 `quote_refresh: true`，形成独立的 `USER_MANUAL_REMAINDER_QUOTE_REFRESH` 人工意图。只纳入原信号尚未处理及延期卖出的证券，原已处理代码、已解析 BUY 数量上限、冻结权重、来源、账户和预算保留；旧两字段模式继续要求原 SELL 证据，不伪造缺失的旧数量。首次合格真实报价按原 BUY 预留数学解析一次 desired 数量，并记录新 as-of、报价、held_before、desired、SELL 上限 `min(desired, held_before)` 和 BUY 目标 desired。SELL 只执行减仓帽；若 desired 高于现持仓，后续 BUY 可按同一 desired 增持；若 desired 低于现持仓，减持完成后禁止反向回买。新目标及报价证据与执行状态原子保存、绑定审计，重启不重复解析或上调原数量。授权最多为当日当前时刻后 600 秒，保留原 30 秒报价、50bp 价差、真实资金和可卖股数门禁；以后交易日不继承该人工意图或 deadline。

2026-10-07 用户明确授权一次同日人工续期后，新增 POST `/api/applied/catchup-renew` 与 `/api/applied/broker-catchup-renew`。它们的原必填字段为 `execution_date`、新 `deadline_utc`、原许可完整内容的 `expected_prior_sha256`、唯一 `renewal_id` 与明确的 `allowed_codes`；仅原人工许可已过期、调度和 worker 停止、同一纽约交易日正常时段、原计划／来源／账户／预算及进度校验通过后，才追加一次最多 600 秒且不超过收盘的许可。原授权与成交不覆盖，已处理代码不重发，已确定数量不重算或上调，未知订单须先对账。旧补单接口仍拒绝不同期限的覆盖；普通调度不调用续期接口，未来交易日不继承。未另行签署下述单证券例外时，续期仍保持 50bp 价差；真实报价时间、30 秒时效、可卖股数、实际资金和实盘隔离始终保留。追加许可自身不启动执行，仍须使用原启动入口；同一信号已登记续期后，只允许同一请求幂等重试，不再延长。

人工单证券例外必须另有明确的人类授权，普通日更不会开启。纸面 `/api/applied/catchup-renew` 可选 `single_sell_spread_bps: 60`，仅适用于原冻结目标为 0、原同日批次只剩 KDK 的卖出；每本股数上限取原实际持仓，签署权限绑定原批次和审计。券商原续期接口不接受该字段。

原 SIM 的已续期期限结束后，POST `/api/applied/broker-manual-residual-sell` 可追加一次独立剩余卖出授权；请求绑定原 plan、execution、renewal、package SHA、固定目标及最大卖出股数、最低限价、唯一 authorization_id 和最多 600 秒期限。`broker-manual-residual-sell-execute` 与 `broker-manual-residual-sell-cancel` 只接受该 ID。执行沿用原 Engine、账户和账本，仅 NORMAL SELL；限价取最终新鲜买一且不得低于授权最低价，股数不上调，原 2% 偏离与 30 秒时效保留。只有本次明确签署的单笔卖出可用 60bp，原默认仍是 50bp；旧授权不覆盖，未来信号不继承。

原 `/api/applied/reconcile` 以该授权的实际全成交、原订单身份、实际持仓达到固定目标和无挂单为依据同步完成状态；已过期授权只能为已发订单记账，不能再下单。其他未完成目标继续保留，重复执行不会重发。自动调度只由原券商 worker 轮询；其运行时 Cohort 不重复调用券商 tick，原限频冷却有效。暂缺合格 SELL 报价时保持等待，不提前恢复 BUY；纸面异常状态仍保留原批次已处理与未处理清单。

纸面收盘估值优先使用原生 MOOMOO RAW USD 日线。仅当目标日原生记录为零行时，可复用当前推荐中已绑定 SHA、五日 OHLCV 重叠资格及原生锚点的 MASSIVE_GROUPED RAW USD 收盘收据；记录真实来源、收盘后观察时间与资格证据，继续校验原始字节、身份和前后哈希。异常或重复原生记录不能回退，PIT 价格指数不能充作美元收盘价。开盘执行仍须使用合格 MOOMOO 实时报价。



纸面账本按实际盘口买入 ask、卖出 bid，整数股，单边 5bp 成本，先卖后买；每个策略各自使用真实收盘持仓与现金。股票身份、常规交易时段、报价时间、新鲜度、价差、冻结模型与输入哈希继续校验。日更由原 `scripts.daily_recommendation` 全局锁保护；打开页面、查看状态与服务停止态启动都不会自动采集或买卖。模型只做冻结推断，不使用 2026 数据训练、调参或改变策略。



券商模拟沿用现行逐股执行的 MARKET 实现，旧 NORMAL 限价订单仍保留原始订单类型、重报价与到期约束。市场报价用于执行资格和资金检查，券商确认的实际成交均价独立记录，不能等同于官方 09:30 开盘价。未知提交、未知成交均价或未完成订单先对账，禁止重复买入；原券商模拟身份变化时停止。窗口结束后不发送新单或改单，但窗口内已提交的 DAY 委托可能依券商规则稍后成交。暂停只阻止后续操作，不撤销已有委托。实盘下单、改单、撤单、解锁与自动执行能力仍不存在。



## 数据、成交与图表接续

手动数据更新模式下，页面只读取已发布缓存；每个交易日下午由用户运行原 `更新今日推荐.ps1` 准备最新已完成交易日的信号、下一交易日目标及图表。同日重跑沿用已接受输入并仅恢复未完成分支，不另设日更组件或定时拉取。已授权调度保持运行且 OpenD 在线时，普通执行使用纽约 09:55–10:20，报价和账户轮询不重新训练或拉取历史数据。研究图表异步调用 `DailySource.start_execution_charts()`，在所有适用交易及手动窗口结束、没有待对账或未知订单时，复用原日更入口和计划共享重作业锁。原 Raw/HGB 与三套固定 MAIN 图表按阶段串行处理；只有两阶段的当前权威回执均验证通过才跳过维护。图表不能延长下单窗口或发送订单。账户成交、持仓和估值继续记在原账本，研究曲线仍是独立描述性回放。

纯图表更新使用原 HGB 展示引用，不改信号包。对历史上已结束的计划，只有普通及已登记人工窗口均截止、无未完成订单、原不可变档案和全部经济输入仍完全一致时，才能保留原执行状态并接受图表内容变化。活动窗口、未来计划和真实输入变化继续严格校验；原成交、数量上限、补单授权和未完成缺口保留，下一信号重新走原账户收盘计划路径。

日更与图表的实际截止日、成功／等待／失败必须分别核实。组件或电脑未运行时无法执行未来任务；重新上线不会倒签或自动补发错过窗口的旧买单。详见 [每日更新说明](../../docs/daily_recommendation.md#每日自动接续)。

## 存储和验证



三策略状态位于 `applied/books`，券商模拟状态位于 `applied/moomoo-best`，三策略模式的手动工作台位于 `applied/manual`，原独立手动工作台位于 `manual`。备份必须停止对应服务或使用 SQLite backup；不能只复制有 WAL 的主数据库，不能删除幂等记录、清空账户或换目录来处理未知订单。运行端校验解析后的真实路径必须处于共享 daily_root 下，仓库、canonical data、cache 和其它用途根会拒绝作为活动账户目录。



组件测试全部使用离线合成来源与模拟 SDK，不证明当前券商端到端成交。运行时将 TEMP/TMP 指向任务 cache_root 子目录，并在仓库根执行：



```powershell

$env:PYTHONPATH = "D:/us-tech-quant;D:/us-tech-quant/apps/moomoo_trading_component"

& "D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe" -B -m unittest discover -s apps/moomoo_trading_component/tests -q

```



`GET /api/health` 返回组件身份、版本与 `live_execution_enabled: false`，不连接券商。`GET /api/applied/view` 返回有界展示投影，`GET /api/applied/state` 保留原完整状态接口；两者只读当前缓存。POST `/api/applied/start`、`stop`、`halt` 使用同源 JSON 和本服务进程的 `X-CSRF-Token`。CSRF 令牌不是账户授权机制；SIMULATE/REAL 隔离与实盘执行锁由后端实际能力界定。早期 `VERIFICATION.md` 为历史证据，当前执行时钟与 D 盘路径以本说明和现行启动器为准。


新增三套 MAIN 的当前性检查只在隔离工作进程读取原日历、发布身份和哈希回执，不解码曲线或账本，不加载模型。真正延长仍由原零拟合驱动完成价格、身份和 CA 资格检查；缺少当期独立 CA 来源时显示 BLOCKED 并保留旧图，不自动调用 SDK 或沿用旧期回执。同一 MAIN 非资源失败身份等待来源修复，MAIN 原 1.5GiB/8GiB 资源门槛恢复后仍遵守原 15 分钟重试间隔；Raw/HGB 保留自身原 owner 规则，不继承这个新门槛。新交易窗口、手动授权、待对账或停止会取消并回收原作业树。

原 Windows runner 若明确报告作业句柄关闭或子树终止未获确认，图表状态为 `QUARANTINED`：不启动下一阶段，保留作业句柄和共享锁；停止先保存金融状态，资源关闭仍明确报错。线程退出不作为回收完成证明，组件不提供自动解除隔离。创建图表作业前的轻量检查出现同样明确的回收失败时，也会立即隔离原资源 owner；后续日志清理异常、来源变化或重试间隔不能解除。未来开盘尚未成熟时，Raw/HGB 显示 `WAITING_OPEN`，只有 MAIN 可按原已完成日资格维护。


## 手机重置后的原生模拟账户接管

手机重置可能使原 US STOCK SIM 原生编号退役。复用原 BestBroker 与同一 SQLite 账本，先 GET `/api/applied/broker-native-reset-precondition` 取得当场控制指纹，再 POST `/api/applied/broker-native-reset-adoption`。正文严格包含 `reset_id`、带时区 `requested_at`、`expected_old_account_id`、`new_account_id`、`target_strategy_id`、`expected_precondition_sha256`、`budget`；请求与原生资金/持仓快照须通过原 60 秒时效检查。

接管要求原两套调度与 worker 停止、无未知或挂单、唯一合格新 US SIM、旧编号不再可用，新账户现金和净值均等于原策略预算且零持仓。原 settings 原字节保存在同库 `native_reset_archive/<reset_id>/`，旧订单、成交和审计前缀保留；已提交修复标记保持原字节。新资本阶段按原现金减预算计算保留资金；原账户的策略进度、目标和人工/自动补单许可均不继承。

接口只返回小型 `ADOPTED_PAUSED` 确认，既不准备目标也不下单。相同请求幂等，不同内容不能复用同一 reset_id。首次显式准备继续调用原 `BestBroker.prepare_published_inputs`，仅计算该模拟仓策略；外层记录 `USER_NATIVE_RESET_CASH_BOOTSTRAP`、实际原生观察时间和新账户阶段，明确不是旧信号收盘时的原生快照。冻结 application 与收盘坐标的数值保持原规则。原 `/api/applied/prepare-current` 仍准备五本纸面与模拟仓；单模拟仓回执不能代替全组件日更完成回执。原开盘、报价、现金、整数股、来源/模型和资源门槛保持。
