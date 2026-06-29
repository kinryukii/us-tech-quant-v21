#!/usr/bin/env python
"""Contract tests for V21.067-R1 factor explainability ledger."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_067_r1_factor_explainability_ledger.py"
WRAPPER = ROOT / "scripts/v21/run_v21_067_r1_factor_explainability_ledger.ps1"
SPEC = importlib.util.spec_from_file_location("v21_067", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_run() -> None:
    source_path, source = MODULE.discover_ranking(ROOT)
    protected = MODULE.protected_paths(ROOT, source_path, ROOT / MODULE.OUT_REL)
    before = {path: digest(path) for path in protected}
    completed = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(WRAPPER),
        ],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = ROOT / MODULE.OUT_REL
    ledger_path = output / MODULE.LEDGER_NAME
    summary_path = output / MODULE.SUMMARY_NAME
    validation_path = output / MODULE.VALIDATION_NAME
    assert ledger_path.is_file()
    assert summary_path.is_file()
    assert validation_path.is_file()
    ledger = pd.read_csv(ledger_path, low_memory=False)
    summary = pd.read_csv(summary_path)
    validation = pd.read_csv(validation_path).iloc[0]
    assert set(MODULE.LEDGER_COLUMNS).issubset(ledger.columns)
    assert set(MODULE.SUMMARY_COLUMNS).issubset(summary.columns)
    assert set(summary["bucket"]) == {"TOP20", "TOP50", "ALL_ELIGIBLE"}
    assert str(validation["research_only"]).upper() == "TRUE"
    assert str(validation["official_mutation"]).upper() == "FALSE"
    assert str(validation["protected_outputs_modified"]).upper() == "FALSE"
    assert len(ledger) == len(source)
    ranked = ledger[ledger["eligible_flag"].astype(str).str.upper() == "TRUE"]
    assert ranked["final_score"].notna().all()
    assert ranked["rank"].notna().all()
    assert int(validation["ledger_rows"]) == int(validation["ranking_rows"])
    assert int(validation["missing_final_score_count"]) == 0
    assert int(validation["missing_rank_count"]) == 0
    assert str(validation["pass_gate"]).upper() == "TRUE"
    assert str(validation["final_status"]).startswith(("PASS_", "PARTIAL_PASS_"))
    assert before == {path: digest(path) for path in protected}


def test_missing_input_is_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        output = root / "outputs/v21/explainability"
        result = MODULE.run_stage(root, output_override=output)
        assert result["final_status"] == (
            "BLOCKED_V21_067_R1_NO_VALID_D_RANKING_INPUT"
        )
        assert result["pass_gate"] is False
        assert (output / MODULE.VALIDATION_NAME).is_file()
        assert (output / MODULE.LEDGER_NAME).is_file()
        assert (output / MODULE.SUMMARY_NAME).is_file()


if __name__ == "__main__":
    test_repository_run()
    test_missing_input_is_blocked()
    print("PASS test_v21_067_r1_factor_explainability_ledger")
