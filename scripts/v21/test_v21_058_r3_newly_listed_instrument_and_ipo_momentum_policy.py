#!/usr/bin/env python
"""Contract tests for V21.058-R3 newly listed momentum policy."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_058_r3_newly_listed_instrument_and_ipo_momentum_policy.py"
WRAPPER = ROOT / "scripts/v21/run_v21_058_r3_newly_listed_instrument_and_ipo_momentum_policy.ps1"
spec = importlib.util.spec_from_file_location("v21_058_r3", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.POLICY_NAME, module.SPACEX_NAME, module.LEDGER_NAME,
    module.BOARD_NAME, module.TOP50_NAME, module.FORCED_NAME,
    module.LINEAGE_NAME, module.SUMMARY_NAME,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
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
    assert all(row["newly_listed_policy_bucket"] for row in rows)
    for row in rows:
        if row["newly_listed_policy_bucket"] != "FULL_HISTORY_SCORING":
            assert row["full_history_score_available"] == "FALSE"
        if row["newly_listed_policy_bucket"] == "IPO_EARLY_MOMENTUM_WATCH":
            assert row["risk_size_bucket"] != "FULL_SIZE_ALLOWED"
            assert row["ticker"] not in top
    spcx = by_ticker["SPCX"]
    if spcx["price_available"] != "TRUE":
        assert spcx["r3_score_status"] == "DATA_INSUFFICIENT"
        assert "SPCX" not in top
    dram = by_ticker["DRAM"]
    if dram["price_available"] != "TRUE":
        assert dram["r3_score_status"] == "DATA_INSUFFICIENT"
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["forced_audit_only_scored_count"] == 0
    assert summary["forced_audit_only_top50_count"] == 0
    assert before == {path: sha(ROOT / path) for path in before}
    assert {path.parent.resolve() for path in out.glob("V21_058_R3*") if path.is_file()} == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_058_r3_newly_listed_instrument_and_ipo_momentum_policy")
