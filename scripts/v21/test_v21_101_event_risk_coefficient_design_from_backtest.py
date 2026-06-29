from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_101_r1_coefficient_design_input_validation.csv",
        "v21_101_r1_coefficient_design_input_validation.json",
        "v21_101_r2_official_event_coefficient_decision.csv",
        "v21_101_r3_research_event_risk_coefficient_spec.csv",
        "v21_101_r4_event_risk_score_formula.md",
        "v21_101_r5_event_risk_bucket_policy.csv",
        "v21_101_r6_top20_forward_event_diagnostic_coefficients.csv",
        "v21_101_r7_coefficient_safety_checks.csv",
        "v21_101_r8_event_risk_coefficient_design_report.md",
        "v21_101_r8_event_risk_coefficient_design_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    required = {
        "FINAL_STATUS", "DECISION", "INPUT_V21_100_STATUS",
        "INPUT_V21_100_R1_STATUS", "PLACEBO_FAILURE_CONFIRMED",
        "PROMISING_NARROW_SUBSETS_FOUND", "OFFICIAL_EVENT_RISK_COEFFICIENT",
        "OFFICIAL_D_INTEGRATION_ALLOWED", "OFFICIAL_SHADOW_RANKING_ALLOWED",
        "RESEARCH_DIAGNOSTIC_COEFFICIENTS_CREATED", "TOP20_FORWARD_ROWS_SCORED",
        "RISK_BUCKETS_CREATED", "MAX_RESEARCH_EXPOSURE_REDUCTION",
        "DEFAULT_EXTREME_EXPOSURE_SCALE",
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED",
        "FORWARD_OBSERVATION_ALLOWED", "EVENT_WEIGHT_RESEARCH_FROZEN",
        "PIT_LEAKAGE_WARNINGS", "PROTECTED_OUTPUTS_MODIFIED",
        "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY",
        "OFFICIAL_ADOPTION_ALLOWED", "D_BASELINE_PRESERVED",
        "RECOMMENDED_NEXT_STAGE",
    }
    assert required <= set(summary)
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["DECISION"] == "EVENT_COEFFICIENTS_DIAGNOSTIC_ONLY_D_INTEGRATION_BLOCKED"
    assert summary["OFFICIAL_EVENT_RISK_COEFFICIENT"] == 0
    assert summary["OFFICIAL_D_INTEGRATION_ALLOWED"] is False
    assert summary["OFFICIAL_SHADOW_RANKING_ALLOWED"] is False
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["EVENT_WEIGHT_RESEARCH_FROZEN"] is True
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True

    official = pd.read_csv(OUT / names[2])
    assert len(official) == 4
    assert official["coefficient_value"].eq(0).all()
    assert official["allowed_for_d_integration"].astype(str).str.upper().eq("FALSE").all()
    assert official["allowed_for_shadow_ranking"].astype(str).str.upper().eq("FALSE").all()
    research = pd.read_csv(OUT / names[3])
    assert len(research) == 5
    assert np.isclose(research["coefficient_value"].sum(), 1.0)
    assert research["allowed_for_d_integration"].astype(str).str.upper().eq("FALSE").all()
    policy = pd.read_csv(OUT / names[5])
    assert set(policy["risk_bucket"]) == {"LOW", "MEDIUM", "HIGH", "EXTREME"}
    assert not policy["exposure_scale"].eq(.25).any()
    scored = pd.read_csv(OUT / names[6])
    assert len(scored) == 20
    assert scored["official_d_weight"].eq(0).all()
    assert scored["official_ranking_penalty"].eq(0).all()
    assert scored["official_trade_action_allowed"].astype(str).str.upper().eq("FALSE").all()
    assert scored["event_risk_score"].between(0, 100).all()
    low = scored["event_confidence"].astype(str).str.upper().eq("LOW")
    assert scored.loc[low, "event_risk_score"].le(60).all()
    safety = pd.read_csv(OUT / names[7])
    assert safety["passed"].astype(str).str.upper().eq("TRUE").all()


if __name__ == "__main__":
    test_chain()
    print("V21.101 event risk coefficient design tests passed.")
