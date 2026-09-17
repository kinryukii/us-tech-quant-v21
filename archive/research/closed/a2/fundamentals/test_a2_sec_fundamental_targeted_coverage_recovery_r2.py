from __future__ import annotations

import ast
import importlib.util
import math
from pathlib import Path

import pandas as pd


SOURCE = Path(__file__).with_name("a2_sec_fundamental_targeted_coverage_recovery_r2.py")
SPEC = importlib.util.spec_from_file_location("recovery_r2", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_static_no_fit_network_or_outcome_reader() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    imports = {node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "fit" not in calls
    assert not ({"urllib", "requests", "httpx", "socket"} & imports)
    text = SOURCE.read_text(encoding="utf-8")
    assert "outer_metrics.csv" not in text
    assert "portfolio_daily.parquet" not in text


def test_checkpoint_and_frozen_contract_constants() -> None:
    assert MODULE.CHECKPOINT_SHA256 == "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
    assert (MODULE.EXPECTED_DATES, MODULE.EXPECTED_ROWS, MODULE.BATCH_SIZE) == (1253, 50120, 25)
    assert math.ceil(MODULE.EXPECTED_DATES * 0.75) == 940


def test_date_deficit_is_exact() -> None:
    rows = []
    for date, covered in (("2024-01-02", 19), ("2024-01-03", 20)):
        for number in range(40):
            rows.append((date, f"S{number}", number < covered))
    panel = pd.DataFrame(rows, columns=["decision_date", "security_id", "covered_under_frozen_contract"])
    panel.decision_date = pd.to_datetime(panel.decision_date)
    old_dates = MODULE.EXPECTED_DATES
    try:
        MODULE.EXPECTED_DATES = 2
        daily = MODULE.date_coverage(panel)
    finally:
        MODULE.EXPECTED_DATES = old_dates
    assert daily.required_covered_count.tolist() == [20, 20]
    assert daily.deficit_count.tolist() == [1, 0]
    assert daily.passes_frozen_per_date_gate.tolist() == [False, True]


def test_greedy_is_deterministic_and_immediate_rescue_first() -> None:
    incidence = pd.DataFrame([
        ("A", "2024-01-02"), ("A", "2024-01-03"),
        ("B", "2024-01-03"), ("B", "2024-01-04"),
    ], columns=["security_id", "decision_date"])
    metadata = pd.DataFrame([
        ("A", "A", "Issuer A", 2, 2, "UNRESOLVED", "gap"),
        ("B", "B", "Issuer B", 2, 2, "UNRESOLVED", "gap"),
    ], columns=["security_id", "ticker", "issuer_name", "raw_top40_occurrence_count", "missing_date_count", "cik_status", "likely_mapping_filer_issue"])
    deficits = {pd.Timestamp("2024-01-02"): 1, pd.Timestamp("2024-01-03"): 2, pd.Timestamp("2024-01-04"): 2}
    one = MODULE.greedy_ranking(incidence, deficits, 4, 1, 3, metadata)
    two = MODULE.greedy_ranking(incidence.sample(frac=1, random_state=7), deficits, 4, 1, 3, metadata)
    pd.testing.assert_frame_equal(one, two)
    assert one.security_id.iloc[0] == "A"
    assert one.simulated_immediate_dates_rescued.iloc[0] == 1


def test_apply_recovery_is_targeted_only() -> None:
    panel = pd.DataFrame([
        (pd.Timestamp("2024-01-02"), "A", False),
        (pd.Timestamp("2024-01-02"), "B", False),
    ], columns=["decision_date", "security_id", "covered_under_frozen_contract"])
    panel["has_valid_sec_identity"] = False
    panel["has_valid_filing_state"] = False
    panel["has_required_feature_coverage"] = False
    panel["coverage_failure_reason"] = "missing"
    cells = pd.DataFrame([
        (pd.Timestamp("2024-01-02"), "A", 1, True),
        (pd.Timestamp("2024-01-02"), "B", 2, True),
    ], columns=["decision_date", "security_id", "new_cik", "new_covered"])
    recovered = MODULE.apply_recoveries(panel, cells, {"A"})
    assert recovered.set_index("security_id").covered_under_frozen_contract.to_dict() == {"A": True, "B": False}


def test_required_contract_markers_and_artifact_branching() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert '"SUPERSEDES_R1_FOR_EXECUTION_ONLY": True' in text
    assert '"R1_ECONOMIC_EVIDENCE_REUSED": False' in text
    assert '"resume_contract.json" if full_pass' in text
    assert '"remaining_coverage_blockers.csv"' in text
    assert 'stop_reason = "FROZEN_COVERAGE_GATE_FIRST_PASS"' in text
