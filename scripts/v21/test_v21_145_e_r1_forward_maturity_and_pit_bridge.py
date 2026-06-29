import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.145_E_R1_FORWARD_MATURITY_AND_PIT_BRIDGE")
REQUIRED = [
    "V21.145_summary.json",
    "V21.145_e_r1_forward_maturity_audit.csv",
    "V21.145_e_r1_vs_a1_forward_comparison.csv",
    "V21.145_e_r1_vs_benchmark_forward_comparison.csv",
    "V21.145_e_r1_pit_reconstruction_feasibility.csv",
    "V21.145_e_r1_adoption_readiness_checklist.csv",
    "V21.145_prior_stage_bridge_summary.csv",
    "V21.145_remaining_blockers.csv",
    "V21.145_readable_report.txt",
]


def summary():
    with (OUT / "V21.145_summary.json").open("r", encoding="utf-8") as f:
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


def test_e_r1_and_a1_present():
    comp = pd.read_csv(OUT / "V21.145_e_r1_vs_a1_forward_comparison.csv")
    assert not comp.empty
    assert {"E_R1_return", "A1_return"}.issubset(comp.columns)
    assert set(comp["bucket"]) == {"top20", "top50"}


def test_forward_maturity_and_pit_audits_exist():
    maturity = pd.read_csv(OUT / "V21.145_e_r1_forward_maturity_audit.csv")
    pit = pd.read_csv(OUT / "V21.145_e_r1_pit_reconstruction_feasibility.csv")
    assert not maturity.empty
    assert {"bucket", "horizon", "matured_count", "pending_count"}.issubset(maturity.columns)
    assert not pit.empty
    assert {"input_requirement", "availability_classification", "evidence"}.issubset(pit.columns)


def test_checklist_has_status_and_evidence():
    checklist = pd.read_csv(OUT / "V21.145_e_r1_adoption_readiness_checklist.csv")
    assert not checklist.empty
    assert checklist["gate_name"].notna().all()
    assert checklist["status"].isin(["PASS", "FAIL", "WARN", "UNKNOWN"]).all()
    assert checklist["evidence_source"].notna().all()
    assert checklist["next_required_action"].notna().all()


def test_report_contains_final_status_and_decision():
    text = (OUT / "V21.145_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in text
    assert "DECISION=" in text
    s = summary()
    assert "FINAL_STATUS" in s
    assert "DECISION" in s
