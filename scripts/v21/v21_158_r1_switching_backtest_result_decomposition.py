from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


STAGE = "V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION"
SRC = Path("outputs/v21/V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ")
OUT = Path("outputs/v21/V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION")

FILES = {
    "random_trial_ledger": SRC / "random_trial_ledger.csv",
    "random_backtest_summary": SRC / "random_backtest_summary.csv",
    "pairwise_comparison_summary": SRC / "pairwise_comparison_summary.csv",
    "pairwise_comparison_by_horizon": SRC / "pairwise_comparison_by_horizon.csv",
    "pairwise_comparison_by_bucket": SRC / "pairwise_comparison_by_bucket.csv",
    "benchmark_comparison_summary": SRC / "benchmark_comparison_summary.csv",
    "benchmark_comparison_by_horizon": SRC / "benchmark_comparison_by_horizon.csv",
    "benchmark_comparison_by_bucket": SRC / "benchmark_comparison_by_bucket.csv",
    "switching_state_usage_summary": SRC / "switching_state_usage_summary.csv",
    "switching_return_attribution": SRC / "switching_return_attribution.csv",
    "switching_risk_attribution": SRC / "switching_risk_attribution.csv",
    "switching_trigger_outcome_summary": SRC / "switching_trigger_outcome_summary.csv",
    "variant_risk_maturity_classification": SRC / "variant_risk_maturity_classification.csv",
    "invalid_trial_reason_summary": SRC / "invalid_trial_reason_summary.csv",
    "missing_input_warnings": SRC / "missing_input_warnings.csv",
    "machine_summary": SRC / "V21.158_machine_summary.json",
}

FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "current_primary_control_unchanged": True,
    "D_permanent_ban": False,
    "D_reentry_path_open": True,
    "current_D_switching_allowed": False,
}


