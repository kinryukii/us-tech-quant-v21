from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pandas as pd

SOURCE = Path(__file__).with_name("a2_sec_fundamental_targeted_coverage_recovery_r1.py")
SPEC = importlib.util.spec_from_file_location("recovery", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_no_fit_network_or_outcome_projection() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "fit" not in called
    imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not ({"urllib", "requests", "httpx", "socket"} & imported)
    assert MODULE.SAFE_MEMBERSHIP_COLUMNS == ["signal_date", "ticker", "a2_rank"]


def test_frozen_contract_unchanged() -> None:
    prereg = json.loads((MODULE.SOURCE / "preregistration.json").read_text(encoding="utf-8"))
    assert MODULE.frozen_gates(prereg)[:3] == (0.60, 0.50, 0.75)
    assert MODULE.sha256_file(MODULE.SOURCE / "preregistration.json") == MODULE.PREREG_SHA
    assert MODULE.sha256_file(MODULE.SOURCE / "sec_concept_contract.json") == MODULE.CONCEPT_SHA


def test_checkpoint_guard_uses_status_fields_not_audit_counts() -> None:
    manifest = MODULE.verify_checkpoint()
    assert sum(key.endswith("_status") for key in manifest["lineage_facts"]) == 3


def test_greedy_is_deterministic_and_deficit_aware() -> None:
    missing = pd.DataFrame([("A", "2024-01-02"), ("A", "2024-01-03"), ("B", "2024-01-02"),
                            ("B", "2024-01-04"), ("C", "2024-01-03"), ("C", "2024-01-04")],
                           columns=["security_id", "signal_date"])
    deficits = {pd.Timestamp("2024-01-02"): 1, pd.Timestamp("2024-01-03"): 2, pd.Timestamp("2024-01-04"): 3}
    one = MODULE.greedy_priority(missing, deficits, {"A": 1, "B": 1, "C": 1})
    two = MODULE.greedy_priority(missing.sample(frac=1, random_state=7), deficits, {"A": 1, "B": 1, "C": 1})
    pd.testing.assert_frame_equal(one, two)
    assert one.security_id.iloc[0] == "A"


def test_incomplete_membership_fails_closed() -> None:
    assert MODULE.probe_membership(MODULE.MEMBERSHIP_CANDIDATES[0])["status"] == "INCOMPLETE"
    assert MODULE.probe_membership(MODULE.MEMBERSHIP_CANDIDATES[1])["status"] == "INCOMPLETE"


def test_overlay_interval_schema_and_failure_handoff() -> None:
    overlay = MODULE.empty_overlay()
    assert {"effective_start_date", "effective_end_date", "old_cik", "new_cik", "mapping_confidence"}.issubset(overlay.columns)
    assert overlay.empty
    text = SOURCE.read_text(encoding="utf-8")
    assert '"RESUME_CONTRACT_SHA256": "NOT_APPLICABLE"' in text
    assert '"NON_TARGETED_UNRESOLVED_CIK_REPAIR_COUNT": 0' in text
