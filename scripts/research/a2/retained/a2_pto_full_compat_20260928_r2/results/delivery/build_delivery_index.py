"""Create a Chinese reading index from fixed results, without changing analysis."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
source = ROOT / "results/analysis/ALL_COMBINATIONS.csv"
rows = {}
counts = Counter()
with source.open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        rows[(int(r["year"]), r["path_id"])] = r
        counts[(int(r["year"]), r["result_sign"])] += 1
assert len(rows) == 16388

examples = [
    ("预测器", "hgb__identity__diagonal__mean_variance", "ridge__identity__diagonal__mean_variance"),
    ("组内融合（RF＋Extra）", "random_trees__ridge_stack__diagonal__mean_variance", "random_trees__equal__diagonal__mean_variance"),
    ("风险", "hgb__identity__ledoit_wolf__mean_variance", "hgb__identity__diagonal__mean_variance"),
    ("优化", "ridge__identity__diagonal__mean_variance", "ridge__identity__diagonal__positive_equal"),
]
chosen = []
def pct(x):
    return f"{float(x) * 100:.2f}%"

lines = [
    "# 固定清单实验交付索引", "",
    "2025 验证和 2026 冻结研究评估的事前清单执行已结束。全部实际回放账户的独立账本审计通过，共核验 153,152,976 行、mismatch 为零；668 个冻结文件和 29 个保护输入哈希一致。正式完整候选池仍为 `BLOCKED_DATA`，不能将本次合格子池研究回放称为完整池成功或首次盲测。", "",
    "## 范围与覆盖", "",
    "31 个逻辑预测成员、11 个预先限定的成员组、11 种组内融合、13 种风险模型、4 种优化方法；目标仓位融合和 RL 单列。成员组是事前有限清单，并非 31 成员的全部幂集。", "",
    "两年共 16,388 路线：13,424 路线完成独立账户回放，2,964 路线保留失败。每年 6,708 PTO＋4 RL 完成；1,196 PTO＋全部 286 目标仓位融合因 linear_q 依赖失败而受阻。没有目标仓位融合实际账户比较证据。", "",
    "| 年度 | 正收益 | 负收益 | 零收益 | 失败 |", "| --- | ---: | ---: | ---: | ---: |",
]
for year in (2025, 2026):
    lines.append(f"| {year} | {counts[(year, 'POSITIVE')]:,} | {counts[(year, 'NEGATIVE')]:,} | {counts[(year, 'ZERO')]:,} | {counts[(year, 'FAILED_OR_UNRESOLVED')]:,} |")
lines += ["", "底层 172 个拟合规格：160 成功、12 失败；4 个同目标 Elastic Net 数值续算使实际 fit 调用为 176。评估账户阶段 fit 为零。MLP 固定预算未收敛警告保留；可用不等于收敛。linear_q 的 LP 返回空解后报错，原 HiGHS 状态未完整保留，不能补称已确认某一种退出原因。", "",
          "2025 / 2026 分别有 1,924 / 1,939 条完成路线包含近似求解，共 710,749 次固定迭代上限决策；可行账户完成不代表所有优化达到 KKT 收敛。", "",
          "## 固定上下文例子", "",
          "以下均为 2026 截至 9 月 24 日、扣共同费用后的价格指数指示性研究结果，用于描述固定清单，不据此选择或追加新策略。每一行只改变表中指定层。", "",
          "| 改变维度 | 账户 | 净收益 | 最大回撤 | 平均股票敞口 | 费用 | 未认证净值日 | 迭代上限决策 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
for dimension, treatment, reference in examples:
    for label, path_id in (("处理", treatment), ("固定参照", reference)):
        r = rows[(2026, path_id)]
        chosen.append(r)
        lines.append(f"| {dimension} / {label} | `{path_id}` | {pct(r['indicative_return'])} | {pct(r['indicative_max_drawdown'])} | {pct(r['mean_gross_exposure'])} | {float(r['total_fees']):,.0f} | {int(float(r['uncertified_nav_days']))} | {int(float(r['optimization_iteration_limit_decisions']))} |")
interactions = {}
for year in (2025, 2026):
    interactions[year] = (float(rows[(year, "hgb__identity__ledoit_wolf__mean_variance")]["indicative_return"])
                          - float(rows[(year, "ridge__identity__ledoit_wolf__mean_variance")]["indicative_return"])
                          - float(rows[(year, "hgb__identity__diagonal__mean_variance")]["indicative_return"])
                          + float(rows[(year, "ridge__identity__diagonal__mean_variance")]["indicative_return"]))
lines += ["", "这些例子中若干 2026 账户有 87/183 个未认证净值日，不能把它们与 0 未认证日账户的收益差当作完整可比的真实股东收益证据。stale/unknown 估值字段和候选 UNKNOWN 身份是不同概念，详细表见审阅说明。守恒审计通过证明按冻结规则核算一致，并未消除数据资格边界。", "",
          f"HGB/Ridge、LW/diagonal 的四格收益交互（固定 MV）为 2026 {interactions[2026]*100:+.4f} 个百分点、2025 {interactions[2025]*100:+.4f} 个百分点；敞口、回撤和费用的对应交互同时见 INTERACTIONS.csv。此为相关账户的描述性四格差值，不能当作 IID 或因果效应。组内学习融合也有负结果，不能把各层边际冠军直接拼接。", "",
          "Ridge＋diagonal＋robust MV 在两年均全现金、收益/回撤/费用为零，不能解释成学习能力提高。原生预测指标、校准 mu 指标和账户结果分别报告；原生概率/分位数/分布尾部虽保存，主 PTO 经 mu 接口和独立风险层运行，不能据此宣称原生尾部直接进入下游优化的收益。", "",
          "## 风险 × 优化全格比较", "",
          "![风险与优化的固定单元比较](risk_optimizer_comparison.png)", "",
          "每格是同样 129 条已完成独立账户的描述性均值，包含已标记近似求解，不是目标仓位融合或可投资合成账户。正权等权的 258 个预测流年度在 13 风险下四项指标严格相同，对照验证通过。", "",
          "## 数据与时间边界", "",
          "原 24 家机构各 Top100 合法股票并集，按最晚实际申报后第 5 个美股交易日生效；新季度未公开或未生效时沿用最近有效季度。2026 原始 111,868 候选键中 QUALIFIED 62,393、UNKNOWN 47,271、明确不合格 2,204；隔离一个已知 GLW 冲突后新买可用 62,392 键。83 个已离池持仓上下文只用于持有/卖出，不能新买。所有原始键与不可预测原因都保存。", "",
          "训练、标准化、校准与时间合法折外融合只用 <2026 数据；整个批次冻结后才运行 2026，保留此前曝光记录。收益为价格指数坐标回放，身份映射、机构选择及供应商到达时间仍有局限，未认证为真实股东总收益。", "",
          "## 完整产物与核验", "",
          "- [完整报告](../analysis/REPORT.md)；[全部组合、正负与失败](../analysis/ALL_COMBINATIONS.csv)；[分层发现及净值质量审阅说明](../ANALYSIS_FINDINGS.md)。",
          "- [350 行各层主效应](../analysis/FACTOR_MAIN_EFFECTS.csv)；[41,870 行配对比较](../analysis/PAIRED_EFFECTS.csv)；[45,704 行四格交互](../analysis/INTERACTIONS.csv)。",
          "- [1,520 行原生/校准/融合预测指标](../analysis/PREDICTION_METRICS.csv)；[账本文件索引](../analysis/LEDGER_INVENTORY.csv)；[固定分析收据](../analysis/ANALYSIS_RECEIPT.json)。",
          "- [预测接口兼容矩阵](../../COMPATIBILITY_MATRIX.csv)；[风险与优化兼容矩阵](../../RISK_OPTIMIZER_COMPATIBILITY.csv)；[事前清单](../../PREDECLARED_PATHS.csv)；[合同](../../EXPERIMENT_CONTRACT.md)。",
          "- [训练与依赖失败独立核对](../audits/DECLARED_COVERAGE_INDEPENDENT_REVIEW.json)；[最终工件完整性](../audits/FINAL_BATCH_INTEGRITY_REVIEW.json)。",
          "- [2025 全量独立审计](../evaluation_2025/independent_audit/AUDIT_COVERAGE_RECEIPT.json)；[2026 全量独立审计](../evaluation_2026/independent_audit/AUDIT_COVERAGE_RECEIPT.json)。",
          "", "668 个封存绑定文件及 29 个保护输入全部哈希一致；证据限这些已登记文件，不冒称整个旧目录逐字节认证。本任务没有在旧批次或 Raw A2 目录写入、删除。模型、预测、目标、订单、执行结果、成交、费用、持仓、现金/NAV 的关联保留在对应年度目录。事前清单执行结束，不追加模型、种子、期限、阈值或权重搜索。", ""]
(OUT / "DELIVERY.md").write_text("\n".join(lines), encoding="utf-8")
(OUT / "FIXED_CONTEXT_EXAMPLES.json").write_text(json.dumps({"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "examples": chosen, "new_fits": 0, "new_searches": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": "READING_INDEX_CREATED", "path_years": len(rows), "example_rows": len(chosen)}))
