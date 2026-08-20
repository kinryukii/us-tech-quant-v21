# FAST3 SOXX Directional Opportunity Autonomous Research Agent

## 完整自主开发、训练、随机回测与迭代总指令

你现在负责在以下 Windows 本地量化仓库中，完整开发并持续推进 FAST3 SOXX Directional Opportunity 研究系统：

* 代码仓库：`D:\us-tech-quant`
* 数据根目录：`D:\us-tech-quant-data`
* 结果根目录：`D:\us-tech-quant-results`
* Python 虚拟环境：`D:\us-tech-quant-envs\us-tech-quant-main`
* 时区：`America/New_York`
* 逻辑时间字段：`timestamp_et`
* 辅助时间字段：`timestamp_utc`

现有 canonical 24 小时分钟数据路径：

```text
D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical\
symbol=<SYMBOL>\year=<YYYY>\month=<MM>\data.parquet
```

现有六个标的：

```text
QQQ
SOXX
TQQQ
SQQQ
SOXL
SOXS
```

已知 canonical 数据合同至少包含：

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

在开始开发前，必须只读核验实际 schema、时间范围、分区完整性、重复时间戳、缺失值、无效 OHLC、异常成交量和复权状态。不得凭本指令假定全部字段始终存在。

---

# 一、最终研究目标

开发一个只使用决策时点之前可获得信息的模型，用于预测 SOXX 底层方向和可交易机会。

研究目标是：

1. 大多数月份保持正收益或接近持平。
2. 在不确定、震荡和无优势时允许空仓。
3. 主要依靠明显趋势日和高质量方向机会贡献利润。
4. 首先预测 SOXX 的底层方向和预期收益。
5. 只有在信号通过全部门禁后，才将：

   * 正向信号映射到 SOXL；
   * 负向信号映射到 SOXS。
6. 不直接以 SOXL/SOXS 的未来收益训练方向模型，避免杠杆衰减、跟踪误差和路径依赖污染底层方向学习。
7. SOXL/SOXS 仅用于真实执行映射、成本、滑点、流动性和跟踪误差模拟。

长期平均每天捕获 SOXX 约 1% 毛机会是远期研究目标，不是必须达到的回测门槛，也不得为了达到该数字进行参数搜索、样本筛选或报告美化。

研究系统不得下真实订单：

```text
broker_action_allowed=False
live_trading_allowed=False
official_adoption_allowed=False
research_only=True
```

---

# 二、不可修改的硬约束

以下规则优先级高于收益、胜率、Sharpe、开发速度和任何模型表现。

## 2.1 禁止未来函数

任何特征在时间 `t` 形成决策时，只能使用时间 `t` 或更早已经完整形成且真实可获得的数据。

必须做到：

1. 所有 rolling、EMA、标准化、分位数、行业宽度和统计量只能向后计算。
2. 不得使用 centered rolling window。
3. 不得对完整历史数据先标准化、再切分训练集和测试集。
4. scaler、imputer、PCA、特征筛选、阈值和模型必须只在当前训练窗口拟合。
5. 分钟 K 线在该分钟结束前不可视为完整。
6. 如果在 `10:00:00` 决策，默认只能使用 `09:59` 或更早已经完成的 bar。
7. 默认至少加入一根 bar 的执行延迟。
8. 标签和特征不得共享未来价格。
9. 不得用全天最高价、最低价、收盘价、全天成交量构造盘中信号。
10. 不得利用后续才能确定的 session classification。
11. 不得使用未来复权因子。
12. 任何外部宏观、财报、成分股、新闻或事件数据必须具有真实发布时间和发布时间延迟。
13. 财报必须按公开发布时间进入系统，不能按财报所属季度或数据库最终日期进入。
14. 宏观数据必须使用当时首次发布值；除非明确标记，否则不得使用后来修订值。
15. 模型选择过程中不得读取最终 confirmation 数据。
16. regime 模型如果使用 HMM，只能使用实时 filtering，禁止使用利用未来序列的 smoothing。
17. 不得通过全历史极值确定阈值。
18. 不得使用全样本最优交易时段。
19. 不得使用完整测试集结果反向调整因子。
20. 任何可能存在泄漏的实现都必须 fail closed，而不是默认继续。

每项特征必须保存：

