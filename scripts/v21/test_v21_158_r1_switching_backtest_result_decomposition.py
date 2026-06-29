from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION")


def test_core_discovered_and_summaries() -> None:
    disc = pd.read_csv(OUT / "input_discovery_report.csv")
    assert disc[disc["source_name"].eq("random_trial_ledger")]["usable"].astype(bool).iloc[0]
    strat = pd.read_csv(OUT / "strategy_level_summary.csv")
    for variant in ["A1_ONLY", "GOVERNED_SWITCHING_CURRENT_RULES", "SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE", "QQQ_BENCHMARK"]:
        assert variant in set(strat["variant"])


def test_governed_shadow_and_d_classifications() -> None:
    roles = pd.read_csv(OUT / "strategy_role_implication_summary.csv")
    role = dict(zip(roles["variant"], roles["role_implication"]))
    assert role["GOVERNED_SWITCHING_CURRENT_RULES"] == "NOT_DIFFERENT_FROM_A1"
    assert role["SHADOW_SWITCHING_CANDIDATE_NOT_ACTIONABLE"] == "NOT_ACTIONABLE_SHADOW_ONLY"
    assert role["D_ORIGINAL_REFERENCE"] == "FROZEN_REFERENCE_ONLY"
    assert role["D_R2C_REFERENCE"] == "REJECTED_CURRENT_VERSION"


def test_ranked_tables_mark_non_actionable() -> None:
    for name in ["best_by_average_return.csv", "best_by_winrate_vs_QQQ.csv", "best_by_left_tail.csv", "best_by_drawdown_proxy.csv", "best_by_return_drawdown_ratio.csv", "best_by_stability_and_validity.csv"]:
        df = pd.read_csv(OUT / name)
        assert "non_actionable" in df.columns
        if "D_ORIGINAL_REFERENCE" in set(df["variant"]):
            assert df[df["variant"].eq("D_ORIGINAL_REFERENCE")]["non_actionable"].astype(bool).all()


def test_qqq_proxy_and_machine_summary_flags() -> None:
    s = json.loads((OUT / "V21.158_R1_machine_summary.json").read_text(encoding="utf-8"))
    for key in [
        "FINAL_STATUS", "DECISION", "latest_price_date_used", "source_v21_158_status",
        "governed_switching_differs_from_a1", "governed_switching_classification",
        "shadow_switching_classification", "shadow_candidate_states_observed",
        "best_variant_by_avg_return", "best_variant_by_winrate_vs_qqq",
        "best_variant_by_left_tail", "best_variant_by_return_drawdown_ratio",
        "A1_vs_QQQ_winrate", "governed_vs_A1_winrate", "shadow_vs_A1_winrate",
        "shadow_vs_QQQ_winrate", "A1_role_implication", "E_R1_role_implication",
        "softcap_role_implication", "C_role_implication", "D_original_role_implication",
        "D_R2C_role_implication", "recommended_next_stage", "D_permanent_ban",
        "D_reentry_path_open", "current_D_switching_allowed", "research_only",
        "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified",
        "current_primary_control_unchanged",
    ]:
        assert key in s
    assert s["D_permanent_ban"] is False
    assert s["D_reentry_path_open"] is True
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False


def test_outputs_and_no_mutation_claims() -> None:
    required = [
        "pairwise_decomposition_matrix.csv", "pairwise_key_findings.csv", "benchmark_decomposition_summary.csv",
        "governed_switching_decomposition.csv", "shadow_switching_decomposition.csv",
        "switching_edge_attribution.csv", "strategy_role_implication_summary.csv",
        "V21.158_R1_readable_report.txt", "V21.158_R1_machine_summary.json",
    ]
    for name in required:
        assert (OUT / name).exists(), name
    report = (OUT / "V21.158_R1_readable_report.txt").read_text(encoding="utf-8")
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "protected_outputs_modified=false" in report
