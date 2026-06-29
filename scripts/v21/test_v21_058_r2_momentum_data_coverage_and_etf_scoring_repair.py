#!/usr/bin/env python
"""Contract tests for V21.058-R2 ETF data coverage repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_058_r2_momentum_data_coverage_and_etf_scoring_repair.py"
WRAPPER = ROOT / "scripts/v21/run_v21_058_r2_momentum_data_coverage_and_etf_scoring_repair.ps1"
spec = importlib.util.spec_from_file_location("v21_058_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.COVERAGE_NAME, module.MAPPING_NAME, module.BENCHMARK_NAME,
    module.REGIME_NAME, module.LEDGER_NAME, module.TOP50_NAME,
    module.FORCED_NAME, module.WARN_NAME, module.LINEAGE_NAME,
    module.SUMMARY_NAME,
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
    r1_rows = list(csv.DictReader((ROOT / module.R1_LEDGER_REL).open("r", encoding="utf-8")))
    repaired = list(csv.DictReader((out / module.LEDGER_NAME).open("r", encoding="utf-8")))
    top = list(csv.DictReader((out / module.TOP50_NAME).open("r", encoding="utf-8")))
    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert len(repaired) >= len(r1_rows)
    assert all(row["score_computed"] == "TRUE" for row in top)
    scores = [float(row["momentum_leadership_score"]) for row in top]
    assert scores == sorted(scores, reverse=True)
    assert all(row["research_only"] == "TRUE" for row in repaired)
    assert all(row["hardcoded_inclusion_violation_flag"] == "FALSE" for row in forced)
    for row in repaired:
        if row["instrument_type"] == "LEVERAGED_LONG_ETF":
            assert row["risk_size_bucket"] != "FULL_SIZE_ALLOWED"
        if row["instrument_type"] == "INVERSE_ETF" and row["risk_off_confirmed"] != "TRUE":
            assert row["chase_permission"] == "HEDGE_ONLY"
            assert row["risk_size_bucket"] in {"WATCH_ONLY", "BLOCKED"}
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["high_momentum_auto_exhaustion_violation_count"] == 0
    assert summary["leveraged_full_size_violation_count"] == 0
    assert summary["inverse_non_hedge_violation_count"] == 0
    assert before == {path: sha(ROOT / path) for path in before}
    assert {path.parent.resolve() for path in out.glob("V21_058_R2*") if path.is_file()} == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_058_r2_momentum_data_coverage_and_etf_scoring_repair")
