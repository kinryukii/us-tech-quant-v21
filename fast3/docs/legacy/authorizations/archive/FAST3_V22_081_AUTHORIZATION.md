# FAST3 V22.081 有限预算自我改进研究授权

## 1. 新阶段授权

这是一个新的、独立的 FAST3 研究阶段：

`V22.081_FAST3_BOUNDED_SELF_IMPROVEMENT_ENGINE_R1`

它不是已经关闭的 Generation 2、Generation 3、Generation 3R2 或 Generation 3R3 的续写。先前代际的终止结论必须保留，但不得据此拒绝执行本阶段。

已知起点：

```text
PRIOR_COMPLETED_STAGE=V22.080B
PRIOR_STATUS=PASS
PRIOR_DECISION=PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE
PRIOR_TOP5_LIFT=1.36122855
PRIOR_TOP5_NET_RETURN_10BPS=-0.001966
```

上述结果说明既有候选失败，不代表禁止研究新的、严格隔离的候选。

## 2. 目标

在不修改 canonical 数据、不使用未来信息、不触碰真实或模拟券商下单的前提下，建立并实际运行一个有限预算闭环：

```text
随机连续历史窗口抽取
-> 训练因子权重或紧凑模型
-> Development 内部时间外回测
-> 根据内部 OOS 结果有限调整
-> 再训练和再回测
-> 稳定性淘汰
-> 冻结冠军
-> 一次 Validation
-> 条件满足后一次 Confirmation
```

允许反复训练，但只允许从 Development 内部的时间外结果获得自适应反馈。

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

禁止：

- 修改、覆盖、插值、前向填充或合成 canonical OHLCV；
- 使用未来价格、未来标签、未来 VIX、未来成分股数据构造特征；
- 普通随机打散分钟样本；
- 用 Validation 或 Confirmation 反复调参；
- 只保留最好随机种子、最好年份或最好交易；
- 为了得到正收益降低成本、删除困难时期或修改冻结门禁；
- 创建券商订单、调用 Moomoo 下单接口或打开任何交易授权；
- 自动 push、merge、reset、clean 或重写 Git 历史；
- 伪造、推算、美化或选择性隐藏实验结果。

## 4. 数据与时间合同

代码根目录：`D:\us-tech-quant`

数据根目录：`D:\us-tech-quant-data`

结果根目录：`D:\us-tech-quant-results`

优先复用 canonical 六 ETF 24 小时分钟数据：QQQ、SOXX、TQQQ、SQQQ、SOXL、SOXS。

优先使用逻辑时间 `timestamp_et`（America/New_York）和辅助时间 `timestamp_utc`。任何标签窗口、特征窗口、执行延迟和交易价格必须明确基于时间戳。

在读取经济结果前冻结一次总时间合同：

```text
Development research pool
Embargo
Validation holdout
Embargo
Final Confirmation holdout
```

Development 内部允许进行多次随机连续窗口 nested walk-forward。每个内部实验仍必须满足：

```text
inner_train -> purge/embargo -> inner_oos
```

随机对象可以是训练起点、连续窗口长度、市场状态覆盖、固定随机种子、成本和延迟压力情景；不得随机打乱单条分钟样本。

## 5. 反复训练的正确范围

允许在 Development 内最多进行 50 个完整实验。每个实验可以：

- 重新抽取连续 as-of 时间窗口；
- 重新拟合因子权重；
- 调整有限数量的特征开关、正则化、模型复杂度和交易阈值；
- 根据 Development 内部 OOS 中位表现、稳定性和成本耐受性保留或淘汰候选；
- 将冠军、第二候选和第三候选保存在统一注册表中。

不得使用 Validation 或 Confirmation 指标继续修改同一阶段的因子权重、阈值、标签或交易规则。

当 Development 搜索结束后，只冻结一个冠军并打开 Validation 一次：

- Validation 通过：冻结全部合同，允许打开 Confirmation 一次；
- Validation 失败：本阶段结束，不得根据失败细节再次调参；
- Confirmation 通过：仅允许部署零订单 Prospective Shadow；
- Confirmation 失败：本阶段结束，不得再次修改并重开 Confirmation。

## 6. 模型和因子范围

优先复用已有 FAST3 特征与工具。允许的基础因子族：

- 多时间尺度收益、动量、反转；
- MA、EMA、RSI、KDJ、BOLL；
- VWAP 偏离、成交量异常、量价背离；
- 已实现波动率、最大回撤、波动压缩与扩张；
- 跳空、盘前累计收益、Session 和时间段；
- SOXX 相对 QQQ 强弱及相关性；
- SOXL、SOXS 真实可成交路径特征；
- VIX 水平、变化率、短中期动量、日内变化和波动状态；
- 仅在本地已有可靠 PIT 数据时使用 SOXX 成分股广度和权重股同步性。

禁止为了扩充数量引入无法证明 PIT、时间戳或数据血缘的新因子。默认最多 40 个活跃特征。

优先模型：

- Logistic Regression；
- Elastic Net；
- 受限深度 Decision Tree；
- 受限深度 Random Forest；
- 小型 HistGradientBoosting。

最多五个模型族。禁止大型深度学习和无边界超参数搜索。

优先实现三个输出：Opportunity、Direction、Entry；如现有数据合同不足以可靠拆分，可先实现一个紧凑两阶段模型，但必须保留 `NO_TRADE`。

## 7. 实验预算和复杂度限制

硬上限：

