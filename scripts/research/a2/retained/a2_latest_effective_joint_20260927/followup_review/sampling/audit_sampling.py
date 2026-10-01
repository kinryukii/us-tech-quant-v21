"""Read-only reproduction of frozen date sampling; no model import or fit."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CONTRACT_PATH = ROOT / "joint_linear_tree_artifacts/PRE_FIT_CONTRACT.json"
RECEIPT_PATH = ROOT / "joint_linear_tree_artifacts/FIT_RECEIPT.json"
SOURCE_PATH = ROOT / "joint_linear_tree.py"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def reproduce_sampler():
    # Compile the original function alone, without importing training code,
    # estimator modules, checkpoints or a model registry.
    text = SOURCE_PATH.read_text(encoding="utf-8")
    node = next(x for x in ast.parse(text).body if isinstance(x, ast.FunctionDef) and x.name == "select_dates")
    definition = ast.get_source_segment(text, node)
    namespace = {"np": np, "pd": pd}
    exec(compile(definition, str(SOURCE_PATH)+":select_dates_only", "exec"), namespace)
    return namespace["select_dates"], hashlib.sha256(definition.encode("utf-8")).hexdigest()


def describe_stage(frame, stage, end, saved, select_dates, budget, multiplier):
    train = frame[(frame.signal_date >= "2023-01-01") & (frame.signal_date < end) & (frame.label_end_date < end)].copy()
    maximum_base_rows = budget // multiplier
    selected, dates = select_dates(train, maximum_base_rows)
    dates = pd.DatetimeIndex(dates)
    actual = [str(x.date()) for x in dates]
    assert actual == saved["dates"], (stage, "DATE_SELECTION_MISMATCH")
    assert len(selected) == saved["base_rows"]
    assert len(selected)*multiplier == saved["counterfactual_rows"] <= budget
    assert str(selected.signal_date.max().date()) == saved["train_signal_max"]
    assert str(selected.label_end_date.max().date()) == saved["train_label_end_max"]
    counts = train.groupby("signal_date", sort=True).size()
    assert len(dates) == min(len(counts), maximum_base_rows // int(counts.max()))
    # Independently reproduce the index arithmetic as well as invoking the
    # original function, so stale receipt data cannot silently be accepted.
    expected_indices = np.unique(np.linspace(0, len(counts)-1, num=len(dates), dtype=int))
    assert list(counts.index[expected_indices]) == list(dates)
    positions = counts.index.get_indexer(dates)
    calendar_gaps = np.diff(dates.to_numpy(dtype="datetime64[D]")).astype(int)
    omitted_session_gaps = np.diff(positions)-1
    max_gap_index = int(np.argmax(calendar_gaps))
    months = pd.period_range(train.signal_date.min(), train.signal_date.max(), freq="M")
    rows = []
    for month in months:
        available = train.loc[train.signal_date.dt.to_period("M").eq(month)]
        chosen = selected.loc[selected.signal_date.dt.to_period("M").eq(month)]
        chosen_dates = sorted(chosen.signal_date.unique())
        rows.append({"stage": stage, "year": month.year, "month": str(month),
            "eligible_dates": int(available.signal_date.nunique()), "eligible_base_rows": len(available),
            "selected_date_count": len(chosen_dates), "selected_dates": ";".join(str(pd.Timestamp(x).date()) for x in chosen_dates),
            "selected_base_rows": len(chosen), "counterfactual_multiplier": multiplier,
            "counterfactual_rows": len(chosen)*multiplier, "stage_row_budget": budget,
            "stage_budget_fraction_contributed": len(chosen)*multiplier/budget})
    annual = []
    for year in sorted(train.signal_date.dt.year.unique()):
        chosen = selected.loc[selected.signal_date.dt.year.eq(year)]
        available = train.loc[train.signal_date.dt.year.eq(year)]
        annual.append({"year": int(year), "eligible_dates": int(available.signal_date.nunique()),
            "selected_dates": int(chosen.signal_date.nunique()), "selected_base_rows": len(chosen),
            "counterfactual_rows": len(chosen)*multiplier})
    summary = {"stage": stage, "cutoff_exclusive": end, "eligible_base_rows": len(train),
        "eligible_dates": len(counts), "densest_day_rows": int(counts.max()),
        "maximum_base_rows": maximum_base_rows, "date_count_rule": "floor(maximum_base_rows / densest_day_rows)",
        "selected_date_count": len(dates), "selected_dates": actual, "base_rows": len(selected),
        "counterfactual_multiplier": multiplier, "counterfactual_rows": len(selected)*multiplier,
        "row_budget": budget, "budget_utilization": len(selected)*multiplier/budget,
        "unused_budget_rows": budget-len(selected)*multiplier,
        "date_coverage_fraction": len(dates)/len(counts), "base_row_coverage_fraction": len(selected)/len(train),
        "month_count": len(months), "missing_months": [r["month"] for r in rows if r["selected_date_count"] == 0],
        "maximum_calendar_days_between_selected_dates": int(calendar_gaps.max()),
        "maximum_calendar_gap_start": actual[max_gap_index], "maximum_calendar_gap_end": actual[max_gap_index+1],
        "maximum_unsampled_eligible_sessions_between_selected_dates": int(omitted_session_gaps.max()),
        "first_and_last_eligible_dates_selected": dates[0] == counts.index[0] and dates[-1] == counts.index[-1],
        "annual": annual, "exact_date_receipt_match": True, "exact_row_receipt_match": True,
        "implementation_deviation_detected": False}
    return summary, rows


def write_report(stages, rows):
    validation, final = stages
    month_lookup = {(r["stage"], r["month"]): r for r in rows}
    lines = ["# 30/27 个训练日期与预算：只读审计", "",
        "**结论：实际日期和行数完全符合原冻结采样器，没有发现实现偏离；时间覆盖稀疏属于原固定设计的不足。** 本审计不改变本批模型。", "",
        "这里的 validation 指供 2025 验证使用的模型，其训练年份为 2023–2024；final 指供 2026 测试使用的最终模型，其训练年份为 2023–2025。30 和 27 均为模型实际训练日期数，不是整个数据集日期数，也不是验证评分日期数。", "",
        "**适用范围仅为七个监督动作价值估计器：Ridge、Elastic Net、逻辑回归、HGB、Q10、Q50、Q90。** 30/27 日期及本预算不代表直接组合 MLP、RL、PCA/协方差风险或状态辅助模型的日期覆盖。", "",
        "## 实际覆盖与预算", "",
        "| 训练阶段 | 可用日期 / 实际训练日期 | 原始观测行 | 状态动作行 | 20万预算利用率 | 未用预算 | 缺月 | 最大日期间隔 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for stage in stages:
        lines.append(f"| {stage['stage']} | {stage['eligible_dates']} / {stage['selected_date_count']} ({stage['date_coverage_fraction']:.1%}) | {stage['base_rows']:,} | {stage['counterfactual_rows']:,} | {stage['budget_utilization']:.4%} | {stage['unused_budget_rows']:,} | {len(stage['missing_months'])}/{stage['month_count']} | {stage['maximum_calendar_days_between_selected_dates']} 自然日；中间漏 {stage['maximum_unsampled_eligible_sessions_between_selected_dates']} 个可用会话 |")
    lines += ["", "每条原始股票观测固定组合 3 种账户状态 × 5 种动作，即倍率 15；反事实行数不能解释为独立市场样本数。7 个监督方法共用同阶段日期和样本，实际拟合日志的行数全部一致。", "",
        "原算法先计算 `floor(200000 / 15) = 13333` 条基准观测预算，再按最密日保守预留整个横截面：validation 最密日 442 行，`floor(13333/442)=30`；final 最密日 480 行，`floor(13333/480)=27`。随后在全部可用日期索引上等距取整，首尾日期均入选。这解释了为什么最终模型覆盖年份增加，实际日期反而减少。算法没有按实际已选日的剩余容量补采，也没有保证每月被选中。", "",
        f"validation 最大间隔为 {validation['maximum_calendar_gap_start']} 至 {validation['maximum_calendar_gap_end']}；final 为 {final['maximum_calendar_gap_start']} 至 {final['maximum_calendar_gap_end']}。final 未覆盖月份：{', '.join(final['missing_months'])}。", "",
        "## 每年与每月实际日期", "",
        "| 阶段 | 年份 | 已选日期 / 可用日期 | 基准观测 | 状态动作行 |", "|---|---:|---:|---:|---:|",
    ]
    for stage in stages:
        for year in stage["annual"]:
            lines.append(f"| {stage['stage']} | {year['year']} | {year['selected_dates']} / {year['eligible_dates']} | {year['selected_base_rows']:,} | {year['counterfactual_rows']:,} |")
    lines += ["", "2024 年可用日的 250/252 差异来自标签成熟边界：validation 不允许标签跨入 2025，final 可以使用在 2025 成熟的标签。", "",
        "下表列月份内的实际日号；“—”表示该训练阶段不包含此年，“缺”表示该月有可用日期但没有被采中。逐月原始行数、动作行数和预算贡献详见同目录 `coverage.csv`。", "",
        "| 月份 | validation 实际日号 | final 实际日号 |", "|---|---|---|",
    ]
    for month in sorted({r["month"] for r in rows}):
        cells = []
        for stage in ("validation", "final"):
            row = month_lookup.get((stage, month))
            cells.append("—" if row is None else ", ".join(s[-2:] for s in row["selected_dates"].split(";") if s) or "缺")
        lines.append(f"| {month} | {cells[0]} | {cells[1]} |")
    lines += ["", "## 实现与设计的区别", "",
        "本审计校验原输入 SHA256、按原标签成熟条件重建可用日期，仅提取原源码中的 `select_dates` 函数独立运行，并另外复算等距索引；与保存日期列表、基准行数、15 倍行数及所有拟合日志逐项一致。没有导入训练模块、加载模型或调用 fit，没有读取 2026 经济值，既有输入/源码哈希未变。详见 `VERIFICATION.json`。", "",
        "实现没有偏离，不能因此推断当前设计覆盖充分：final 只见 3.6% 的可用训练日期、漏掉 9 个月，且预算尚余 30,845 行。该不足可能降低状态覆盖和跨时期稳定性；本审计没有用经济表现判断影响大小，也不重训或替换本批模型。", "",
        "## 下一版明确方案（仅建议，未执行）", "",
        "若保持 20 万行预算，建议预先登记“按月均衡、月内分散、股票确定性抽样”：仍取最多 13,333 条基准观测和 15 倍动作扩展，保留当前时间划分和标签到期门槛。", "",
        "1. 将基准观测配额均分至各训练月，余数按月份先后分配。24 个月各 555/556 条；36 个月各 370/371 条。总动作行最多 199,995。",
        "2. 每月在可用日期序列的四个固定时间分位取 4 日，将月配额均分到这些日。于是 validation 覆盖 96 个日期，final 覆盖 144 个日期，并保证所有训练月有代表。",
        "3. 日内按固定 seed 与日期/证券键的哈希排序取股票，不读取收益、价格跳变或模型误差选样。每条入选观测仍保留全部 3×5 状态动作；验证与测试继续使用完整合格池。",
        "这一方案明确改变“每个训练日必须保留完整横截面”的旧设计，必须作为下一版独立登记，不能悄悄补入本批。如果必须保留完整横截面，则建议改为每月至少一日、事前将预算提高至 30 万；当前 final 最密日上界下，36 日 × 480 股 × 15 = 259,200 行。两种约束选择都应先冻结，再训练，不能据收益决定。", "",
        "下一版验收应检查每月覆盖、日期最大间隔、各月观测配额、样本哈希、标签边界与总预算；覆盖变好仍不等于已证明泛化或避免过拟合。",
    ]
    (HERE / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    contract, receipt = read(CONTRACT_PATH), read(RECEIPT_PATH)
    source = Path(contract["source"])
    original_hashes = {str(p): sha(p) for p in [CONTRACT_PATH, RECEIPT_PATH, SOURCE_PATH, source]}
    assert original_hashes[str(source)] == contract["source_sha256"] == receipt["source_sha256"]
    # Only identity, date and availability metadata are read, never return,
    # prediction, price or economic-result columns.
    columns = ["signal_date", "ticker", "label_end_date", "label_available", "new_buy_eligible"]
    frame = pd.read_parquet(source, columns=columns)
    frame = frame.loc[frame.label_available & frame.new_buy_eligible].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert frame.signal_date.lt("2026-01-01").all() and frame.label_end_date.lt("2026-01-01").all()
    assert not frame.duplicated(["signal_date", "ticker"]).any()
    multiplier = len(contract["action_grid"])*len(contract["counterfactual_states_current_cash_age"])
    budget = contract["maximum_counterfactual_rows_per_fit"]
    select_dates, function_hash = reproduce_sampler()
    stages, rows = [], []
    for stage, end in (("validation", "2025-01-01"), ("final", "2026-01-01")):
        summary, coverage = describe_stage(frame, stage, end, receipt["sampling"][stage], select_dates, budget, multiplier)
        for fit in [r for r in receipt["fits"] if r["stage"] == stage]:
            assert fit["train_rows"] == summary["counterfactual_rows"]
        stages.append(summary)
        rows.extend(coverage)
    pd.DataFrame(rows).to_csv(HERE / "coverage.csv", index=False, encoding="utf-8-sig")
    assert all(sha(p) == expected for p, expected in original_hashes.items())
    verification = {"status": "PASS_EXACT_FROZEN_SAMPLING_REPRODUCTION", "read_columns": columns,
        "source_hashes": original_hashes, "select_dates_function_sha256": function_hash, "stages": stages,
        "models_loaded": 0, "model_calls": 0, "fit_calls": 0, "test2026_economic_values_read": 0,
        "existing_sources_and_models_modified": False,
        "conclusion": "Implementation matches frozen date sampler and saved rows exactly; any time-coverage weakness is a limitation of the fixed design, not an implementation deviation."}
    (HERE / "VERIFICATION.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(stages, rows)
    print(json.dumps({"status": verification["status"], "stages": stages}, ensure_ascii=False))


if __name__ == "__main__":
    main()
