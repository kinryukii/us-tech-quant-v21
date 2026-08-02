# FAST3 全流程自主开发与部署总指令

你负责从当前仓库状态开始，连续完成 FAST3 的全部研究开发流程。

不要只完成一个中间版本后停止，不要在每个阶段结束后请求用户确认。必须按照预先冻结的门禁自动向下推进：

```text
V22.080A 历史机会 Atlas
→ V22.080B 可预测性研究
→ V22.080C 冻结策略与 Confirmation
→ V22.080D Prospective Shadow 部署
```

执行原则：

```text
上游门禁通过 → 自动进入下一阶段
上游门禁失败 → 如实停止 FAST3，不得为了继续而降低标准
代码或测试失败 → 修复并重跑，不得只报告“尚未完成”
外部不可恢复阻塞 → 报告真实阻塞、退出码和已完成范围
```

本任务的目标不是强制得到正面策略结论，而是完成 FAST3 的完整研究链，并得到以下两类最终结果之一：

```text
A. FAST3 未发现稳定、经济上可执行的预测优势，研究线正式停止
B. FAST3 通过 Atlas、Validation 和 Confirmation，完成前向影子系统部署
```

Prospective Shadow 需要未来数据积累，因此本次能够完成的是：

```text
完成 V22.080D 代码、冻结合同、每日独立 Runner、状态存储、首次初始化和烟雾运行
```

不能在没有未来样本时声称 Prospective Shadow 已经验证通过。

---

# 一、项目环境

仓库：

```text
D:\us-tech-quant
```

数据根目录：

```text
D:\us-tech-quant-data
```

正式结果根目录：

```text
D:\us-tech-quant-results
```

本地结果目录：

```text
D:\us-tech-quant\.local_results
```

当前分支：

```text
checkpoint/v22-078a-24h-event-entry-strategy-20260731
```

已知提交：

```text
commit  = f388fb7
message = Add V22.079A FAST3 strategy family failure attribution
```

V22.079A 位于名称仍含 V22.078A 的分支上，不需要重写。

当前已存在但尚未完成的文件：

```text
scripts/v22/v22_080a_fast3_24h_one_percent_move_atlas_r1.py
scripts/v22/test_v22_080a_fast3_24h_one_percent_move_atlas_r1.py
scripts/v22/run_v22_080a_fast3_24h_one_percent_move_atlas_r1.ps1
```

必须优先检查并继续这些文件，不能重新创建另一套 V22.080A。

开始时搜索：

```text
TODO
pass
NotImplementedError
placeholder
dummy
return None
空 DataFrame 占位
未调用函数
未完成 summary 字段
```

发现后直接补完。

---

# 二、FAST3 的真实目标

FAST3 的原始目标是：

> 在 QQQ 和 SOXX 的全天 24 小时分钟行情中，识别可能发生的约 1% 上涨或下跌方向运动，并通过 TQQQ、SQQQ、SOXL、SOXS 的真实分钟价格，研究是否能够获得接近 3% 的实际交易收益。

固定映射：

```text
QQQ 上涨  → TQQQ
QQQ 下跌  → SQQQ
SOXX 上涨 → SOXL
SOXX 下跌 → SOXS
```

必须明确：

```text
基础指数上涨或下跌约 1%
不等于三倍 ETF 一定获得 3%
```

必须计入：

```text
识别延迟
实际入场价
实际退出价
ETF 跟踪误差
杠杆路径效应
反向 ETF 结构
买卖价差
滑点
扩展时段流动性
时间戳不同步
交易成本
```

严禁使用：

```text
leveraged_return = underlying_return × 3
```

必须使用真实 ETF OHLC。

FAST3 也不代表每天保证获利 3%。真实策略必须允许：

```text
NO_TRADE
```

---

# 三、旧研究的定位

V22.065～V22.079 已研究过：

```text
盘前 Gap
盘前趋势延续
SOXL 和 UP_GAP_STRONG 子群
09:45 确认入场
跨 Session 趋势延续
预定义事件后的追涨或追跌
紧凑线性模型
非线性结构诊断
策略族失败归因
```

已知结果包括：

```text
Validation AUC ≈ 0.4209
Top 20% return ≈ -0.0000244
FINAL_DECISION=STOP_CURRENT_FAST3_DIRECTION
```

这些结果只否定旧的错误实现方向，不能否定 FAST3 的原始目标。

禁止继续：

```text
修改 09:45 为其他相邻时间
继续扫描盘前 Gap 阈值
继续搜索类似突破阈值
大规模止盈止损网格
大规模持有期网格
给旧趋势信号增加一个条件并重新命名
```

可复用：

```text
canonical 数据
时间合同
PIT 与无泄漏框架
Confirmation 隔离
lineage
summary
CSV 与 Markdown 输出
pytest
PowerShell Runner
安全门禁
```

---

# 四、数据合同

Canonical 路径已确认：