```text
MAX_COMPLETE_EXPERIMENTS=50
MAX_MODEL_FAMILIES=5
MAX_ACTIVE_FEATURES=40
MAX_ACTIVE_CANDIDATES=3
MAX_PARAMETER_CONFIGS=200
MAX_REPOSITORY_FILES_FOR_STAGE=6
```

仓库中本阶段原则上只允许：

1. 一个主 Python 程序；
2. 一个测试文件；
3. 一个 PowerShell Runner；
4. 一个紧凑配置文件；
5. 一个状态或合同文件；
6. 必要时一个零订单 shadow runner。

不得每轮新增脚本、版本目录、报告文件或备份文件。修复当前主文件，不得创建 V22.081A/B/C、R2/R3 等无必要变体。

结果统一写入：

`D:\us-tech-quant-results\fast3_v22_081_bounded_self_improvement`

统一注册表使用一个 `experiment_registry.jsonl` 或 `experiment_registry.parquet`。仅保存基准模型和前三名候选的模型文件；其他候选只保留配置与指标行。

## 8. 每轮实验必须记录

至少记录：

```text
experiment_id
parent_experiment_id
created_at
random_seed
train_start
train_end
embargo_start
embargo_end
oos_start
oos_end
label_contract_hash
feature_contract_hash
model_contract_hash
feature_count
model_type
factor_weights_or_importance
thresholds
cost_bps
delay_minutes
trade_count
no_trade_rate
net_expectancy
median_net_return
max_drawdown
top_signal_lift
calibration_score
year_stability
regime_stability
seed_stability
concentration
selection_source
failure_reason
decision
```

所有失败实验也必须登记。

## 9. 优化与淘汰

禁止只优化累计收益。候选评分至少综合：

- 10bps 成本后期望；
- 20bps 压力结果；
- 多个连续时间窗口的中位表现；
- Top 信号 lift；
- 概率校准；
- 最大回撤；
- 换手与交易次数；
- 年份、Session、Regime 和随机种子稳定性；
- 权重方向稳定性；
- 收益是否集中在少数交易；
- 模型复杂度惩罚。

每次候选变异最多改变：一个模型类别、三个超参数、两个交易阈值和一个退出规则。一次不得大规模同时改变全部合同。

最多保留三名活跃候选。连续 15 个完整实验没有 Development 内部 OOS 实质改善时停止搜索。

## 10. 成本和执行压力测试

正式候选至少测试：

```text
COST_BPS = 5, 10, 20, 30
DELAY_MINUTES = 0, 1, 3, 5
```

必须使用真实 SOXL/SOXS OHLC。不得用 SOXX 收益乘三代替。

## 11. Validation 和 Confirmation 门禁

冻结冠军打开 Validation 前，必须保存全部合同 SHA256 和 `VALIDATION_READ_COUNT=0`。

Validation 至少要求：

- 10bps 成本后整体期望为正；
- 多数预声明时间子窗口为正；
- 20bps 下没有完全崩溃；
- 结果不依赖单一年份、单一随机种子或少于 5% 的交易；
- 最大回撤和权重漂移在预声明范围内；
- 泄漏测试、执行映射测试和输出合同测试全部通过。

Validation 通过后，冻结并只读取 Confirmation 一次。Confirmation 失败后不得回到调参循环。

## 12. 合法停止条件

满足任一条件即可结束：

- 达到 50 个完整实验；
- 连续 15 个实验无实质改善；
- 所有候选在 10bps 下稳定为负；
- 结果只在单一年份、单一随机种子或极少交易中有效；
- 权重方向频繁反转；
- Validation 一次性失败；
- Confirmation 一次性失败；
- Confirmation 通过并完成零订单 shadow；
- Codex 使用额度或本机计算资源耗尽；
- 出现确实需要用户登录、凭证或缺失数据的外部硬阻塞。

单次 Codex 回合结束、普通测试失败、性能问题、路径错误、序列化错误或某一个候选失败，都不是整阶段停止条件。必须保存检查点，让下一回合继续。

## 13. 最终输出

统一结果目录中至少生成：

```text
v22_081_status.json
v22_081_checkpoint.json
experiment_registry.jsonl
champion_config.json
v22_081_summary.json
v22_081_report.md
V22_081_DONE.flag
```

`V22_081_DONE.flag` 只能在本阶段真正达到合法停止条件且最终文件已验证后创建。

最终摘要必须包括：

```text
FINAL_STATUS
FINAL_DECISION
STOP_REASON
EXPERIMENT_COUNT
BEST_MODEL_TYPE
BEST_FEATURE_COUNT
BEST_FEATURES
BEST_FACTOR_WEIGHTS
BEST_THRESHOLDS
DEVELOPMENT_OOS_METRICS
VALIDATION_READ_COUNT
VALIDATION_RESULT
CONFIRMATION_READ_COUNT
CONFIRMATION_RESULT
MEDIAN_NET_RETURN_10BPS
MEDIAN_NET_RETURN_20BPS
MAX_DRAWDOWN
TOP_SIGNAL_LIFT
TRADE_COUNT
NO_TRADE_RATE
SEED_STABILITY
REGIME_STABILITY
WEIGHT_STABILITY
PAPER_SHADOW_ALLOWED
BROKER_ACTION_ALLOWED
OFFICIAL_ADOPTION_ALLOWED
RESULT_DIRECTORY
SUMMARY_PATH
RECOMMENDED_NEXT_COMMAND
```

测试通过只代表实现通过，不代表策略盈利。任何负面或不确定结论必须原样报告。
