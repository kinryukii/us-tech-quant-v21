from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

P = Path(__file__).with_name("v21_252_r1_factor_sign_convention_and_top_beta_export.py")
S = importlib.util.spec_from_file_location("m252r1", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def seed(repo: Path) -> Path:
    root = repo / m.V252_REL
    fields = ["factor_name", "factor_family", "factor_subtype", "forward_window", "topn_scope", "source_mode", "beta_standardized", "beta_abs_rank", "beta_sign", "beta_t_stat_or_bootstrap_score", "rank_ic", "bucket_spread_top_minus_bottom", "positive_date_rate", "p10_impact", "worst5_impact", "repeated_loser_impact", "turnover_impact", "concentration_impact", "strategy_most_helped", "strategy_most_hurt", "recommended_action", "confidence_label", "warning_flags"]
    rows = [
        {"factor_name": "Risk", "factor_family": "Risk", "factor_subtype": "family", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE_SNAPSHOT", "beta_standardized": "0.05", "beta_abs_rank": "1", "beta_sign": "positive", "beta_t_stat_or_bootstrap_score": "1", "rank_ic": "0.2", "bucket_spread_top_minus_bottom": "0.03", "positive_date_rate": "1", "p10_impact": "0.01", "worst5_impact": "0.01", "repeated_loser_impact": "0", "turnover_impact": "0", "concentration_impact": "0", "strategy_most_helped": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "strategy_most_hurt": "A1", "recommended_action": "increase", "confidence_label": "MEDIUM", "warning_flags": ""},
        {"factor_name": "repeated_loser_penalty", "factor_family": "Risk", "factor_subtype": "new_repair", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE_SNAPSHOT", "beta_standardized": "-0.04", "beta_abs_rank": "2", "beta_sign": "negative", "beta_t_stat_or_bootstrap_score": "-1", "rank_ic": "-0.2", "bucket_spread_top_minus_bottom": "-0.02", "positive_date_rate": "0", "p10_impact": "-0.02", "worst5_impact": "-0.02", "repeated_loser_impact": "-0.04", "turnover_impact": "0", "concentration_impact": "0", "strategy_most_helped": "A1", "strategy_most_hurt": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "recommended_action": "decrease", "confidence_label": "MEDIUM", "warning_flags": ""},
        {"factor_name": "volatility", "factor_family": "Risk", "factor_subtype": "technical", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE_SNAPSHOT", "beta_standardized": "0.03", "beta_abs_rank": "3", "beta_sign": "positive", "beta_t_stat_or_bootstrap_score": "1", "rank_ic": "0.1", "bucket_spread_top_minus_bottom": "0.01", "positive_date_rate": "1", "p10_impact": "0.01", "worst5_impact": "0.01", "repeated_loser_impact": "0", "turnover_impact": "0", "concentration_impact": "0", "strategy_most_helped": "A1", "strategy_most_hurt": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "recommended_action": "increase", "confidence_label": "MEDIUM", "warning_flags": ""},
        {"factor_name": "gap_overnight_risk_factor", "factor_family": "Risk", "factor_subtype": "new_repair", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE_SNAPSHOT", "beta_standardized": "-0.02", "beta_abs_rank": "4", "beta_sign": "negative", "beta_t_stat_or_bootstrap_score": "-1", "rank_ic": "-0.1", "bucket_spread_top_minus_bottom": "-0.01", "positive_date_rate": "0", "p10_impact": "-0.01", "worst5_impact": "-0.01", "repeated_loser_impact": "0", "turnover_impact": "0", "concentration_impact": "0", "strategy_most_helped": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "strategy_most_hurt": "A1", "recommended_action": "decrease", "confidence_label": "MEDIUM", "warning_flags": ""},
    ]
    wc(root / "factor_effect_coefficient_master.csv", rows, fields)
    wc(root / "factor_positive_negative_effect_summary.csv", [{"factor_name": "Risk", "forward_window": "1D", "topn_scope": "20", "source_mode": "LIVE_SNAPSHOT", "beta_sign": "positive", "recommended_action": "increase"}], ["factor_name", "forward_window", "topn_scope", "source_mode", "beta_sign", "recommended_action"])
    wc(root / "factor_weight_adjustment_recommendation.csv", [{"factor_name": "Risk", "factor_family": "Risk", "recommended_action": "increase", "confidence_label": "MEDIUM", "basis": "beta"}], ["factor_name", "factor_family", "recommended_action", "confidence_label", "basis"])
    wc(root / "strategy_factor_exposure_effect_matrix.csv", [{"strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "factor_name": "Risk", "forward_window": "1D", "topn_scope": "20", "average_factor_exposure_z": "1", "beta_standardized": "0.05", "estimated_contribution": "0.05", "contribution_rank": "1", "positive_or_negative_driver": "positive", "source_mode": "LIVE_SNAPSHOT", "warning_flags": ""}, {"strategy": "A1", "factor_name": "repeated_loser_penalty", "forward_window": "1D", "topn_scope": "20", "average_factor_exposure_z": "1", "beta_standardized": "-0.04", "estimated_contribution": "-0.04", "contribution_rank": "1", "positive_or_negative_driver": "negative", "source_mode": "LIVE_SNAPSHOT", "warning_flags": ""}], ["strategy", "factor_name", "forward_window", "topn_scope", "average_factor_exposure_z", "beta_standardized", "estimated_contribution", "contribution_rank", "positive_or_negative_driver", "source_mode", "warning_flags"])
    return root


def test_top_beta_export_penalty_semantics_and_safety(tmp_path):
    repo = tmp_path / "repo"
    root = seed(repo)
    before = (root / "factor_effect_coefficient_master.csv").read_bytes()
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert (root / "factor_effect_coefficient_master.csv").read_bytes() == before
    assert summary["factor_count_loaded"] == 4
    assert summary["top_positive_factor_names"][0] == "Risk"
    assert summary["top_negative_factor_names"][0] == "repeated_loser_penalty"
    assert summary["repeated_loser_penalty_semantic_action"] == "decrease_or_cap_adjusted_score_weight"
    assert summary["volatility_semantic_action"] == "cap_or_diagnostic_only"
    assert summary["gap_overnight_risk_semantic_action"] == "increase_penalty_or_risk_control"
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert "higher_is_worse" in (out / "penalty_factor_direction_audit.csv").read_text(encoding="utf-8")
    assert "official_adoption_allowed" in (out / "coefficient_guided_weight_action_input.csv").read_text(encoding="utf-8")
    for name in ["factor_top_positive_beta_leaderboard.csv", "factor_top_negative_beta_leaderboard.csv", "factor_sign_convention_audit.csv", "factor_semantic_effect_interpretation.csv", "e_r2_exact_factor_coefficient_table.csv", "new_factor_lite_exact_factor_coefficient_table.csv", "a1_left_tail_exact_factor_coefficient_table.csv", "v21_252_r1_summary.json", "V21.252_R1_factor_sign_convention_top_beta_report.txt"]:
        assert (out / name).exists()


def test_missing_inputs_fail(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "FAIL_V21_252_R1_BLOCKED"
    assert summary["error_count"] == 1