```text
D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical\symbol=<SYMBOL>\year=<YYYY>\month=<MM>\data.parquet
```

六个标的：

```text
QQQ
SOXX
TQQQ
SQQQ
SOXL
SOXS
```

字段：

```text
timestamp_et
timestamp_utc
broker_trade_date
session
open
high
low
close
volume
```

时间合同：

```text
logical timestamp column = timestamp_et
logical timezone         = America/New_York
secondary timestamp      = timestamp_utc
```

禁止重新下载、重新转换或复制完整 canonical 数据。

每个阶段运行时必须审计：

```text
路径
分区数
行数
日期范围
必要字段
重复时间戳
时间单调性
OHLC 合法性
session 枚举
```

缺失状态必须明确区分：

```text
真实为零
没有样本
文件缺失
字段缺失
无法计算
```

使用：

```text
SOURCE_DATA_MISSING
NOT_AVAILABLE
NOT_COMPUTABLE
INSUFFICIENT_SAMPLE
```

不得用 0、空字符串或 False 伪装未知值。

---

# 五、全流程安全合同

在整个 FAST3 研究链中固定：

```text
BROKER_ACTION_ALLOWED=false
PAPER_TRADING_ALLOWED=false
OFFICIAL_ADOPTION_ALLOWED=false
ORDER_GENERATION_ALLOWED=false
```

禁止：

```text
调用 broker 下单接口
生成可执行订单
自动修改每日 V22.044 研究链
声称可以稳定每天赚 3%
```

Prospective Shadow 也只能生成不可执行的研究记录，不能生成订单对象。

---

# 六、版本与文件控制

允许建立四个正式阶段：

```text
V22.080A_FAST3_24H_ONE_PERCENT_MOVE_ATLAS_R1
V22.080B_FAST3_ONE_PERCENT_MOVE_PREDICTABILITY_PREFLIGHT_R1
V22.080C_FAST3_FROZEN_STRATEGY_CONFIRMATION_R1
V22.080D_FAST3_PROSPECTIVE_SHADOW_R1
```

每个阶段最多创建：

```text
1 个 Python 主程序
1 个 pytest 文件
1 个 PowerShell Runner
```

不要建立：

```text
V22.080A0
V22.080A1
V22.080B0
临时修复版本
大量重复审计版本
```

非必要辅助函数优先放在对应主程序内，或复用已有稳定工具。

不要复制大型输入，不提交生成结果和模型二进制到 Git。

---

# 七、执行策略

Agent 必须连续工作：

```text
检查当前代码
→ 补完
→ py_compile
→ pytest
→ 修复
→ 重跑
→ 全量 Runner
→ 读取 summary
→ 根据门禁自动进入下一阶段
```

普通错误不能作为停止理由：

```text
列名错误
fixture 错误
类型错误
JSON 序列化错误
路径错误
PowerShell 输出错误
首次 pytest 失败
首次 Runner 失败
```

这些必须修复后重跑。

开发优先级：

```text
核心研究逻辑
→ 正确输出
→ 测试
→ 全量运行
→ 报告
→ 排版
```

报告排版不得阻塞研究执行。

---

# 八、V22.080A：24H 1% Move Atlas

## 8.1 目标

回答：

```text
历史上是否存在足够多的 1% 方向运动？
这些运动持续多久、出现在哪些 Session？
延迟后还剩多少收益？
真实三倍 ETF 可以捕捉多少？
是否值得进入预测研究？
```

V22.080A 不训练模型，不生成信号。

## 8.2 Historical Move Atlas

标签只建立在：

```text
QQQ
SOXX
```

按 `timestamp_et` 排序，使用固定、非重叠 directional-change 状态机。

维护：

```text
running_low
running_low_timestamp
running_high
running_high_timestamp
```

障碍：

```text
up_target   = running_low × 1.01
down_target = running_high × 0.99
```

上涨事件：

```text
high 第一次触及 up_target
direction=UP
start=running_low
target=第一次触及 +1% 的分钟
```

下跌事件：

```text
low 第一次触及 down_target
direction=DOWN
start=running_high
target=第一次触及 -1% 的分钟
```

完成一个事件后，从目标 bar 的下一根 bar 重新开始搜索，避免同方向重复重叠事件。

如果同一分钟同时可能触及上下目标：

```text
AMBIGUOUS_INTRABAR_ORDER
```

该记录进入审计，不进入主要延迟和 ETF 映射统计。

禁止：

```text
自由搜索整段未来的完美低点和高点
使用最终最高价或最低价作为终点
将历史起点称为实时可交易入场点
```

事件起点标记：

```text
start_type=EX_POST_MOVE_START
```

## 8.3 事件字段

输出：

```text
v22_080a_move_event_catalog.csv
```

至少包含：

