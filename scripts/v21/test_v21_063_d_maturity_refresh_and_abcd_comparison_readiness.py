#!/usr/bin/env python
"""Contract test for V21.063 D refresh and ABCD comparison readiness."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / (
    "scripts/v21/v21_063_d_maturity_refresh_and_abcd_comparison_readiness.py"
)
WRAPPER = ROOT / (
    "scripts/v21/run_v21_063_d_maturity_refresh_and_abcd_comparison_readiness.ps1"
)
spec = importlib.util.spec_from_file_location("v21_063_d", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.LEDGER_NAME, module.SUMMARY_NAME, module.READINESS_NAME,
    module.AUDIT_NAME, module.VALIDATION_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    source_text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]", source_text)
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", source_text)

    v62_summary, _, _ = module.discover_v21_062_d(ROOT)
    abcd_path, _, _ = module.discover_abcd_maturity(ROOT)
    protected = module.protected_paths(ROOT, v62_summary.parent, abcd_path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(WRAPPER),
        ],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    out = ROOT / module.OUT_REL
    assert all((out / name).is_file() for name in REQUIRED)
    ledger = list(csv.DictReader(
        (out / module.LEDGER_NAME).open("r", encoding="utf-8")
    ))
    summary = next(csv.DictReader(
        (out / module.SUMMARY_NAME).open("r", encoding="utf-8")
    ))
    readiness = list(csv.DictReader(
        (out / module.READINESS_NAME).open("r", encoding="utf-8")
    ))
    validation = json.loads(
        (out / module.VALIDATION_NAME).read_text(encoding="utf-8")
    )

    ids = [row["observation_id"] for row in ledger]
    assert ids and len(ids) == len(set(ids))
    total = int(summary["total_rows"])
    pending = int(summary["refreshed_pending_count"])
    matured = int(summary["refreshed_matured_count"])
    missing = int(summary["refreshed_price_missing_count"])
    assert pending + matured + missing == total
    for row in ledger:
        has_return = bool(row["realized_forward_return"].strip())
        assert has_return == (row["refreshed_maturity_status"] == "MATURED")
        if row["refreshed_maturity_status"] != "MATURED":
            assert row["realized_forward_return"].strip() not in {"0", "0.0"}
        assert row["research_only"] == "TRUE"

    assert validation["source_observation_ids_preserved"] is True
    assert validation["missing_return_zero_fill_count"] == 0
    assert validation["price_date_warning_reconciled"] is True
    assert validation["v21_062_outputs_modified"] is False
    assert validation["a0_a1_b_c_d_source_files_modified"] is False
    assert validation["protected_outputs_modified"] == []
    assert summary["official_mutation"] == "False"
    assert summary["preferred_policy_selected"] == "False"
    assert summary["recommendation_allowed"] == "False"
    assert summary["trade_action_created"] == "False"
    assert summary["broker_execution_supported"] == "False"
    assert summary["research_only"] == "True"
    assert all(row["preferred_policy_selected"] == "False" for row in readiness)
    assert {row["comparator"] for row in readiness} == {"A1", "B", "C"}

    if matured == 0:
        assert summary["abcd_comparison_ready"] == "False"
        assert summary["abcd_comparison_ready_level"] == "NONE"
        assert summary["final_status"] == module.NO_MATURITY_STATUS
        assert summary["decision"] == module.NO_MATURITY_DECISION
    elif all(
        int(summary[f"matched_matured_rows_vs_{label}"]) > 0
        for label in ("A1", "B", "C")
    ):
        assert summary["abcd_comparison_ready_level"] == "READY"
        assert summary["final_status"] == module.READY_STATUS
        assert summary["decision"] == module.READY_DECISION
    else:
        assert summary["abcd_comparison_ready_level"] == "PARTIAL"
        assert summary["final_status"] == module.PARTIAL_STATUS
        assert summary["decision"] == module.PARTIAL_DECISION

    assert before == {path: sha(ROOT / path) for path in before}
    assert {
        path.parent.resolve()
        for path in out.glob("V21_063_*")
        if path.is_file()
    } == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_063_d_maturity_refresh_and_abcd_comparison_readiness")
