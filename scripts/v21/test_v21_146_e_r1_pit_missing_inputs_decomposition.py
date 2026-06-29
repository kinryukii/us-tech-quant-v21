import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.146_E_R1_PIT_MISSING_INPUTS_DECOMPOSITION")
REQUIRED = [
    "V21.146_summary.json",
    "V21.146_pit_missing_input_inventory.csv",
    "V21.146_repairability_classification.csv",
    "V21.146_minimum_viable_pit_bridge.csv",
    "V21.146_e_r1_vs_a1_pit_comparability.csv",
    "V21.146_repair_roadmap.csv",
    "V21.146_forward_maturity_interaction.csv",
    "V21.146_remaining_blockers.csv",
    "V21.146_readable_report.txt",
]

INPUT_FAMILIES = {
    "historical price panel",
    "historical adjusted close",
    "historical technical factors",
    "historical momentum factors",
    "historical risk factors",
    "historical market regime factors",
    "historical data trust factors",
    "historical fundamental factors if used",
    "historical universe membership",
    "historical sector / industry metadata",
    "historical repaired metadata source",
    "historical ranking weights",
    "historical scoring formula",
    "historical exclusion rules",
    "historical stale/missing ticker rules",
    "historical benchmark data",
    "delisted ticker coverage",
}


def summary():
    with (OUT / "V21.146_summary.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def test_required_outputs_and_controls():
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["strategy_adoption_allowed"] is False
    assert s["research_only"] is True


def test_inventory_includes_all_required_families():
    inv = pd.read_csv(OUT / "V21.146_pit_missing_input_inventory.csv")
    assert INPUT_FAMILIES.issubset(set(inv["input_family"]))
    assert inv["availability_classification"].isin(
        ["AVAILABLE_PIT_STRICT", "AVAILABLE_PIT_LITE", "CURRENT_SNAPSHOT_ONLY", "MISSING", "UNKNOWN"]
    ).all()


def test_repairability_for_every_missing_or_pit_lite_input():
    inv = pd.read_csv(OUT / "V21.146_pit_missing_input_inventory.csv")
    repair = pd.read_csv(OUT / "V21.146_repairability_classification.csv")
    need = inv[inv["availability_classification"].isin(["AVAILABLE_PIT_LITE", "CURRENT_SNAPSHOT_ONLY", "MISSING", "UNKNOWN"])]
    assert set(need["input_family"]).issubset(set(repair["input_family"]))
    assert repair["repairability_classification"].notna().all()


def test_comparability_and_roadmap_exist():
    comp = pd.read_csv(OUT / "V21.146_e_r1_vs_a1_pit_comparability.csv")
    road = pd.read_csv(OUT / "V21.146_repair_roadmap.csv")
    assert not comp.empty
    assert "comparability_classification" in comp.columns
    assert not road.empty
    assert "priority" in road.columns


def test_report_contains_status_and_decision():
    text = (OUT / "V21.146_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
