from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION")
REQ = [
    "softcap_return_attribution_by_strategy.csv",
    "softcap_risk_attribution_by_strategy.csv",
    "b_softcap_ticker_contribution_detail.csv",
    "b_softcap_day_level_attribution.csv",
    "overheated_name_validation.csv",
    "redistributed_weight_recipient_audit.csv",
    "drawdown_source_audit.csv",
    "p5_source_audit.csv",
    "cross_strategy_softcap_interpretation.csv",
    "V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name


def test_controls_and_lineage() -> None:
    report = (OUT / "V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION_REPORT.md").read_text(encoding="utf-8")
    assert "protected_outputs_modified=false" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "E_R1_diagnostic_only=true" in report
    assert "not used as adoption evidence" in report
    assert "soft_cap_not_retuned=true" in report


def test_contribution_reconciles() -> None:
    ret = pd.read_csv(OUT / "softcap_return_attribution_by_strategy.csv")
    for _, row in ret.iterrows():
        parts = row["capped_overheated_contribution_delta"] + row["redistributed_recipient_contribution_delta"] + row["transaction_cost_slippage_effect"]
        assert abs(parts - row["return_delta"]) < 1e-10


def test_risk_and_detail_outputs_nonempty() -> None:
    assert not pd.read_csv(OUT / "softcap_risk_attribution_by_strategy.csv").empty
    assert not pd.read_csv(OUT / "drawdown_source_audit.csv").empty
    assert not pd.read_csv(OUT / "p5_source_audit.csv").empty
    assert not pd.read_csv(OUT / "b_softcap_ticker_contribution_detail.csv").empty


def test_day_level_each_window_day() -> None:
    d = pd.read_csv(OUT / "b_softcap_day_level_attribution.csv")
    assert not d.empty
    assert d["date"].nunique() == len(d)
    assert {"QQQ_daily_return", "B_baseline_daily_return", "B_soft_cap_daily_return", "soft_cap_daily_delta"}.issubset(d.columns)
