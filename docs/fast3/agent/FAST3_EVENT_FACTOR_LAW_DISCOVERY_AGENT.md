# FAST3 事件中心因子规律发现 Agent 执行合同 R1

你正在 `FAST3_REPO_ROOT` 指向的现有 FAST3 仓库中工作。直接实施并运行真实数据，不要只写计划。目标是围绕 QQQ/SOXX 每一次未来 24 小时内先触达 ±1% 的事件，研究事件发生前各因子的水平和变化轨迹，分别检验线性与非线性规律，再使用预先冻结、连续且按时间隔离的随机区间进行反复但有上限的训练与回测。

普通模型失败不是询问用户的理由；应继续到合同允许的明确停止点。不得编造、补写、美化或把 synthetic 结果冒充真实结果。

## 0. 两条最高原则

1. **严防过拟合**：禁止未来函数、随机打散相邻分钟行、反复查看同一测试区间、后验改标签/阈值/Top-K、无限增加因子和组合、只展示最好种子或最好时间块。
2. **严防系统膨胀**：优先复用现有 FAST3/V22.080B 代码和数据合同；不得创建新的 V22 多层版本链、Atlas/Guard/Registry 子系统或 Runner 套 Runner。

“反复训练”只能在本合同预注册的轮数、模型数、因子数和新鲜时间块预算内进行。不能为了得到 PASS 而训练到成功为止。

## 1. 固定研究目标

保持以下定义不变：

- 底层：`QQQ`, `SOXX`。
- 决策网格：每 5 分钟一个候选时点。
- 入场基准：决策后的下一有效分钟开盘价。
- 标签窗口：未来 24 个自然小时。
- 标签：`UP_FIRST`、`DOWN_FIRST`、`NO_EVENT`。
- 上下障碍：底层价格相对入场价 ±1%。
- 同一分钟上下障碍同时触发：`AMBIGUOUS_EXCLUDE`，不得有利排序。
- 执行映射：QQQ UP→TQQQ，QQQ DOWN→SQQQ，SOXX UP→SOXL，SOXX DOWN→SOXS。
- Opportunity 门槛：0.60；最终候选 Top5%；成本 10bps 与 20bps；单账户单持仓。
- 禁止读取 `2025-02-08 00:00:00 America/New_York` 及之后的 Confirmation 行。

训练底层 ±1% 并使用三倍 ETF 执行是本合同的固定设计，不得在本轮改成“直接预测 ETF 3%”。

## 2. 路径和写入边界

环境变量：

- `FAST3_REPO_ROOT`：仓库根目录。
- `FAST3_DATA_ROOT`：外置只读数据根目录。
- `FAST3_RESULTS_ROOT`：本轮唯一可写结果目录。
- `FAST3_EXTERNAL_RESULTS_ROOT`：外置归档目录；Agent 不直接写，由启动器结束后同步。
- `FAST3_AGENT_RUN_ID`：本次运行 ID。
- `FAST3_AGENT_LIMITS_PATH`：限制 JSON。

所有结果、检查点和失败记录写入 `$FAST3_RESULTS_ROOT`。不得修改 canonical 数据，不得在仓库根目录新增入口文件，不得 Git stage/commit/push。

## 3. 必须继承并核验的历史事实

先读取原始 summary、report、代码和当前完成结果，不得只依赖本提示：

- V22.080B：Top5 lift 约 1.36122855，10bps 后净收益约 -0.001966。
- 最近一次最小实证 Development：最佳 H2 Top5 lift 约 1.34316664，10bps 后约 -0.00010356，结论 `STOP_NOT_ECONOMIC_AFTER_COST`。
- 历史已没有可证明完全未观察的干净区间。历史随机时间块只能称为 Development/Robustness，不能称为 Frozen Validation。
- 现有失败并非允许无限调 HGB；本轮必须先建立事件中心的因子规律证据。

若原始文件与上述描述不同，以原始可验证文件为准并记录差异。

## 4. Phase A：只读数据、session 和历史证据审计

先完成只读审计并生成：

- `FAST3_EVIDENCE_LEDGER.json`
- `FAST3_SESSION_FACTOR_AUDIT.json`

必须检查六 ETF canonical 分区、时区、字段、坏点隔离、日期覆盖、V22.065/V22.080/FAST3-004/最近 Development 结果和现有可复用模块。

### Session 硬门禁

列出 canonical 中所有原始 `session` 字符串及行数。禁止把未识别值静默映射为统一 unknown code。

仅当字符串语义可以从现有数据合同或代码明确证明时，允许在看到模型结果前做一次“同义名称映射”最小修复，例如 RTH 名称差异；修复必须写入审计和测试。若仍有无法解释的 session 行，最终使用 `STOP_DATA_CONTRACT_INVALID`。

## 5. Phase B：冻结事件、因子和随机时间块合同

在查看本轮任何因子事件率、模型结果或收益前，生成：

`FAST3_EVENT_FACTOR_DISCOVERY_CONTRACT.json`

合同必须冻结：

- 数据分区集合和 hash；
- 事件标签、5 分钟网格、24 小时窗口、±1%、下一分钟入场；
- 10/20bps、0.60、Top5、单账户规则；
- 事件/非事件匹配规则；
- factor dictionary；
- 神奇九转定义；
- 训练轮数和每轮配置；
- 每轮连续随机时间块的开始/结束日期、seed、purge、embargo；
- 选择规则、通过规则和停止规则。

随机块日期必须在查看本轮因子结果之前按固定种子生成并写入合同。观察过的块立即写入 Round Ledger 并永久退休；不得再次用于后续选择。

## 6. Phase C：建立每一个 1% 事件和匹配对照

生成 `fast3_event_ledger.parquet`。至少记录：

- event/candidate id；
- underlying、方向、decision/entry/hit/horizon 时间；
- `UP_FIRST/DOWN_FIRST/NO_EVENT/AMBIGUOUS`；
- 触达耗时；
- 触达前最大顺向和逆向波动；
- session、年份、月份、星期和时段；
- 24 小时标签并发数量和 uniqueness weight；
- 是否属于非重叠解释事件簇；
- 匹配 control id。

允许保留全部 5 分钟候选训练行，但必须使用 `1 / 同期重叠标签数量` 的 uniqueness weight，或者等价的经过测试的独立性权重。用于解释规律的主表必须同时提供非重叠事件簇，避免把同一波行情重复计算数百次。

每个真实事件匹配 1–3 个 `NO_EVENT` 对照，匹配至少包含：标的、session、时代、基础波动率桶、星期/时段。禁止只看事件而不看普通时间。

## 7. Phase D：冻结因子字典

生成 `FAST3_FACTOR_DICTIONARY.json`。最多 28 个基础因子通道、96 个最终派生列、8 个预注册交互。

允许的因子族仅限限制 JSON：收益/动量、波动和区间、相对量与量价、VWAP、MA/EMA、BOLL(7)、RSI、KDJ、突破回撤、QQQ/SOXX 相对强弱、缺口与 session、VIX 水平和变化、神奇九转以及数据质量门禁。

每个基础因子可使用：当前水平、5/15/60 分钟变化、斜率、加速度，以及只在训练 fold 拟合的 percentile/z-score。不得在 Round 1 后新增因子族。

### 神奇九转固定定义

三个周期仅限 5 分钟、60 分钟、日线：

- 上行条件：`close[t] > close[t-4]`；下行条件相反。
- 连续计数中断即归零；保存 signed count、raw run length、完成 9、距完成数量、bars since 9、sequence strength、sequence return。
- 日线只能使用前一个完整收盘日，禁止当天未完成日 K。
- 不预设 9 一定反转；必须同时检验趋势延续与反转。

只允许 8 个预注册交互：九转×波动率、相对量、VIX 水平、VIX 变化、VWAP 距离、相对强弱、session，以及趋势×成交量。

## 8. Phase E：逐因子线性和非线性规律

输出：

- `fast3_factor_linear_results.csv`
- `fast3_factor_nonlinear_results.csv`

### 线性测试

对每个因子和允许变换分别运行单因子 multinomial/regularized logistic，报告：

- UP/DOWN/NO_EVENT 系数、标准误/CI；
- 标准化效应；
- 单因子 AUC/lift；
- 跨连续 block 的符号一致性；
- 控制 matched controls 后的效应；
- 移除最佳 1% 事件后的方向是否保持。

### 非线性测试

先做训练内分位箱，再使用 spline/GAM-like logistic 和受限浅层 HGB，寻找单调、U 形、倒 U 形、阈值、饱和和方向反转。分箱边界只能在训练块拟合。

每个因子/区间至少输出：样本数、UP/DOWN/NO_EVENT 率、相对基准 lift、平均触达时间、10/20bps 执行结果、年份/session/block 稳定性。

只保留满足限制 JSON 中事件数、方向数和跨 block 稳定性门槛的规律。不能因为某一年度或某个 session 很好就保留。

## 9. Phase F：有上限的反复训练与新鲜随机块回测

总计最多 3 个训练轮 + 1 个最终审计轮，模型族最多 3 个，总配置最多 18 个；五个固定种子必须全部报告。

建议轮次：

1. **Round 1**：单因子规律和线性多因子基准。
2. **Round 2**：使用 Round 1 中跨块稳定的因子，比较线性与 spline/GAM-like 非线性。
3. **Round 3**：受限浅层 HGB 和最多 8 个预注册交互；只允许基于前一轮失败类型做一个假设族变化。
4. **Final Audit**：冻结最终候选后，在 5 个预注册新鲜连续时间块上一次性测试；结果出现后不得继续调参。

每轮开始前，向 `FAST3_ROUND_LEDGER.jsonl` 追加一条不可覆盖记录，包含：

- round id 和角色；
- 已冻结因子、变换、模型、参数；
- 使用的训练块和本轮新鲜审计块；
- 输入 hash；
- 允许的唯一修改；
- 预算剩余量。

每轮结束追加完整结果和失败原因。观察过的时间块标记 `RETIRED_AFTER_OBSERVATION=true`。

禁止随机逐行 KFold。随机回测只能抽取完整连续 60/90/120 日区间，边界至少 24 小时 purge/embargo，并尽量互不重叠。

### 允许根据失败做什么

每轮最多一个假设族变化，例如：

- 删除跨 block 方向反转的因子；
- 在线性和预注册非线性表示之间选择；
- 在已经登记的 8 个交互中启用一个小集合；
- 调整相邻正则强度或浅层复杂度。

禁止新增因子族、改变标签/窗口/0.60/Top5/成本、搜索新的九转周期、增加未登记交互、根据最终审计结果再训练。

若新鲜时间块耗尽、预算耗尽或没有稳定规律，立即停止。

## 10. 防泄漏和执行硬门禁

真实训练前必须运行测试并记录：

- 每个因子时间戳 ≤ decision time；
- 日线九转只使用前一完成日；
- VIX 使用 PIT 对齐值；
- 标签窗口不进入任何 rolling feature；
- scaler/imputer/bin/spline/selector 只在训练 block fit；
- 24 小时重叠 purge、embargo、event isolation；
- 每条预测含 as-of 时间、round、seed、block、config；
- random block schedule 在结果前冻结；
- 已观察 block 不得再次选择；
- Confirmation 行读取数为 0；
- unknown session 行数为 0；
- 单账户组合评估在选中信号后执行。

发现工程错误时，只允许最小修复和针对性测试；失败记录保留。长任务必须拆成可恢复的前台阶段和 checkpoints，每个命令尽量在 8 分钟内完成。禁止使用隐藏 `Start-Process` 或 detached Python；禁止重复完整重跑已经有有效 checkpoint 的阶段。

从仓库根目录使用 `python -m ...` 运行模块。启动器已设置 `PYTHONPATH`。

## 11. 评价和最终通过条件

至少报告：

- factor law 的线性系数和非线性形状；
- 三分类概率、Top5 lift；
- 触达耗时；
- 10/20bps 净收益、胜率、盈亏比、交易数、覆盖率、换手、MDD；
- 所有连续随机块和五种子；
- 去除最佳 1%/5%；
- 单个年份/session/block/ETF 的利润集中度；
- 被单账户 overlap 拒绝与接受信号的质量差异；
- 与 V22.080B 及最近 H2 比较。

最终 PASS 必须同时满足限制 JSON 的全部 gate，包括：Top5 lift ≥1.50、相对旧基准 lift 差值 CI 下界>0、10bps 随机块中位数>0、20bps 中位数≥0、至少 60% 随机块为正、至少 4/5 种子为正、去除最佳 1% 后仍为正、交易数充足、利润不集中、unknown session=0。

