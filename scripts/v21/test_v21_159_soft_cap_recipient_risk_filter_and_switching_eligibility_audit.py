import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT"
REQ = [
    "input_discovery_report.csv",
    "softcap_recipient_weight_ledger.csv",
    "softcap_recipient_return_contribution.csv",
    "softcap_recipient_downside_contribution.csv",
    "softcap_capped_name_attribution.csv",
    "softcap_weight_redistribution_summary.csv",
    "softcap_recipient_risk_score_ledger.csv",
    "softcap_filter_variant_portfolios.csv",
    "softcap_filter_variant_validity_ledger.csv",
    "softcap_filter_variant_refill_ledger.csv",
    "softcap_filter_backtest_summary.csv",
    "softcap_filter_backtest_by_horizon.csv",
    "softcap_filter_backtest_by_bucket.csv",
    "softcap_filter_pairwise_vs_a1.csv",
    "softcap_filter_pairwise_vs_raw_softcap.csv",
    "softcap_filter_pairwise_vs_qqq.csv",
    "recipient_risk_reduction_summary.csv",
    "recipient_filter_tradeoff_summary.csv",
    "softcap_risk_source_classification.csv",
    "softcap_switching_eligibility_audit.csv",
    "softcap_recommended_candidate.csv",
    "missing_input_warnings.csv",
    "V21.159_readable_report.txt",
    "V21.159_machine_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.159_machine_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_input_discovery():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    discovery = read("input_discovery_report.csv")
    assert "v21_158_r1_strategy_level_summary" in set(discovery["source_name"])
    assert "b_softcap_ticker_contribution_detail" in set(discovery["source_name"])
    assert discovery.loc[discovery["source_name"] == "b_softcap_ticker_contribution_detail", "usable"].astype(str).str.lower().eq("true").any()


def test_recipient_weight_deltas_and_capped_distinction():
    ledger = read("softcap_recipient_weight_ledger.csv")
    assert not ledger.empty
    assert (ledger.loc[ledger["is_recipient"].astype(str).str.lower() == "true", "weight_delta"] > 0).all()
    assert (ledger.loc[ledger["is_capped_name"].astype(str).str.lower() == "true", "weight_delta"] < 0).all()
    assert ledger["ticker"].str.upper().eq(ledger["ticker"]).all()


def test_recipient_risk_score_warning_columns():
    risk = read("softcap_recipient_risk_score_ledger.csv")
    cols = {
        "repeated_loser_flag",
        "left_tail_warning",
        "drawdown_warning",
        "sector_concentration_warning",
        "industry_concentration_warning",
        "data_quality_warning",
        "recipient_risk_score",
        "recipient_risk_bucket",
    }
    assert cols.issubset(risk.columns)
    assert set(risk["recipient_risk_bucket"]).issubset({"LOW", "MEDIUM", "HIGH", "INVALID_DATA"})


def test_filter_variants_exclude_and_refill_same_ranking_only():
    ports = read("softcap_filter_variant_portfolios.csv")
    refills = read("softcap_filter_variant_refill_ledger.csv")
    assert "SOFTCAP_FILTER_COMBINED_RISK" in set(ports["filter_variant"])
    assert ports.groupby(["filter_variant", "portfolio_bucket"])["final_filter_weight"].sum().round(8).eq(1.0).all()
    if not refills.empty:
        assert refills["same_strategy"].astype(str).str.lower().eq("true").all()
        assert refills["same_as_of_date"].astype(str).str.lower().eq("true").all()
        assert refills["lower_ranked_name_used"].astype(str).str.lower().eq("true").all()


def test_clean_stats_exclude_partial_and_switching_stays_disabled():
    validity = read("softcap_filter_variant_validity_ledger.csv")
    stats = read("softcap_filter_backtest_summary.csv")
    valid_variants = set(validity.loc[validity["is_valid_trial"].astype(str).str.lower() == "true", "filter_variant"])
    assert set(stats["filter_variant"]).issubset(valid_variants)
    elig = read("softcap_switching_eligibility_audit.csv")
    assert elig["softcap_switching_allowed"].astype(str).str.lower().eq("false").all()


def test_machine_summary_policy_flags_and_required_fields():
    s = summary()
    required = {
        "FINAL_STATUS",
        "DECISION",
        "latest_price_date_used",
        "softcap_recipient_rows",
        "capped_name_count",
        "recipient_count",
        "recipient_risk_source_classification",
        "best_filter_variant",
        "best_filter_avg_return",
        "best_filter_winrate_vs_a1",
        "best_filter_winrate_vs_qqq",
        "best_filter_left_tail_improvement_rate",
        "best_filter_drawdown_improvement_rate",
        "high_risk_recipient_weight_raw",
        "high_risk_recipient_weight_best_filter",
        "softcap_role_review_candidate",
        "softcap_forward_tracking_candidate",
        "softcap_switching_allowed",
        "softcap_blocker_after_v21_159",
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
    assert s["softcap_switching_allowed"] is False