```text
feature_name
source_symbol
source_field
lookback
availability_lag
decision_timestamp
maximum_source_timestamp
is_point_in_time
leakage_test_status
```

必须自动验证：

```text
maximum_source_timestamp <= decision_timestamp - required_execution_lag
```

任何违反均直接失败。

## 2.2 严禁过拟合

不得以“最佳单次回测”作为结论。

禁止：

* 无限搜索参数直到出现漂亮结果；
* 仅报告最佳 seed；
* 仅报告最佳年份；
* 删除表现差的市场阶段；
* 在同一验证集上反复试验后仍把它称为独立验证；
* 看到 confirmation 结果后继续修改模型；
* 因某个模型失败而反转标签或反转排名；
* 事后挑选最有利的止盈止损；
* 只优化胜率；
* 只优化总收益；
* 通过大量无经济含义因子碰运气；
* 用深度神经网络掩盖样本不足；
* 将随机窗口中的最高结果当作预期结果；
* 将 gross return 当作可执行 net return；
* 在结果不理想时降低交易成本；
* 修改 seed 以寻找成功结果；
* 重复读取最终 holdout。

必须采用：

* chronological split；
* nested walk-forward；
* purging；
* embargo；
* block bootstrap；
* 多随机种子；
* 多市场阶段；
* 多成本情景；
* 多执行延迟情景；
* 参数敏感性测试；
* 多重检验惩罚；
* 结果集中度检查；
* confirmation 单次读取；
* prospective shadow。

---

# 三、预测对象与交易对象必须分离

## 3.1 预测对象

核心预测对象始终是：

```text
SOXX
```

模型至少输出：

```text
expected_soxx_return
probability_up
probability_down
directional_confidence
estimated_uncertainty
expected_favorable_excursion
expected_adverse_excursion
recommended_action
```

其中：

```text
recommended_action ∈ {LONG, SHORT, FLAT}
```

## 3.2 交易映射

只有模型通过全部 OOS 门禁时才模拟：

```text
LONG  -> SOXL
SHORT -> SOXS
FLAT  -> no position
```

SOXL/SOXS 映射必须使用实际分钟价格，不得简单将 SOXX 收益乘以三。

必须建模：

* SOXL/SOXS 实际成交价格；
* 买卖价差代理；
* 滑点；
* 交易费用；
* 杠杆跟踪偏差；
* 隔夜路径依赖；
* 波动拖累；
* 拆股和复权；
* 成交量和流动性；
* 极端行情暂停交易风险；
* 信号产生至成交之间的延迟。

---

# 四、标签体系

不得只设计一个标签然后反复优化。

至少建立以下互相独立但共享 PIT 合同的标签：

## 4.1 固定期限方向标签

基于 SOXX 从实际可成交时点开始的未来收益：

```text
15m
30m
60m
120m
RTH close
next major session boundary
```

标签仅用于训练和评价，不可进入特征。

## 4.2 三重障碍标签

基于 SOXX：

* 上方收益障碍；
* 下方风险障碍；
* 最大持有时间。

障碍宽度必须基于决策时点以前的 ATR 或 realized volatility 确定。

不得用未来波动率确定障碍。

## 4.3 机会标签

区分：

```text
direction_correct
tradable_after_costs
large_trend_opportunity
choppy_or_no_edge
```

“趋势机会”不得单纯使用未来最大上涨或最大下跌作为可实现收益。必须结合真实交易路径和执行规则评价。

## 4.4 连续目标

同时预测：

```text
future_return
future_MFE
future_MAE
risk_adjusted_expected_return
```

MFE 和 MAE 只能作为预测目标或分析字段，不能被当作模型实际成交收益。

---

# 五、优先加入的因子体系

因子不得一次全部加入。必须按组进行消融和增量验证。

每个因子必须满足：

1. 有明确经济或市场结构解释；
2. 可在决策时点获得；
3. 有独立单元测试；
4. 有缺失值处理合同；
5. 在多个 OOS 窗口方向基本稳定；
6. 加入后不是只提高训练集表现；
7. 不严重提高换手率或成本敏感性。

## 5.1 SOXX 多时间尺度趋势因子

必须优先开发：

