import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING"
REQ = [
    "c_r2_shadow_ranking_full.csv",
    "c_r2_shadow_ranking_top50.csv",
    "c_r2_top20_vs_a1_c_overlap.csv",
    "c_r2_factor_attribution.csv",
    "c_r2_risk_attribution.csv",
    "c_r2_sector_industry_concentration.csv",
    "c_r2_data_quality_warnings.csv",
    "V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING_report.txt",
    "V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING_summary.json").read_text(encoding="utf-8"))


def test_required_output_files_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name


def test_summary_policy_flags():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["c_r2_adoption_blocked_by_default"] is True
    assert s["DECISION"] == "C_R2_FORWARD_TRACKING_ONLY"


def test_ranking_and_top50_shape_and_top20_marker():
    full = read("c_r2_shadow_ranking_full.csv")
    top50 = read("c_r2_shadow_ranking_top50.csv")
    assert len(full) > 0
    assert 0 < len(top50) <= 50
    assert "is_top20" in full.columns
    assert full["is_top20"].astype(str).str.lower().isin(["true", "false"]).all()
    assert full["is_top20"].astype(str).str.lower().eq("true").sum() == min(20, len(full))
    assert "c_r2_score" in full.columns
    assert "selected_regime" in full.columns
    assert "regime_confidence" in full.columns
    assert "eligible_for_c_r2" in full.columns


def test_selected_regime_weights_sum_to_one():
    s = summary()
    assert round(sum(s["selected_regime_weights"].values()), 10) == 1.0
    full = read("c_r2_shadow_ranking_full.csv")
    assert round(float(full["factor_weight_sum_selected_regime"].iloc[0]), 10) == 1.0


def test_output_directory_is_isolated_and_no_protected_official_modified():
    s = summary()
    assert OUT.as_posix().endswith("outputs/v21/V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
    assert s["protected_outputs_modified"] is False


def test_comparison_and_diagnostics_present():
    overlap = read("c_r2_top20_vs_a1_c_overlap.csv")
    assert {"C_R2_vs_A1", "C_R2_vs_C_ORIGINAL"}.issubset(set(overlap["comparison"]))
    assert {"summary", "rank_diff"}.issubset(set(overlap["row_type"]))
    risk = read("c_r2_risk_attribution.csv")
    assert {"Top20", "Top50"}.issubset(set(risk["bucket"]))
    conc = read("c_r2_sector_industry_concentration.csv")
    assert {"sector", "industry"}.issubset(set(conc["dimension"]))
