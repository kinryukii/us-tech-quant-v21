"""Publish all prespecified policies and reused controls; no winner deployment."""
from pathlib import Path
from datetime import datetime, timezone
import json
import hashlib
import numpy as np
import pandas as pd
from portfolio_policy import POLICIES

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
OLD = WORK / "a2_buy_sell_cash_multimodel_20260928"
LABELS = {"base_ridge": "Ridge单模型", "base_hgb": "HGB单模型", "base_mlp": "MLP单模型",
          "fixed_pred": "固定预测融合", "learned_fixed": "学习固定权重", "stack_ridge": "线性Stacking",
          "stack_mlp": "小型MLP Stacking", "conditional_gate": "条件门控", "ridge_then_hgb": "Ridge→HGB修正",
          "hgb_then_ridge": "HGB→Ridge修正", "decision_blend": "目标仓位融合",
          "ensemble_equal": "旧等权集成", "ensemble_consensus_risk": "旧分歧风险", "ensemble_stacked": "旧学习权重",
          "original_A2_scores_common_account_reference_r1": "原A2分数共同参照"}


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_sources(mapping):
    for path, digest in mapping.items():
        assert sha(path) == digest, f"FROZEN_DEPENDENCY_DRIFT:{path}"


def expected_calendar(year):
    if year == 2025:
        price_path = WORK / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
        prices = pd.read_parquet(price_path, columns=["ticker", "trade_date"])
        days = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") & prices.trade_date.between("2025-07-01", "2025-12-31"), "trade_date"].unique()))
    else:
        calendar_path = WORK / "a2_latest_effective_joint_20260927/data/calendar.parquet"
        days = pd.DatetimeIndex(pd.read_parquet(calendar_path).query("is_test").trade_date)
    assert len(days) == (128 if year == 2025 else 183)
    assert days.is_unique and days.is_monotonic_increasing
    return days


def check_dates(folder, year, expected):
    daily = pd.read_parquet(folder / "daily.parquet")
    actual = pd.DatetimeIndex(daily.date)
    assert actual.equals(expected), f"ACCOUNT_WINDOW_DRIFT:{folder}"
    return {"year": year, "account": str(folder), "days": len(actual),
            "first_date": str(actual[0].date()), "last_date": str(actual[-1].date()),
            "exact_frozen_calendar_match": True}, daily


def reused(year, name):
    if name == "original_A2_scores_common_account_reference_r1":
        folder = WORK / name / "account"
        receipt = read(folder / "PATH_COMPLETE.json")
        metric = receipt["metrics"]
        result = {"policy": name, "year": year, "days": metric["days"],
                  "indicative_net_return": metric["net_bookkeeping_return"], "indicative_max_drawdown": metric["max_drawdown"],
                  "mean_actual_cash": metric["mean_actual_cash_weight"], "fees_usd": metric["fees_usd"],
                  "half_turnover": metric["cumulative_half_turnover"], "trades": metric["trades"],
                  "uncertified_days": metric["uncertified_days"], "actual_names_max": metric["actual_position_count_max"]}
    else:
        folder = OLD / ("ensemble_2025_H2" if year == 2025 else "ensemble_2026") / "cost_10" / name
        receipt = read(folder / "PATH_COMPLETE.json")
        metric = receipt["metrics"]
        daily = pd.read_parquet(folder / "daily.parquet")
        nav = np.r_[1e6, daily.nav.to_numpy(float)]
        result = {"policy": name, "year": year, "days": metric["days"], "indicative_net_return": metric["indicative_return"],
                  "indicative_max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()) if np.isfinite(nav).all() else None,
                  "mean_actual_cash": metric["mean_cash"], "fees_usd": metric["fees"], "half_turnover": metric["half_turnover"],
                  "trades": metric["trades"], "uncertified_days": metric["uncertified_days"], "actual_names_max": metric["actual_names_max"]}
    hashes = {str(folder / "PATH_COMPLETE.json"): sha(folder / "PATH_COMPLETE.json")}
    for ledger, digest in receipt["ledger_sha256"].items():
        path = folder / (ledger + ".parquet")
        assert sha(path) == digest
        hashes[str(path)] = digest
    result.update(source="frozen_existing_account_reused", blind_test=False, shareholder_total_return_certified=False)
    return result, hashes, folder


