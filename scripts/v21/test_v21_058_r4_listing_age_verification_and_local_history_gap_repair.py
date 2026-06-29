#!/usr/bin/env python
"""Contract tests for V21.058-R4 listing-age verification."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_058_r4_listing_age_verification_and_local_history_gap_repair.py"
WRAPPER = ROOT / "scripts/v21/run_v21_058_r4_listing_age_verification_and_local_history_gap_repair.ps1"
spec = importlib.util.spec_from_file_location("v21_058_r4", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.VERIFICATION_NAME, module.RECLASS_NAME, module.TQQQ_NAME,
    module.DRAM_NAME, module.SPCX_NAME, module.LEDGER_NAME, module.BOARD_NAME,
    module.TOP50_NAME, module.LINEAGE_NAME, module.SUMMARY_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    assert (ROOT / module.REFERENCE_REL).is_file()
    protected = [path for path in (ROOT / module.A0_REL, ROOT / module.R1_SNAPSHOT_REL) if path.is_file()]
    for base in (ROOT / "outputs", ROOT / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            text = path.as_posix().lower()
            if ("official" in text and ("rank" in text or "weight" in text)) or "real_book" in text or "realbook" in text or "broker" in text:
                protected.append(path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True,
    )
    summary_path = ROOT / module.OUT_REL / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if str(summary["FINAL_STATUS"]).startswith("FAIL_"):
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    out = ROOT / module.OUT_REL
    assert all((out / name).is_file() for name in REQUIRED)
    rows = list(csv.DictReader((out / module.LEDGER_NAME).open("r", encoding="utf-8")))
    top = {row["ticker"] for row in csv.DictReader((out / module.TOP50_NAME).open("r", encoding="utf-8"))}
    by_ticker = {row["ticker"]: row for row in rows}
    tqqq = by_ticker["TQQQ"]
    assert tqqq["repaired_r4_policy_bucket"] == "LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED"
    assert tqqq["ipo_watch_removed"] == "TRUE"
    assert tqqq["r4_score_scope"] == "UNSCORED_COVERAGE_REPAIR_REQUIRED"
    assert "TQQQ" not in top
    assert by_ticker["SPCX"]["r4_score_status"] == "DATA_INSUFFICIENT"
    assert by_ticker["DRAM"]["r4_score_status"] == "DATA_INSUFFICIENT"
    assert summary["local_history_gap_misclassified_as_ipo_count"] == 0
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["forced_audit_only_scored_count"] == 0
    assert summary["forced_audit_only_top50_count"] == 0
    assert before == {path: sha(ROOT / path) for path in before}
    assert {path.parent.resolve() for path in out.glob("V21_058_R4*") if path.is_file()} == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_058_r4_listing_age_verification_and_local_history_gap_repair")
