from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_100_r1_failure_decomposition_input_validation.csv",
        "v21_100_r1_failure_decomposition_input_validation.json",
        "v21_100_r1_missed_upside_decomposition.csv",
        "v21_100_r1_ticker_concentration_audit.csv",
        "v21_100_r1_event_type_concentration_audit.csv",
        "v21_100_r1_placebo_failure_forensic.csv",
        "v21_100_r1_narrow_subset_diagnostic.csv",
        "v21_100_r1_event_weight_failure_decomposition_report.md",
        "v21_100_r1_event_weight_failure_decomposition_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    required = {
        "FINAL_STATUS", "DECISION", "INPUT_V21_100_STATUS",
        "BEST_DIAGNOSTIC_VARIANT", "PRIMARY_FAILURE_REASON",
        "MISSED_UPSIDE_DOMINATES", "TICKER_CONCENTRATION_DETECTED",
        "EVENT_TYPE_CONCENTRATION_DETECTED", "PLACEBO_FAILURE_CONFIRMED",
        "PROMISING_SUBSETS_FOUND", "PROMISING_SUBSETS_COUNT",
        "FORWARD_ONLY_SUBSETS_RECOMMENDED", "EVENT_WEIGHT_RESEARCH_ALLOWED",
        "EVENT_WEIGHT_D_INTEGRATION_ALLOWED",
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED", "PIT_LEAKAGE_WARNINGS",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED",
        "RESEARCH_ONLY", "OFFICIAL_ADOPTION_ALLOWED", "D_BASELINE_PRESERVED",
        "RECOMMENDED_NEXT_STAGE",
    }
    assert required <= set(summary)
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["INPUT_V21_100_STATUS"] == "PASS"
    assert summary["PLACEBO_FAILURE_CONFIRMED"] is True
    assert summary["EVENT_WEIGHT_D_INTEGRATION_ALLOWED"] is False
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    decomposition = pd.read_csv(OUT / names[2])
    assert set(decomposition["variant_id"]) == {
        "POST_EVENT_OVERLAY_025", "POST_EVENT_OVERLAY_050",
        "FULL_EVENT_RISK_HEAVY", "EVENT_TYPE_PLUS_TICKER_HEAVY",
    }
    assert decomposition["research_only"].astype(str).str.upper().eq("TRUE").all()
    ticker = pd.read_csv(OUT / names[3])
    assert abs(ticker["share_of_total_improvement"].sum() - 1.0) < 1e-8
    event_type = pd.read_csv(OUT / names[4])
    assert abs(event_type["share_of_total_improvement"].sum() - 1.0) < 1e-8
    placebo = pd.read_csv(OUT / names[5])
    assert (~placebo["passed"].map(lambda x: str(x).upper() in {"TRUE", "1"})).any()
    subsets = pd.read_csv(OUT / names[6])
    assert len(subsets) == 8
    assert subsets["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()


if __name__ == "__main__":
    test_chain()
    print("V21.100-R1 event weight failure decomposition tests passed.")
