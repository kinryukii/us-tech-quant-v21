from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_chain() -> None:
    names = [
        "v21_098_r1_input_validation.csv",
        "v21_098_r1_input_validation.json",
        "v21_098_r2_event_vulnerability_policy_buckets.csv",
        "v21_098_r3_event_policy_variants.csv",
        "v21_098_r4_top20_forward_policy_observation_ledger.csv",
        "v21_098_r5_historical_support_diagnostic_summary.csv",
        "v21_098_r6_current_d_top20_event_policy_dashboard.csv",
        "v21_098_r7_event_aware_entry_throttle_overlay_report.md",
        "v21_098_r7_event_aware_entry_throttle_overlay_summary.json",
    ]
    assert all((OUT / name).is_file() for name in names)
    summary = json.loads((OUT / names[-1]).read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] == "PASS"
    assert summary["TOP20_FORWARD_EVENTS_LOADED"] == 20
    assert summary["POLICY_VARIANTS_TESTED_OR_SCHEDULED"] == 10
    assert summary["TOP20_POLICY_OBSERVATION_ROWS"] == 1800
    assert summary["HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"] is False
    assert summary["PIT_LEAKAGE_WARNINGS"] == 0
    assert summary["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert summary["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert summary["RESEARCH_ONLY"] is True
    assert summary["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert summary["D_BASELINE_PRESERVED"] is True
    assert summary["V21_097_INPUTS_PRESERVED"] is True

    variants = pd.read_csv(OUT / names[3])
    assert variants["policy_variant"].nunique() == 10
    assert variants["historical_pre_event_backtest_allowed"].astype(str).str.upper().eq("FALSE").all()
    ledger = pd.read_csv(OUT / names[4])
    assert ledger.groupby(["ticker", "policy_variant"]).size().eq(9).all()
    assert ledger["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()
    support = pd.read_csv(OUT / names[5])
    assert support["historical_pre_event_backtest_allowed"].astype(str).str.upper().eq("FALSE").all()
    dashboard = pd.read_csv(OUT / names[6])
    assert len(dashboard) == 20
    assert dashboard["official_adoption_allowed"].astype(str).str.upper().eq("FALSE").all()


if __name__ == "__main__":
    test_chain()
    print("V21.098 event policy research tests passed.")
