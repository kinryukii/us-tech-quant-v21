import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN"
REQ = [
    "blocker_decomposition_summary.csv",
    "true_data_blockers.csv",
    "maturity_wait_blockers.csv",
    "capital_execution_blockers.csv",
    "non_blocking_data_warnings.csv",
    "stale_missing_ticker_impact.csv",
    "top20_top50_data_blocker_impact.csv",
    "switch_maturity_data_dependency.csv",
    "data_repair_action_plan.csv",
    "data_gate_reclassification.csv",
    "protected_output_mutation_audit.csv",
    "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_report.txt",
    "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_remain_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False


def test_decomposition_summary_has_rows():
    assert len(read("blocker_decomposition_summary.csv")) > 0


def test_true_data_blockers_exists_even_if_empty():
    df = read("true_data_blockers.csv")
    assert "impact_class" in df.columns


def test_maturity_wait_is_separate():
    df = read("maturity_wait_blockers.csv")
    assert len(df) > 0
    assert "MATURITY_WAIT_NOT_DATA_DEFECT" in set(df["decomposition_class"])


def test_capital_execution_is_separate():
    df = read("capital_execution_blockers.csv")
    assert len(df) > 0
    assert "CAPITAL_CONSTRAINT_NOT_DATA_DEFECT" in set(df["decomposition_class"])


def test_stale_missing_includes_known_names_if_present():
    df = read("stale_missing_ticker_impact.csv")
    expected = {"BITF", "PSTG", "SATS", "TQQQ"}
    assert expected.issubset(set(df["ticker"]))


def test_data_gate_reclassification_exists():
    df = read("data_gate_reclassification.csv")
    assert len(df) == 1
    assert "adjusted_data_gate_status" in df.columns


def test_protected_audit_clean():
    audit = read("protected_output_mutation_audit.csv")
    assert len(audit) == 1
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
    assert str(audit["audit_clean"].iloc[0]).lower() == "true"


def test_no_official_or_protected_outputs_modified():
    s = summary()
    assert s["protected_outputs_modified"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["official_adoption_allowed"] is False


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT
