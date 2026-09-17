# FAST3 V22.082 有限多代自动推进授权

## 1. 目标与关键修正

新阶段：`V22.082_FAST3_BOUNDED_MULTIGENERATION_AUTOPILOT_R1`。

V22.081 已真实完成 50 个实验，并以 `FAIL_CONFIRMATION` 结束。该失败结论必须保留，不得覆盖或美化。V22.082 的关键改动是把“单代终止”与“全局终止”分开：

```text
单个候选失败 -> 淘汰候选，继续本代
本代 Validation 失败 -> 冻结本代，自动进入下一代
本代 Confirmation 失败 -> 冻结本代，自动归因并进入下一代
达到全局停止条件 -> 才创建 V22_082_GLOBAL_DONE.flag
```

用户授权 Agent 在项目范围内自主实现、测试、训练、随机时序回测、调整有限因子/模型/阈值、诊断失败并自动推进下一代，不需要逐步确认。所有研究仍然仅限本地研究，禁止任何真实或模拟券商订单。

## 2. 路径

- 代码仓库：`D:\us-tech-quant`
- 数据根目录：`D:\us-tech-quant-data`
- V22.081 冻结结果：`D:\us-tech-quant-results\fast3_v22_081_bounded_self_improvement`
- V22.082 结果目录：`D:\us-tech-quant-results\fast3_v22_082_multigeneration_autopilot`
- 运行预算：`autopilot_budget.json`

## 3. 不可变安全边界

始终保持：

```text
RESEARCH_ONLY=true
CANONICAL_DATA_WRITABLE=false
BROKER_ACTION_ALLOWED=false
PAPER_BROKER_ORDER_ALLOWED=false
ORDER_GENERATION_ALLOWED=false
OFFICIAL_ADOPTION_ALLOWED=false
REMOTE_PUSH_ALLOWED=false
```

禁止修改 canonical 数据、合成或插值 OHLC、使用未来数据、普通随机打散分钟样本、用 SOXX 收益乘三替代 SOXL/SOXS、反复打开同一留出集、针对单笔留出交易补丁、创建订单、访问券商执行、Git reset/clean/push/merge、伪造或选择性隐藏结果。

## 4. V22.081 的处理

必须审计 V22.081 的 summary、report、registry、champion、代码和时间切分。其 Validation 与 Confirmation 均标记为已消费，不得在 V22.082 中重开或据此直接调参。允许把 V22.081 用于高层失败分类，例如：

```text
CONFIRMATION_SIGN_REVERSAL
EXCESS_DRAWDOWN
REGIME_INSTABILITY
```

不得围绕 V22.081 Confirmation 的具体日期、交易或收益路径做定向参数补丁。只有在严格更晚的滚动时序中，已发生历史才可依法成为训练历史；否则仅作为已知诊断，不作为新留出证据。

## 5. 全局时间合同

在读取任何新的 V22.082 留出经济结果前，冻结并哈希全局 split schedule。优先采用严格时间顺序的扩展窗口：

```text
Generation 1: past Development -> embargo -> Validation 1 -> embargo -> Confirmation 1
Generation 2: expanded past -> embargo -> Validation 2 -> embargo -> Confirmation 2
...
```

每个 Validation/Confirmation 只能读取一次。某一代结束后，该留出集被标记 `CONSUMED=true`，不得重开。下一代必须使用预先声明的新的未见 outer fold。

如果数据跨度不足以支持预算中的代数，Agent 必须在经济结果读取前计算最大可辩护代数并写入 split schedule。未见 outer fold 耗尽时，应以 `INSUFFICIENT_UNTOUCHED_OUTER_FOLDS` 全局停止，不得伪造新数据。

## 6. 单代内部闭环

每一代允许在其 Development pool 中反复进行有限实验：

```text
随机连续 as-of 窗口
-> inner train
-> purge/embargo
-> inner OOS
-> 训练因子权重/紧凑模型
-> 真实 SOXL/SOXS 成本与延迟回测
-> 稳定性淘汰
-> 冻结本代冠军
-> 一次 Validation
-> 条件通过后一次 Confirmation
```

随机的是连续时间窗口起点、长度、固定种子、预声明成本/延迟情景和市场状态覆盖，不得随机打乱单条分钟样本。

## 7. 多代自动闭环

本代失败后必须：

1. 保存完整结果、合同哈希和失败原因；
2. 把当前 Validation/Confirmation 标记为已消费；
3. 分类失败；
4. 生成有限的下一代 mutation plan；
5. 选择 split schedule 中下一个未消费 outer fold；
6. 自动开始下一代；
7. 只在全局停止条件满足时停止总引擎。

失败分类至少支持：

```text
NO_DEVELOPMENT_EDGE
VALIDATION_SIGN_REVERSAL
CONFIRMATION_SIGN_REVERSAL
EXCESS_DRAWDOWN
COST_FRAGILITY
DELAY_FRAGILITY
REGIME_INSTABILITY
YEAR_CONCENTRATION
SESSION_CONCENTRATION
SEED_INSTABILITY
WEIGHT_INSTABILITY
TRADE_CONCENTRATION
DATA_OR_LINEAGE_BLOCKER
```

## 8. 下一代允许调整的范围

每次代际变异最多改变：

```text
1 个模型族
3 个超参数
2 个交易/概率阈值
1 个标签期限
1 个退出规则
```

允许根据失败类型：提高 NO_TRADE、加入硬回撤门禁、降低模型复杂度、删除不稳定因子、分离 Opportunity/Direction/Entry、加入可靠 PIT VIX 或 Regime 交互、调整预声明标签期限、加强校准、加强 20bps 与执行延迟耐受。

禁止一次推翻全部架构，禁止根据留出集中的特定日期或单笔交易做补丁。

## 9. 因子、模型与执行

最多 40 个活跃因子、5 个紧凑模型族、3 个活跃候选。优先：Logistic Regression、Elastic Net、受限深度树、受限 Random Forest、小型 HistGradientBoosting。禁止大型深度学习和无界搜索。

优先使用已有 PIT 因子：多尺度收益、动量/反转、MA/EMA/RSI/KDJ/BOLL、VWAP、成交量异常、波动率、回撤、压缩/扩张、跳空、盘前收益、Session、SOXX/QQQ 相对强弱、真实 SOXL/SOXS 路径。VIX 和成分股广度只有在本地时间戳与血缘可靠时使用。

正式候选至少压力测试：

```text
COST_BPS=5,10,20,30
DELAY_MINUTES=0,1,3,5
```

必须保留明确 `NO_TRADE` 动作。

## 10. 优化与硬门禁

禁止只优化累计收益。评分和门禁至少覆盖：10/20bps 成本后期望、中位时间窗口表现、概率校准、最大回撤、换手、随机种子/年份/Session/Regime 稳定性、权重漂移、交易集中度、复杂度、成本和延迟脆弱性。

最大回撤必须是预声明的硬门禁。类似 V22.081 的 46% 回撤不得仅因均值收益为正而被接受。具体门槛由 Agent 根据持有期限和现有研究合同在读取新留出结果前冻结并记录。

## 11. 固定全局预算

默认由一键启动器写入：

```text
MAX_GENERATIONS=6
EXPERIMENTS_PER_GENERATION=50
MAX_TOTAL_EXPERIMENTS=300
MAX_ACTIVE_CANDIDATES=3
MAX_MODEL_FAMILIES=5
MAX_ACTIVE_FEATURES=40
CONSECUTIVE_GENERATION_NO_IMPROVEMENT_STOP=3
SAME_CONFIRMATION_FAILURE_CLASS_STOP=3
```

实际总实验数不得超过 `min(MAX_TOTAL_EXPERIMENTS, MAX_GENERATIONS * EXPERIMENTS_PER_GENERATION)`。

## 12. 全局停止条件

只有下列条件之一满足，才允许创建 `V22_082_GLOBAL_DONE.flag`：

- 某代通过全部冻结门禁，仅获准零订单 Prospective Shadow；
- 达到最大代数；
- 达到全局实验上限；
- 连续 3 代没有外层实质改善；
- 连续 3 代出现相同的实质 Confirmation 失败类型；
- 没有可辩护的未见 outer fold；
- 所有授权紧凑模型族均形成稳定负面证据；
- 真实外部数据、登录或凭证硬阻塞使合法研究无法继续。

下列情况不是全局停止：单一候选失败、普通测试失败、当前代 Validation 失败、当前代 Confirmation 失败、单个 Codex 回合结束、实现 bug 修复、性能问题或序列化错误。必须保存 checkpoint 并继续。

## 13. 防止系统膨胀

禁止创建 V22.082A/B/C/R2/R3 或按实验复制代码。V22.082 核心实现原则上最多新增 4 个文件：主 Python、测试、紧凑配置、必要时一个执行 wrapper。所有代共享同一代码和注册表。

统一结果文件：

```text
autopilot_budget.json
split_schedule.json
generation_registry.jsonl
experiment_registry.jsonl
v22_082_global_checkpoint.json
latest_generation_summary.json
champion_config.json
v22_082_global_summary.json
v22_082_report.md
V22_082_GLOBAL_DONE.flag
```

不为每个实验创建目录或报告。最多保存三个候选模型文件；被淘汰模型只保留指标和配置记录。

## 14. 必须记录

实验注册表至少包含 generation_id、experiment_id、parent、seed、完整时间区间、合同哈希、模型与因子、阈值、成本/延迟、交易数、NO_TRADE率、净期望、中位收益、最大回撤、lift、校准、年份/Regime/Session/Seed/权重稳定性、集中度、失败原因和决策。

代际注册表至少包含 generation_id、parent_generation_id、outer_fold_id、mutation_reason、development结果、Validation读取次数与结果、Confirmation读取次数与结果、失败分类、相对上一代改善、holdout_consumed、next_generation_action。

## 15. 最终输出

全局 summary/report 必须如实输出：完成代数、总实验数、每代结果、最佳候选、全部已消费 holdout、全局停止原因、稳定性和成本/延迟结果，以及：

```text
PROSPECTIVE_SHADOW_ALLOWED
BROKER_ACTION_ALLOWED=false
PAPER_BROKER_ORDER_ALLOWED=false
ORDER_GENERATION_ALLOWED=false
OFFICIAL_ADOPTION_ALLOWED=false
```

任何测试、训练、回测、文件、指标或结论都不得编造。执行不足时保存 checkpoint、已完成内容和唯一下一步动作，不得假称完成。
