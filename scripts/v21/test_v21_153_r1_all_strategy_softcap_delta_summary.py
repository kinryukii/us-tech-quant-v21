from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.153_R1_ALL_STRATEGY_SOFTCAP_DELTA_SUMMARY")


def test_outputs_exist() -> None:
    assert (OUT / "all_strategy_softcap_delta_summary.csv").exists()
    assert (OUT / "compact_readable_report.txt").exists()


def test_required_fields() -> None:
    df = pd.read_csv(OUT / "all_strategy_softcap_delta_summary.csv")
    required = {
        "strategy",
        "baseline_return",
        "soft_cap_return",
        "return_delta",
        "baseline_excess_vs_QQQ",
        "soft_cap_excess_vs_QQQ",
        "excess_delta_vs_QQQ",
        "baseline_max_drawdown",
        "soft_cap_max_drawdown",
        "drawdown_delta",
        "baseline_p5",
        "soft_cap_p5",
        "p5_delta",
        "improved_return_true_false",
        "improved_drawdown_true_false",
        "improved_left_tail_true_false",
        "overall_interpretation",
    }
    assert required.issubset(df.columns)
    assert len(df) >= 5


def test_report_has_final_label_and_controls() -> None:
    report = (OUT / "compact_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_LABEL=" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report
    assert "protected_outputs_modified=false" in report