```text
1m / 3m / 5m / 15m / 30m / 60m / 120m / 390m backward returns
log returns
EMA slope
EMA distance
MA20 / MA50 distance and slope
multi-horizon trend alignment
Donchian breakout distance
recent high/low breakout strength
VWAP distance
VWAP slope
VWAP same-side persistence
ADX / directional movement
Bollinger position and bandwidth
RSI
KDJ
MACD-like momentum
price acceleration
trend persistence
pullback depth
recovery speed
higher-high / lower-low structure
```

不得机械叠加大量高度相关指标。必须做相关性聚类和组内消融。

## 5.2 波动率与市场状态因子

必须加入：

```text
realized volatility
ATR
intrabar range
Parkinson-like range estimator
volatility of volatility
volatility percentile based only on past data
short-vol / long-vol ratio
overnight volatility
premarket volatility
RTH volatility
range expansion
range compression
gap size
gap direction
gap persistence
gap fill progress
trend-versus-chop regime
```

市场状态至少区分：

```text
LOW_VOL_RANGE
HIGH_VOL_RANGE
UP_TREND
DOWN_TREND
GAP_TREND
REVERSAL
EVENT_RISK
DATA_UNTRUSTED
```

regime 必须由当时数据实时确定，不得利用完整未来区间重新分类。

## 5.3 成交量与流动性因子

基于现有 bar 数据开发：

```text
relative volume by time of day
volume acceleration
volume surprise versus trailing same-time distribution
price-volume confirmation
up-bar / down-bar volume proxy
Amihud-like illiquidity proxy
zero-volume or stale-bar ratio
volume concentration
breakout volume confirmation
VWAP participation proxy
price impact proxy
```

若没有逐笔或盘口数据，不得伪造 order imbalance、真实 spread 或买卖方向。

## 5.4 跨资产方向和风险偏好因子

使用现有六 ETF 的同时点历史数据：

```text
QQQ trend
QQQ relative strength
SOXX minus QQQ relative return
SOXX / QQQ ratio trend
TQQQ and SQQQ confirmation
SOXL and SOXS tracking behavior
leveraged ETF divergence
long-versus-inverse ETF consistency
cross-symbol lead-lag using only lagged values
```

不得使用同一分钟尚未完成的其他 ETF bar。

需要测试：

* QQQ 是否领先 SOXX；
* SOXX 是否领先 QQQ；
* 杠杆 ETF 偏离是否具有信息；
* 偏离是否只是噪声或流动性问题。

任何 lead-lag 必须通过严格延迟验证。

## 5.5 半导体行业专属因子

优先研究但不是强制立即加入：

```text
SOXX relative strength versus QQQ
SOXX versus SMH spread
semiconductor breadth
weighted component momentum
component dispersion
percentage of components above VWAP
percentage of components above EMA
leader-laggard structure
NVDA / AVGO / AMD / TSM / ASML / MU 等龙头的滞后方向
semiconductor earnings-event density
semiconductor-specific overnight lead
```

但只有获得以下条件后才能使用成分股因子：

* 历史时点真实成分股名单；
* 历史时点真实权重；
* 退市股票保留；
* 正确复权；
* 无幸存者偏差；
* 数据真实发布时间明确。

如果只有当前成分股名单，则只能标记为：

```text
CURRENT_UNIVERSE_EXPLORATORY_ONLY
```

不得作为历史正式结论。

## 5.6 时间和交易时段因子

加入：

```text
minute of session
session type
minutes since session open
minutes until session close
day of week
month
month-end
quarter-end
holiday-adjacent flag
options-expiration calendar flag
opening range state
lunch-hour state
power-hour state
premarket-to-open transition
overnight-to-RTH transition
```

时间因子必须与价格因子联合验证，不得仅因某个历史时间段表现好就固定交易。

## 5.7 事件风险因子

若可获得真实 PIT 数据，可加入：

```text
FOMC schedule
CPI schedule
PPI schedule
NFP schedule
major semiconductor earnings schedule
major index rebalance schedule
options expiration
known exchange holiday / shortened session
```

只能使用事前已知的：

```text
event_type
scheduled_time
time_until_event
time_since_event_release
```

不得在事件发布前使用：

```text
actual_value
surprise
market reaction
revised_value
```

## 5.8 数据可信度因子

必须将数据质量作为模型门禁的一部分：

