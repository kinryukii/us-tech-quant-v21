#!/usr/bin/env python
"""Contract tests for V21.059-R1 ABCD experiment harness."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_059_r1_momentum_dynamic_abcd_versioned_experiment_harness.py"
WRAPPER = ROOT / "scripts/v21/run_v21_059_r1_momentum_dynamic_abcd_versioned_experiment_harness.ps1"
spec = importlib.util.spec_from_file_location("v21_059_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
REQUIRED = (
    module.CONFIG_NAME, module.A0_NAME, module.A1_NAME, module.B_NAME,
    module.C_NAME, module.COMPONENTS_NAME, module.TOP20_NAME, module.TOP50_NAME,
    module.FORCED_NAME, module.EXCLUSION_NAME, module.LINEAGE_NAME,
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
    existing_backtests = {path.as_posix() for path in (ROOT / module.OUT_REL).glob("*BACKTEST*")} if (ROOT / module.OUT_REL).exists() else set()
    completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True)
    summary_path = ROOT / module.OUT_REL / module.SUMMARY_NAME
    assert summary_path.is_file(), completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if str(summary["FINAL_STATUS"]).startswith("FAIL_"):
        assert completed.returncode != 0
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    out = ROOT / module.OUT_REL
    assert all((out / name).is_file() for name in REQUIRED)
    source_a0 = list(csv.DictReader((ROOT / module.A0_REL).open("r", encoding="utf-8")))
    view_a0 = list(csv.DictReader((out / module.A0_NAME).open("r", encoding="utf-8")))
    assert len(source_a0) == len(view_a0)
    assert [row["observation_id"] for row in source_a0] == [row["observation_id"] for row in view_a0]
    assert all(row["recomputed"] == "FALSE" for row in view_a0)
    configs = {row["variant_id"]: row for row in csv.DictReader((out / module.CONFIG_NAME).open("r", encoding="utf-8"))}
    assert configs["B_MOMENTUM_STATIC_R1"]["fixed_momentum_weight"] == "0.20"
    assert float(summary["c_dynamic_momentum_weight"]) == (0.15 if summary["market_regime"] == "UNKNOWN" else float(summary["c_dynamic_momentum_weight"]))
    for name in (module.B_NAME, module.C_NAME):
        rows = list(csv.DictReader((out / name).open("r", encoding="utf-8")))
        scores = [float(row["final_shadow_score"]) for row in rows]
        assert scores == sorted(scores, reverse=True)
        assert all(row["eligible_for_variant_ranking"] == "TRUE" for row in rows)
    forced = list(csv.DictReader((out / module.FORCED_NAME).open("r", encoding="utf-8")))
    assert set(module.FORCED) == {row["ticker"] for row in forced}
    for ticker in ("DRAM", "SPCX"):
        row = next(item for item in forced if item["ticker"] == ticker)
        assert row["present_in_b"] == row["present_in_c"] == "FALSE"
    assert summary["hardcoded_inclusion_violation_count"] == 0
    assert summary["local_price_missing_ranked_violation_count"] == 0
    assert summary["tqqq_ipo_watch_violation_count"] == 0
    assert summary["leveraged_full_size_violation_count"] == 0
    assert summary["inverse_non_hedge_violation_count"] == 0
    assert before == {path: sha(ROOT / path) for path in before}
    assert {path.as_posix() for path in out.glob("*BACKTEST*")} == existing_backtests
    assert not list(out.glob("*OBSERVATION*LEDGER*"))
    assert {path.parent.resolve() for path in out.glob("V21_059_R1*") if path.is_file()} == {out.resolve()}


if __name__ == "__main__":
    test_repository_wrapper()
    print("PASS test_v21_059_r1_momentum_dynamic_abcd_versioned_experiment_harness")
