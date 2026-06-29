#!/usr/bin/env python
"""Contract tests for V21.061-R1 maturity comparison."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_061_r1_abcd_maturity_comparison_report.py"
WRAPPER = ROOT / "scripts/v21/run_v21_061_r1_abcd_maturity_comparison_report.ps1"
spec = importlib.util.spec_from_file_location("v21_061_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.MATURED_NAME, module.WINDOW_NAME, module.PAIR_NAME,
    module.BACKTEST_NAME, module.CAPTURE_NAME, module.FORCED_NAME,
    module.RECOMMENDATION_NAME, module.LINEAGE_NAME, module.SUMMARY_NAME,
)
ALLOWED_RECOMMENDATIONS = {
    "KEEP_BASELINE", "CONTINUE_OBSERVATION", "MOMENTUM_STATIC_PROMISING",
    "MOMENTUM_DYNAMIC_PROMISING", "MOMENTUM_VARIANT_REJECTED",
    "NEED_MORE_MATURITY", "DATA_COVERAGE_REPAIR_NEEDED",
}
ALLOWED_STATUSES = {
    module.PASS_STATUS, module.PARTIAL_STATUS, module.FAIL_A0,
    module.FAIL_SOURCE, module.FAIL_HARDCODED, module.FAIL_PRICE,
    module.FAIL_PROMOTION, module.FAIL_MUTATION,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    protected = [
        path for path in (
            ROOT / module.LEDGER_REL, ROOT / module.A0_CANONICAL_REL,
            ROOT / module.R1_SNAPSHOT_REL,
        ) if path.is_file()
    ]
    for base in (ROOT / "outputs", ROOT / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            text = path.as_posix().lower()
            if (
                ("official" in text and ("rank" in text or "weight" in text))
                or "real_book" in text or "realbook" in text or "broker" in text
            ):
                protected.append(path)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True,
    )
    out = ROOT / module.OUT_REL
    summary_path = out / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] in ALLOWED_STATUSES
    if summary["FINAL_STATUS"].startswith("FAIL_"):
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert all((out / name).is_file() for name in REQUIRED)

    source = list(csv.DictReader((ROOT / module.LEDGER_REL).open("r", encoding="utf-8")))
    matured = list(csv.DictReader((out / module.MATURED_NAME).open("r", encoding="utf-8")))
    assert len(source) == len(matured)
    assert [row["observation_id"] for row in source] == [row["observation_id"] for row in matured]
    a0_source = [row["observation_id"] for row in source if row["variant_id"] == "A0_CURRENT_TESTING_LOCKED"]
    a0_result = [row["observation_id"] for row in matured if row["variant_id"] == "A0_CURRENT_TESTING_LOCKED"]
    assert a0_source == a0_result
    assert all(row["research_only"] == "TRUE" for row in matured)

    recommendation = list(csv.DictReader((out / module.RECOMMENDATION_NAME).open("r", encoding="utf-8")))
    assert len(recommendation) == 1
    assert recommendation[0]["recommendation_status"] in ALLOWED_RECOMMENDATIONS
    assert recommendation[0]["production_adoption_allowed"] == "FALSE"
    assert recommendation[0]["official_use_allowed"] == "FALSE"
    if summary["matured_observation_count"] == 0:
        assert recommendation[0]["recommendation_status"] == "NEED_MORE_MATURITY"

    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert set(module.FORCED) == {row["ticker"] for row in forced}
    for ticker in ("DRAM", "SPCX"):
        row = next(item for item in forced if item["ticker"] == ticker)
        if row["local_price_missing_flag"] == "TRUE":
            assert sum(int(row[f"matured_count_{short}"]) for short in ("A0", "A1", "B", "C")) == 0
    assert summary["production_adoption_allowed"] is False
    assert summary["official_use_allowed"] is False
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["local_price_missing_ranked_violation_count"] == 0
    assert summary["tqqq_ipo_watch_violation_count"] == 0
    assert summary["a0_recomputed"] is False
    assert summary["a0_modified"] is False
    assert before == {path: sha(ROOT / path) for path in before}
    assert all(row["research_only"] == "TRUE" for row in forced + recommendation)
    assert {path.parent.resolve() for path in out.glob("V21_061_R1*") if path.is_file()} == {out.resolve()}
    assert not list(out.glob("V21_061_R1*OFFICIAL_RECOMMENDATION*"))
    assert not list(out.glob("V21_061_R1*BROKER_ACTION*"))


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_061_r1_abcd_maturity_comparison_report")