```text
missing_bar_ratio
stale_price_ratio
zero_volume_ratio
timestamp_gap
cross-symbol synchronization quality
invalid_ohlc_flag
abnormal_return_flag
source_latency
session_consistency
split-adjustment uncertainty
```

出现高风险数据状态时应输出：

```text
FLAT
```

而不是强行预测。

---

# 六、模型开发顺序

不得一开始使用复杂模型。

必须依次建立：

## Stage 0：不可交易基准

* 永远做多；
* 永远做空；
* 永远空仓；
* 前一分钟方向延续；
* 简单均线趋势；
* VWAP 同侧；
* opening range breakout；
* 随机信号。

任何模型必须与这些基准比较。

## Stage 1：可解释线性模型

至少包含：

```text
logistic regression
ridge regression
elastic net
calibrated linear classifier
```

## Stage 2：可解释非线性模型

允许：

```text
GAM
shallow decision tree
small random forest
ExtraTrees with strict constraints
gradient boosting with shallow depth
LightGBM / XGBoost with strong regularization
```

约束建议：

```text
max_depth <= 4
small number of leaves
large min_samples_leaf
strong L1/L2
feature subsampling
row subsampling
early stopping
limited boosting rounds
```

参数范围必须预先登记，不得根据 confirmation 扩大。

## Stage 3：稳定集成

只允许集成已经单独通过 OOS 门禁的模型。

集成权重只能用训练和 validation 数据确定。

不得用测试期表现计算权重。

## Stage 4：时间自适应

允许：

* expanding-window retraining；
* rolling-window retraining；
* weekly retraining；
* monthly retraining；
* stability-weighted model selection。

禁止：

* 在标签结果尚未形成时更新；
* 利用未来 bar 回填模型；
* 对 confirmation 期间逐日调整后仍称其为 holdout。

默认不使用深度神经网络。除非所有简单模型均完成、样本量充分且非线性结构证据明确，否则禁止新增 Transformer、LSTM 或大型神经网络。

---

# 七、决策与空仓机制

模型不得被迫每天交易。

建立三层门禁：

## 7.1 方向门禁

只有当：

```text
max(probability_up, probability_down) >= direction_threshold
```

才进入下一步。

阈值必须在训练窗口确定，并通过 validation 验证稳定性。

## 7.2 期望收益门禁

必须满足：

```text
expected_net_return > estimated_cost
expected_net_return > uncertainty_buffer
```

## 7.3 市场质量门禁

以下情况默认空仓：

* 数据异常；
* 流动性不足；
* 价差代理过高；
* 方向模型分歧严重；
* regime 不在已验证范围；
* 事件前风险过高；
* 参数外推；
* 特征超出训练分布；
* 模型不确定性过高。

空仓是有效决策，不得因减少交易次数而被惩罚。

---

# 八、交易模拟合同

默认：

```text
maximum_concurrent_position = 1
long_symbol = SOXL
short_symbol = SOXS
allow_flat = True
```

必须至少测试以下持有和退出机制：

1. 固定期限退出；
2. 反向信号退出；
3. volatility-adjusted stop；
4. volatility-adjusted take profit；
5. maximum holding time；
6. time stop；
7. trailing protection；
8. session boundary forced exit；
9. 隔夜持仓与不隔夜持仓分别测试。

不得对每个随机窗口单独寻找最优止盈止损。

交易规则必须在训练阶段冻结，然后在 validation 和测试阶段原样使用。

所有模拟至少考虑：

```text
signal_delay = 1 bar
execution_delay = 0 to 2 additional bars stress test
base_cost
2x_cost
3x_cost
slippage
failed fill proxy
no-trade on invalid price
```

不得使用当根 K 线最低价买入或最高价卖出。

默认使用信号后下一根可成交 bar 的保守价格，例如：

* 做多买入使用下一 bar open 加滑点；
* 做空方向通过买入 SOXS 实现；
* 卖出使用下一 bar open 减滑点。

---

# 九、数据切分和 confirmation 隔离

按时间将全部数据分成：

```text
DEVELOPMENT
VALIDATION
CONFIRMATION
PROSPECTIVE_SHADOW
```

## 9.1 Development

用于：

* 特征开发；
* 模型训练；
  -初步参数研究；
* 随机窗口回测。

## 9.2 Validation

用于：

