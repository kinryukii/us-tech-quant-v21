import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR"
REQ = [
    "c_r2_proxy_source_audit.csv",
    "c_r2_missing_proxy_root_cause.csv",
    "c_r2_repaired_proxy_table.csv",
    "c_r2_r1_shadow_ranking_full.csv",
    "c_r2_r1_shadow_ranking_top50.csv",
    "c_r2_r1_vs_v21_161_original_comparison.csv",
    "c_r2_r1_factor_attribution_delta.csv",
    "c_r2_r1_regime_audit.csv",
    "c_r2_r1_data_quality_warnings.csv",
    "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_report.txt",
    "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_exist_and_summary_exists():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert summary()["decision"] == "C_R2_FORWARD_TRACKING_ONLY_REPAIR_AUDITED"


def test_policy_flags_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["c_r2_adoption_allowed"] is False


def test_proxy_audit_and_root_cause():
    audit = read("c_r2_proxy_source_audit.csv")
    assert len(audit) > 0
    assert {"profitability_proxy", "fcf_quality_proxy", "value_proxy", "market_regime_source"}.issubset(set(audit["proxy_name"]))
    roots = read("c_r2_missing_proxy_root_cause.csv")
    assert len(roots) > 0
    assert "root_cause" in roots.columns


def test_repaired_ranking_and_top50():
    full = read("c_r2_r1_shadow_ranking_full.csv")
    top50 = read("c_r2_r1_shadow_ranking_top50.csv")
    assert len(full) > 0
    assert 0 < len(top50) <= 50
    assert "is_top20" in full.columns
    assert full["is_top20"].astype(str).str.lower().eq("true").sum() == min(20, len(full))


def test_regime_audit_required_fields_and_fallback_reason():
    s = summary()
    audit = read("c_r2_r1_regime_audit.csv")
    required = {
        "selected_regime",
        "regime_confidence",
        "regime_source",
        "regime_selected_by_signal",
        "regime_selected_by_fallback",
    }
    assert required.issubset(audit.columns)
    assert s["selected_regime"] in {"risk_on", "neutral", "risk_off"}
    if s["regime_selected_by_fallback"] is True:
        assert s.get("fallback_reason")


def test_output_directory_is_isolated_and_no_protected_modified():
    s = summary()
    assert OUT.as_posix().endswith("outputs/v21/V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
    assert s["protected_outputs_modified"] is False


def test_comparison_and_factor_delta():
    comp = read("c_r2_r1_vs_v21_161_original_comparison.csv")
    assert {"summary", "rank_diff"}.issubset(set(comp["row_type"]))
    assert {"Top20", "Top50"}.issubset(set(comp.loc[comp["row_type"].eq("summary"), "bucket"]))
    delta = read("c_r2_r1_factor_attribution_delta.csv")
    assert len(delta) > 0
    s = summary()
    assert "original_v21_161_top20_overlap" in s
    assert "original_v21_161_top50_overlap" in s
