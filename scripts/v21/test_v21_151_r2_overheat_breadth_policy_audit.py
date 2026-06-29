from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.151_R2_OVERHEAT_BREADTH_POLICY_AUDIT")
REQUIRED = [
    "overheat_breadth_policy_summary.csv",
    "policy_variant_metrics_by_strategy_bucket_horizon.csv",
    "primary_candidate_policy_comparison.csv",
    "effective_holdings_breadth_comparison.csv",
    "cash_weight_exposure_audit.csv",
    "top50_fill_detail.csv",
    "soft_cap_weight_audit.csv",
    "relaxed_threshold_breadth_audit.csv",
    "left_tail_policy_comparison.csv",
    "V21.151_R2_OVERHEAT_BREADTH_POLICY_AUDIT_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_controls_and_e_r1_diagnostic() -> None:
    s = pd.read_csv(OUT / "overheat_breadth_policy_summary.csv").iloc[0]
    assert bool(s["official_adoption_allowed"]) is False
    assert bool(s["broker_action_allowed"]) is False
    assert bool(s["protected_outputs_modified"]) is False
    assert bool(s["research_only"]) is True
    assert bool(s["E_R1_diagnostic_only"]) is True


def test_invalid_replay_lineage_not_adoption_evidence() -> None:
    report = (OUT / "V21.151_R2_OVERHEAT_BREADTH_POLICY_AUDIT_REPORT.md").read_text(encoding="utf-8")
    assert "not used as adoption evidence" in report


def test_no_lookahead_and_top50_fill_records_rank() -> None:
    fills = pd.read_csv(OUT / "top50_fill_detail.csv")
    assert {"fill_ticker", "original_rank", "fill_reason"}.issubset(fills.columns)
    if not fills.empty:
        assert (fills["original_rank"] > 20).all()
        assert (fills["original_rank"] <= 50).all()


def test_cash_held_has_cash_exposure_and_no_padding_claim() -> None:
    m = pd.read_csv(OUT / "policy_variant_metrics_by_strategy_bucket_horizon.csv")
    cash = m[m["policy_variant"].eq("OVERHEAT_SKIP_CASH_HELD")]
    assert not cash.empty
    assert (cash["average_cash_weight"] >= 0).all()
    s = pd.read_csv(OUT / "overheat_breadth_policy_summary.csv").iloc[0]
    assert bool(s["implicit_padding_or_filling_applied"]) is False


def test_entered_only_records_concentration_and_effective_count() -> None:
    b = pd.read_csv(OUT / "effective_holdings_breadth_comparison.csv")
    entered = b[b["policy_variant"].eq("OVERHEAT_SKIP_ENTERED_ONLY_REWEIGHT")]
    assert not entered.empty
    assert entered["effective_holding_count"].notna().all()
    assert entered["concentration_proxy"].notna().all()


def test_relaxed_thresholds_fixed_not_optimized() -> None:
    r = pd.read_csv(OUT / "relaxed_threshold_breadth_audit.csv")
    assert not r.empty
    assert (r["RSI_threshold"] == 82).all()
    assert (r["KDJ_K_threshold"] == 92).all()
    assert (~r["optimized_on_forward_returns"].astype(bool)).all()
