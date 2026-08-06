# FAST3 最小实证验证 Agent 执行合同

你正在 `FAST3_REPO_ROOT` 指向的现有 FAST3 仓库中工作。直接执行，不要只写计划。普通测试失败、模型未通过门槛或历史区间被判定污染，都不是询问用户的理由；应按本合同继续到明确停止点并如实报告。

## 0. 唯二最高要求

1. **防止过拟合**：禁止未来函数、验证集反复利用、无限调参、后验改阈值、后验挑选子群。
2. **防止系统膨胀**：优先复用和最小修改；不得新增多层 Runner、Atlas、Guard、Registry 或 A/B/C/D 补丁链。

禁止伪造、推测、补写或美化任何运行结果。没有实际运行就必须写 `NOT_RUN`；失败必须保留。

## 1. 本轮一次性目标

依次完成：

1. 建立 `FAST3_EVIDENCE_LEDGER.json`，确认历史污染区间及可能干净区间。
2. 在看到本轮真实 Development 结果前冻结 `FAST3_EXPERIMENT_CONTRACT.json`。
3. 复用现有组件运行真实 Development。
4. 初始最多 8 个配置；允许根据 Development 结果进行**一次、最多 4 个相邻配置**的有限微调。
5. 总计最多 3 个模型族、12 个配置、5 个固定随机种子。
6. 以 V22.080B 为固定基准；不显著优于基准或成本后不为正则停止。
7. 只有存在可证明未污染的历史区间时，才可一次性运行 Frozen Validation；否则冻结最终候选并准备 Prospective Forward Shadow，但不实盘。

## 2. 路径与写入边界

环境变量：

- `FAST3_REPO_ROOT`：代码仓库。
- `FAST3_DATA_ROOT`：外置只读数据根目录。
- `FAST3_RESULTS_ROOT`：本轮可写的仓库内暂存结果目录。
- `FAST3_EXTERNAL_RESULTS_ROOT`：外置长期结果根目录；本轮 Agent 不直接写入，由启动器在结束后同步。
- `FAST3_AGENT_RUN_ID`：本次运行 ID。

所有本轮产物必须先写入：

`$FAST3_RESULTS_ROOT`

不得修改或重写 `FAST3_DATA_ROOT` 中 canonical 数据。不得创建新的顶层目录。不得使用仓库中的 `configs/`；统一复用 `config/`。

## 3. 必须继承的历史事实

先查原始代码、summary、report、manifest 验证。若原始文件与下列描述不同，以可验证原始产物为准并报告差异：

- V22.080A：24 小时价格波动机会数量充足，但不证明可预测性。
- V22.080B：
  - `LEGACY_TOP5_LIFT=1.36122855`
  - `LEGACY_NET_RETURN_10BPS=-0.001966`
  - `PRE_REGISTERED_LIFT_GATE=1.50`
  - 历史结论：`PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE`
- FAST3-004：
  - `RESEARCH_FIT_CALL_COUNT=56`
  - `SYNTHETIC_RESEARCH_FIT_EXECUTED=true`
  - `FINAL_MODEL_TRAINING_EXECUTED=false`
  - `REAL_DEVELOPMENT_RUN_EXECUTED=false`
  - `FROZEN_VALIDATION_RUN_EXECUTED=false`
  - `FAST3_004_EMPIRICAL_VALIDATION_STATUS=NOT_RUN`
- Opportunity 阈值 `0.60` 为执行前预注册阈值，不得修改。
- V22.065A/B 的局部子群结果只能用于登记已测试假设和失败路线，不得继续组合挖掘。
- V22.065C/V22.066 不构成成功前瞻验证。

## 4. Phase A：只读发现和 Evidence Ledger

先只读检查，不立即改模型。定位并读取：

- canonical 六 ETF 24h 分钟数据合同及日期覆盖；
- 现有标签、特征、0.60 阈值定义；
- V22.065、V22.066、V22.080A、V22.080B、FAST3-004 的代码与结果；
- 既有 walk-forward、purge、embargo、交易成本、预测和报告组件；
- 历史 Development、Validation、Atlas、Shadow、随机回测、子群实验；
- 已有 manifest/registry/summary schema，能复用则不得新建重复体系。

生成 `$FAST3_RESULTS_ROOT/FAST3_EVIDENCE_LEDGER.json`。每个实验至少记录：

- `experiment_id`
- `code_path`
- `result_path`
- `data_start`, `data_end`, `symbols`
- `label_definition`
- `feature_families`
- `models_tested`
- `thresholds_tested`
- `top_k_values_tested`
- `regimes_or_subgroups_tested`
- `results_observed`
- `used_for_model_selection`
- `used_for_threshold_selection`
- `used_for_feature_design`
- `contamination_status`
- `eligibility_for_frozen_validation`
- `evidence_source`
- `notes`

