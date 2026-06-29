#!/usr/bin/env python
"""Contract tests for V21.060-R2 multi-seed random backtest."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py"
WRAPPER = ROOT / "scripts/v21/run_v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.ps1"
spec = importlib.util.spec_from_file_location("v21_060_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.RESULTS_NAME, module.SEED_NAME, module.OVERALL_NAME, module.PAIR_NAME,
    module.SELECTION_NAME, module.FORCED_NAME, module.LINEAGE_NAME, module.SUMMARY_NAME,
)
ALLOWED = {
    module.PASS_STATUS, module.PARTIAL_STATUS, module.FAIL_A0, module.FAIL_HARDCODED,
    module.FAIL_PRICE, module.FAIL_TQQQ, module.FAIL_MUTATION,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_wrapper() -> None:
    protected = module.protected_files(ROOT)
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected}
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True,
    )
    out = ROOT / module.OUT_REL
    summary_path = out / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["FINAL_STATUS"] in ALLOWED
    assert completed.returncode == (1 if summary["FINAL_STATUS"].startswith("FAIL_") else 0), completed.stdout + completed.stderr
    assert all((out / name).is_file() for name in REQUIRED)
    variants = set()
    result_count = 0
    with (out / module.RESULTS_NAME).open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            result_count += 1
            variants.add(row["variant_id"])
            assert row["variant_id"] != "A0_CURRENT_TESTING_LOCKED"
            assert row["research_only"] == "TRUE" and row["point_in_time_valid"] == "TRUE"
            assert row["price_data_status"] == "PASS" and row["realized_forward_return"]
    assert result_count > 0
    assert variants == set(module.VARIANTS)
    assert (out / module.PAIR_NAME).stat().st_size > 0
    assert (out / module.SELECTION_NAME).stat().st_size > 0
    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert set(module.FORCED) == {row["ticker"] for row in forced}
    for ticker in ("DRAM", "SPCX"):
        row = next(item for item in forced if item["ticker"] == ticker)
        if row["local_price_missing_flag"] == "TRUE":
            assert row["included_in_any_seed"] == "FALSE"
    tqqq = next(row for row in forced if row["ticker"] == "TQQQ")
    assert tqqq["tqqq_ipo_watch_violation_flag"] == "FALSE"
    assert summary["a0_replayed"] is False
    assert summary["a0_modified"] is False
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["local_price_missing_included_violation_count"] == 0
    assert summary["tqqq_ipo_watch_violation_count"] == 0
    assert summary["production_adoption_allowed"] is False
    assert summary["official_use_allowed"] is False
    assert before == {path: sha(ROOT / path) for path in before}
    assert {path.parent.resolve() for path in out.glob("V21_060_R2*") if path.is_file()} == {out.resolve()}
    assert not list(out.glob("*OFFICIAL_RECOMMENDATION*"))
    assert not list(out.glob("*BROKER_ACTION*"))


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest")
