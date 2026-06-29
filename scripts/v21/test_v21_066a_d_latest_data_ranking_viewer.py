#!/usr/bin/env python
"""Contract test for V21.066A D latest-data ranking viewer."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_066a_d_latest_data_ranking_viewer.py"
WRAPPER = ROOT / "scripts/v21/run_v21_066a_d_latest_data_ranking_viewer.ps1"
spec = importlib.util.spec_from_file_location("v21_066a", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.TOP20_NAME, module.TOP50_NAME, module.FULL_NAME,
    module.SUMMARY_NAME, module.AUDIT_NAME, module.VALIDATION_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]", source)
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", source)
    source_summary, _, _ = module.discover_d_source(ROOT)
    protected = module.protected_paths(ROOT, source_summary.parent)
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
    full = list(csv.DictReader((out / module.FULL_NAME).open("r", encoding="utf-8")))
    top20 = list(csv.DictReader((out / module.TOP20_NAME).open("r", encoding="utf-8")))
    top50 = list(csv.DictReader((out / module.TOP50_NAME).open("r", encoding="utf-8")))
    summary = next(csv.DictReader(
        (out / module.SUMMARY_NAME).open("r", encoding="utf-8")
    ))
    validation = json.loads(
        (out / module.VALIDATION_NAME).read_text(encoding="utf-8")
    )
    eligible = [row for row in full if row["eligible_flag"] == "True"]
    assert len(top20) == min(20, len(eligible))
    assert len(top50) == min(50, len(eligible))
    ranks = [row["rank"] for row in eligible]
    assert len(ranks) == len(set(ranks))
    assert all(row["ticker"] for row in full)
    assert all(row["source_variant"] == module.SOURCE_VARIANT for row in full)
    assert all(abs(float(row["base_weight"]) - 0.60) < 1e-12 for row in full)
    assert all(abs(float(row["momentum_weight"]) - 0.40) < 1e-12 for row in full)
    assert all(row["research_only"] == "True" for row in full)
    assert summary["research_only"] == "True"
    assert summary["recommendation_allowed"] == "False"
    assert summary["official_mutation"] == "False"
    assert summary["trade_action_created"] == "False"
    assert summary["protected_outputs_modified"] == "False"
    assert validation["official_ranking_mutation"] is False
    assert validation["official_recommendation_mutation"] is False
    assert validation["broker_output_mutation"] is False
    assert validation["trade_action_created"] is False
    assert validation["abcd_ledger_mutation"] is False
    assert validation["protected_outputs_modified"] == []
    if summary["recomputed_latest_data"] == "True":
        assert summary["final_status"] == module.RECOMPUTED_STATUS
        assert summary["decision"] == module.RECOMPUTED_DECISION
    else:
        assert summary["final_status"] == module.PERSISTED_STATUS
        assert summary["decision"] == module.PERSISTED_DECISION
    assert before == {path: sha(ROOT / path) for path in before}
    assert {
        path.parent.resolve()
        for path in out.glob("V21_066A_*") if path.is_file()
    } == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_066a_d_latest_data_ranking_viewer")
