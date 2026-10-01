"""Read-only accounting of saved ensemble decisions; no predictor loads or replay.

The quantile-zero calculation is a same-state arithmetic intervention. It has
no account evolution, trades, outcome labels or PnL calculation.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "a2_buy_sell_cash_multimodel_20260928"
MEMBERS = ["joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb", "joint_quantile_risk", "joint_mlp"]
TOL = 2e-9


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def project(matrix, coefficients, slots, budget, consensus=False, max_weight=.1):
    matrix = np.asarray(matrix, float)
    coefficients = np.asarray(coefficients, float)
    assert matrix.ndim == 2 and matrix.shape[1] == len(coefficients)
    assert np.isfinite(matrix).all() and (matrix >= 0).all()
    assert (coefficients >= 0).all() and abs(coefficients.sum() - 1) < 1e-8
    mean = matrix @ coefficients
    dispersion = np.sqrt(((matrix - mean[:, None]) ** 2) @ coefficients)
    consensus_weights = mean / (1 + dispersion / (mean + .01)) if consensus else mean.copy()
    capped = np.minimum(consensus_weights, max_weight)
    clipped = capped.copy()
    keep = np.argsort(-clipped, kind="stable")[:slots]
    mask = np.zeros(len(clipped)); mask[keep] = 1
    clipped *= mask
    budgeted = clipped.copy()
    if budgeted.sum() > budget:
        budgeted *= budget / budgeted.sum()
    return dict(mean=mean, dispersion=dispersion, consensus=consensus_weights,
                capped=capped, topk=clipped, budgeted=budgeted)


def numeric_covariance(names, lookup, covariance):
    """Reconstitute only the existing frozen numeric risk matrix, no fitting."""
    answer = np.eye(len(names)) * .08 ** 2
    pairs = [(i, lookup[t]) for i, t in enumerate(names) if t in lookup]
    if pairs:
        ix, src = zip(*pairs)
        answer[np.ix_(ix, ix)] = covariance[np.ix_(src, src)]
    return answer


def risk_projection(weights, locked, covariance, limit=.015):
    # Algebraically the same quadratic as the archived 60-step bisection. Use
    # its full vector evaluation to make the original stage directly auditable.
    def variance(scale):
        full = np.r_[weights * scale, locked]
        return float(full @ covariance @ full)
    if variance(0) > limit ** 2:
        return 0.
    if variance(1) <= limit ** 2:
        return 1.
    lo, hi = 0., 1.
    for _ in range(60):
        mid = (lo + hi) / 2
        if variance(mid) <= limit ** 2:
            lo = mid
        else:
            hi = mid
    return lo


def adapt(names, weights, current, held, final_reserved, ops, eligible, slots, budget, max_weight=.1):
    active = {t: min(float(w), max_weight) for t, w in zip(names, weights)
              if t not in ops and t not in final_reserved}
    start = sum(weights)
    eligible_start = sum(active.values())
    for t in active:
        if not eligible.get(t, False) and active[t] > current.get(t, 0.):
            active[t] = max(0., current.get(t, 0.))
    eligible_end = sum(active.values())
    ordered = sorted([t for t, w in active.items() if w > 0], key=lambda t: (t not in held, -active[t], t))
    for t in ordered[slots:]:
        active[t] = 0.
    slot_end = sum(active.values())
    if slot_end > budget:
        for t in active:
            active[t] *= budget / slot_end
    losses = dict(adapter_exclusion_loss=start-eligible_start,
                  adapter_eligibility_loss=eligible_start-eligible_end,
                  adapter_slots_loss=eligible_end-slot_end,
                  adapter_budget_loss=slot_end-sum(active.values()))
    return active, losses


def cancellation(matrix, coefficients, current):
    changes = matrix - np.asarray(current)[:, None]
    individual = float(np.abs(changes).sum(axis=0) @ coefficients)
    blended = float(np.abs(changes @ coefficients).sum())
    positive = (np.maximum(changes, 0) @ coefficients)
    negative = (np.maximum(-changes, 0) @ coefficients)
    return dict(weighted_member_desired_gross_change=individual,
                blended_desired_gross_change=blended,
                desired_change_cancellation=individual-blended,
                desired_change_cancellation_fraction=(individual-blended)/individual if individual > 0 else 0.,
                direction_conflict_tickers=int(((positive > 1e-12) & (negative > 1e-12)).sum()))


def main():
    paths = sorted(p for p in SOURCE.glob("ensemble_*/cost_*/ensemble_*") if p.is_dir())
    assert len(paths) == 14, len(paths)
    source_paths = set()
    for p in paths:
        source_paths.update(p / n for n in ["raw_model_outputs.parquet", "signal_contexts.parquet", "target_decisions.parquet", "daily.parquet", "PATH_COMPLETE.json", "metadata.json"])
    source_paths.update(SOURCE / n for n in ["ensemble_policy.py", "engine_v2.py", "adapters.py", "risk_aux.py"])
    risk_data = {}
    for stage in ["validation", "final"]:
        path = SOURCE / "risk_artifacts" / stage / "frozen_covariance.npz"
        source_paths.add(path)
        with np.load(path, allow_pickle=False) as data:
            risk_data[stage] = ({str(t): i for i, t in enumerate(data["tickers"])}, data["covariance"].copy())
    eligibility = {}
    for year, path in [(2025, HERE.parent / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"),
                       (2026, HERE.parent / "a2_qualification_holdings_v1_20260927/data/test_features_context.parquet")]:
        source_paths.add(path)
        frame = pd.read_parquet(path, columns=["signal_date", "ticker", "new_buy_eligible"])
        frame = frame[frame.signal_date.dt.year.eq(year)]
        eligibility[year] = {date: dict(zip(g.ticker, g.new_buy_eligible.fillna(False).astype(bool))) for date, g in frame.groupby("signal_date")}
    before = {str(p): sha(p) for p in sorted(source_paths)}
    signals, member_rows, pair_rows, daily_rows = [], [], [], []
    checked = []
    for p in paths:
        scenario = p.relative_to(SOURCE).as_posix()
        year = int(p.parents[1].name.split("_")[1]); stage = "final" if year == 2026 else "validation"
        candidate = p.name; consensus = candidate == "ensemble_consensus_risk"
        cost = int(p.parent.name.split("_")[1])
        raw = pd.read_parquet(p / "raw_model_outputs.parquet").set_index("decision_id")
        ctx = pd.read_parquet(p / "signal_contexts.parquet").set_index("decision_id")
        targets = pd.read_parquet(p / "target_decisions.parquet")
        target_groups = {key: g for key, g in targets.groupby("decision_id")}
        daily = pd.read_parquet(p / "daily.parquet").set_index("date")
        meta = json.loads((p / "metadata.json").read_text(encoding="utf-8"))
        cap = float(meta["max_target_invested"]); max_weight = float(meta["max_target_weight"])
        receipt = json.loads((p / "PATH_COMPLETE.json").read_text(encoding="utf-8"))
        for stem in ["raw_model_outputs", "signal_contexts", "target_decisions", "daily"]:
            assert sha(p / f"{stem}.parquet") == receipt["ledger_sha256"][stem]
        for day, d in daily.iterrows():
            daily_rows.append(dict(scenario=scenario, candidate=candidate, year=year, cost_bps=cost, date=day,
                                   cash=d.cash, cash_weight=d.cash_weight, nav=d.nav,
                                   valuation_status=d.valuation_status, certified_nav_available=pd.notna(d.certified_nav),
                                   ratio_scope="certified_local_price_index" if pd.notna(d.certified_nav) else "indicative_uncertified_NAV",
                                   economic_qualification="not_full_2026_economically_qualified" if year == 2026 else "pre2026_research_index"))
        for decision_id, c in ctx.iterrows():
            r = raw.loc[decision_id]; date = c.signal_date; daily_state = daily.loc[date]
            common_data = json.loads(r.raw_model_outputs_json)
            row = dict(scenario=scenario, candidate=candidate, year=year, cost_bps=cost,
                       decision_id=decision_id, signal_date=date, policy_called=bool(c.policy_called),
                       valuation_status=daily_state.valuation_status,
                       certified_nav_available=pd.notna(daily_state.certified_nav),
                       ratio_scope="certified_local_price_index" if pd.notna(daily_state.certified_nav) else "indicative_uncertified_NAV",
                       economic_qualification="not_full_2026_economically_qualified" if year == 2026 else "pre2026_research_index",
                       observed_signal_cash_weight=c.cash_weight, nav=c.nav,
                       initial_reserved_weight=c.reserved_weight, final_reserved_weight=c.final_reserved_weight,
                       reserved_slots=c.final_reserved_slots)
            if not c.policy_called:
                row["decomposition_status"] = "UNKNOWN_NAV_RETAINED_NO_DECOMPOSITION"
                signals.append(row); continue
            names = sorted(common_data or {})
            if not names:
                row.update(decomposition_status="NO_COMMON_OPINIONS_RETAINED", active_target_weight=c.active_target_weight,
                           target_cash_weight=1-c.final_reserved_weight-c.active_target_weight)
                signals.append(row); continue
            first = common_data[names[0]]; coefficients = np.array(first["coefficients"], float)
            member_names = first["member_names"]; assert member_names == MEMBERS
            matrix = np.array([common_data[t]["member_targets"] for t in names], float)
            assert all(common_data[t]["coefficients"] == first["coefficients"] for t in names)
            current = json.loads(c.current_weights_json); held = set(json.loads(c.current_units_json))
            reserved = json.loads(c.reserved_tickers_json); final_reserved = set(json.loads(c.final_reserved_tickers_json))
            ops = json.loads(r.operational_exits_json)
            extra_locked = [t for t, w in current.items() if w > 0 and t not in names and t not in reserved and t not in ops]
            extra_weight = sum(current[t] for t in extra_locked)
            budget = max(0., c.available_weight-extra_weight); slots = max(0, int(c.available_slots)-len(extra_locked))
            stages = project(matrix, coefficients, slots, budget, consensus, max_weight)
            saved_scale = float(first["risk_scale"])
            covariance = None; locked_weights = np.array([current[t] for t in reserved+extra_locked])
            if consensus:
                covariance = numeric_covariance(names+reserved+extra_locked, *risk_data[stage])
                rebuilt_scale = risk_projection(stages["budgeted"], locked_weights, covariance)
                assert abs(rebuilt_scale-saved_scale) < TOL
            postrisk = stages["budgeted"]*saved_scale
            saved = np.array([common_data[t]["ensemble_target"] for t in names])
            raw_targets = json.loads(r.model_decisions_json)
            error = float(np.max(np.abs(postrisk-saved)))
            assert error < TOL and max(abs(postrisk[i]-raw_targets[t]) for i, t in enumerate(names)) < TOL
            assert np.max(np.abs(stages["mean"]-np.array([common_data[t]["mean_target"] for t in names]))) < TOL
            assert np.max(np.abs(stages["dispersion"]-np.array([common_data[t]["disagreement"] for t in names]))) < TOL
            eligible = eligibility[year].get(date, {})
            adapted, adapter_losses = adapt(names, postrisk, current, held, final_reserved, ops, eligible,
                                            int(c.final_available_slots), float(c.final_available_weight), max_weight)
            active_sum = sum(adapted.values()); assert abs(active_sum-c.active_target_weight) < TOL
            group = target_groups.get(decision_id, targets.iloc[:0])
            saved_adapted = dict(zip(group.loc[group.order_type.eq("TARGET_WEIGHT"), "ticker"], group.loc[group.order_type.eq("TARGET_WEIGHT"), "adapted_target_weight"]))
            assert all(abs(saved_adapted.get(t, 0)-w) < TOL for t, w in adapted.items())
            member_exposure = matrix.sum(axis=0)
            member_unused = coefficients*(budget-member_exposure)
            gap = cap-float(c.final_reserved_weight)-budget
            components = dict(fixed_reserve_cash=1-cap, weighted_member_unused_budget=float(member_unused.sum()),
                              disagreement_shrinkage=float(stages["mean"].sum()-stages["consensus"].sum()),
                              single_name_cap_loss=float(stages["consensus"].sum()-stages["capped"].sum()),
                              topk_truncation_loss=float(stages["capped"].sum()-stages["topk"].sum()),
                              ensemble_budget_loss=float(stages["topk"].sum()-stages["budgeted"].sum()),
                              risk_scaling_loss=float(stages["budgeted"].sum()-postrisk.sum()),
                              ledger_adaptation_loss=float(postrisk.sum()-active_sum),
                              reservation_budget_identity_adjustment=gap)
            target_cash = 1-float(c.final_reserved_weight)-active_sum
            identity_error = sum(components.values())-target_cash
            assert abs(identity_error) < TOL
            row.update(components); row.update(adapter_losses)
            row.update(decomposition_status="RECONSTRUCTED", common_tickers=len(names), ensemble_slots=slots,
                       active_budget=budget, extra_locked_weight=extra_weight, active_target_weight=active_sum,
                       target_cash_weight=target_cash, identity_error=identity_error,
                       projection_max_abs_error=error, recorded_risk_scale=saved_scale,
                       observed_minus_target_cash=c.cash_weight-target_cash,
                       retained_holdings_are_not_cash=True)
            row.update(cancellation(matrix, coefficients, [current.get(t, 0.) for t in names]))
            zero_matrix = matrix.copy(); qindex = MEMBERS.index("joint_quantile_risk"); zero_matrix[:, qindex] = 0.
            zero_stages = project(zero_matrix, coefficients, slots, budget, consensus, max_weight)
            zero_scale = risk_projection(zero_stages["budgeted"], locked_weights, covariance) if consensus else 1.
            zero_target = zero_stages["budgeted"]*zero_scale
            zero_adapted, _ = adapt(names, zero_target, current, held, final_reserved, ops, eligible,
                                    int(c.final_available_slots), float(c.final_available_weight), max_weight)
            zero_active = sum(zero_adapted.values()); zero_cash = 1-float(c.final_reserved_weight)-zero_active
            target_l1 = sum(abs(zero_adapted.get(t, 0.)-adapted.get(t, 0.)) for t in set(zero_adapted)|set(adapted))
            row.update(quantile_coefficient=float(coefficients[qindex]), quantile_member_active_exposure=float(member_exposure[qindex]),
                       quantile_weighted_unused_budget=float(member_unused[qindex]),
                       quantile_zero_target_cash=zero_cash, quantile_zero_cash_difference=zero_cash-target_cash,
                       quantile_zero_active_target_l1_difference=target_l1, quantile_zero_risk_scale=zero_scale,
                       counterfactual_scope="same_state_fixed_coefficients_full_numeric_reprojection_no_trajectory_no_PnL")
            signals.append(row)
            for j, member in enumerate(MEMBERS):
                member_rows.append(dict(scenario=scenario, decision_id=decision_id, signal_date=date, member=member,
                                        coefficient=float(coefficients[j]), active_budget=budget,
                                        active_exposure=float(member_exposure[j]),
                                        unused_active_budget=float(budget-member_exposure[j]),
                                        weighted_unused_active_budget=float(member_unused[j]),
                                        nonzero_target_count=int((matrix[:,j]>1e-12).sum()),
                                        desired_gross_change=float(np.abs(matrix[:,j]-[current.get(t,0.) for t in names]).sum()),
                                        ratio_scope=row["ratio_scope"],economic_qualification=row["economic_qualification"],
                                        meaning="member_target_already_contains_base_constraints_not_unconstrained_preference"))
            for j,k in combinations(range(len(MEMBERS)),2):
                union=(matrix[:,j]>1e-12)|(matrix[:,k]>1e-12)
                intersection=(matrix[:,j]>1e-12)&(matrix[:,k]>1e-12)
                pair_rows.append(dict(scenario=scenario,decision_id=decision_id,signal_date=date,
                                      member_a=MEMBERS[j],member_b=MEMBERS[k],
                                      target_l1_distance=float(np.abs(matrix[:,j]-matrix[:,k]).sum()),
                                      target_overlap_weight=float(np.minimum(matrix[:,j],matrix[:,k]).sum()),
                                      positive_support_jaccard=float(intersection.sum()/union.sum()) if union.any() else np.nan,
                                      ratio_scope=row["ratio_scope"],economic_qualification=row["economic_qualification"]))
        checked.append(scenario)
        print(f"accounted {scenario}", flush=True)
    frame = pd.DataFrame(signals); member_frame=pd.DataFrame(member_rows); pairs=pd.DataFrame(pair_rows)
    daily_frame=pd.DataFrame(daily_rows)
    numeric = [c for c in frame if pd.api.types.is_numeric_dtype(frame[c]) and c not in ["year","cost_bps","policy_called","certified_nav_available","retained_holdings_are_not_cash"]]
    summary = frame.groupby(["scenario","candidate","year","cost_bps"],sort=False)[numeric].mean().add_prefix("mean_").reset_index()
    counts = frame.groupby("scenario").agg(signal_days=("decision_id","size"),uncertified_signal_days=("certified_nav_available",lambda x:int((~x).sum())),
                                            reconstructed_signals=("decomposition_status",lambda x:int(x.eq("RECONSTRUCTED").sum())))
    summary=summary.merge(counts,on="scenario",validate="one_to_one")
    zero_counts=frame.groupby("scenario").agg(quantile_zero_exact_target_signals=("quantile_zero_active_target_l1_difference",lambda x:int((x<1e-12).sum())),
                                             quantile_zero_max_target_l1=("quantile_zero_active_target_l1_difference","max"),
                                             quantile_zero_max_cash_difference_abs=("quantile_zero_cash_difference",lambda x:float(x.abs().max())))
    summary=summary.merge(zero_counts,on="scenario",validate="one_to_one")
    summary["ratio_scope"] = np.where(summary.uncertified_signal_days.gt(0),"includes_indicative_uncertified_NAV_days","certified_local_price_index_only")
    summary["economic_qualification"] = np.where(summary.year.eq(2026),"not_full_2026_economically_qualified","pre2026_research_index")
    summary["counterfactual_scope"] = "same_state_fixed_coefficients_full_numeric_reprojection_no_trajectory_no_PnL"
    member_summary=member_frame.groupby(["scenario","member"],sort=False).agg(coefficient=("coefficient","first"),
                      mean_active_exposure=("active_exposure","mean"),mean_weighted_unused_budget=("weighted_unused_active_budget","mean"),
                      max_active_exposure=("active_exposure","max"),zero_exposure_signals=("active_exposure",lambda x:int((x<1e-12).sum())),signals=("active_exposure","size")).reset_index()
    member_summary=member_summary.merge(summary[["scenario","ratio_scope","economic_qualification"]],on="scenario",validate="many_to_one")
    for name, data in [("cash_signals",frame),("cash_members",member_frame),("cash_member_summary",member_summary),("cash_overlap",pairs),
                       ("cash_summary",summary),("cash_last_signal",frame.sort_values("signal_date").groupby("scenario",sort=False).tail(1)),("cash_daily",daily_frame)]:
        data.to_csv(HERE/f"{name}.csv",index=False,encoding="utf-8-sig")
    assert all(sha(Path(p))==digest for p,digest in before.items()),"READ_ONLY_SOURCE_CHANGED"
    write_report(summary,member_summary,frame)
    receipt=dict(status="PASS",scenario_count=len(checked),scenarios=checked,signal_rows=len(frame),
                 reconstructed_signals=int(frame.decomposition_status.eq("RECONSTRUCTED").sum()),
                 omitted_signals=0,max_identity_error=float(frame.identity_error.abs().max()),
                 max_projection_error=float(frame.projection_max_abs_error.abs().max()),
                 fit_calls=0,predictor_loads=0,trajectory_replays=0,model_or_weight_searches=0,
                 numeric_frozen_covariance_read=True,source_files_unchanged=True,source_sha256=before,
                 actual_limits=["member opinions already include individual eligibility/capacity/position constraints",
                                "member unused budget cannot be identified as purely active cash preference",
                                "held reserved assets are exposure, not cash",
                                "quantile zero calculation fixes account state and coefficients; it does not estimate PnL causality",
                                "2026 NAV ratios are explicitly flagged by date; even certified dates do not certify full original pool or economic coordinate"],
                 output_sha256={p.name:sha(p) for p in sorted(list(HERE.glob("cash_*.csv"))+[HERE/"cash_analysis.md"])},
                 code_sha256=sha(Path(__file__)))
    (HERE/"cash_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:receipt[k] for k in ["status","scenario_count","signal_rows","reconstructed_signals","max_identity_error","max_projection_error"]}),flush=True)


def write_report(summary,members,signals):
    lines=["# 冻结集成的现金来源与同状态机械拆解", "", "覆盖全部 14 个既有集成场景；没有新训练、模型预测、轨迹回放或权重搜索。场景与每日信号不是独立经济样本。",
           "", "现金恒等式按既有处理次序拆解：目标现金 = 5% 固定储备 + 加权成员未使用的可动预算 + 分歧收缩 + 单名上限损耗 + TOP20/剩余名额截断 + 总预算缩放 + 风险缩放 + 账本适配 + 预算与保留仓的恒等式修正。",
           "", "成员意见已包含其自身资格、名额、单名上限和预算约束，因此‘未使用预算’不能全部归因于主动看空或模型偏好。各损耗按实际顺序计算，顺序改变会改变分配；这里只报告冻结算法的精确流水。保留旧仓单独报告为风险敞口，不算现金。实际现金与目标现金的差额含上一轮信号执行、价格变化等，不能一概归入成交阻塞。",
           "", "下表为逐信号平均、单位为净值百分点；2026 包含未认证 NAV 日，仅为指示性拆解。即使某日局部价格指数 NAV 已认证，也不代表全年原候选池和经济映射已合格。", "",
           "|场景|目标现金|成员未用预算|其中分位成员|分歧收缩|TOP 截断|风险缩放|保留旧仓敞口|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    focus=summary[summary.scenario.str.startswith("ensemble_2025_H2/")|summary.scenario.str.startswith("ensemble_2026/cost_10/")]
    for r in focus.itertuples():
        lines.append(f"|{r.scenario}|{r.mean_target_cash_weight*100:.3f}|{r.mean_weighted_member_unused_budget*100:.3f}|{r.mean_quantile_weighted_unused_budget*100:.3f}|{r.mean_disagreement_shrinkage*100:.3f}|{r.mean_topk_truncation_loss*100:.3f}|{r.mean_risk_scaling_loss*100:.3f}|{r.mean_final_reserved_weight*100:.3f}|")
    lines += ["", "将分位数风险成员的每只股票目标设为零，保留其集成权重和同一账户状态，重新进行分歧、上限、名额、预算、冻结风险矩阵及账本资格投影。该运算没有形成新持仓路径，不产生反事实收益。其作用是检验这个成员在当前决策里有多少股票敞口不能由同权重的现金成员替代。", "",
              "|场景|信号数|替换后目标完全相同的信号数|平均现金变化（百分点）|最大目标 L1 差（百分点）|均值前的换手意见抵消（百分点）|", "|---|---:|---:|---:|---:|---:|"]
    for r in focus.itertuples():
        lines.append(f"|{r.scenario}|{r.signal_days}|{r.quantile_zero_exact_target_signals}|{r.mean_quantile_zero_cash_difference*100:.6f}|{r.quantile_zero_max_target_l1*100:.6f}|{r.mean_desired_change_cancellation*100:.3f}|")
    qmembers=members[members.member.eq("joint_quantile_risk")]
    h2=qmembers[qmembers.scenario.eq("ensemble_2025_H2/cost_10/ensemble_stacked")].iloc[0]
    y26=qmembers[qmembers.scenario.eq("ensemble_2026/cost_10/ensemble_stacked")].iloc[0]
    active_components=["single_name_cap_loss","ensemble_budget_loss","risk_scaling_loss","ledger_adaptation_loss"]
    unchanged_components=all(signals[c].abs().max()<1e-12 for c in active_components)
    lines += ["", f"最直接的证据是：学习权重路线把 {y26.coefficient*100:.0f}% 的系数分给了近现金的分位数风险成员。该成员在 2025H2 的 {int(h2.zero_exposure_signals)}/{int(h2.signals)} 个信号、2026 的 {int(y26.zero_exposure_signals)}/{int(y26.signals)} 个信号原意见股票敞口为零；即使其偶尔提供小仓位，通常也在后续 TOP 名额截断中消失。2025H2 所有信号的最终目标均可由同权重现金成员精确替代；2026 仅 1 月 2 日替换影响最终目标。这证明当前原型中这一成员几乎可被现金成员替代，尚不能据此断言预测互补创造了收益增量。",
              "", ("全 14 场景的单名上限、集成总预算缩放、协方差风险上限及账本适配均没有产生实质的额外现金（适配仅有浮点误差）。分歧风险路线的额外现金实际来自分歧收缩与 TOP 截断，不能解释为波动率上限在主动控仓。" if unchanged_components else "各约束是否产生现金必须依逐日流水判断。"),
              "", "‘换手意见抵消’ = Σ成员权重×|成员目标−相同当前仓位| − |加权均值目标−相同当前仓位|，是决策向量上的三角不等式差，不是已成交换手或收益贡献。成员目标支持集重叠及 L1 距离逐日另存 cash_overlap.csv；它们描述差异，不证明信息互补或超额收益。",
              "", "审计边界：所有既有信号及问题估值日保留；cash_signals.csv/cash_daily.csv 有逐日资格标记，cash_receipt.json 记录只读源哈希、原账本哈希核验与恒等式误差。全 14 场景汇总见 cash_summary.csv；各成员未用预算见 cash_member_summary.csv。"]
    (HERE/"cash_analysis.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
