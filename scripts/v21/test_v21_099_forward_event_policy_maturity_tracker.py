from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_099_r1_policy_observation_input_validation.csv",
        "v21_099_r1_policy_observation_input_validation.json",
        "v21_099_r2_policy_checkpoint_maturity_status.csv",
        "v21_099_r3_matured_policy_observation_outcomes.csv",
        "v21_099_r4_policy_variant_performance_summary.csv",
        "v21_099_r5_ticker_forward_policy_summary.csv",
        "v21_099_r6_forward_event_policy_maturity_report.md",
        "v21_099_r6_forward_event_policy_maturity_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    required = {
        "FINAL_STATUS", "DECISION", "INPUT_V21_098_STATUS",
        "POLICY_OBSERVATION_ROWS_LOADED", "POLICY_CHECKPOINTS_MATURED",
        "POLICY_CHECKPOINTS_PENDING", "POLICY_CHECKPOINTS_PRICE_MISSING",
        "MATURED_POLICY_OUTCOME_ROWS", "POLICY_VARIANTS_EVALUATED",
        "SEVERE_LOSS_EVENTS_OBSERVED", "AVOIDED_LOSS_COUNT",
        "MISSED_UPSIDE_COUNT", "BEST_POLICY_VARIANT_SO_FAR",
        "WORST_POLICY_VARIANT_SO_FAR", "LEFT_TAIL_IMPROVEMENT_OBSERVED",
        "MISSED_WINNER_RISK_OBSERVED", "FORWARD_POLICY_OBSERVATION_ALLOWED",
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED",
        "OFFICIAL_POLICY_ADOPTION_ALLOWED", "PIT_LEAKAGE_WARNINGS",
        "PROTECTED_OUTPUTS_MODIFIED", "OFFICIAL_OUTPUTS_MODIFIED",
        "RESEARCH_ONLY", "OFFICIAL_ADOPTION_ALLOWED",
        "D_BASELINE_PRESERVED", "RECOMMENDED_NEXT_STAGE",
    }
    assert required <= set(summary)
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["POLICY_OBSERVATION_ROWS_LOADED"] == 1800
    assert summary["POLICY_VARIANTS_EVALUATED"] == 10
    assert summary["MATURED_POLICY_OUTCOME_ROWS"] == summary["POLICY_CHECKPOINTS_MATURED"]
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["OFFICIAL_POLICY_ADOPTION_ALLOWED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    maturity = pd.read_csv(OUT / names[2])
    assert len(maturity) == 1800
    assert set(maturity["checkpoint_maturity_status"]) <= {
        "MATURED", "PENDING_FUTURE_CHECKPOINT", "PENDING_PRICE_DATA",
        "PRICE_MISSING", "INVALID_DATE", "EVENT_DATE_CHANGED_NEEDS_REVIEW",
    }
    outcomes = pd.read_csv(OUT / names[3])
    assert len(outcomes) == summary["MATURED_POLICY_OUTCOME_ROWS"]
    if len(outcomes):
        assert outcomes["research_only"].astype(str).str.upper().eq("TRUE").all()
        assert outcomes["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()
    variants = pd.read_csv(OUT / names[4])
    assert variants["policy_variant"].nunique() == 10
    assert variants["research_only"].astype(str).str.upper().eq("TRUE").all()
    assert variants["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()


if __name__ == "__main__":
    test_chain()
    print("V21.099 forward event policy maturity tracker tests passed.")