```text
event_id
underlying_symbol
direction
start_type
start_timestamp_et
start_timestamp_utc
start_price
target_timestamp_et
target_timestamp_utc
target_price
duration_minutes
start_session
target_session
cross_session_flag
underlying_mfe
underlying_mae_before_target
calendar_date_et
year
month
ambiguity_status
data_quality_status
```

统一方向：

```text
MFE 为正
MAE 为负
```

## 8.4 Session

复用 canonical `session`，归一为：

```text
OVERNIGHT
PREMARKET
REGULAR_TRADING_HOURS
AFTER_HOURS
UNKNOWN_SESSION
```

记录起点 Session、目标 Session 和跨 Session 状态。

## 8.5 延迟

评估：

```text
0
1
3
5
10
15
```

分钟。

延迟入场：

```text
desired_time = ex_post_start + latency
entry = desired_time 之后第一根有效基础指数 bar 的 open
```

若该 bar 晚于目标触及时间：

```text
TARGET_ALREADY_REACHED_BEFORE_DELAY
```

输出：

```text
event_id
latency_minutes
delayed_entry_timestamp_et
delayed_entry_price
remaining_underlying_return
remaining_time_to_target_minutes
delayed_underlying_mfe
delayed_underlying_mae
latency_mapping_status
```

## 8.6 三倍 ETF 映射

固定映射：

```text
QQQ UP    → TQQQ
QQQ DOWN  → SQQQ
SOXX UP   → SOXL
SOXX DOWN → SOXS
```

ETF 入场匹配：

```text
完全相同 timestamp
否则时间差不超过 1 分钟的第一根有效 bar
否则失败
```

ETF 入场价格：

```text
matched ETF bar open
```

ETF 退出：

```text
基础指数 target_timestamp 之后第一根有效 ETF bar open
最大允许偏差 1 分钟
```

状态：

```text
SUCCESS
ENTRY_TIMESTAMP_MISMATCH
EXIT_TIMESTAMP_MISMATCH
MISSING_LEVERAGED_DATA
INVALID_ENTRY_PRICE
INVALID_EXIT_PRICE
NOT_COMPUTABLE
```

收益：

```text
gross_return = exit_price / entry_price - 1
net_return_0bps  = gross_return
net_return_10bps = gross_return - 0.001
net_return_20bps = gross_return - 0.002
```

路径：

```text
leveraged_mfe
leveraged_mae
hit_2pct
hit_2_5pct
hit_3pct
time_to_2pct_minutes
time_to_2_5pct_minutes
time_to_3pct_minutes
```

## 8.7 080A 门禁

预先固定：

```text
minimum_total_events = 500
minimum_events_per_underlying_direction = 100
minimum_leveraged_mapping_success_rate = 0.98
primary_latency_minutes = 3
minimum_etf_2pct_hit_rate = 0.15
minimum_etf_3pct_hit_rate = 0.05
```

判断顺序：

```text
数据合同失败
→ SOURCE_DATA_CONTRACT_INCOMPLETE

样本不足
→ INSUFFICIENT_INDEPENDENT_MOVE_SAMPLE

ETF 映射成功率不足
→ LEVERAGED_MAPPING_CONTRACT_INCOMPLETE

3 分钟延迟下：
2%触及率 <15% 或 3%触及率 <5%
→ INSUFFICIENT_POST_LATENCY_CAPTURE_OPPORTUNITY

全部通过
→ SUFFICIENT_24H_MOVE_OPPORTUNITY_FOR_PREDICTABILITY_RESEARCH
```

如果不通过，停止整个 FAST3 下游研究，输出最终负面结论，不得强行进入 080B。

## 8.8 080A 输出

```text
v22_080a_summary.json
v22_080a_move_event_catalog.csv
v22_080a_session_distribution.csv
v22_080a_latency_capture.csv
v22_080a_underlying_to_leveraged_mapping.csv
v22_080a_year_stability.csv
v22_080a_zero_and_missing_diagnostic.csv
v22_080a_report.md
```

---

# 九、V22.080B：Predictability Preflight

仅在 080A 通过时自动开始。

## 9.1 目标

回答：

> 在不知道未来结果的情况下，候选时间点之前的信息是否能够稳定区分未来哪一侧 1% 先到达，并产生正的真实 ETF 成本后期望收益？

## 9.2 Decision Candidate Atlas

在 QQQ 和 SOXX 上建立固定 5 分钟网格：

```text
minute % 5 == 0
```

当前分钟必须已经完整结束。

候选参考入场：

```text
下一有效分钟 open
```

未来最多 24 个自然小时设置对称障碍：

```text
upper = entry_price × 1.01
lower = entry_price × 0.99
```

标签：

```text
UP_1PCT_FIRST
DOWN_1PCT_FIRST
NO_1PCT_MOVE_WITHIN_HORIZON
AMBIGUOUS_BOTH_TOUCHED_SAME_BAR
```

构建方向化样本：

```text
每个 candidate 分别产生 UP 和 DOWN 两个方向研究行
```

标签：

