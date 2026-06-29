from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_099_r1_active_event_window_input_validation.csv",
        "v21_099_r1_active_event_window_input_validation.json",
        "v21_099_r1_active_event_window_calendar.csv",
        "v21_099_r1_current_active_event_watch_dashboard.csv",
        "v21_099_r1_next_maturity_trigger_table.csv",
        "v21_099_r1_active_event_window_monitor_report.md",
        "v21_099_r1_active_event_window_monitor_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    required = {
        "FINAL_STATUS", "DECISION", "INPUT_V21_098_STATUS", "INPUT_V21_099_STATUS",
        "TOP20_EVENTS_TRACKED", "POLICY_OBSERVATION_ROWS_TRACKED",
        "CURRENT_ACTIVE_EVENT_WINDOW_ROWS", "CURRENT_APPROACHING_EVENT_ROWS",
        "EARLIEST_EVENT_DATE", "EARLIEST_T_MINUS_5_DATE",
        "EARLIEST_EXPECTED_MATURITY_DATE", "DAYS_TO_EARLIEST_EVENT",
        "DAYS_TO_EARLIEST_MATURITY", "FORWARD_POLICY_OBSERVATION_ALLOWED",
        "POLICY_PERFORMANCE_EVALUATION_ALLOWED",
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED", "PIT_LEAKAGE_WARNINGS",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY",
        "OFFICIAL_ADOPTION_ALLOWED", "D_BASELINE_PRESERVED", "RECOMMENDED_NEXT_STAGE",
    }
    assert required <= set(summary)
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["TOP20_EVENTS_TRACKED"] == 20
    assert summary["POLICY_OBSERVATION_ROWS_TRACKED"] == 1800
    assert summary["POLICY_PERFORMANCE_EVALUATION_ALLOWED"] is False
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    calendar = pd.read_csv(OUT / names[2])
    assert len(calendar) == 20
    assert calendar["research_only"].astype(str).str.upper().eq("TRUE").all()
    watch = pd.read_csv(OUT / names[3])
    assert len(watch) == 20
    assert watch["official_trade_action_allowed"].astype(str).str.upper().eq("FALSE").all()
    assert watch["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()
    allowed_states = {
        "OUTSIDE_EVENT_WINDOW", "APPROACHING_T_MINUS_20",
        "APPROACHING_T_MINUS_10", "APPROACHING_T_MINUS_5",
        "INSIDE_T_MINUS_5_TO_T0", "INSIDE_T0_TO_T_PLUS_3",
        "INSIDE_T_PLUS_3_TO_T_PLUS_20", "POST_EVENT_OBSERVATION_MATURED",
        "DATE_INVALID",
    }
    assert set(watch["event_window_state"]) <= allowed_states
    triggers = pd.read_csv(OUT / names[4])
    assert len(triggers) == 1800
    assert triggers["research_only"].astype(str).str.upper().eq("TRUE").all()
    assert triggers["expected_maturity_date"].notna().all()


if __name__ == "__main__":
    test_chain()
    print("V21.099-R1 active event-window monitor tests passed.")
