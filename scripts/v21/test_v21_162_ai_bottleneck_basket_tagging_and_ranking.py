import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING"
REQ = [
    "ai_bottleneck_universe_tags.csv",
    "ai_bottleneck_shadow_ranking_full.csv",
    "ai_bottleneck_shadow_ranking_top50.csv",
    "ai_bottleneck_top20.csv",
    "ai_bottleneck_subtheme_concentration.csv",
    "ai_bottleneck_single_name_concentration.csv",
    "ai_bottleneck_vs_a1_c_r2_c_overlap.csv",
    "ai_bottleneck_non_eligible_c_r2_top20.csv",
    "ai_bottleneck_data_quality_warnings.csv",
    "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING_report.txt",
    "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING_summary.json",
]
TAXONOMY = {
    "DRAM_HBM_NAND",
    "STORAGE_HDD_SSD",
    "SEMICAP_EQUIPMENT",
    "ADVANCED_PACKAGING_TEST",
    "DATACENTER_POWER",
    "COOLING_THERMAL",
    "ELECTRIFICATION_GRID",
    "AI_INFRA_INDUSTRIAL",
    "ASIA_AI_SUPPLY_CHAIN",
    "NON_AI_BOTTLENECK",
}


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert summary()["decision"] == "AI_BOTTLENECK_FORWARD_TRACKING_ONLY"


def test_policy_flags_remain_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False
    assert s["ai_bottleneck_adoption_allowed"] is False


def test_tag_universe_and_taxonomy():
    tags = read("ai_bottleneck_universe_tags.csv")
    assert len(tags) > 0
    required_cols = {
        "ticker",
        "company_name",
        "ai_bottleneck_eligible",
        "primary_ai_bottleneck_theme",
        "secondary_ai_bottleneck_theme",
        "ai_bottleneck_score",
        "tag_confidence",
        "tag_source",
        "manual_review_required",
        "reason",
    }
    assert required_cols.issubset(tags.columns)
    conc = read("ai_bottleneck_subtheme_concentration.csv")
    assert TAXONOMY.issubset(set(conc["primary_ai_bottleneck_theme"]))
    assert "NON_AI_BOTTLENECK" in set(tags["primary_ai_bottleneck_theme"])


def test_ranking_shapes():
    full = read("ai_bottleneck_shadow_ranking_full.csv")
    top50 = read("ai_bottleneck_shadow_ranking_top50.csv")
    top20 = read("ai_bottleneck_top20.csv")
    assert len(full) > 0
    assert 0 < len(top50) <= 50
    assert 0 < len(top20) <= 20
    assert "ai_bottleneck_shadow_score" in full.columns


def test_non_eligible_c_r2_top20_and_concentration_diagnostics_exist():
    non = read("ai_bottleneck_non_eligible_c_r2_top20.csv")
    assert non is not None
    sub = read("ai_bottleneck_subtheme_concentration.csv")
    single = read("ai_bottleneck_single_name_concentration.csv")
    assert {"Top20", "Top50"}.issubset(set(sub["bucket"]))
    assert {"Top20", "Top50"}.issubset(set(single["bucket"]))
    assert "score_contribution_weight" in single.columns


def test_overlap_diagnostics_exist():
    ov = read("ai_bottleneck_vs_a1_c_r2_c_overlap.csv")
    expected = {
        "AI_BOTTLENECK_vs_A1",
        "AI_BOTTLENECK_vs_C_R2_REPAIRED",
        "AI_BOTTLENECK_vs_C_ORIGINAL",
    }
    assert expected.issubset(set(ov["comparison"]))
    assert {"Top20", "Top50"}.issubset(set(ov["bucket"]))


def test_output_directory_is_isolated_and_no_protected_modified():
    s = summary()
    assert OUT.as_posix().endswith("outputs/v21/V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
    assert s["protected_outputs_modified"] is False
