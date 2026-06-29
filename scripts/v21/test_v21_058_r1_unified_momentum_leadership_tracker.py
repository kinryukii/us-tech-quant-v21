#!/usr/bin/env python
"""Contract tests for V21.058-R1 unified momentum tracker."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_058_r1_unified_momentum_leadership_tracker.py"
WRAPPER = ROOT / "scripts/v21/run_v21_058_r1_unified_momentum_leadership_tracker.ps1"
spec = importlib.util.spec_from_file_location("v21_058_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (module.LEDGER_NAME, module.TOP50_NAME, module.LEADERSHIP_NAME, module.CHASE_NAME, module.EXHAUSTION_NAME, module.FORCED_NAME, module.DATA_WARN_NAME, module.FLOW_NAME, module.LINEAGE_NAME, module.SUMMARY_NAME)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_contract(root: Path, summary: dict[str, object], before: dict[str, str]) -> None:
    out = root / module.OUT_REL
    assert all((out / name).is_file() for name in REQUIRED)
    rows = list(csv.DictReader((out / module.LEDGER_NAME).open("r", encoding="utf-8")))
    top = {row["ticker"] for row in csv.DictReader((out / module.TOP50_NAME).open("r", encoding="utf-8"))}
    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert set(module.FORCED) == {row["ticker"] for row in forced}
    assert all(row["research_only"] == "TRUE" for row in rows)
    for row in rows:
        if row["score_computed"] == "TRUE":
            for field in ("absolute_momentum_score", "relative_momentum_score", "momentum_acceleration_score", "trend_persistence_score", "exhaustion_risk_score", "momentum_leadership_score", "momentum_state", "chase_permission", "risk_size_bucket"):
                assert row[field]
        if row["entered_by_forced_audit_only"] == "TRUE":
            assert row["eligible_for_unified_pool"] == row["score_computed"] == "FALSE"
            assert row["ticker"] not in top
        if row["momentum_state"] == "MOMENTUM_EXHAUSTION":
            assert row["deterioration_confirmation_flag"] == "TRUE"
        if row["instrument_type"] == "LEVERAGED_LONG_ETF":
            assert row["risk_size_bucket"] != "FULL_SIZE_ALLOWED"
        if row["instrument_type"] == "INVERSE_ETF" and row["risk_off_confirmed"] != "TRUE":
            assert row["chase_permission"] == "HEDGE_ONLY"
            assert row["risk_size_bucket"] in {"WATCH_ONLY", "BLOCKED"}
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["forced_audit_only_scored_count"] == 0
    assert summary["forced_audit_only_top50_count"] == 0
    assert summary["high_momentum_auto_exhaustion_violation_count"] == 0
    assert summary["leveraged_full_size_violation_count"] == 0
    assert summary["inverse_non_hedge_violation_count"] == 0
    assert before == {path: sha(root / path) for path in before}
    assert {path.parent.resolve() for path in out.glob("V21_058_R1*") if path.is_file()} == {out.resolve()}


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
    completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True)
    summary_path = ROOT / module.OUT_REL / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if str(summary["FINAL_STATUS"]).startswith(("FAIL_", "BLOCKED_")):
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert_contract(ROOT, summary, before)


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_058_r1_unified_momentum_leadership_tracker")
