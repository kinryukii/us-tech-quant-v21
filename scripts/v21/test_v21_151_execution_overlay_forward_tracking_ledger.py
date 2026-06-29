from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER")
REQUIRED = [
    "forward_execution_overlay_ledger.csv",
    "matured_forward_metrics_by_variant.csv",
    "pending_forward_observations.csv",
    "invalid_forward_observations.csv",
    "skipped_entry_audit.csv",
    "left_tail_forward_comparison.csv",
    "baseline_vs_overheat_skip_comparison.csv",
    "V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_no_protected_official_or_broker_mutation_claimed() -> None:
    report = (OUT / "compact_readable_report.txt").read_text(encoding="utf-8")
    assert "protected_outputs_modified=false" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report


def test_e_r1_remains_diagnostic_only() -> None:
    ledger = pd.read_csv(OUT / "forward_execution_overlay_ledger.csv")
    e = ledger[ledger["strategy_name"].eq("E_R1_REPAIRED")]
    assert not e.empty
    assert e["diagnostic_only"].astype(bool).all()


def test_invalid_replay_not_adoption_evidence() -> None:
    report = (OUT / "V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER_REPORT.md").read_text(encoding="utf-8")
    assert "not used as adoption evidence" in report


def test_no_lookahead_execution() -> None:
    ledger = pd.read_csv(OUT / "forward_execution_overlay_ledger.csv")
    ranking = pd.to_datetime(ledger["ranking_date"])
    signal = pd.to_datetime(ledger["execution_signal_date"])
    assert (signal <= ranking).all()
    executed = ledger[ledger["execution_date"].notna() & ledger["execution_date"].astype(str).ne("")]
    if not executed.empty:
        assert (pd.to_datetime(executed["execution_date"]) > pd.to_datetime(executed["ranking_date"])).all()


def test_pending_and_invalid_excluded_from_matured_metrics() -> None:
    ledger = pd.read_csv(OUT / "forward_execution_overlay_ledger.csv")
    metrics = pd.read_csv(OUT / "matured_forward_metrics_by_variant.csv")
    grouped = ledger.groupby(["strategy_name", "execution_variant", "bucket", "horizon", "maturity_status"]).size().unstack(fill_value=0)
    for _, row in metrics.iterrows():
        key = (row["strategy_name"], row["execution_variant"], row["bucket"], row["horizon"])
        matured = int(grouped.loc[key].get("matured", 0)) if key in grouped.index else 0
        pending = int(grouped.loc[key].get("pending", 0)) if key in grouped.index else 0
        invalid = int(grouped.loc[key].get("invalid", 0)) if key in grouped.index else 0
        assert int(row["matured_observations"]) == matured
        assert int(row["pending_observations"]) == pending
        assert int(row["invalid_observations"]) == invalid


def test_skip_reasons_recorded_for_skipped_entries() -> None:
    skipped = pd.read_csv(OUT / "skipped_entry_audit.csv")
    if not skipped.empty:
        assert skipped["skip_reason"].notna().all()
        assert skipped["skip_reason"].astype(str).str.len().gt(0).all()


def test_transaction_cost_and_slippage_recorded() -> None:
    ledger = pd.read_csv(OUT / "forward_execution_overlay_ledger.csv")
    assert (ledger["transaction_cost_bps_per_side"] == 10.0).all()
    assert (ledger["slippage_bps_per_side"] == 5.0).all()