只要某段数据曾用于因子、标签、模型、超参数、阈值、Top-K、持仓期、止盈止损、Regime/子群筛选，或查看结果后决定保留路线，就视为污染。无法证明干净则标记：

`CONTAMINATED_BY_UNCERTAINTY`

汇总必须含：

- `contaminated_intervals`
- `potentially_clean_intervals`
- `confirmed_clean_intervals`
- `frozen_validation_available`
- `evidence_gaps`

不得为了得到 Frozen Validation 而假设历史区间干净。

## 5. Phase B：冻结实验合同

在查看本轮 Development 结果之前生成：

`$FAST3_RESULTS_ROOT/FAST3_EXPERIMENT_CONTRACT.json`

冻结：

- Development、Selection、可能 Frozen Validation 的时间范围；
- symbols、时间字段、数据 hash/分区 hash；
- purge、embargo、事件重叠隔离；
- 现有标签、特征、预测窗口、Opportunity 定义；
- 固定 `0.60` 阈值；
- 固定 Top5；
- 10bps 与 20bps 成本；
- 固定指标、选择规则、停止规则；
- 初始配置及 4 个微调名额；
- 五个随机种子。

若没有确认干净的历史区间，必须冻结：

`FROZEN_VALIDATION_MODE=PROSPECTIVE_FORWARD_SHADOW`

禁止新增因子、删除因子以追求更好结果、修改标签、预测窗口、0.60 阈值、Top-K、成本或数据区间。

模型预算：

1. 一个正则化线性基准；
2. 一个已有依赖支持的受限浅层非线性模型；
3. 当前 FAST3 主候选模型。

模型族最多 3 个。初始配置最多 8 个，预留微调最多 4 个，全阶段最多 12 个。若仓库无冻结种子，使用：

`[104729, 130363, 155921, 196613, 262147]`

不得只报告最好种子。

## 6. Phase C：防泄漏硬门禁

真实训练前必须有可执行检查并运行：

- 特征时间不晚于决策时间；
- 标签窗口不进入特征窗口；
- scaler/imputer/encoder/selector 仅在训练 fold 拟合；
- 每个 fold 独立 fit；
- 重叠标签 purge；
- 测试区间实施 embargo；
- 同一事件不同时进入训练与验证；
- Frozen 区间不参与 fit、fit_transform、阈值或模型选择；
- 每条预测可追溯 as-of 时间；
- 不使用未来修订值；
- 0.60 阈值未被动态修改。

若发现真实泄漏或时间逻辑错误：做最小修复、增加针对性测试、将受影响旧结果标为 `INVALID`，然后重新运行；工程错误修复后的重跑不计入额外模型配置。若无法安全修复，输出 `STOP_DATA_OR_IMPLEMENTATION_INVALID`。

## 7. Phase D：真实 Development

使用严格时间顺序的 purged walk-forward。禁止普通随机 K-Fold、打乱时间、全样本预处理、验证集无限调参、重新搜索阈值/Top-K/持仓期、根据 Regime 结果加过滤器、只展示最佳配置。

至少报告：

- pooled Top5 lift；
- 每 fold Top5 lift；
- 10bps/20bps 净期望；
- 胜率、盈亏比、交易数量、Opportunity 覆盖率、换手率、最大回撤；
- 5 种子稳定性；
- fold 中位数和最差四分位；
- 去除最佳 1% 和 5% 交易后的结果；
- 现有 Regime 下诊断结果。

Regime 只用于稳定性审查，不能用于本轮挑选交易范围。

候选选择顺序：

1. 数据和防泄漏全部有效；
2. median fold Top5 lift；
3. median fold 10bps net expectancy；
4. 正收益 fold 比例；
5. 种子稳定性；
6. 去除最佳 1%/5% 后仍有优势；
7. 参数邻域稳定。

## 8. 一次有限微调

初始结果后允许一次最多 4 个配置的局部微调，但必须：

- 只围绕初始阶段最稳定的一个候选；
- 不新增模型族、因子或特征选择体系；
- 不修改标签、0.60、Top5、成本、数据区间或 Regime 过滤器；
- 不触碰 Frozen Validation；
- 不进行第二轮微调；
- 未通过也不得继续追加。

允许的参数仅限相邻复杂度/正则化：正则强度、最大树深、最小叶样本、保守学习率与迭代数组合、subsample/feature fraction。

运行前先向 `FAST3_EXPERIMENT_CONTRACT.json` 的只追加附录登记：

- `selected_candidate`
- `reason_for_refinement`
- `parameters_to_refine`
- `exact_reserved_configs`

先登记后执行，最多 4 组。

## 9. 基准与通过条件

固定：

- `LEGACY_TOP5_LIFT=1.36122855`
- `LEGACY_NET_RETURN_10BPS=-0.001966`
- `PRE_REGISTERED_LIFT_GATE=1.50`

“显著优于旧基准”至少要求同时满足：

