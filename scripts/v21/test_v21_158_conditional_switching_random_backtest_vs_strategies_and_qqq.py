from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ")
REQ = [
    "input_discovery_report.csv", "random_trial_ledger.csv", "random_backtest_summary.csv",
    "pairwise_comparison_summary.csv", "pairwise_comparison_by_horizon.csv", "pairwise_comparison_by_bucket.csv",
    "benchmark_comparison_summary.csv", "benchmark_comparison_by_horizon.csv", "benchmark_comparison_by_bucket.csv",
    "switching_state_usage_summary.csv", "switching_return_attribution.csv", "switching_risk_attribution.csv",
    "switching_trigger_outcome_summary.csv", "variant_risk_maturity_classification.csv",
    "invalid_trial_reason_summary.csv", "missing_input_warnings.csv", "V21.158_readable_report.txt", "V21.158_machine_summary.json",
]


def test_outputs_and_summary_fields() -> None:
    for name in REQ:
        assert (OUT / name).exists(), name
    s = json.loads((OUT / "V21.158_machine_summary.json").read_text(encoding="utf-8"))
    for key in [
        "FINAL_STATUS", "DECISION", "latest_price_date_used", "random_seed_count", "random_draws_per_seed",
        "total_random_trials", "valid_random_trials", "invalid_random_trials", "valid_trial_rate",
        "variants_compared", "benchmark_used", "nasdaq_index_available", "qqq_used_as_nasdaq_proxy",
        "governed_switching_differs_from_a1", "governed_switching_classification", "shadow_switching_classification",
        "shadow_candidate_states_observed", "A1_vs_QQQ_winrate", "governed_vs_A1_winrate", "shadow_vs_A1_winrate",
        "shadow_vs_QQQ_winrate", "D_permanent_ban", "D_reentry_path_open", "current_D_switching_allowed",
        "research_only", "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified",
        "current_primary_control_unchanged",
    ]:
        assert key in s


def test_switching_inputs_loaded_and_governed_a1_only() -> None:
    d = pd.read_csv(OUT / "input_discovery_report.csv")
    assert d[d["source_name"].eq("state_machine_rules")]["usable"].astype(bool).iloc[0]
    trials = pd.read_csv(OUT / "random_trial_ledger.csv")
    gov = trials[trials["selected_variant"].eq("GOVERNED_SWITCHING_CURRENT_RULES")]
    assert set(gov["selected_strategy_used"]) == {"A1_ONLY"}


def test_shadow_can_use_e_r1_and_is_not_actionable() -> None:
    trials = pd.read_csv(OUT / "random_trial_ledger.csv")
    shadow = trials[trials["selected_variant"].eq("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE")]
    assert shadow["not_actionable"].astype(bool).all()
    if "STATE_DEFENSIVE_A1_E_R1" in set(shadow["selected_state"]):
        assert "E_R1_ONLY" in set(shadow["selected_strategy_used"])


def test_current_d_not_in_switching_paths_and_reentry_open() -> None:
    trials = pd.read_csv(OUT / "random_trial_ledger.csv")
    switch = trials[trials["selected_variant"].isin(["GOVERNED_SWITCHING_CURRENT_RULES", "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE"])]
    assert "D_ORIGINAL_REFERENCE" not in set(switch["selected_strategy_used"])
    s = json.loads((OUT / "V21.158_machine_summary.json").read_text(encoding="utf-8"))
    assert s["D_permanent_ban"] is False
    assert s["D_reentry_path_open"] is True


def test_reproducible_seeds_and_clean_validity() -> None:
    trials = pd.read_csv(OUT / "random_trial_ledger.csv")
    assert trials["seed"].nunique() == 20
    valid = trials[trials["is_valid_trial"].astype(bool)]
    portfolio_valid = valid[~valid["selected_variant"].eq("QQQ_BENCHMARK")]
    assert (portfolio_valid["valid_holding_count"] >= portfolio_valid["requested_holding_count"]).all()
    qqq_valid = valid[valid["selected_variant"].eq("QQQ_BENCHMARK")]
    assert (qqq_valid["valid_holding_count"] == 1).all()
    invalid = trials[~trials["is_valid_trial"].astype(bool)]
    if not invalid.empty:
        assert invalid["invalid_reason"].notna().all()


def test_pairwise_and_benchmark() -> None:
    pair = pd.read_csv(OUT / "pairwise_comparison_summary.csv")
    assert not pair.empty
    assert ((pair["left_variant"] == "A1_ONLY") & (pair["right_variant"] == "QQQ_BENCHMARK")).any()
    bench = pd.read_csv(OUT / "benchmark_comparison_summary.csv")
    assert not bench.empty


def test_nasdaq_warning_and_classifications() -> None:
    miss = pd.read_csv(OUT / "missing_input_warnings.csv")
    assert "NASDAQ_INDEX_UNAVAILABLE_QQQ_USED_AS_PROXY" in set(miss["warning"])
    cls = pd.read_csv(OUT / "variant_risk_maturity_classification.csv")
    assert cls[cls["variant"].eq("GOVERNED_SWITCHING_CURRENT_RULES")]["classification"].iloc[0] == "NOT_DIFFERENT_FROM_A1"
    assert cls[cls["variant"].eq("SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE")]["classification"].iloc[0] == "NOT_ACTIONABLE"


def test_no_mutation_flags() -> None:
    s = json.loads((OUT / "V21.158_machine_summary.json").read_text(encoding="utf-8"))
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
