from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21"


def test_outputs_and_integrity() -> None:
    required = [
        "v21_093_r1_event_master_ledger.csv",
        "v21_093_r1_event_schema_validation.json",
        "v21_093_r1_event_schema_validation.md",
        "v21_093_r2_event_risk_features.csv",
        "v21_093_r2_event_risk_feature_summary.csv",
        "v21_093_r2_event_risk_feature_validation.json",
        "v21_093_r2_event_risk_feature_validation.md",
        "v21_093_r3_d_event_risk_ranking_variants.csv",
        "v21_093_r3_variant_top20_top50_summary.csv",
        "v21_093_r3_join_validation.json",
        "v21_093_r3_join_validation.md",
        "v21_093_r4_random_event_risk_backtest_rows.csv",
        "v21_093_r4_random_event_risk_backtest_summary.csv",
        "v21_093_r4_random_event_risk_backtest_validation.json",
        "v21_093_r4_random_event_risk_backtest_validation.md",
        "v21_093_r5_event_risk_factor_decision_report.md",
        "v21_093_r5_event_risk_factor_decision_summary.json",
    ]
    assert all((OUT / name).is_file() for name in required)
    final = json.loads((OUT / required[-1]).read_text(encoding="utf-8"))
    assert final["FINAL_STATUS"] == "PASS"
    assert final["D_BASELINE_PRESERVED"] is True
    assert final["PROTECTED_OUTPUTS_MODIFIED"] is False
    assert final["OFFICIAL_OUTPUTS_MODIFIED"] is False
    assert final["RESEARCH_ONLY"] is True
    assert final["OFFICIAL_ADOPTION_ALLOWED"] is False
    assert final["PIT_LEAKAGE_WARNINGS"] == 0
    assert final["VARIANTS_TESTED"] == 5

    ledger = pd.read_csv(OUT / required[0])
    assert ledger["event_id"].is_unique
    assert pd.to_numeric(ledger["severity"]).between(0, 100).all()
    assert ledger["known_as_of_timestamp"].notna().all()

    features = pd.read_csv(OUT / required[3])
    assert not features.duplicated(["ticker", "as_of_date"]).any()
    assert features["event_risk_score"].between(0, 100).all()

    variants = pd.read_csv(OUT / required[7])
    baseline = variants[variants["variant_id"].eq("D_BASELINE_PRESERVED")]
    assert (baseline["D_rank"] == baseline["variant_rank"]).all()
    assert (baseline["D_final_score"] == baseline["event_adjusted_score"]).all()


if __name__ == "__main__":
    test_outputs_and_integrity()
    print("V21.093 risk event factor validation chain tests passed.")