* 模型选择；
* 阈值选择；
* 交易规则比较；
* 稳定性门禁。

Validation 可以被多次使用，但必须记录使用次数。使用越多，结果可信度折扣越大。

## 9.3 Confirmation

必须在项目开始时按时间冻结。

要求：

```text
confirmation_read_count = 0
```

在开发和自我改进阶段：

* 不读取 confirmation；
* 不统计 confirmation；
* 不加载 confirmation 特征；
* 不输出 confirmation 日期分布；
* 不根据 confirmation 调整任何代码。

只有 champion 完全冻结并通过全部门禁后，才允许单次读取：

```text
confirmation_read_count = 1
```

读取后不得再修改模型。若失败，只能报告失败并开启新的研究世代，新的 confirmation 必须来自未来新增数据，不能重复利用旧 confirmation 继续调参。

## 9.4 Prospective shadow

confirmation 通过后仍不能直接交易。

必须进行前瞻 shadow：

```text
broker_action_allowed=False
```

每日只使用当时已有数据生成信号，并等待真实未来结果形成后评价。

---

# 十、随机回测体系

随机回测不是随机切乱数据。

禁止 random train_test_split。

每个随机试验必须保持时间顺序，并从可用历史中随机抽取 as-of 锚点。

## 10.1 随机窗口

随机生成不同：

```text
train_length
validation_length
test_length
as_of_date
market_regime_mix
execution_delay
cost_multiplier
```

建议阶段：

```text
smoke stage: >= 20 windows
research stage: >= 100 windows
candidate stage: >= 250 windows
final robustness stage: >= 500 windows
```

若计算资源不足，允许减少数量，但必须如实报告，不得声称完成更高阶段。

## 10.2 Walk-forward

每个窗口执行：

```text
train -> validate -> freeze -> test
```

训练、验证、测试必须完全按时间排序。

## 10.3 Purge 与 embargo

purge 长度至少覆盖：

```text
maximum_feature_lookback
maximum_label_horizon
maximum_holding_period
```

相邻训练和测试区间必须设置 embargo，防止重叠标签和序列相关泄漏。

## 10.4 Bootstrap

使用以天或周为单位的 block bootstrap，不得逐分钟独立抽样。

评价：

```text
return distribution
Sharpe distribution
maximum drawdown distribution
hit-rate distribution
monthly consistency
tail loss
probability of loss
```

## 10.5 压力测试

每个候选必须测试：

* 基准成本；
* 2 倍成本；
* 3 倍成本；
* 额外 1 bar 延迟；
* 额外 2 bar 延迟；
* 随机漏掉部分成交；
* 随机缺失少量 bar；
* 部分特征延迟；
* 参数小幅扰动；
* 阈值小幅扰动；
* 开仓时间小幅扰动；
* 不同随机 seed；
* 去除最赚钱月份；
* 去除最赚钱若干交易日；
* 极端波动期；
* 低波动震荡期；
* 上涨市场；
* 下跌市场；
* 快速反转市场。

---

# 十一、防过拟合统计门禁

每个候选至少报告：

```text
number_of_trials
number_of_features
number_of_hyperparameter_combinations
train_performance
validation_performance
test_performance
train_validation_gap
validation_test_gap
Deflated Sharpe Ratio
Probability of Backtest Overfitting
bootstrap confidence interval
parameter sensitivity
feature stability
monthly win ratio
profit concentration
turnover
cost sensitivity
delay sensitivity
```

如果技术上可实现，加入：

```text
White Reality Check
Hansen SPA
multiple-testing adjustment
false discovery rate
```

候选不得仅因平均收益最高而晋级。

必须优先选择：

* 中位数表现更好；
* 分布左尾更安全；
* 参数平台更宽；
* 跨窗口方向一致；
* 成本后仍为正；
* 延迟后仍为正；
* 交易逻辑可解释；
* 特征数量更少；
* 模型复杂度更低；
* 训练与测试差距更小。

---

# 十二、候选晋级硬门禁

不得预设必须实现每天 1%。

候选只有同时满足以下条件才能成为 champion：