```text
direction 对应的一侧先到达 → target_first=1
另一侧先到或未达到目标 → target_first=0
AMBIGUOUS → 排除并审计
```

每行映射到对应真实三倍 ETF。

## 9.3 严格时间切分

按日期顺序切分，不允许随机切分。

只使用 unique broker_trade_date 或 ET 日期确定边界，不查看收益结果。

建议：

```text
Development = 最早 60%
Validation  = 接下来的 20%
Confirmation= 最后的 20%
```

在相邻 split 之间加入至少：

```text
5 个交易日 embargo
```

或不短于最大 24 小时标签窗口的隔离。

同一天和高度重叠窗口不得跨 split。

080B 只能读取：

```text
Development
Validation
```

必须保持：

```text
CONFIRMATION_ROW_READ_COUNT=0
```

Confirmation 数据必须由独立加载入口隔离。

## 9.4 特征时间约束

所有特征必须满足：

```text
feature_timestamp <= decision_timestamp
```

严禁：

```text
未来最高价
未来最低价
目标触及时间
实际持续时间
未来成交量
未来波动率
未来 Session
任何由最终结果产生的字段
```

## 9.5 特征族

控制在紧凑、可解释的范围内。

### Noise Area 与相同时刻异常程度

```text
return_from_session_start
same_time_historical_return_percentile
distance_above_noise_boundary
distance_below_noise_boundary
same_time_range_zscore
```

历史基准只能使用候选时点之前的数据。

### ORB，仅限 RTH

固定使用 15 分钟 Opening Range，不进行窗口网格搜索：

```text
distance_to_opening_range_high
distance_to_opening_range_low
opening_range_width
opening_range_volume
```

### VWAP

```text
vwap_distance
vwap_slope
minutes_above_vwap
minutes_below_vwap
vwap_reclaim_state
pullback_depth
```

### 波动率与成交量

```text
realized_vol_5m
realized_vol_15m
realized_vol_30m
realized_vol_60m
volatility_expansion
relative_volume
volume_acceleration
target_difficulty
```

### 多周期动量

```text
return_5m
return_15m
return_30m
return_60m
momentum_consistency
recent_acceleration
range_position
```

### 六 ETF 联动

```text
QQQ_SOXX_direction_agreement
TQQQ_QQQ_leverage_deviation
SOXL_SOXX_leverage_deviation
long_inverse_direction_agreement
cross_asset_relative_strength
```

所有 rolling scaler、分位数、边界和缺失值规则只能在 Development 拟合。

## 9.6 模型

先建立基准：

```text
unconditional baseline
session-only
symbol-only
direction-only
volatility-only
logistic regression
```

允许的非线性模型：

```text
GAM-like spline + logistic regression
DecisionTreeClassifier(max_depth <= 3)
小型 Gradient Boosting / HistGradientBoosting
```

优先使用仓库已有依赖。

禁止：

```text
LSTM
Transformer
大型神经网络
大规模自动调参
贝叶斯超参数搜索
```

超参数候选必须在运行前固定为一个很小的集合。

模型和阈值选择只能使用 Development。

Validation 只做独立验证，不反复调整。

## 9.7 经济标签与评价

对每个方向候选使用对应真实 ETF 的：

```text
next-bar open 入场
+3%目标
不利路径
24小时超时
10bps round-trip 主成本
20bps 压力成本
```

080B 主指标：

```text
TargetFirstRate
Lift over unconditional baseline
Precision at top 1%
Precision at top 5%
Precision at top 10%
ETF net expectancy at 10bps
ETF net expectancy at 20bps
Brier score
Calibration
No-trade rate
year stability
session stability
symbol stability
profit concentration
```

AUC 仅作为辅助指标。

## 9.8 080B 通过门禁

Validation 必须同时满足：

```text
top_5pct_selected_count >= 100
top_5pct_target_first_lift >= 1.50
top_5pct_mean_net_return_10bps > 0
top_5pct_mean_net_return_20bps > 0
至少 3 个独立年份或年度分组方向一致
单一 execution ETF 利润贡献 < 70%
Top 5 笔交易利润贡献 < 25%
不存在关键特征在 Development 与 Validation 明显方向反转
```

如果样本覆盖不足，应返回：

```text
INSUFFICIENT_VALIDATION_SAMPLE
```

如果预测可分但经济上不可执行：

```text
PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE
```

如果收益过度集中：

```text
EDGE_TOO_CONCENTRATED_FOR_FREEZE
```

只有全部通过：

```text
PREDICTABILITY_VALIDATED_FOR_FROZEN_CONFIRMATION
```

才进入 080C。

## 9.9 080B 输出

```text
v22_080b_summary.json
v22_080b_split_contract.json
v22_080b_candidate_label_audit.csv
v22_080b_feature_contract.json
v22_080b_baseline_results.csv
v22_080b_model_results.csv
v22_080b_validation_topk.csv
v22_080b_calibration.csv
v22_080b_stability.csv
v22_080b_concentration.csv
v22_080b_zero_and_missing_diagnostic.csv
v22_080b_report.md
```

