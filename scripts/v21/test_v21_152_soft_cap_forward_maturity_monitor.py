from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR")
R3 = Path("outputs/v21/V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE")
REQUIRED = [
    "soft_cap_maturity_monitor_ledger.csv",
    "matured_soft_cap_observations.csv",
    "pending_soft_cap_observations.csv",
    "invalid_soft_cap_observations.csv",
    "soft_cap_matured_metrics_by_policy.csv",
    "primary_candidate_vs_baseline_maturity_comparison.csv",
    "primary_candidate_vs_QQQ_maturity_comparison.csv",
    "maturity_calendar.csv",
    "left_tail_maturity_comparison.csv",
    "V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR_REPORT.md",
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
    report = (OUT / "V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR_REPORT.md").read_text(encoding="utf-8")
    assert "not used as adoption evidence" in report


def test_no_lookahead() -> None:
    ledger = pd.read_csv(OUT / "soft_cap_maturity_monitor_ledger.csv")
    assert (pd.to_datetime(ledger["signal_date"]) <= pd.to_datetime(ledger["ranking_date"])).all()
    executed = ledger[ledger["execution_date"].notna() & ledger["execution_date"].astype(str).ne("")]
    if not executed.empty:
        assert (pd.to_datetime(executed["execution_date"]) > pd.to_datetime(executed["ranking_date"])).all()
    exited = ledger[ledger["required_exit_date"].notna() & ledger["required_exit_date"].astype(str).ne("")]
    if not exited.empty:
        assert (pd.to_datetime(exited["required_exit_date"]) > pd.to_datetime(exited["ranking_date"])).all()


def test_soft_cap_weights_not_retuned_and_match_r3() -> None:
    ledger = pd.read_csv(OUT / "soft_cap_maturity_monitor_ledger.csv")
    assert ledger["weight_matches_v21_151_r3"].astype(bool).all()
    r3 = pd.read_csv(R3 / "soft_cap_forward_tracking_ledger.csv")
    cols = ["strategy_name", "execution_policy", "bucket", "horizon", "ticker", "final_weight"]
    merged = ledger[cols].merge(r3[cols], on=cols[:-1], suffixes=("", "_r3"))
    assert ((merged["final_weight"] - merged["final_weight_r3"]).abs() < 1e-12).all()


def test_pending_invalid_excluded_from_matured_metrics() -> None:
    ledger = pd.read_csv(OUT / "soft_cap_maturity_monitor_ledger.csv")
    metrics = pd.read_csv(OUT / "soft_cap_matured_metrics_by_policy.csv")
    grouped = ledger.groupby(["strategy_name", "execution_policy", "bucket", "horizon", "maturity_status"]).size().unstack(fill_value=0)
    for _, row in metrics.iterrows():
        key = (row["strategy_name"], row["execution_policy"], row["bucket"], row["horizon"])
        assert int(row["matured_observations"]) == int(grouped.loc[key].get("matured", 0))
        assert int(row["pending_observations"]) == int(grouped.loc[key].get("pending", 0))
        assert int(row["invalid_observations"]) == int(grouped.loc[key].get("invalid", 0))


def test_costs_recorded() -> None:
    ledger = pd.read_csv(OUT / "soft_cap_maturity_monitor_ledger.csv")
    assert (ledger["transaction_cost_bps_per_side"] == 10.0).all()
    assert (ledger["slippage_bps_per_side"] == 5.0).all()