1. 预注册聚合 Top5 lift >= 1.50；
2. 相对 1.36122855 的 paired/bootstrap 95% CI 差值下界 > 0；不能配对时明确使用保守非配对 bootstrap；
3. median fold 10bps net expectancy > 0；
4. 超过半数 walk-forward folds 的 10bps 净期望为正；
5. 优势不完全依赖最佳 1% 交易；
6. 五个种子之间结论不反转；
7. 完整报告 20bps 结果。

任一候选都不同时满足，则立即停止，不得继续搜索。

## 10. Frozen Validation

仅在 Evidence Ledger 证明存在真正未污染历史区间时：

- Development 与唯一一次微调结束后选定一个候选；
- 冻结代码、配置、数据、模型 hash；
- 只运行一次 Frozen Validation；
- 运行后不得修改或重跑。

没有可信干净区间时：

- 输出 `NO_UNCONTAMINATED_HISTORICAL_HOLDOUT`；
- 生成固定候选和 forward shadow 所需最小配置；
- 不伪造历史验证，不连接实盘。

## 11. 防膨胀硬限制

不创建新的 V22 多层版本链。优先复用现有 FAST3 文件。

本轮最多允许新增到仓库源代码区：

- 2 个代码文件；
- 1 个针对性测试文件；
- 2 个配置/manifest 文件。

结果文件不计入，但只放 `$FAST3_RESULTS_ROOT`。禁止新 Atlas、Guard、Registry、Runner 调 Runner、多份重复 summary、整仓格式化、无关重构、Git commit/push/stage。

如现有模块能承载功能，直接修改。最终报告必须列出新增和修改文件，并说明必要性。

## 12. 必须产物

至少输出到 `$FAST3_RESULTS_ROOT`：

- `FAST3_EVIDENCE_LEDGER.json`
- `FAST3_EXPERIMENT_CONTRACT.json`
- `fast3_development_summary.json`
- `fast3_fold_metrics.csv`
- `fast3_predictions.parquet`
- `FAST3_DEVELOPMENT_REPORT.md`

报告必须含所有初始配置、所有微调配置、全部失败结果、五种子结果、与 V22.080B 比较、bootstrap 方法与 CI、成本敏感性、极端交易依赖、Regime 诊断、污染判断、Frozen 是否可用/执行、因子/标签/0.60 是否改变、总配置数及文件变更。

## 13. 唯一允许的最终主决策

从下列选择一个：

- `PASS_DEVELOPMENT_READY_FOR_FROZEN_VALIDATION`
- `PASS_DEVELOPMENT_READY_FOR_FORWARD_SHADOW`
- `STOP_NO_SIGNIFICANT_IMPROVEMENT_OVER_V22_080B`
- `STOP_NOT_ECONOMIC_AFTER_COST`
- `STOP_MODEL_INSTABILITY`
- `STOP_NO_UNCONTAMINATED_HISTORICAL_HOLDOUT`
- `STOP_DATA_OR_IMPLEMENTATION_INVALID`

Development 通过但无干净历史集时，使用 `PASS_DEVELOPMENT_READY_FOR_FORWARD_SHADOW`，并在次级状态记录无历史 holdout。

## 14. 完成定义和控制台最终摘要

只有真实数据 Development 已运行并有可验证产物，才能标记执行完成。仅完成框架、synthetic fixture、测试或空报告不得声称完成。

最终消息和报告必须输出：

- `FINAL_STATUS`
- `FINAL_DECISION`
- `EVIDENCE_LEDGER_PATH`
- `EXPERIMENT_CONTRACT_PATH`
- `CONTAMINATED_INTERVAL_COUNT`
- `CONFIRMED_CLEAN_INTERVAL_COUNT`
- `FROZEN_VALIDATION_AVAILABLE`
- `FROZEN_VALIDATION_EXECUTED`
- `INITIAL_CONFIG_COUNT`
- `REFINEMENT_CONFIG_COUNT`
- `TOTAL_CONFIG_COUNT`
- `MODEL_FAMILY_COUNT`
- `RANDOM_SEED_COUNT`
- `BEST_MODEL_NAME`
- `BEST_TOP5_LIFT`
- `LEGACY_TOP5_LIFT`
- `LIFT_DELTA`
- `LIFT_DELTA_CI_LOW`
- `LIFT_DELTA_CI_HIGH`
- `BEST_NET_RETURN_10BPS`
- `BEST_NET_RETURN_20BPS`
- `POSITIVE_FOLD_RATIO_10BPS`
- `FEATURES_CHANGED`
- `LABEL_CHANGED`
- `OPPORTUNITY_THRESHOLD_CHANGED`
- `DATA_LEAKAGE_TESTS_PASSED`
- `NEW_CODE_FILE_COUNT`
- `MODIFIED_FILE_COUNT`
- `REPORT_PATH`

现在开始执行。先建立只读证据地图，再冻结合同，随后运行防泄漏门禁、真实 Development、最多一次有限微调，并在硬停止点结束。
