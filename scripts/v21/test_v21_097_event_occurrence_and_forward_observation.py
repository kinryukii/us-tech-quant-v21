from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_097_r1_event_input_validation.csv",
        "v21_097_r1_event_input_validation.json",
        "v21_097_r2_historical_event_occurrence_return_rows.csv",
        "v21_097_r2_historical_event_occurrence_price_join_validation.json",
        "v21_097_r3_event_type_impact_summary.csv",
        "v21_097_r4_ticker_event_vulnerability_summary.csv",
        "v21_097_r4_sector_event_vulnerability_summary.csv",
        "v21_097_r5_top20_forward_event_observation_schedule.csv",
        "v21_097_r5_top20_forward_event_observation_status.csv",
        "v21_097_r6_current_d_event_risk_dashboard.csv",
        "v21_097_r7_event_occurrence_and_forward_observation_report.md",
        "v21_097_r7_event_occurrence_and_forward_observation_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["TOP20_FORWARD_EVENT_ROWS_LOADED"] == 20
    assert summary["TOP20_FORWARD_OBSERVATION_CHECKPOINTS_CREATED"] == 180
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True
    assert summary["V21_096_LEDGER_PRESERVED"] is True

    returns = pd.read_csv(OUT / names[2])
    assert {"return_1d", "return_5d", "return_20d", "excess_return_5d"}.issubset(returns.columns)
    schedule = pd.read_csv(OUT / names[7])
    assert schedule.groupby("ticker").size().eq(9).all()
    dashboard = pd.read_csv(OUT / names[9])
    assert dashboard["ranking_penalty_allowed"].astype(str).str.upper().eq("FALSE").all()
    assert dashboard["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()


if __name__ == "__main__":
    test_chain()
    print("V21.097 event occurrence and forward observation tests passed.")
