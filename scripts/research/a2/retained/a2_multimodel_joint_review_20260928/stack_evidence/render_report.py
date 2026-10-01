from pathlib import Path
import json
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent/'a2_multimodel_joint_20260928'
def load(name): return json.loads((HERE/name).read_text(encoding='utf-8'))
def link(label,path,line=None):
    return f'[{label}]({path.as_posix()}{":"+str(line) if line else ""})'

result=load('RESULT.json');p=result['posthoc_verification'];models=load('meta_internal_evidence.json')
stationarity=load('ridge_label_coefficient_stationarity.json')
oof=load('oof_full_reconstruction.json')
rows=[]
for m in models:
    rows.append(f"| {m['stage']} | {'＋'.join(map(str,m['oof_years']))} | {m['train_rows']:,} | {m['train_signal_max']} | {m['train_label_end_max']} | {m['cutoff_exclusive']} |")
text=f'''# 2025 堆叠证据链：冻结工件实物核验与全量输出重现

结论：现有 `validation` 工件完整重现了原 2025 堆叠的 **{p['days']} 个决策日、{p['stock_date_rows']:,} 个股票日、{p['action_values']:,} 个动作预测值**，最大绝对差为 **{p['validation_max_abs_error']:.3g}**，目标仓位不一致 **{p['validation_target_mismatches']}** 行。没有重新训练，也没有重新跑组合账本。原结果与截止 2024 年的 validation 链一致，未发现把 final 阶段用于这份 2025 账本的输出证据。

不过，原回放没有逐策略写出运行时加载的模型、阶段和归一化器哈希。**本报告不能补造当时不存在的加载日志。**结论等级是“原始冻结记录＋事后全量确定性输出重现”，不能升格为“当时逐次加载已被独立签证”。

## 两阶段和标准化器对应

| 元模型阶段 | 元层 OOF 年份 | scaler 与 Ridge 行数 | 最大信号日期 | 最大标签终点 | 排他训练边界 |
|---|---|---:|---|---|---|
{chr(10).join(rows)}

2024 OOF 的基础模型是 `early`：训练信号截止 2023-12-27、标签终点截止 2023-12-29。2025 OOF 和 2025 实际推理基础模型是 `validation`：训练信号截止 2024-12-27、标签终点截止 2024-12-31。`final` 基础模型训练信号截止 2025-12-29、标签终点截止 2025-12-31，只适于其冻结设计声明的 2026 推理用途。这些训练时钟来自原训练收据；本次把其工件哈希和 OOF 预测重现对应起来，没有把元层的 2025 OOF 当成 2025 验证元训练数据。

两个 joblib 都实际包含 `StandardScaler → Ridge`。从已保存 OOF 矩阵纯算术计算的均值、总体方差、标准差，与 joblib 内 `mean_ / var_ / scale_` **逐值完全相等**；`n_samples_seen_` 分别为 90,000 / 180,000。joblib 的 scaler 均值/scale、Ridge 系数/截距也与原 `FIT_RECEIPT.json` 完全相等。没有调用 `.fit()` 来“验证”参数。

另外用保存的 OOF 标签直接计算 Ridge 正规方程残差：validation / final 的相对 L2 残差分别为 {stationarity[0]['relative_normal_equation_residual']:.3g} / {stationarity[1]['relative_normal_equation_residual']:.3g}，截距与中心化公式完全相等。这是已有系数对原目标的算术一致性诊断；原 `lsqr` 为近似解，不能把 `tol=1e-6` 直接当作正规方程相对残差阈值。未重求或优化系数，详见 {link('标签—系数残差证据',HERE/'ridge_label_coefficient_stationarity.json')}。

| 阶段 | meta joblib SHA-256 |
|---|---|
| validation | `{models[0]['artifact_sha256']}` |
| final | `{models[1]['artifact_sha256']}` |

上述文件哈希各自同时匹配原 fit 收据及原 `FROZEN_BEFORE_REPLAY.json`。内部数组单独散列了 dtype、shape 和小端 float64 内容，见 {link('内部证据 JSON',HERE/'meta_internal_evidence.json')}；可检索对应表见 {link('阶段—哈希映射 CSV',HERE/'meta_stage_hash_mapping.csv')}。

## OOF 与训练标签的实物证据

本次读取原始 pre-2026 特征表，按保存的股票日 key 对齐，完整重建了两个年份的 OOF，各 6,000 个股票日 × 3 个账户状态 × 5 个动作 = 90,000 行。2024 覆盖 250 个日期，2025 覆盖 248 个日期；15 个扩增行共享一个股票日结果，不能算作 15 份独立样本。

两年保存标签与原函数按固定容量、费用、风险惩罚及 ±20% 训练截尾重建的标签完全相等。2024 元特征最大绝对误差 {oof[0]['feature_max_abs_error']:.3g}，2025 为 {oof[1]['feature_max_abs_error']:.3g}，均低于 1e-12；这点浮点差来自重新分块推理，未改原矩阵。原样本 key / 矩阵文件哈希均匹配原收据。完整结果见 {link('OOF 全量重建证据',HERE/'oof_full_reconstruction.json')} 和 {link('基础预测器时钟',HERE/'predictor_clocks.json')}。

## 原回放路径与本次实际加载

原冻结代码路径为：

1. {link('evaluate.py:130',ROOT/'evaluate.py',130)} 对 2025 设置 `stage='validation'`，{link('evaluate.py:151',ROOT/'evaluate.py',151)} 将其传给 `PolicyV2(name,stage)`。
2. {link('adapters.py:23',ROOT/'adapters.py',23)} 将同一 stage 传给 `StackedPolicy`。
3. {link('ensemble.py:128',ROOT/'ensemble.py',128)} 根据 stage 选择唯一 meta 收据记录，先校验文件哈希，再读取 meta joblib；随后加载同阶段基础模型、MLP 和归一化器，并核对 `inference_dependencies[stage]`。
4. {link('adapters.py:38',ROOT/'adapters.py',38)} 每日仅根据当时正持仓更新 age，再计算动作值及有预算约束的目标仓位。

原冻结清单创建时间为 `{result['original_records']['frozen_created_utc']}`，列出的 {result['original_records']['frozen_manifest_items']} 个输入当前全部匹配；原 `COMPLETE.json` 记录 `fit_attempts=0`、`sources_unchanged=true`。这些是**当时保存的记录**。清单包含 validation 和 final 两套文件，故“清单匹配”本身不证明某策略当时加载哪一套。

本次另外拦截 `joblib.load / numpy.load / torch.load`，生成 {link('本次实际加载记录',HERE/'posthoc_loaded_hashes.csv')}，明确标记 `POSTHOC_ACTUAL_LOAD`。它把两个 meta、十四个基础监督工件、两个 MLP 和两个 MLP 归一化器分别对应回冻结哈希。不能把这张新记录解释成原回放期间生成的记录。

## 原 2025 输出的全量指纹辨识

对每个已保存决策日，使用原 pre-2026 特征、原 `decision_input_tickers` 和原 `signal_contexts` 的账户持仓/现金/预算；age 严格按原 adapter 的顺序，只从历次 ctx 中的正持仓累计并重置。未用收益标签推理，也未改变历史账户状态。

validation 工件重推得到 {p['validation_matching_cells_atol_1e_12']:,}/{p['action_values']:,} 个动作值在 1e-12 内相等，其中 {p['validation_exact_cells']:,} 个浮点值数值完全相等；重建分配器目标与历史 `model_decisions_json` 的差异为 {p['validation_target_mismatches']}，历史 raw 目标与 `target_decisions.raw_model_weight` 的差异为 {p['raw_vs_target_ledger_mismatches']}。这把“模型 → 标准化器 → 特征/ctx → 动作值 → 原目标账本”连接起来。

**事后技术负对照：**用 final 工件在完全相同的历史输入/账户状态重推，{p['final_negative_control_distinct_days']}/{p['days']} 天出现差异，{p['final_negative_control_distinct_cells']:,}/{p['action_values']:,} 个动作值差异超过 1e-12，最大绝对差 {p['final_negative_control_max_abs_error']:.6g}。该对照消费了训练至 2025 年的模型，不能作为样本外比较；没有计算其组合仓位、交易或收益，也没有据此选模型。

逐日证据见 {link('每日输出指纹 CSV',HERE/'daily_output_fingerprint_comparison.csv')}；每个股票日的 5 个历史、validation 与 final 技术负对照值见 {link('全量动作值对照 Parquet',HERE/'all_stock_action_output_comparison.parquet')}。各动作下标 0–4 对应仓位 0%、2.5%、5%、7.5%、10%。

## 结果标签和边界

本次不修改原报告或原账本。建议新报告统一将该 2025 结果标为：

> **2025 冻结 validation 堆叠的回溯价格指数结果；原预测与目标经事后全量重现；非盲测，缺原始逐策略运行时加载签证。**

不应标为“前瞻实盘验证”“独立盲测冠军”“原运行时加载记录齐全”或“已证明对所有形式的未来泄漏免疫”。本次证明覆盖已保存 pre-2026 表、模型/标准化器、原代码、原 ctx 以及原输出之间的一致性；不额外认证供应商历史到达时钟、完整 13F 池来源或股东总收益价格坐标。基础模型 OOF → 实际推理时重新拟合带来的分布漂移、三状态网格中现金与原仓位共线等方法局限仍存在。

执行期间 fit/backward 禁止守卫计数为 {result['no_fit_attempts']}；输入前后哈希完全不变。原始工件未改、未训练、未跑组合、未读 2026 结果、未调权重或重选冠军。机器结论见 {link('RESULT.json',HERE/'RESULT.json')}，可复核只读脚本见 {link('audit_stack.py',HERE/'audit_stack.py')}。
'''
(HERE/'REPORT.md').write_text(text,encoding='utf-8')
print('REPORT_WRITTEN',HERE/'REPORT.md')
