from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE")
REQUIRED = [
    "soft_cap_forward_tracking_ledger.csv",
    "soft_cap_weight_detail.csv",
    "soft_cap_forward_metrics_by_policy.csv",
    "pending_soft_cap_observations.csv",
    "invalid_soft_cap_observations.csv",
    "baseline_vs_soft_cap_comparison.csv",
    "overheat_skip_vs_soft_cap_comparison.csv",
    "effective_breadth_forward_audit.csv",
    "left_tail_forward_comparison.csv",
    "V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_controls_and_e_r1_diagnostic() -> None:
    report = (OUT / "compact_readable_report.txt").read_text(encoding="utf-8")
    assert "protected_outputs_modified=false" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "E_R1_diagnostic_only=true" in report


def test_invalid_lineage_not_adoption_evidence() -> None:
    report = (OUT / "V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE_REPORT.md").read_text(encoding="utf-8")
    assert "not used as adoption evidence" in report


def test_no_lookahead() -> None:
    ledger = pd.read_csv(OUT / "soft_cap_forward_tracking_ledger.csv")
    assert (pd.to_datetime(ledger["signal_date"]) <= pd.to_datetime(ledger["ranking_date"])).all()
    executed = ledger[ledger["execution_date"].notna() & ledger["execution_date"].astype(str).ne("")]
    if not executed.empty:
        assert (pd.to_datetime(executed["execution_date"]) > pd.to_datetime(executed["ranking_date"])).all()


def test_soft_cap_weights_fixed_and_sum_to_one() -> None:
    weights = pd.read_csv(OUT / "soft_cap_weight_detail.csv")
    soft = weights[weights["execution_policy"].eq("OVERHEAT_SOFT_CAP_R1")]
    assert not soft.empty
    grouped = soft.groupby(["strategy_name", "bucket", "horizon", "signal_date"])["final_weight"].sum()
    assert ((grouped - 1.0).abs() < 1e-8).all()
    assert (~soft["optimized_on_forward_returns"].astype(bool)).all()


def test_capped_weight_redistributed_only_to_non_overheated() -> None:
    w = pd.read_csv(OUT / "soft_cap_weight_detail.csv")
    soft = w[w["execution_policy"].eq("OVERHEAT_SOFT_CAP_R1")]
    assert (soft.loc[soft["overheat_flag"].astype(bool), "redistributed_weight_received"] == 0).all()
    assert (soft.loc[~soft["overheat_flag"].astype(bool), "redistributed_weight_received"] >= 0).all()


def test_no_top50_fill_inside_soft_cap() -> None:
    w = pd.read_csv(OUT / "soft_cap_weight_detail.csv")
    soft_top20 = w[(w["execution_policy"].eq("OVERHEAT_SOFT_CAP_R1")) & (w["bucket"].eq("Top20"))]
    assert (soft_top20["original_rank"] <= 20).all()


def test_pending_invalid_excluded_and_costs_recorded() -> None:
    ledger = pd.read_csv(OUT / "soft_cap_forward_tracking_ledger.csv")
    metrics = pd.read_csv(OUT / "soft_cap_forward_metrics_by_policy.csv")
    grouped = ledger.groupby(["strategy_name", "execution_policy", "bucket", "horizon", "maturity_status"]).size().unstack(fill_value=0)
    for _, row in metrics.iterrows():
        key = (row["strategy_name"], row["execution_policy"], row["bucket"], row["horizon"])
        if key in grouped.index:
            assert int(row["matured_observations"]) == int(grouped.loc[key].get("matured", 0))
            assert int(row["pending_observations"]) == int(grouped.loc[key].get("pending", 0))
            assert int(row["invalid_observations"]) == int(grouped.loc[key].get("invalid", 0))
    assert (ledger["transaction_cost_bps_per_side"] == 10.0).all()
    assert (ledger["slippage_bps_per_side"] == 5.0).all()