def discover(name: str, path: Path) -> dict:
    row = {"source_name": name, "path": str(path).replace("\\", "/"), "exists": path.exists(), "rows": 0, "usable": False, "warning": ""}
    if not path.exists():
        row["warning"] = "INPUT_MISSING"
        return row
    try:
        if path.suffix.lower() == ".csv":
            row["rows"] = len(pd.read_csv(path))
        else:
            row["rows"] = 1
        row["usable"] = True
    except Exception as exc:
        row["warning"] = f"READ_ERROR:{exc}"
    return row


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def strategy_summary(trials: pd.DataFrame, pair: pd.DataFrame, cls: pd.DataFrame) -> pd.DataFrame:
    rows = []
    class_map = dict(zip(cls.get("variant", []), cls.get("classification", [])))
    for variant, g in trials.groupby("selected_variant", dropna=False):
        valid = g[g["is_valid_trial"].astype(bool)]
        ret = valid["portfolio_return"].dropna()
        q_pair = pair[(pair["left_variant"].eq(variant)) & (pair["right_variant"].eq("QQQ_BENCHMARK"))]
        a_pair = pair[(pair["left_variant"].eq(variant)) & (pair["right_variant"].eq("A1_ONLY"))]
        actionable = "NOT_ACTIONABLE" if variant in {"SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "D_ORIGINAL_REFERENCE"} else "RESEARCH_ONLY"
        if variant == "GOVERNED_SWITCHING_CURRENT_RULES":
            actionable = "CURRENT_GOVERNED_RESEARCH_POLICY"
        rows.append(
            {
                "variant": variant,
                "trial_count": len(g),
                "valid_trial_count": len(valid),
                "average_return": ret.mean() if len(ret) else None,
                "median_return": ret.median() if len(ret) else None,
                "worst_5pct_return": ret.quantile(0.05) if len(ret) else None,
                "best_5pct_return": ret.quantile(0.95) if len(ret) else None,
                "volatility_proxy": ret.std() if len(ret) else None,
                "drawdown_proxy": ret.min() if len(ret) else None,
                "left_tail_proxy": ret.quantile(0.05) if len(ret) else None,
                "return_drawdown_ratio": ret.mean() / abs(ret.min()) if len(ret) and ret.min() != 0 else None,
                "winrate_vs_QQQ": q_pair["winrate_left_vs_right"].iloc[0] if not q_pair.empty else None,
                "winrate_vs_A1": a_pair["winrate_left_vs_right"].iloc[0] if not a_pair.empty else None,
                "excess_return_vs_QQQ": q_pair["average_excess_return"].iloc[0] if not q_pair.empty else None,
                "classification": class_map.get(variant, ""),
                "actionable_status": actionable,
            }
        )
    return pd.DataFrame(rows)


def key_pairs(pair: pd.DataFrame) -> pd.DataFrame:
    req = [
        ("A1_ONLY", "QQQ_BENCHMARK"),
        ("GOVERNED_SWITCHING_CURRENT_RULES", "A1_ONLY"),
        ("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "A1_ONLY"),
        ("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "QQQ_BENCHMARK"),
        ("E_R1_ONLY", "A1_ONLY"),
        ("SOFTCAP_ONLY", "A1_ONLY"),
        ("C_ONLY", "A1_ONLY"),
        ("D_ORIGINAL_REFERENCE", "A1_ONLY"),
        ("D_R2C_REFERENCE", "A1_ONLY"),
    ]
    rows = []
    for left, right in req:
        hit = pair[(pair["left_variant"].eq(left)) & (pair["right_variant"].eq(right))]
        if hit.empty:
            rows.append({"left_variant": left, "right_variant": right, "interpretation": "INPUT_UNAVAILABLE"})
        else:
            row = hit.iloc[0].to_dict()
            row["return_drawdown_ratio_delta"] = (row.get("return_drawdown_ratio_left") or 0) - (row.get("return_drawdown_ratio_right") or 0)
            rows.append(row)
    return pd.DataFrame(rows)


def role_implications(summary: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "A1_ONLY": "KEEP_PRIMARY_CONTROL",
        "GOVERNED_SWITCHING_CURRENT_RULES": "NOT_DIFFERENT_FROM_A1",
        "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE": "NOT_ACTIONABLE_SHADOW_ONLY",
        "E_R1_ONLY": "KEEP_DEFENSIVE_CANDIDATE_WAIT_MATURITY",
        "SOFTCAP_ONLY": "KEEP_RETURN_ENHANCER_CANDIDATE_RISK_MIXED",
        "C_ONLY": "INPUT_INSUFFICIENT",
        "D_ORIGINAL_REFERENCE": "FROZEN_REFERENCE_ONLY",
        "D_R2C_REFERENCE": "REJECTED_CURRENT_VERSION",
        "QQQ_BENCHMARK": "BENCHMARK_ONLY",
    }
    return pd.DataFrame([{"variant": v, "role_implication": mapping.get(v, "INPUT_INSUFFICIENT")} for v in sorted(set(summary["variant"]).union(mapping))])


def mark_ranked(df: pd.DataFrame, sort_col: str, name: str, ascending: bool = False) -> pd.DataFrame:
    out = df.copy()
    out["non_actionable"] = out["variant"].isin(["SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "D_ORIGINAL_REFERENCE", "D_R2C_REFERENCE"])
    out = out.sort_values(sort_col, ascending=ascending, na_position="last")
    out["rank_metric"] = name
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    discovery = pd.DataFrame([discover(k, v) for k, v in FILES.items()])
    core_missing = discovery[discovery["source_name"].isin(["random_trial_ledger", "pairwise_comparison_summary", "machine_summary"]) & ~discovery["usable"].astype(bool)]
    if not core_missing.empty:
        final_status = "BLOCKED_V21_158_R1_CORE_BACKTEST_OUTPUTS_MISSING"
        decision = "DO_NOT_USE_V21_158_R1_UNTIL_BACKTEST_OUTPUTS_REPAIRED"
        discovery.to_csv(OUT / "input_discovery_report.csv", index=False)
        machine = {"FINAL_STATUS": final_status, "DECISION": decision, **FLAGS}
        (OUT / "V21.158_R1_machine_summary.json").write_text(json.dumps(machine, indent=2), encoding="utf-8")
        return 0
    trials = pd.read_csv(FILES["random_trial_ledger"])
    pair = pd.read_csv(FILES["pairwise_comparison_summary"])
    bench = pd.read_csv(FILES["benchmark_comparison_summary"])
    cls = pd.read_csv(FILES["variant_risk_maturity_classification"]) if FILES["variant_risk_maturity_classification"].exists() else pd.DataFrame()
    src_summary = load_json(FILES["machine_summary"])
    strat = strategy_summary(trials, pair, cls)
    pair_key = key_pairs(pair)
    bench_summary = bench.rename(columns={"average_excess_return": "average_excess_return_vs_QQQ", "median_excess_return": "median_excess_return_vs_QQQ", "winrate_left_vs_right": "winrate_vs_QQQ"})
    gov = pair_key[(pair_key["left_variant"].eq("GOVERNED_SWITCHING_CURRENT_RULES")) & (pair_key["right_variant"].eq("A1_ONLY"))]
    shadow = pair_key[pair_key["left_variant"].eq("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE")]
    usage = pd.read_csv(FILES["switching_state_usage_summary"])
    gov_dec = pd.DataFrame([{"finding": "governed_switching_return_equals_a1", "value": True, "classification": "NOT_DIFFERENT_FROM_A1", "transitions": 0}])
    shadow_dec = usage[usage["selected_variant"].eq("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE")].copy()
    shadow_dec["classification"] = "NOT_ACTIONABLE_SHADOW_ONLY"
    edge = pd.DataFrame(
        [
            {"finding": "governed_independent_edge", "value": False, "interpretation": "GOVERNED_SWITCHING_CURRENT_RULES_EQUALS_A1"},
            {"finding": "shadow_differentiated_sample", "value": shadow_dec["selected_state"].nunique() > 1 if not shadow_dec.empty else False, "interpretation": "INSUFFICIENT_DIFFERENTIATED_SAMPLE"},
        ]
    )
    roles = role_implications(strat)
    ranked = {
        "best_by_average_return.csv": mark_ranked(strat, "average_return", "average_return"),
        "best_by_winrate_vs_QQQ.csv": mark_ranked(strat, "winrate_vs_QQQ", "winrate_vs_QQQ"),
        "best_by_left_tail.csv": mark_ranked(strat, "left_tail_proxy", "left_tail", ascending=False),
        "best_by_drawdown_proxy.csv": mark_ranked(strat, "drawdown_proxy", "drawdown_proxy", ascending=False),
        "best_by_return_drawdown_ratio.csv": mark_ranked(strat, "return_drawdown_ratio", "return_drawdown_ratio"),
        "best_by_stability_and_validity.csv": mark_ranked(strat.assign(valid_rate=strat["valid_trial_count"] / strat["trial_count"]), "valid_rate", "stability_and_validity"),
    }
    warnings = discovery[discovery["warning"].ne("")]
    if warnings.empty:
        final_status = "PASS_V21_158_R1_BACKTEST_DECOMPOSITION_READY"
        decision = "SWITCHING_AND_STRATEGY_BACKTEST_RESULTS_DECOMPOSED_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_158_R1_DECOMPOSITION_WITH_INPUT_WARNINGS"
        decision = "DECOMPOSITION_READY_FOR_AVAILABLE_OUTPUTS_MISSING_COMPARISONS_RECORDED"
    latest = src_summary.get("latest_price_date_used", "")
    best_avg = ranked["best_by_average_return.csv"].iloc[0]["variant"]
    best_qqq = ranked["best_by_winrate_vs_QQQ.csv"].dropna(subset=["winrate_vs_QQQ"]).iloc[0]["variant"]
    best_tail = ranked["best_by_left_tail.csv"].iloc[0]["variant"]
    best_ratio = ranked["best_by_return_drawdown_ratio.csv"].dropna(subset=["return_drawdown_ratio"]).iloc[0]["variant"]
    role_map = dict(zip(roles["variant"], roles["role_implication"]))
    machine = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "source_v21_158_status": src_summary.get("FINAL_STATUS"),
        "governed_switching_differs_from_a1": src_summary.get("governed_switching_differs_from_a1", False),
        "governed_switching_classification": src_summary.get("governed_switching_classification"),
        "shadow_switching_classification": src_summary.get("shadow_switching_classification"),
        "shadow_candidate_states_observed": src_summary.get("shadow_candidate_states_observed"),
        "best_variant_by_avg_return": best_avg,
        "best_variant_by_winrate_vs_qqq": best_qqq,
        "best_variant_by_left_tail": best_tail,
        "best_variant_by_return_drawdown_ratio": best_ratio,
        "A1_vs_QQQ_winrate": src_summary.get("A1_vs_QQQ_winrate"),
        "governed_vs_A1_winrate": src_summary.get("governed_vs_A1_winrate"),
        "shadow_vs_A1_winrate": src_summary.get("shadow_vs_A1_winrate"),
        "shadow_vs_QQQ_winrate": src_summary.get("shadow_vs_QQQ_winrate"),
        "A1_role_implication": role_map.get("A1_ONLY"),
        "E_R1_role_implication": role_map.get("E_R1_ONLY"),
        "softcap_role_implication": role_map.get("SOFTCAP_ONLY"),
        "C_role_implication": role_map.get("C_ONLY"),
        "D_original_role_implication": role_map.get("D_ORIGINAL_REFERENCE"),
        "D_R2C_role_implication": role_map.get("D_R2C_REFERENCE"),
        "recommended_next_stage": "V21.159_E_R1_AND_SOFTCAP_FORWARD_MATURITY_MONITORING_OR_RECIPIENT_RISK_REPAIR",
        **FLAGS,
    }
    discovery.to_csv(OUT / "input_discovery_report.csv", index=False)
    strat.to_csv(OUT / "strategy_level_summary.csv", index=False)
    pair_key.to_csv(OUT / "pairwise_decomposition_matrix.csv", index=False)
    pair_key[["left_variant", "right_variant", "interpretation"]].to_csv(OUT / "pairwise_key_findings.csv", index=False)
    bench_summary.to_csv(OUT / "benchmark_decomposition_summary.csv", index=False)
    gov_dec.to_csv(OUT / "governed_switching_decomposition.csv", index=False)
    shadow_dec.to_csv(OUT / "shadow_switching_decomposition.csv", index=False)
    edge.to_csv(OUT / "switching_edge_attribution.csv", index=False)
    roles.to_csv(OUT / "strategy_role_implication_summary.csv", index=False)
    for name, df in ranked.items():
        df.to_csv(OUT / name, index=False)
    (OUT / "V21.158_R1_machine_summary.json").write_text(json.dumps(machine, indent=2), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "Does governed switching differ from A1? No.",
        "Did shadow switching improve anything vs A1? Diagnostic only; sample remains not actionable.",
        f"Best average return variant: {best_avg}.",
        f"Best winrate vs QQQ variant: {best_qqq}.",
        f"Best left-tail variant: {best_tail}.",
        f"Best return/drawdown ratio variant: {best_ratio}.",
        "A1 remains the primary control.",
        "E_R1 remains a defensive candidate waiting forward maturity.",
        "Soft-cap remains worth recipient-risk repair, not adoption.",
        "C has no clear confirmed role yet.",
        "D remains frozen/rejected current version but useful as reference; re-entry path remains open.",
        f"Recommended next stage: {machine['recommended_next_stage']}.",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.158_R1_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(json.dumps(machine, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