1. 大多数独立 OOS 窗口净收益为正。
2. 多数月份为正或接近持平。
3. 在 2 倍合理成本下仍保持正期望。
4. 加入至少 1 bar 延迟后不发生结构性崩溃。
5. 收益不能完全依赖单一年份。
6. 收益不能完全依赖单一方向。
7. 收益不能主要来自一两次异常交易。
8. 去除最赚钱的少数交易日后仍具有可解释的正边际，或至少不出现整体逻辑反转。
9. 参数轻微变化后表现没有断崖。
10. 不存在已知未来函数。
11. confirmation 尚未被读取。
12. 相比简单基准具有稳定增量。
13. 净收益、回撤、换手和尾部风险之间合理。
14. 模型校准有效，置信度越高的组实际表现总体越好。
15. FLAT 状态确实降低了无优势时期损失，而不是仅仅删除亏损样本。

以下只能作为目标参考，不得通过降低标准强行满足：

```text
desired_oos_sharpe >= 1.0
desired_positive_month_ratio >= 0.60
desired_positive_random_window_ratio >= 0.65
desired_2x_cost_expectancy > 0
desired_max_drawdown_controlled = True
desired_probability_of_backtest_overfitting < 0.20
```

若数据不支持这些水平，必须明确报告，不得美化。

---

# 十三、因子选择方式

禁止仅根据全样本 feature importance 选因子。

必须采用：

1. 单因子方向稳定性；
2. 单因子分桶；
3. 不同市场状态下表现；
4. 不同年份表现；
5. permutation importance，仅在当前 OOS 框架内使用；
6. SHAP，仅作为解释工具，不能证明因果；
7. group ablation；
8. leave-one-feature-group-out；
9. stability selection；
10. 相关性聚类；
11. 冗余删除；
12. 特征漂移检查。

每次迭代最多进行一个主要研究改动，例如：

* 新增一个因子组；
* 删除一个不稳定因子组；
* 更换一种模型；
* 修改一种标签；
* 修改一项交易退出规则；
* 修改一种 regime gate。

禁止一次同时修改大量因素后无法归因。

---

# 十四、自我训练和自我改进循环

持续自主执行以下循环，不要等待用户逐步确认：

## Iteration Step 1：读取当前 champion 和实验记录

读取：

```text
experiment_registry
current_champion
rejected_candidates
known_failures
data_contract
leakage_audit
```

不得重复已经明确失败且没有新证据的实验。

## Iteration Step 2：提出一个可证伪假设

例如：

```text
假设：SOXX 相对 QQQ 的多尺度强弱可以提高趋势日识别，并减少震荡日误交易。
```

必须在看到本次结果前记录：

```text
hypothesis
expected_mechanism
changed_component
primary_metric
failure_condition
```

## Iteration Step 3：实现最小必要改动

* 优先复用现有代码；
* 不无意义创建新版本；
* 不复制大型输入数据；
* 不生成二进制模型垃圾；
* 不修改 canonical 数据；
* 不覆盖历史正式结果；
* 修改范围应可审计。

## Iteration Step 4：运行测试

至少包括：

```text
compile
schema test
timestamp test
future-leakage test
feature lag test
split test
purge test
embargo test
confirmation zero-read test
execution delay test
cost test
determinism test
smoke backtest
```

任何测试失败，先修复再继续。

## Iteration Step 5：阶段化回测

顺序：

```text
small smoke
limited randomized research
full randomized comparison
robustness stress
```

不得每次小改动都直接运行最昂贵的全量回测。

## Iteration Step 6：与 champion 公平比较

必须使用同一组冻结窗口、相同 seed、相同成本、相同执行规则。

比较：

```text
median OOS return
lower confidence bound
drawdown
positive-window ratio
positive-month ratio
turnover
cost robustness
delay robustness
parameter stability
profit concentration
```

## Iteration Step 7：接受或拒绝

仅当 challenger 在多个核心指标上稳定优于 champion，且没有增加不可接受风险时，才能替换 champion。

输出：

```text
ACCEPT_CHALLENGER
REJECT_CHALLENGER
INCONCLUSIVE
```

不得因单个指标略高就接受。

## Iteration Step 8：记录结果

每轮记录：

```text
iteration_id
parent_candidate
code_hash
data_manifest_hash
feature_manifest_hash
window_manifest_hash
seed_manifest
hypothesis
changes
tests
metrics
decision
failure_reason
next_allowed_research
```

## Iteration Step 9：继续下一轮

根据失败原因选择下一项最有信息价值的实验。