不要输出大型特征矩阵副本，除非现有仓库惯例明确要求小型索引清单。

---

# 十、V22.080C：Frozen Strategy Confirmation

仅在 080B 通过时自动开始。

## 10.1 冻结合同

冻结以下全部内容：

```text
candidate grid
feature list
feature transformations
missing-value handling
model class
hyperparameters
calibration method
probability threshold
expected-return threshold
underlying-to-ETF mapping
entry delay
entry price convention
profit target
stop loss
maximum holding period
cost assumption
selection priority
overlap handling
```

生成：

```text
v22_080c_frozen_contract.json
```

计算 SHA256，并在所有输出中引用。

冻结后不得修改。

## 10.2 退出合同

FAST3 主目标固定：

```text
ETF profit target = +3%
maximum holding horizon = 24 natural hours
```

止损不做大规模网格搜索。

使用 Development 成功目标事件的：

```text
MAE_BEFORE_TARGET 分布
```

确定止损：

```text
stop = 成功事件 MAE 的预定义分位数
```

建议固定使用 80% 覆盖分位，并裁剪到：

```text
0.75% 至 1.50%
```

该规则和裁剪范围必须在读取 Confirmation 前冻结。

如果数据无法支持该估计，返回：

```text
STOP_CONTRACT_NOT_ESTIMABLE
```

## 10.3 信号与持仓约束

每 5 分钟评估一次。

固定：

```text
同一时刻比较 QQQ-UP、QQQ-DOWN、SOXX-UP、SOXX-DOWN
仅选择预期净收益最高且超过阈值的一个候选
最多一个并发持仓
已有持仓时不新开仓
目标、止损或24小时超时退出
```

不得根据 Confirmation 调整阈值。

## 10.4 模型最终拟合

冻结模型结构、超参数和阈值后，可在：

```text
Development + Validation
```

上重新拟合一次。

然后加载 Confirmation。

在冻结完成前：

```text
CONFIRMATION_ROW_READ_COUNT=0
```

Confirmation 只允许正式评价一次。

## 10.5 Confirmation 评价

必须使用真实 ETF OHLC 和固定：

```text
10bps round-trip 主成本
20bps round-trip 压力成本
1/3/5分钟延迟敏感性
```

评价：

```text
trade_count
target_first_rate
stop_first_rate
timeout_rate
mean_net_return
median_net_return
profit_factor
win_rate
max_drawdown
CVaR_95
longest_loss_streak
annualized opportunity frequency
symbol attribution
session attribution
year attribution
Top5 profit concentration
single-symbol concentration
delay sensitivity
```

置信区间和 bootstrap 必须按交易日或 move family 分组，不能把相邻分钟候选当作独立样本。

## 10.6 080C 通过门禁

预先固定：

```text
confirmation_trade_count >= 75
mean_net_return_10bps > 0
mean_net_return_20bps > 0
profit_factor_10bps >= 1.20
target_first_rate > unconditional_selected_baseline
maximum_drawdown <= 25%
single_etf_profit_contribution < 70%
top5_profit_concentration < 25%
至少两个 execution ETF 具有非负成本后期望
1分钟和3分钟额外延迟后期望不发生完全反转
```

建议同时报告按日 block bootstrap 的 95% CI。

如果 CI 下界不为正，不必自动否决，但必须标记：

```text
STATISTICAL_CONFIDENCE_WEAK
```

不得隐瞒。

允许最终决策：

```text
CONFIRMATION_ACCEPTED_FOR_PROSPECTIVE_SHADOW
CONFIRMATION_REJECTED_NEGATIVE_EXPECTANCY
CONFIRMATION_REJECTED_COST_SENSITIVITY
CONFIRMATION_REJECTED_CONCENTRATION
CONFIRMATION_REJECTED_INSUFFICIENT_SAMPLE
```

只有第一种进入 080D。

## 10.7 080C 输出

```text
v22_080c_summary.json
v22_080c_frozen_contract.json
v22_080c_frozen_contract_sha256.txt
v22_080c_confirmation_trades.csv
v22_080c_confirmation_metrics.csv
v22_080c_cost_sensitivity.csv
v22_080c_delay_sensitivity.csv
v22_080c_stability.csv
v22_080c_concentration.csv
v22_080c_zero_and_missing_diagnostic.csv
v22_080c_report.md
```

模型文件只在确有必要时保存一个小型序列化文件，并记录 SHA256。不得保存重复模型。

---

# 十一、V22.080D：Prospective Shadow 部署

仅在 080C 通过时自动开始。

## 11.1 目标

部署一个独立、幂等、零订单的前向影子系统。

它必须：