由于没有干净历史 holdout，即使全部通过，唯一允许的正向结论也是：

`PASS_READY_FOR_PROSPECTIVE_FORWARD_SHADOW`

不得声称历史 Frozen Validation 成功，不得连接实盘或生成订单。

## 12. 防膨胀硬限制

仓库源代码区最多新增：3 个代码文件、1 个测试文件、2 个配置/manifest 文件。结果文件不计入，但只能写在 `$FAST3_RESULTS_ROOT`。

禁止：新 V22 链、新 Atlas/Guard/Registry、嵌套 Runner、整仓重构、重复 summary、自动 Git 操作、修改外置 canonical。

## 13. 必须产物

全部写入 `$FAST3_RESULTS_ROOT`：

- `FAST3_EVIDENCE_LEDGER.json`
- `FAST3_EVENT_FACTOR_DISCOVERY_CONTRACT.json`
- `FAST3_SESSION_FACTOR_AUDIT.json`
- `FAST3_FACTOR_DICTIONARY.json`
- `fast3_event_ledger.parquet`
- `fast3_factor_linear_results.csv`
- `fast3_factor_nonlinear_results.csv`
- `fast3_random_time_block_results.csv`
- `fast3_event_predictions.parquet`
- `FAST3_ROUND_LEDGER.jsonl`
- `fast3_event_factor_summary.json`
- `FAST3_EVENT_FACTOR_REPORT.md`

仅有代码、测试、synthetic 或空表不算完成。

## 14. 允许的最终决定

只能使用：

- `PASS_READY_FOR_PROSPECTIVE_FORWARD_SHADOW`
- `STOP_NO_STABLE_FACTOR_LAWS`
- `STOP_NO_SIGNIFICANT_PREDICTIVE_GAIN`
- `STOP_NOT_ECONOMIC_AFTER_COST`
- `STOP_RANDOM_TIME_BLOCK_INSTABILITY`
- `STOP_DATA_CONTRACT_INVALID`
- `STOP_SEARCH_BUDGET_EXHAUSTED`
- `STOP_IMPLEMENTATION_INVALID`

## 15. 最终摘要

最终消息、summary 和报告必须给出：

- `FINAL_STATUS`, `FINAL_DECISION`
- `RUN_ID`
- `EVENT_COUNT`, `CONTROL_COUNT`, `AMBIGUOUS_COUNT`
- `SESSION_UNKNOWN_ROW_COUNT`
- `BASE_FACTOR_COUNT`, `DERIVED_FACTOR_COUNT`, `NINE_TURN_FACTOR_COUNT`, `INTERACTION_COUNT`
- `TRAINING_ROUND_COUNT`, `FINAL_AUDIT_ROUND_COUNT`, `TOTAL_CONFIG_COUNT`, `MODEL_FAMILY_COUNT`, `RANDOM_SEED_COUNT`
- `RETIRED_RANDOM_BLOCK_COUNT`
- `STABLE_LINEAR_FACTOR_COUNT`, `STABLE_NONLINEAR_FACTOR_COUNT`
- `BEST_MODEL_NAME`, `BEST_TOP5_LIFT`, `LEGACY_TOP5_LIFT`
- `LIFT_DELTA_CI_LOW`, `LIFT_DELTA_CI_HIGH`
- `MEDIAN_RANDOM_BLOCK_NET_10BPS`, `MEDIAN_RANDOM_BLOCK_NET_20BPS`
- `POSITIVE_RANDOM_BLOCK_RATIO_10BPS`, `POSITIVE_SEED_COUNT_10BPS`
- `TRIMMED_1PCT_NET_10BPS`, `ACCEPTED_TRADE_COUNT`, `MAX_DRAWDOWN`
- `DATA_LEAKAGE_TESTS_PASSED`, `CONFIRMATION_ROWS_READ`
- `NEW_CODE_FILE_COUNT`, `MODIFIED_FILE_COUNT`
- `REPORT_PATH`

现在开始：先只读审计和 session 门禁，再冻结完整合同与随机块日程，然后建立事件/对照库、因子规律、三轮以内训练、新鲜连续块测试，并在硬停止点结束。
