import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.160_D_R3_RISK_CONSTRAINED_REBUILD_FEASIBILITY_AUDIT"
REQ = [
    "input_discovery_report.csv",
    "d_return_source_decomposition.csv",
    "d_vs_a1_return_contribution_by_ticker.csv",
    "d_vs_a1_return_contribution_by_sector.csv",
    "d_vs_a1_return_contribution_by_industry.csv",
    "d_outlier_return_contribution.csv",
    "d_risk_source_decomposition.csv",
    "d_concentration_audit.csv",
    "d_left_tail_drawdown_audit.csv",
    "d_repeated_loser_audit.csv",
    "d_neutralization_retention_audit.csv",
    "d_regime_sensitivity_audit.csv",
    "d_r3_candidate_design_spec.json",
    "d_r3_candidate_portfolios.csv",
    "d_r3_candidate_refill_ledger.csv",
    "d_r3_candidate_validity_ledger.csv",
    "d_r3_candidate_backtest_summary.csv",
    "d_r3_candidate_backtest_by_horizon.csv",
    "d_r3_candidate_backtest_by_bucket.csv",
    "d_r3_pairwise_vs_a1.csv",
    "d_r3_pairwise_vs_d_original.csv",
    "d_r3_pairwise_vs_qqq.csv",
    "d_r3_pairwise_vs_e_r1_left_tail.csv",
    "d_r3_reentry_gate_evaluation.csv",
    "d_r3_gate_failure_reasons.csv",
    "d_r3_probationary_overlay_permission_audit.csv",
    "d_r3_recommended_candidate.csv",
    "d_role_implication_summary.csv",
    "missing_input_warnings.csv",
    "V21.160_readable_report.txt",
    "V21.160_machine_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.160_machine_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_input_discovery():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    discovery = read("input_discovery_report.csv")
    assert "D_original_ranking" in set(discovery["source_name"])
    assert "A1_ranking" in set(discovery["source_name"])
    assert "V21_158_R1_strategy_summary" in set(discovery["source_name"])
    assert "V21_155_D_reentry_gate_spec" in set(discovery["source_name"])


def test_d_roles_preserved_and_not_permanently_banned():
    roles = read("d_role_implication_summary.csv")
    assert "D_ORIGINAL_REMAINS_FROZEN_REFERENCE" in set(roles["role_implication"])
    assert "D_R2C_REMAINS_REJECTED_CURRENT_VERSION" in set(roles["role_implication"])
    s = summary()
    assert s["D_permanent_ban"] is False
    assert s["D_reentry_path_open"] is True
    assert s["D_current_switching_allowed"] is False


def test_candidate_portfolios_generated_without_mutating_d_original():
    ports = read("d_r3_candidate_portfolios.csv")
    assert not ports.empty
    assert "D_R3_COMBINED_RISK_CONSTRAINED" in set(ports["candidate_variant"])
    assert ports["strategy"].eq("D_WEIGHT_OPTIMIZED_R1").all()
    spec = json.loads((OUT / "d_r3_candidate_design_spec.json").read_text(encoding="utf-8"))
    assert spec["official_adoption_allowed"] is False
    assert spec["broker_action_allowed"] is False


def test_refill_same_d_ranking_same_date_lower_rank_only():
    refills = read("d_r3_candidate_refill_ledger.csv")
    if not refills.empty:
        assert refills["same_D_ranking"].astype(str).str.lower().eq("true").all()
        assert refills["same_as_of_date"].astype(str).str.lower().eq("true").all()
        assert refills["lower_ranked_name_used"].astype(str).str.lower().eq("true").all()


def test_clean_stats_exclude_partial_and_no_immature_pairs():
    validity = read("d_r3_candidate_validity_ledger.csv")
    stats = read("d_r3_candidate_backtest_summary.csv")
    valid = set(validity.loc[validity["is_valid_trial"].astype(str).str.lower() == "true", "candidate_variant"])
    assert set(stats["candidate_variant"]).issubset(valid)
    assert validity["immature_forward_window_excluded"].astype(str).str.lower().isin(["false", "true"]).all()
    pair = read("d_r3_pairwise_vs_a1.csv")
    assert "one_sided_invalid_pair_excluded" in pair.columns


def test_gate_failures_and_d_r3_not_actionable():
    gates = read("d_r3_reentry_gate_evaluation.csv")
    fails = read("d_r3_gate_failure_reasons.csv")
    assert not gates.empty
    assert "concentration_gate_pass" in gates.columns
    assert "left_tail_gate_pass" in gates.columns
    assert "repeated_loser_gate_pass" in gates.columns
    assert "neutralization_retention_gate_pass" in gates.columns
    assert gates["forward_maturity_gate_pass"].astype(str).str.lower().eq("false").all()
    assert not fails.empty
    perm = read("d_r3_probationary_overlay_permission_audit.csv")
    assert perm["primary_control_allowed"].astype(str).str.lower().eq("false").all()
    assert perm["switching_allowed"].astype(str).str.lower().eq("false").all()
    assert perm["broker_action_allowed"].astype(str).str.lower().eq("false").all()


def test_machine_summary_mandatory_fields_and_policy_flags():
    s = summary()
    required = {
        "FINAL_STATUS",
        "DECISION",
        "latest_price_date_used",
        "D_original_best_avg_return_confirmed",
        "D_current_switching_allowed",
        "D_permanent_ban",
        "D_reentry_path_open",
        "d_return_source_primary",
        "d_risk_source_primary",
        "candidate_count",
        "best_d_r3_candidate",
        "best_d_r3_avg_return",
        "best_d_r3_winrate_vs_a1",
        "best_d_r3_winrate_vs_qqq",
        "best_d_r3_left_tail_improvement_vs_a1",
        "best_d_r3_drawdown_improvement_vs_a1",
        "best_d_r3_concentration_gate_pass",
        "best_d_r3_left_tail_gate_pass",
        "best_d_r3_repeated_loser_gate_pass",
        "best_d_r3_neutralization_retention_gate_pass",
        "best_d_r3_forward_maturity_gate_pass",
        "best_d_r3_reentry_gate_pass",
        "d_r3_forward_tracking_candidate",
        "d_r3_switching_allowed",
        "d_r3_adoption_allowed",
        "d_r3_broker_action_allowed",
        "D_original_role_after_v21_160",
        "D_R2C_role_after_v21_160",
        "D_R3_role_after_v21_160",
        "recommended_next_stage",
        "governed_state_unchanged",
        "current_primary_control_unchanged",
        "research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
        "protected_outputs_modified",
    }
    assert required.issubset(s)
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["governed_state_unchanged"] is True
    assert s["current_primary_control_unchanged"] is True
    assert s["D_current_switching_allowed"] is False
    assert s["D_permanent_ban"] is False
    assert s["D_reentry_path_open"] is True
    assert s["d_r3_switching_allowed"] is False
    assert s["d_r3_adoption_allowed"] is False
    assert s["d_r3_broker_action_allowed"] is False