```text
读取最新 canonical 数据
加载冻结合同和冻结模型
只计算当前及过去尚未处理的决策时点
生成不可执行的 shadow decision
跟踪 pending shadow positions
在未来数据到达后结算结果
不修改模型
不调整阈值
不重写历史记录
```

## 11.2 独立入口

创建：

```text
scripts/v22/v22_080d_fast3_prospective_shadow_r1.py
scripts/v22/test_v22_080d_fast3_prospective_shadow_r1.py
scripts/v22/run_v22_080d_fast3_prospective_shadow_r1.ps1
```

不得自动接入或修改 V22.044 每日链。

Runner 必须可以单独手动运行。

## 11.3 状态与幂等

状态目录必须保存：

```text
last_processed_timestamp
frozen_contract_sha256
model_sha256
shadow_signal ledger
pending_position ledger
matured_trade ledger
daily summary
```

重复运行同一数据：

```text
不得重复生成同一 shadow signal
不得重复结算同一 shadow trade
输出必须确定且幂等
```

## 11.4 Shadow 输出

每个决策记录：

```text
decision_timestamp_et
underlying
direction
execution_etf
model_probability
expected_net_return
threshold_passed
shadow_action
reason
frozen_contract_sha256
```

`shadow_action` 只允许：

```text
SHADOW_ENTER
NO_TRADE
SHADOW_HOLD
SHADOW_EXIT_TARGET
SHADOW_EXIT_STOP
SHADOW_EXIT_TIMEOUT
```

这些是研究状态，不是订单。

严禁输出 broker order schema。

## 11.5 080D 初始部署结论

本次运行只能在系统成功部署、烟雾测试和首次初始化后输出：

```text
PROSPECTIVE_SHADOW_DEPLOYED_AWAITING_SAMPLE
```

不得输出：

```text
PROSPECTIVE_SHADOW_VALIDATED
OFFICIAL_ADOPTION_ALLOWED
READY_FOR_LIVE_TRADING
```

## 11.6 未来正式 Shadow 门禁

将以下门禁写入冻结评估合同，但本次不伪造其完成：

```text
minimum_calendar_days = 60
minimum_matured_shadow_trades = 100
mean_net_return_10bps > 0
mean_net_return_20bps > 0
profit_factor_10bps >= 1.20
single_etf_profit_contribution < 70%
top5_profit_concentration < 25%
no frozen-contract hash mismatch
no retrospective model modification
```

未积累足够未来样本时：

```text
OFFICIAL_ADOPTION_ALLOWED=false
```

## 11.7 080D 输出

```text
v22_080d_summary.json
v22_080d_shadow_decisions.csv
v22_080d_pending_positions.csv
v22_080d_matured_trades.csv
v22_080d_daily_metrics.csv
v22_080d_state.json
v22_080d_zero_and_missing_diagnostic.csv
v22_080d_report.md
```

---

# 十二、每阶段测试和 Runner

每阶段保持约 10～20 个高价值测试，不创建大量重复测试。

共同测试：

```text
时间戳和时区
输入字段
确定性
重复运行幂等
缺失值语义
安全字段
Confirmation 隔离
不生成订单
```

080A 额外测试：

```text
上涨事件
下跌事件
第一次触及
事件重置
同 bar 歧义
六种延迟
四种 ETF 映射
时间偏差
ETF 目标触及时间
```

080B 额外测试：

```text
5分钟候选网格
first-passage 标签
同 bar 双障碍
24小时 horizon
特征时间不晚于候选时间
rolling 统计仅使用过去
split embargo
Confirmation 零读取
```

080C 额外测试：

```text
冻结合同哈希
冻结后不可修改
Confirmation 只读取一次
真实交易仿真
目标/止损/超时顺序
同 bar 目标止损歧义保守处理
成本和延迟
```

080D 额外测试：

```text
状态恢复
重复运行不重复信号
pending 到 matured
模型和合同 hash 一致
无 broker action
无订单对象
```

每个 Runner 必须：

```text
py_compile
targeted pytest
清理当前阶段旧结果
全量实际运行
读取 summary
打印关键字段
返回真实 exit code
```

---

# 十三、性能要求

数据规模为多年 24 小时分钟数据。

要求：

```text
按 QQQ 组和 SOXX 组处理
使用 NumPy 数组或顺序索引
使用 searchsorted 或 timestamp index
避免 DataFrame.iterrows()
避免每个候选重复扫描完整未来历史
避免每个延迟重新读取 Parquet
避免大型 DataFrame 重复复制
```

可以使用高效的批量 future-barrier 算法、双指针或预计算索引。

禁止：

```text
静默抽样
只运行部分年份
跳过扩展时段
只运行部分标的却声称全量
```

如果性能不足，优化实现，不得修改研究定义。

---

# 十四、Git 和结果管理

每个通过的阶段可建立一个本地 checkpoint commit：

```text
V22.080A complete
V22.080B complete
V22.080C complete
V22.080D deployed
```

仅提交：