不要随机堆因子。优先解决：

1. 数据或泄漏问题；
2. OOS 不稳定；
3. 成本敏感；
4. 延迟敏感；
5. regime 失效；
6. 空仓阈值失效；
7. 因子非单调；
8. 模型校准差；
9. 收益过度集中；
10. 才考虑新增模型复杂度。

---

# 十五、自动迭代期间的资源和 Token 规则

目标是在可用执行预算、上下文和 Token 允许范围内尽可能持续推进，而不是完成一轮后主动停止。

必须：

1. 不向用户询问下一步。
2. 不因一次失败停止。
3. 不因结果未达到每日 1% 停止。
4. 自动分析失败原因并进入下一轮。
5. 持续执行：

   ```text
   hypothesis
   implementation
   test
   random backtest
   comparison
   accept/reject
   next hypothesis
   ```
6. 接近 Token、上下文或执行资源限制时，必须先保存完整 checkpoint。
7. 不得为了“用完 Token”输出重复分析、无意义版本或伪造运行。
8. 如果仍有可执行预算，继续进行下一项最高价值实验。
9. 如果无法继续运行命令，必须完成代码、测试、运行指令和真实状态说明。
10. 不得声称执行了实际上没有执行的测试或回测。
11. 不得声称使用了全部 Token，除非系统能够真实确认。
12. 不得承诺后台继续运行。
13. 每一阶段都必须产生可恢复状态。

checkpoint 至少包含：

```text
current_status
current_champion
last_completed_iteration
running_or_failed_command
completed_tests
remaining_tests
completed_backtests
remaining_backtests
known_failures
next_exact_action
exact_resume_command
```

---

# 十六、代码与产物结构

优先使用稳定目录，避免每一轮制造新脚本版本。

建议：

```text
D:\us-tech-quant\scripts\v22\fast3_agent\
    config.py
    data_contract.py
    feature_pipeline.py
    labels.py
    splits.py
    models.py
    simulator.py
    randomized_backtest.py
    robustness.py
    leakage_audit.py
    experiment_registry.py
    champion_manager.py
    run_autoresearch.py
    tests\
```

结果：

```text
D:\us-tech-quant-results\fast3_autoresearch\
    current\
    checkpoints\
    experiments\
    champion\
    reports\
```

每个 experiment 只保存必要的：

```text
config.json
manifest.json
metrics.json
decision.json
summary.md
trades.parquet
daily_metrics.parquet
window_metrics.parquet
feature_audit.parquet
logs.txt
```

不得复制 canonical 输入数据。

不得无必要保存大型 pickle、模型快照或重复 DataFrame。

---

# 十七、必须生成的最终报告

最终或资源耗尽前必须生成：

```text
FAST3_AUTORESEARCH_FINAL_REPORT.md
FAST3_AUTORESEARCH_FINAL_SUMMARY.json
FAST3_AUTORESEARCH_EXPERIMENT_REGISTRY.parquet
FAST3_AUTORESEARCH_CHAMPION_CONFIG.json
FAST3_AUTORESEARCH_LEAKAGE_AUDIT.json
FAST3_AUTORESEARCH_RANDOM_WINDOW_METRICS.parquet
FAST3_AUTORESEARCH_RESUME_COMMAND.txt
```

报告必须明确区分：

```text
in_sample
validation
randomized_oos
confirmation
prospective_shadow
```

报告必须包含：

1. 实际读取的数据范围；
2. 实际使用的 symbol；
3. 实际使用的因子；
4. 被拒绝的因子；
5. 所有模型；
6. 总试验次数；
7. confirmation 读取次数；
8. 泄漏检查；
9. 随机回测分布；
10. 成本压力；
11. 延迟压力；
12. 月度一致性；
13. 趋势日贡献；
14. 震荡日表现；
15. 多头和空头分别表现；
16. SOXX 信号与 SOXL/SOXS 执行差异；
17. 最大回撤；
18. 最差窗口；
19. 最差月份；
20. 收益集中度；
21. 当前是否具有统计可信度；
22. 当前是否达到 prospective shadow 条件；
23. 仍然未知的风险；
24. 下一步唯一推荐研究方向。

严禁只展示最佳结果。

---

# 十八、最终状态枚举

最终只能使用以下之一：