def table(frame, include_qualification=False):
    lines = ["|政策|净记账收益 / 指示收益|最大回撤|平均实际现金|费用美元|未认证估值日|",
             "|---|---:|---:|---:|---:|---:|"]
    for row in frame.itertuples():
        def pct(value):
            return f"{100*value:.2f}%" if pd.notna(value) else "未知"
        lines.append(f"|{LABELS[row.policy]}|{pct(row.indicative_net_return)}|{pct(row.indicative_max_drawdown)}|{pct(row.mean_actual_cash)}|{row.fees_usd:,.0f}|{row.uncertified_days}|")
    return "\n".join(lines)


def main():
    base = read(ROOT / "base_artifacts/TRAIN_RECEIPT.json")
    meta = read(ROOT / "meta_artifacts/TRAIN_RECEIPT.json")
    assert base["status"] == "PASS_FIXED_NINE_BASE_FITS" and base["regressor_fit_calls"] == 9
    assert meta["status"] == "PASS" and meta["predictive_fits_or_solves"] == 12
    lock = read(ROOT / "DESIGN_LOCK.json")
    amendment = read(ROOT / "IMPLEMENTATION_GUARDS.json")
    assert sha(ROOT / "DESIGN_LOCK.json") == amendment["parent_design_lock_sha256"]
    effective_sources = dict(lock["source_sha256"])
    for path, change in amendment["changes"].items():
        assert effective_sources[path] == change["previous_sha256"]
        effective_sources[path] = change["corrected_sha256"]
    validate_sources(effective_sources)
    assert sha(ROOT / "base_artifacts/BASE_PRE_FIT.json") == lock["base_prepare_sha256"]
    assert sha(ROOT / "meta_artifacts/META_DESIGN.json") == lock["meta_design_sha256"]
    assert base["parent_design_lock_sha256"] == sha(ROOT / "DESIGN_LOCK.json")
    validate_sources(read(ROOT / "NEW_DATA_ADMISSION.json")["source_sha256"])
    rows, source_bindings = [], dict(effective_sources)
    account_days, date_checks = [], []
    for year in [2025, 2026]:
        expected = expected_calendar(year)
        folder = ROOT / f"evaluation_{year}"
        completed = read(folder / "COMPLETE.json")
        assert completed["status"] == "PASS" and completed["policies"] == 11 and completed["evaluation_fit_attempts"] == 0
        validate_sources(read(folder / "FROZEN_BEFORE_REPLAY.json")["source_sha256"])
        source_bindings.update(read(folder / "FROZEN_BEFORE_REPLAY.json")["source_sha256"])
        for name in POLICIES:
            account = folder / name
            receipt = read(account / "PATH_COMPLETE.json")
            assert receipt["audit"]["status"] == "PASS"
            for ledger, digest in receipt["ledger_sha256"].items():
                assert sha(account / (ledger + ".parquet")) == digest
            row = receipt["metrics"]
            rows.append(row)
            dates, daily = check_dates(account, year, expected)
            date_checks.append(dates)
            account_days.append(daily.assign(policy=name, year=year))
        reference_names = ["ensemble_equal", "ensemble_consensus_risk", "ensemble_stacked"]
        if year == 2025:
            reference_names.append("original_A2_scores_common_account_reference_r1")
        for name in reference_names:
            row, hashes, account = reused(year, name)
            dates, _ = check_dates(account, year, expected)
            date_checks.append(dates)
            rows.append(row); source_bindings.update(hashes)
    results = pd.DataFrame(rows)
    results.to_csv(ROOT / "ALL_COMPARISONS.csv", index=False)
    pd.concat(account_days, ignore_index=True).to_parquet(ROOT / "ALL_NEW_ACCOUNT_DAYS.parquet", index=False)
    differences = []
    for year in [2025, 2026]:
        subset = results.loc[results.year.eq(year)].set_index("policy")
        for name in POLICIES[3:]:
            for control in ["base_ridge", "base_hgb", "base_mlp", "ensemble_equal"] + (["original_A2_scores_common_account_reference_r1"] if year == 2025 else []):
                a, b = subset.loc[name], subset.loc[control]
                differences.append({"year": year, "policy": name, "control": control,
                    "net_return_difference_pp": 100 * (a.indicative_net_return - b.indicative_net_return),
                    "max_drawdown_difference_pp": 100 * (a.indicative_max_drawdown - b.indicative_max_drawdown),
                    "mean_cash_difference_pp": 100 * (a.mean_actual_cash - b.mean_actual_cash),
                    "fees_saved_usd": b.fees_usd - a.fees_usd,
                    "whole_policy_comparison_not_component_causality": True})
    pd.DataFrame(differences).to_csv(ROOT / "COMBINATION_CONTROL_DIFFERENCES.csv", index=False)
    h2 = results.loc[results.year.eq(2025)]
    future = results.loc[results.year.eq(2026)]
    weights = {}
    for stage in ["validation", "final"]:
        weights[stage] = read(ROOT / f"meta_artifacts/{stage}/learned_fixed.json")["coefficients"]
    controls = h2.set_index("policy")
    learned, hgb, original = (controls.loc[n] for n in ["learned_fixed", "base_hgb", "original_A2_scores_common_account_reference_r1"])
    findings = f"学习固定权重在H2的净记账收益为{100*learned.indicative_net_return:.2f}%，相对同新HGB增加{100*(learned.indicative_net_return-hgb.indicative_net_return):.2f}个百分点，但最大回撤由{100*hgb.indicative_max_drawdown:.2f}%变为{100*learned.indicative_max_drawdown:.2f}%。相对原A2共同账户参照，收益仍低{100*(original.indicative_net_return-learned.indicative_net_return):.2f}个百分点、回撤也更大；本批未证明替代原A2的优势。"
    comparison_text = []
    for name in POLICIES[3:]:
        row = controls.loc[name]
        comparison_text.append(f"- {LABELS[name]}相对同新HGB基础的净记账收益差 {100*(row.indicative_net_return-controls.loc['base_hgb'].indicative_net_return):+.2f} 个百分点，相对旧等权 {100*(row.indicative_net_return-controls.loc['ensemble_equal'].indicative_net_return):+.2f} 个百分点，相对原A2分数共同参照 {100*(row.indicative_net_return-controls.loc['original_A2_scores_common_account_reference_r1'].indicative_net_return):+.2f} 个百分点。")
    gate_lines = []
    for year in [2025, 2026]:
        gates = pd.read_csv(ROOT / f"evaluation_{year}/DAILY_GATE_WEIGHTS.csv")
        text = ", ".join(f"{b}均值{gates['gate_'+b].mean():.3f}、范围[{gates['gate_'+b].min():.3f},{gates['gate_'+b].max():.3f}]" for b in ["ridge", "hgb", "mlp"])
        gate_lines.append(f"- {year}：{text}。")
    mechanics = read(ROOT / "POLICY_MECHANICS_RECEIPT.json")
    assert mechanics["status"] == "PASS_READ_ONLY_POLICY_MECHANICS"
    validate_sources(mechanics["source_sha256"])
    mechanism_rows = pd.read_csv(ROOT / "POLICY_MECHANICS.csv").set_index(["year", "policy"])
    blend_h2 = next(item for item in mechanics["decision_blend_summary"] if item["year"] == 2025)
    blend_future = next(item for item in mechanics["decision_blend_summary"] if item["year"] == 2026)
    mechanism_text = f"H2目标仓位融合在126个信号日中，按名额截断平均移除了{100*blend_h2['mean_weight_removed_by_truncation_and_downscale']:.2f}个百分点的目标权重；126日政策投影后的股票集合全部等于相同账户状态下的HGB成员集合，因为该阶段HGB系数大于另两者系数之和。它主要改变各票权重和剩余敞口，不能把结果解释成三个模型拓宽了最终持仓集合。信号时点隐含目标现金均值{100*mechanism_rows.loc[(2025, 'decision_blend'), 'mean_signal_implied_cash']:.2f}%，全部128个收盘账户日的实际现金均值20.00%，两者时钟不同。2026的181个信号日，在政策投影后、账本资格适配前也全部保留同状态HGB成员集合，政策截断平均移除{100*blend_future['mean_weight_removed_by_truncation_and_downscale']:.2f}个百分点；另有{blend_future['common_adapter_changed_days']}日由统一账户适配器按新增资金资格进一步降权（BYND 6日、SLMT 9日），适配后的集合不因此保证相等。两窗都未触发政策总预算二次缩放，截断和账本适配分开记录；同状态成员集合相同也不等于独立HGB账户路径相同。2026目标比例含未认证NAV，仅作指示值。"
    fee_text = f"H2学习固定权重相对同新HGB的费用只少{hgb.fees_usd-learned.fees_usd:,.0f}美元，实际现金只多{100*(learned.mean_actual_cash-hgb.mean_actual_cash):.2f}个百分点；收益差不能简单归于这两个汇总差值，也尚未证明互补的因果贡献。MLP Stacking费用{controls.loc['stack_mlp'].fees_usd:,.0f}美元，高于同新HGB的{hgb.fees_usd:,.0f}美元，复杂关系拟合并未自动带来更好的账户结果。"
    review_names = ["INDEPENDENT_LEDGER_AUDIT.json", "COMPARISON_REVIEW.json", "GUARD_REVIEW.json", "POLICY_MECHANICS_REVIEW.json"]
    reviews = {}
    for name in review_names:
        review = read(ROOT / name)
        assert review["status"].startswith("PASS"), f"INDEPENDENT_REVIEW_NOT_PASSED:{name}"
        for field in ["source_sha256", "input_sha256"]:
            if field in review:
                validate_sources(review[field])
        reviews[name] = {"status": review["status"], "sha256": sha(ROOT / name)}
    assert (ROOT / "H2_COMPARISON.png").is_file()
    base_tests = read(ROOT / "base_artifacts/BASE_SELF_TEST.json")
    meta_tests = read(ROOT / "meta_artifacts/META_NO_FIT_TEST_RECEIPT.json")
    assert base_tests["status"] == "PASS" and base_tests["fit_calls"] == 0 and all(base_tests["checks"].values())
    assert meta_tests["exit_code"] == 0 and meta_tests["fit_calls"] == 0
    report = f"""# 六类模型协作：实际训练与固定回放结果

六类协作均已进入真实预测或目标形成：8个固定组合设计、3个同基础控制，完成9个基础回归器拟合和12个组合拟合/求解，22条固定账户回放。旧模型、旧权重与原归因批未覆盖，已有7条参考账户直接复用。训练、标准化、门控及组合权重均不使用2026样本；2026参数冻结后评价，未追加轮数、种子或搜索。

{findings}

**2025H2 完整共同账户结果**（128日、100万美元空仓、逐边10bp、同价格/引擎与1%信号ADV买入限制）：

{table(h2)}

**组合相对控制的变化**（描述整套政策，不是因果消融）：

{chr(10).join(comparison_text)}

预测层三个基础版本统一预测原成熟的MEAN_ER_3D_5D_10D_20D目标，训练时裁剪±.30，评估预测和账本不裁剪。它们是为同目标组合新增的有限版本，训练历史从2023开始、抽样及正则与原A2不同，因此新基础相对原A2的差不能归于组合；三条新单模型控制用于区分这一点。

固定预测融合的系数为Ridge/HGB/MLP=.20/.50/.30。OOF学习固定系数为H2 {weights['validation']}；2026 {weights['final']}。线性Stacking使用标准化基础输出后Ridge；小型MLP Stacking使用8隐藏节点。它们学习输出关系，不只是修改等权比例。两个分层臂分别以Ridge先预测/HGB修残差、HGB先预测/Ridge修残差，先后顺序已实际尝试，没有绑定原A2先行。目标仓位融合在同一当前账户状态组合3套TOP20目标，再截取剩余名额，不等同于预测先混合再排名；其分散目标可能降低敞口，现金必须与收益一起阅读。

**条件门控的输出确实随当时状态变化**，网络参数冻结，权重按日变化：

{chr(10).join(gate_lines)}

门控状态来自同一冻结输入的全部new-buy-eligible候选，2026是可核验子池；已持有但非新候选的83行接收同日状态，不进入池均值。4状态为过去20日收益均值、20日波动均值、高于MA20的比例、3预测日内平均分歧，没有未来收益或成交价格字段。全部预测政策按分数和ticker顺序映射每票至多4.75%，缺预算只下缩，旧仓保留由同一账户引擎处理。

本批买入、继续持有和退出由组合排序及目标仓位共同形成：入选并需要加仓的股票提交买入，目标降低或明确为0的可决策旧仓提交减仓/退出；缺输入的保留旧仓交由统一引擎处理。这里没有重新搜索价格买点、现金择时阈值或持仓数量。现金来自既定95%总目标上限、目标融合后的截断、旧仓占用和实际成交约束；条件门控改变模型信任比例，不直接预测现金比例。

{mechanism_text}

{fee_text}

**时间资格与训练预算**：2024 OOF基础只用截至2023的成熟标签；2025 OOF基础只用截至2024的成熟标签。H2组合拟合取2024+2025H1 OOF且target_end严格早于2025-07-01，最后训练signal2025-05-30、成熟2025-06-30。最终组合取2024—2025 OOF且target_end严格早于2026-01-01，最后signal2025-12-02、成熟2025-12-31。每基础最多50000行、每组合阶段最多40000键，全部成熟日期参与，逐日总样本权重相等。OOF216412行/502日全部保留，9583条目标不可用记录保留但不参与拟合；严格成熟截止另行执行，排除原因另表。股票行和重复标签不是独立收益样本。

基础MLP全部跑满40轮、小型Stacking按固定80轮；未收敛告警保留在各FIT_RECEIPT中，不能把预算完成说成优化已经收敛。阶段身份加载、年度OOF cutoff及未来字段拒绝已有边界测试；组合拟合和全部回放前的实现性校验修正记录在IMPLEMENTATION_GUARDS.json，参数和预算不变。

**2026 冻结后的事后核验**（183日、并非全年；下表收益/回撤/现金涉及未认证估值，只作指示值）：

{table(future, True)}

完整原池仍111868候选，其中47271未知；保留原完整记录的路径和哈希，原池完整合格日为0。GLW 2026-02-26事件日/调整特征冲突仍未解决；旧warning=False也不代表该输入已经济合格。每条新账户自行计数未认证日，未套用旧政策数字、删除问题日或默认清仓。公开13F/事件时点与真实供应商历史到达仍有区别；指数单位和现金流会计核对不等于真实原股数、股息或并购现金结算认证。2026不用于选冠军、改权重或宣称正式优势。

2026线性Stacking的0未认证估值日已独立核实：183日和181信号均完整，3629条持仓估值全部有当日close，首日之后持有19—20只股票。这个结果只表示该路径通过现有价格质量门，不认证完整候选池或GLW等经济输入。旧2026三条集成metadata将起始写为非交易日2026-01-01，新批写为首交易日2026-01-02；实际账户日与信号日逐一相同，该标签差异已记录。

八个设计、22条同源场景展示研究取舍，不构成8或22份独立样本，不恢复已观察过的盲测。净增量判断先看与同基础控制的差，再看共同账户参照；费用差和现金差不能直接命名为模型互补的因果收益。

22条新路径共3421账户日，现金、费用、交易单位累计、NAV、次交易日执行、买入资格/ADV和保留旧仓已独立核验；29条比较路径逐一同窗，29行指标与72组差值重算通过。独立资格边界和现金形成机制也有单独收据。通过的是实现、会计及比较核验，经济资格与优化收敛限制继续保留。

![H2预设顺序的收益、回撤与现金比较](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/H2_COMPARISON.png)

- [全部比较表](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/ALL_COMPARISONS.csv)
- [组合相对控制的差](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/COMBINATION_CONTROL_DIFFERENCES.csv)
- [目标现金与实际现金](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/POLICY_MECHANICS.csv)、[仓位融合逐日截断](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/DECISION_BLEND_DAYS.csv)
- [固定设计](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/DESIGN_CONTRACT.md)、[基础训练收据](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/base_artifacts/TRAIN_RECEIPT.json)、[组合训练收据](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/meta_artifacts/TRAIN_RECEIPT.json)
- [数据资格](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/NEW_DATA_ADMISSION.json)、[本批核验](C:/Users/Lenovo/Documents/CODING开发/a2_collaboration_methods_20260928_r1/VERIFICATION.json)
"""
    (ROOT / "REPORT.md").write_text(report, encoding="utf-8")
    validate_sources(source_bindings)
    verification = {"status": "PASS_FIXED_SIX_FAMILIES_WITH_DATA_AND_OPTIMIZATION_LIMITATIONS",
        "checked_utc": datetime.now(timezone.utc).isoformat(), "base_regressor_fits": 9, "meta_predictive_fits_and_solves": 12,
        "new_replay_paths": 22, "reused_old_paths": 7, "combination_designs": 8, "same_base_controls": 3,
        "new_2026_fit_rows": 0, "evaluation_fit_attempts": 0, "parameter_searches": 0,
        "new_account_days": sum(len(frame) for frame in account_days),
        "all_window_dates_preserved": len(date_checks) == 29 and all(item["exact_frozen_calendar_match"] for item in date_checks),
        "account_window_checks": date_checks,
        "original_unknown_candidate_records_retained": 47271, "complete_original_pool_certified_days": 0,
        "shareholder_total_return_certified": False, "blind_test": False, "2026_winner_selected": False,
        "causal_model_complementarity_proven": False, "prior_results_overwritten": False,
        "independent_reviews": reviews,
        "saved_base_no_fit_self_checks": len(base_tests["checks"]),
        "saved_meta_no_fit_test_exit_code": meta_tests["exit_code"],
        "bound_source_sha256": source_bindings,
        "delivery_sha256": {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.name != "VERIFICATION.json"}}
    (ROOT / "VERIFICATION.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in verification.items() if not k.endswith("sha256") and k != "account_window_checks"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