```text
Python
pytest
PowerShell Runner
必要小型合同文件
```

不要提交：

```text
canonical 数据
大型 CSV 结果
.local_results
模型训练缓存
临时 profiler 输出
备份文件
```

不要执行远程 push，除非当前环境已有明确授权和任务要求。

---

# 十五、完整停止规则

以下任何一个阶段失败，都必须停止下游研究：

```text
080A 机会不足
080B 无稳定可预测性
080B 成本后无经济价值
080B 收益过度集中
080C Confirmation 失败
```

停止时必须输出：

```text
FINAL_STATUS=PASS
FINAL_DECISION=<真实负面研究结论>
```

只要程序、测试和审计成功，研究失败仍然可以是 PASS。

不得为了进入下一阶段：

```text
降低 1%目标
降低样本门槛
改变 split
重新读取 Confirmation 调参
挑选最好年份
挑选最好 Session
挑选最好标的
改变成本
```

---

# 十六、最终总报告

无论在哪一阶段停止，最终都必须创建一个总报告：

```text
D:\us-tech-quant\.local_results\v22\FAST3_FINAL_RESEARCH_SUMMARY\fast3_final_summary.json
D:\us-tech-quant\.local_results\v22\FAST3_FINAL_RESEARCH_SUMMARY\fast3_final_report.md
```

总报告必须包含：

```text
FINAL_COMPLETED_STAGE
FINAL_STATUS
FINAL_DECISION
STOP_REASON
SOURCE_DATA_CONTRACT
080A_STATUS
080A_DECISION
080A_KEY_METRICS
080B_STATUS
080B_DECISION
080B_KEY_METRICS
080C_STATUS
080C_DECISION
080C_KEY_METRICS
080D_STATUS
080D_DECISION
FROZEN_CONTRACT_SHA256
MODEL_SHA256
CONFIRMATION_ROW_READ_COUNT
BROKER_ACTION_ALLOWED
PAPER_TRADING_ALLOWED
OFFICIAL_ADOPTION_ALLOWED
ORDER_GENERATION_ALLOWED
RECOMMENDED_NEXT_COMMAND
OUTPUT_PATHS
KNOWN_LIMITATIONS
```

如果 080D 成功部署：

```text
RECOMMENDED_NEXT_COMMAND=
.\scripts\v22\run_v22_080d_fast3_prospective_shadow_r1.ps1
```

如果上游失败：

```text
RECOMMENDED_NEXT_COMMAND=NONE_FAST3_RESEARCH_STOPPED
```

---

# 十七、最终回复格式

完成整个自主任务后，只提交一次最终汇总，不要在每个阶段等待用户确认。

格式：

```text
FAST3_FINAL_COMPLETED_STAGE=
FAST3_FINAL_STATUS=
FAST3_FINAL_DECISION=
FAST3_STOP_REASON=

V22_080A_STATUS=
V22_080A_DECISION=
V22_080A_EVENT_COUNT=
V22_080A_3M_ETF_2PCT_HIT_RATE=
V22_080A_3M_ETF_3PCT_HIT_RATE=
V22_080A_3M_MEDIAN_NET_RETURN_10BPS=

V22_080B_STATUS=
V22_080B_DECISION=
V22_080B_TOP5_LIFT=
V22_080B_TOP5_NET_RETURN_10BPS=
V22_080B_TOP5_NET_RETURN_20BPS=

V22_080C_STATUS=
V22_080C_DECISION=
V22_080C_CONFIRMATION_TRADE_COUNT=
V22_080C_MEAN_NET_RETURN_10BPS=
V22_080C_MEAN_NET_RETURN_20BPS=
V22_080C_PROFIT_FACTOR=
V22_080C_MAX_DRAWDOWN=

V22_080D_STATUS=
V22_080D_DECISION=
V22_080D_SHADOW_DECISION_COUNT=
V22_080D_MATURED_TRADE_COUNT=

FROZEN_CONTRACT_SHA256=
MODEL_SHA256=
CONFIRMATION_ROW_READ_COUNT=
BROKER_ACTION_ALLOWED=
PAPER_TRADING_ALLOWED=
OFFICIAL_ADOPTION_ALLOWED=
ORDER_GENERATION_ALLOWED=

PYTHON_COMPILE_RESULTS=
PYTEST_RESULTS=
RUNNER_RESULTS=
CHANGED_FILES=
CHECKPOINT_COMMITS=
FINAL_SUMMARY_PATH=
FINAL_REPORT_PATH=
RECOMMENDED_NEXT_COMMAND=
KNOWN_LIMITATIONS=
```

现在开始执行。

不要只完成 V22.080A 后停止。

只要上游门禁通过，就自动开发并执行下一阶段。

如果某个研究门禁失败，则以该失败作为 FAST3 的完整最终研究结论，不得强行继续。

