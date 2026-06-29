#!/usr/bin/env python
"""Contract test for V21.062 D daily maturity monitoring."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_062_include_d_daily_maturity_monitoring.py"
WRAPPER = ROOT / "scripts/v21/run_v21_062_include_d_daily_maturity_monitoring.ps1"
spec = importlib.util.spec_from_file_location("v21_062_d", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.LEDGER_NAME, module.SUMMARY_NAME,
    module.AUDIT_NAME, module.VALIDATION_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    source_text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]", source_text)
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", source_text)

    source_summary, source_ledger, source_contract = module.discover_r5(ROOT)
    protected = module.protected_paths(ROOT, source_summary.parent)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    explicit_expected = int(
        source_contract.get("d_forward_observation_row_count", 200)
    )
    source_warning_count = int(
        source_contract.get("d_price_missing_observation_count", 0)
    )
    run = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    out = ROOT / module.OUT_REL
    assert all((out / name).is_file() for name in REQUIRED)

    ledger = list(csv.DictReader(
        (out / module.LEDGER_NAME).open("r", encoding="utf-8")
    ))
    summary = next(csv.DictReader(
        (out / module.SUMMARY_NAME).open("r", encoding="utf-8")
    ))
    validation = json.loads(
        (out / module.VALIDATION_NAME).read_text(encoding="utf-8")
    )
    ids = [row["observation_id"] for row in ledger]
    assert ledger and all(row["source_variant"] == module.SOURCE_VARIANT for row in ledger)
    assert len(ledger) == explicit_expected
    assert source_ledger.is_file()
    assert len(ids) == len(set(ids))
    assert all(ids)
    assert int(summary["duplicate_observation_count"]) == 0
    total = int(summary["total_rows"])
    assert (
        int(summary["pending_count"])
        + int(summary["matured_count"])
        + int(summary["price_missing_count"])
        == total
    )
    assert int(summary["price_date_warning_count"]) == source_warning_count
    assert validation["price_date_warning_preserved"] is True
    assert validation["source_pending_matured_accounting_valid"] is True
    assert validation["local_price_missing_ranking_violation_count"] == 0
    assert validation["local_price_missing_observation_violation_count"] == 0
    assert validation["leveraged_inverse_risk_violation_count"] == 0
    assert validation["tqqq_ipo_watch_violation_count"] == 0
    assert validation["a0_replayed"] is False
    assert validation["a0_modified"] is False
    assert validation["existing_abcd_ledger_modified"] is False
    assert validation["protected_outputs_modified"] == []
    assert validation["official_use"] is False
    assert validation["official_ranking_mutation"] is False
    assert validation["official_recommendation_mutation"] is False
    assert validation["recommendation_allowed"] is False
    assert validation["broker_execution_supported"] is False
    assert summary["research_only"] == "True"
    assert summary["official_mutation"] == "False"
    assert summary["trade_action_created"] == "False"
    assert all(row["research_only"] == "TRUE" for row in ledger)
    assert before == {path: sha(ROOT / path) for path in before}

    matured = int(summary["matured_count"])
    if matured:
        assert summary["final_status"] == module.MATURED_STATUS
        assert summary["decision"] == module.MATURED_DECISION
    else:
        assert summary["final_status"] == module.PENDING_STATUS
        assert summary["decision"] == module.PENDING_DECISION
    assert {
        path.parent.resolve()
        for path in out.glob("V21_062_D_*")
        if path.is_file()
    } == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_062_include_d_daily_maturity_monitoring")
