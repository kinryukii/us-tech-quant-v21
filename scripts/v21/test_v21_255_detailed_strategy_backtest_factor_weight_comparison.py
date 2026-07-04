from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

P = Path(__file__).with_name("v21_255_detailed_strategy_backtest_factor_weight_comparison.py")
S = importlib.util.spec_from_file_location("m255", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def seed(repo: Path) -> Path:
    bt_fields = ["strategy","topn_scope","forward_window","trial_count","average_return","median_return","win_rate","positive_rate","p10_return","worst5_return","source_mode_robustness"]
    wc(repo / m.V254R1_REL / "pre0616_random_asof_trial_summary_by_strategy.csv", [
        {"strategy": "A1", "topn_scope": "20", "forward_window": "1D", "trial_count": "1", "average_return": "0.01", "median_return": "0.01", "win_rate": "1", "positive_rate": "1", "p10_return": "0.0", "worst5_return": "0.0", "source_mode_robustness": "RETROSPECTIVE_SAME_LOGIC_STRESS"},
        {"strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "topn_scope": "20", "forward_window": "1D", "trial_count": "1", "average_return": "0.02", "median_return": "0.02", "win_rate": "1", "positive_rate": "1", "p10_return": "0.01", "worst5_return": "0.01", "source_mode_robustness": "POST_HOC_CANDIDATE_STRESS"},
    ], bt_fields)
    post_fields = ["period"] + bt_fields
    wc(repo / m.V254_REL / "post_0616_to_now_strategy_backtest_summary.csv", [
        {"period": "POST_0616_TO_NOW_RANDOM_ASOF", "strategy": m.E_R3_BASE, "topn_scope": "20", "forward_window": "1D", "trial_count": "1", "average_return": "0.03", "median_return": "0.03", "win_rate": "1", "positive_rate": "1", "p10_return": "0.02", "worst5_return": "0.02", "source_mode_robustness": "POST_HOC_CANDIDATE_STRESS"},
        {"period": "POST_0616_TO_NOW_RANDOM_ASOF", "strategy": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "topn_scope": "20", "forward_window": "1D", "trial_count": "1", "average_return": "0.04", "median_return": "0.04", "win_rate": "1", "positive_rate": "1", "p10_return": "0.0", "worst5_return": "0.0", "source_mode_robustness": "POST_HOC_CANDIDATE_STRESS"},
    ], post_fields)
    wc(repo / m.V254_REL / "random_start_to_now_strategy_backtest_summary.csv", [
        {"period": "RANDOM_START_TO_NOW", "strategy": m.E_R3_BASE, "topn_scope": "20", "forward_window": "1D", "trial_count": "1", "average_return": "0.03", "median_return": "0.03", "win_rate": "1", "positive_rate": "1", "p10_return": "0.02", "worst5_return": "0.02", "source_mode_robustness": "POST_HOC_CANDIDATE_STRESS"},
    ], post_fields)
    wc(repo / m.V253_REL / "e_r3_weight_candidate_master.csv", [{"candidate": m.E_R3_BASE, "factor_family": f, "weight": str(w), "weights_sum": "1"} for f, w in [("Fundamental",0.15),("Technical",0.25),("Strategy",0.15),("Risk",0.31),("Market Regime",0.09),("Data Trust",0.05)]], ["candidate","factor_family","weight","weights_sum"])
    wc(repo / m.V252_REL / "factor_effect_coefficient_master.csv", [{"factor_name": "Risk", "factor_family": "Risk", "beta_standardized": "0.1", "rank_ic": "0.2", "bucket_spread_top_minus_bottom": "0.03", "positive_date_rate": "1", "source_mode": "LIVE"}, {"factor_name": "Strategy", "factor_family": "Strategy", "beta_standardized": "-0.1", "rank_ic": "-0.2", "bucket_spread_top_minus_bottom": "-0.03", "positive_date_rate": "0", "source_mode": "LIVE"}], ["factor_name","factor_family","beta_standardized","rank_ic","bucket_spread_top_minus_bottom","positive_date_rate","source_mode"])
    wc(repo / m.V252R1_REL / "coefficient_guided_weight_action_input.csv", [{"factor_name": "Risk", "coefficient_guided_action": "increase", "sign_conflict": "False", "raw_beta_standardized": "0.1"}, {"factor_name": "Strategy", "coefficient_guided_action": "decrease", "sign_conflict": "False", "raw_beta_standardized": "-0.1"}], ["factor_name","coefficient_guided_action","sign_conflict","raw_beta_standardized"])
    return repo / m.V254R1_REL / "pre0616_random_asof_trial_summary_by_strategy.csv"


def test_v255_outputs_weights_contribution_and_safety(tmp_path):
    repo = tmp_path / "repo"
    prior = seed(repo)
    before = prior.read_bytes()
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert prior.read_bytes() == before
    assert summary["error_count"] == 0
    assert summary["broker_action_allowed"] is False and summary["official_adoption_allowed"] is False
    assert summary["recommended_current_regime_strategy"] == m.E_R3_BASE
    fam = list(csv.DictReader((out / "strategy_family_weight_comparison.csv").open("r", encoding="utf-8")))
    assert any(r["strategy"] == m.E_R3_BASE and r["factor_family"] == "Risk" and float(r["weight"]) == 0.31 for r in fam)
    active = list(csv.DictReader((out / "strategy_active_weight_vs_e_r2.csv").open("r", encoding="utf-8")))
    assert any(r["strategy"] == m.E_R3_BASE and r["factor_family"] == "Risk" and float(r["active_weight"]) > 0 for r in active)
    matrix = list(csv.DictReader((out / "strategy_factor_weight_effectiveness_matrix.csv").open("r", encoding="utf-8")))
    assert any(r["strategy"] == m.E_R3_BASE and r["factor_name"] == "Risk" and float(r["estimated_factor_contribution"]) > 0 for r in matrix)
    assert "POST_HOC" in (out / "strategy_backtest_comparison_master.csv").read_text(encoding="utf-8")
    for name in ["factor_effectiveness_comparison_master.csv","factor_sign_conflict_comparison.csv","strategy_subfactor_weight_comparison.csv","e_r3_post0616_success_attribution.csv","e_r3_pre0616_failure_attribution.csv","new_factor_lite_high_return_attribution.csv","v21_255_summary.json","V21.255_detailed_strategy_backtest_factor_weight_comparison_report.txt"]:
        assert (out / name).exists()


def test_missing_inputs_block(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "FAIL_V21_255_COMPARISON_BLOCKED"
    assert summary["error_count"] == 1