如果通过 Confirmation，则完成 V22.080D 前向影子系统的代码、测试、Runner、冻结合同加载、状态初始化和首次运行；不得假装已经积累未来样本。
<!-- FAST3_OVERNIGHT_AUTONOMY_BEGIN -->
# 十九、无人值守研究与模拟盘记录授权

用户授权 Codex 在本地量化项目范围内无人值守推进，直到以下最早发生的条件：

```text
获得通过冻结 Validation 和 Confirmation 的 FAST3 候选，并完成零订单 Prospective Shadow 记录器
Codex 使用额度耗尽或服务返回 rate/usage limit
到达本地早晨截止时间
出现无法由本地代码和数据解决的真实硬阻塞
严谨证据明确拒绝 FAST3 可预测优势
```

## 19.1 权限和安全边界

允许自主执行：

```text
修改本项目代码、测试、Runner、合同、研究报告
读写 backtests、cache、daily、results 和 .local_results
运行 Python、pytest、PowerShell、Git 本地状态和本地 checkpoint commit
创建可重建的缓存和索引
执行多年全量回测、随机 as-of 回测、block bootstrap 和稳定性分析
修复普通代码、测试、性能、路径和序列化错误
```

持续禁止：

```text
修改 canonical 源数据
真实券商或模拟券商下单
生成 broker order schema
远程 push 或 merge
删除整个仓库或大型数据根目录
把未来数据用于特征或参数选择
根据 Confirmation 反复调参
伪造、选择性隐藏或美化结果
```

模拟盘仅指：

```text
零订单 shadow decision ledger
pending position ledger
matured trade ledger
NO_TRADE 记录
冻结合同、模型和状态哈希
```

## 19.2 自主随机回测循环

在额度仍可用且尚未达到最终停止条件时，允许连续进行高价值的随机回测与策略改进，但必须遵守：

```text
固定随机种子并记录
随机抽取 as-of 起点或连续时间窗口，不随机打乱单条分钟样本
所有窗口保持 PIT/no-leakage
Development 用于拟合和假设生成
Validation 用于有限次数独立比较
Confirmation 在最终冻结前读取数为 0
相邻和重叠窗口按日期或 move family 分组
成本至少包括 10bps 主情景和 20bps 压力情景
必须使用真实 ETF OHLC
报告多重尝试次数和 selection bias 风险
```

每轮必须记录：

```text
iteration_id
predeclared_hypothesis
random_seed
sample_window_contract
feature_contract_hash
strategy_contract_hash
development_metrics
validation_metrics
cost_sensitivity
delay_sensitivity
year/session/ETF stability
concentration
failure_reason
decision
```

只允许紧凑、可解释且计算可控的改进：

```text
数据映射实现修复
PIT 特征质量修复
固定候选特征族的消融
小规模预声明模型集合
阈值从 Development 冻结
执行约束和 NO_TRADE 规则
性能优化
```

禁止用额度做无意义穷举。不得为了“用完 token”重复同一实验、扩大无依据网格或制造文件。额度应用于新的诊断、独立验证、代码审查、测试和稳健性证据。

## 19.3 允许部署到模拟盘记录的最低标准

只有同时满足主合同中的冻结门禁，才能将候选标记为：

```text
SHADOW_RECORDING_ELIGIBLE=true
```

必须至少具备：

```text
冻结特征、模型、阈值、入场、退出、成本和重叠合同
Validation 成本后正期望和稳定性门禁通过
Confirmation 正式一次性评价通过
真实 ETF OHLC
至少 10bps 和 20bps 成本结果
延迟敏感性
收益集中度
合同和模型 SHA256
幂等零订单 shadow runner
首次初始化和重复运行烟雾测试
OFFICIAL_ADOPTION_ALLOWED=false
BROKER_ACTION_ALLOWED=false
PAPER_BROKER_ORDER_ALLOWED=false
```

如果没有候选达到标准，不得伪造一个“可模拟盘策略”。最终必须如实输出拒绝或不确定结论，并保留所有诊断供下一周期使用。

## 19.4 早晨交付物

必须生成：

```text
D:\us-tech-quant\.local_results\v22\FAST3_OVERNIGHT_AUTOPILOT\overnight_summary.json
D:\us-tech-quant\.local_results\v22\FAST3_OVERNIGHT_AUTOPILOT\overnight_report.md
D:\us-tech-quant\.local_results\v22\FAST3_OVERNIGHT_AUTOPILOT\experiment_ledger.csv
D:\us-tech-quant\.local_results\v22\FAST3_OVERNIGHT_AUTOPILOT\OVERNIGHT_DONE.flag
```

如果策略通过，另外提供：

```text
可直接手动运行的 shadow Runner
冻结合同和模型哈希
首次 shadow 初始化结果
RECOMMENDED_NEXT_COMMAND
```

`OVERNIGHT_DONE.flag` 只能在最终交付物已完整写出时创建。
<!-- FAST3_OVERNIGHT_AUTONOMY_END -->