```text
PASS_RESEARCH_PIPELINE_COMPLETE_NO_EDGE_CONFIRMED
PASS_ROBUST_DIRECTIONAL_EDGE_FOUND
PASS_CANDIDATE_READY_FOR_CONFIRMATION
PASS_CONFIRMATION_ACCEPTED_READY_FOR_PROSPECTIVE_SHADOW
FAIL_DATA_CONTRACT
FAIL_LEAKAGE_DETECTED
FAIL_OVERFITTING_RISK
FAIL_NO_ROBUST_EDGE
FAIL_COST_SENSITIVITY
FAIL_DELAY_SENSITIVITY
FAIL_CONFIRMATION
PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED
```

即使结果失败，也必须保存全部真实证据和恢复命令。

失败是合法结果。

不得将：

```text
FAIL_NO_ROBUST_EDGE
```

改写为“接近成功”“具有巨大潜力”或其他美化表达。

---

# 十九、第一轮必须执行的研究优先级

第一轮不要立即搜索大量复杂模型。

按以下顺序：

## Priority 1：基础数据和泄漏审计

* 核验六 ETF canonical；
* 核验时间同步；
* 核验分钟 bar 完成时点；
* 核验复权；
* 核验异常值；
* 建立 confirmation 零读取保护。

## Priority 2：SOXX 基础方向基准

建立：

* 多尺度趋势；
* VWAP；
* gap；
* volatility regime；
* QQQ 相对强弱；
* SOXX/QQQ ratio；
* relative volume；
* FLAT gate。

使用简单 logistic/ridge 和规则基准。

## Priority 3：随机 as-of OOS

完成至少 100 个时间有序随机窗口，输出完整分布。

## Priority 4：SOXL/SOXS 真实执行映射

基于实际 ETF 数据加入：

* 成本；
* 滑点；
* 延迟；
* 跟踪误差；
* 多空非对称性。

## Priority 5：紧凑非线性模型

只有在线性模型和基准完成后，测试：

* GAM；
* shallow gradient boosting；
* small ExtraTrees。

## Priority 6：因子消融

重点判断以下增量：

```text
SOXX-only
+ QQQ cross-asset
+ volatility regime
+ volume/liquidity
+ leveraged ETF divergence
+ time/event gates
```

## Priority 7：空仓阈值和概率校准

比较：

```text
Platt calibration
isotonic calibration
validation-only threshold selection
uncertainty-based abstention
```

---

# 二十、立即执行要求

现在开始实际工作，而不是只生成设计文档。

第一步：

1. 检查仓库当前状态；
2. 检查现有 FAST3 和 V22 代码是否可复用；
3. 检查当前未提交文件，禁止误覆盖用户工作；
4. 只读核验 canonical 数据；
5. 创建稳定的 autoresearch 目录和最小实现；
6. 建立 confirmation 零读取 guard；
7. 建立基础测试；
8. 建立第一组基准模型；
9. 运行测试；
10. 运行第一阶段随机时间窗口回测；
11. 根据真实结果自动进入下一轮；
12. 持续执行，直到执行预算、上下文或 Token 限制迫使停止；
13. 停止前保存完整 checkpoint 和精确恢复命令。

整个过程中：

```text
NEVER FABRICATE
NEVER BEAUTIFY FAILURE
NEVER USE FUTURE DATA
NEVER READ CONFIRMATION DURING DEVELOPMENT
NEVER OPTIMIZE DIRECTLY FOR THE BEST BACKTEST
NEVER CREATE LIVE ORDERS
```

最终在终端摘要中打印：

```text
FINAL_STATUS=
FINAL_DECISION=
CURRENT_CHAMPION=
CONFIRMATION_READ_COUNT=
LEAKAGE_AUDIT_PASS=
RANDOM_WINDOW_COUNT=
POSITIVE_WINDOW_RATIO=
POSITIVE_MONTH_RATIO=
BASE_COST_EXPECTANCY=
TWO_X_COST_EXPECTANCY=
MAX_DRAWDOWN=
PROBABILITY_OF_BACKTEST_OVERFITTING=
PROSPECTIVE_SHADOW_ALLOWED=
BROKER_ACTION_ALLOWED=False
CHECKPOINT_PATH=
REPORT_PATH=
EXACT_RESUME_COMMAND=
```
