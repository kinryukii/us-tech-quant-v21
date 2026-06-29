from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_100_r1_input_validation.csv",
        "v21_100_r1_input_validation.json",
        "v21_100_r2_event_risk_primitives.csv",
        "v21_100_r3_event_risk_weight_grid.csv",
        "v21_100_r4_event_risk_scores_by_variant.csv",
        "v21_100_r5_event_row_weight_backtest_results.csv",
        "v21_100_r6_optional_pit_portfolio_skipped.json",
        "v21_100_r7_event_weight_variant_summary.csv",
        "v21_100_r8_event_weight_robustness_checks.csv",
        "v21_100_r9_event_risk_weight_grid_backtest_report.md",
        "v21_100_r9_event_risk_weight_grid_backtest_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    required = {
        "FINAL_STATUS", "DECISION", "EVENT_ROWS_LOADED", "EVENT_ROWS_USABLE",
        "WEIGHT_VARIANTS_TESTED", "EVENT_ROW_BACKTEST_ROWS",
        "OPTIONAL_PIT_PORTFOLIO_BACKTEST_RUN", "BEST_LEFT_TAIL_VARIANT",
        "BEST_NET_SCORE_VARIANT", "SEVERE_LOSS_REDUCTION_OBSERVED",
        "MISSED_UPSIDE_RISK_OBSERVED", "PLACEBO_CHECK_PASSED",
        "ROBUSTNESS_CHECK_PASSED", "HISTORICAL_EVENT_OCCURRENCE_BACKTEST_ALLOWED",
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED",
        "FORWARD_POLICY_OBSERVATION_ALLOWED", "EVENT_WEIGHT_RESEARCH_ALLOWED",
        "OFFICIAL_EVENT_WEIGHT_ADOPTION_ALLOWED", "PIT_LEAKAGE_WARNINGS",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY",
        "OFFICIAL_ADOPTION_ALLOWED", "D_BASELINE_PRESERVED", "RECOMMENDED_NEXT_STAGE",
    }
    assert required <= set(summary)
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["EVENT_ROWS_USABLE"] > 0
    assert summary["WEIGHT_VARIANTS_TESTED"] == 17
    assert summary["EVENT_ROW_BACKTEST_ROWS"] == summary["EVENT_ROWS_USABLE"] * 17
    assert summary["OPTIONAL_PIT_PORTFOLIO_BACKTEST_RUN"] is False
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["OFFICIAL_EVENT_WEIGHT_ADOPTION_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    primitives = pd.read_csv(OUT / names[2])
    assert primitives["historical_event_occurrence_usable"].astype(str).str.upper().eq("TRUE").all()
    assert primitives["research_only"].astype(str).str.upper().eq("TRUE").all()
    grid = pd.read_csv(OUT / names[3])
    assert len(grid) == 17
    assert set(grid["variant_id"]) >= {
        "EVENT_WEIGHT_CONTROL_0", "FULL_EVENT_RISK_MEDIUM", "POST_EVENT_OVERLAY_025",
    }
    scores = pd.read_csv(OUT / names[4])
    assert scores["historical_pre_event_backtest_allowed"].astype(str).str.upper().eq("FALSE").all()
    known = pd.to_datetime(scores["known_as_of_timestamp"], utc=True).dt.tz_convert(None).dt.normalize()
    starts = pd.to_datetime(scores["risk_window_start"])
    assert (starts >= known).all()
    results = pd.read_csv(OUT / names[5])
    assert results["diagnostic_only"].astype(str).str.upper().eq("TRUE").all()
    skip = json.loads((OUT / names[6]).read_text(encoding="utf-8"))
    assert skip["skip_reason"] == "HISTORICAL_PIT_D_RANKING_SNAPSHOTS_NOT_AVAILABLE"
    variants = pd.read_csv(OUT / names[7])
    assert variants["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()
    robust = pd.read_csv(OUT / names[8])
    assert len(robust) >= 10


if __name__ == "__main__":
    test_chain()
    print("V21.100 event risk weight grid backtest tests passed.")
