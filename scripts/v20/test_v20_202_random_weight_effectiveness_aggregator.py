#!/usr/bin/env python
"""Tests for V20.202 random-weight effectiveness aggregation."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_202_random_weight_effectiveness_aggregator.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_202_random_weight_effectiveness_aggregator.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_202_RANDOM_WEIGHT_EFFECTIVENESS_AGGREGATOR_REPORT.md"

INPUTS = [
    OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_201_WEIGHT_EFFECTIVENESS_SUMMARY.csv",
    OUT_DIR / "V20_201_PIT_LEAKAGE_AUDIT.csv",
    OUT_DIR / "V20_201_SOURCE_COVERAGE_DIAGNOSTICS.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv",
    OUT_DIR / "V20_202_WEIGHT_FAMILY_CORRELATION_DIAGNOSTICS.csv",
    OUT_DIR / "V20_202_WEIGHT_BUCKET_EFFECTIVENESS.csv",
    OUT_DIR / "V20_202_TOP_BOTTOM_TRIAL_DIAGNOSTICS.csv",
    OUT_DIR / "V20_202_ETF_EXCESS_RETURN_DISTRIBUTION.csv",
    OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv",
    REPORT,
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_weight_files() -> list[Path]:
    roots = [ROOT / "outputs", ROOT / "configs", ROOT / "data"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(
                path for path in root.rglob("*.csv")
                if "weight" in path.name.lower() and not path.name.startswith("V20_202_")
            )
    return sorted(files)


def test_v20_202_random_weight_effectiveness_aggregator() -> None:
    before = {path: sha(path) for path in INPUTS if path.exists()}
    protected_before = {path: sha(path) for path in protected_weight_files()}
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=" in result.stdout
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "OFFICIAL_WEIGHT_MUTATED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "REAL_BOOK_SIGNAL_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout
    if "FINAL_STATUS=BLOCKED_" in result.stdout:
        assert before == {path: sha(path) for path in INPUTS if path.exists()}
        assert protected_before == {path: sha(path) for path in protected_weight_files()}
        for path in OUTPUTS:
            assert path.exists() and path.stat().st_size > 0, f"missing blocked output {path}"
        return

    for path in INPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing or empty input {path}"
        assert read_csv(path), f"input has no data rows {path}"
    after = {path: sha(path) for path in INPUTS if path.exists()}
    assert before == after
    protected_after = {path: sha(path) for path in protected_weight_files()}
    assert protected_before == protected_after

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"

    gate_rows = read_csv(OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"]
    assert gate["research_only"] == "TRUE"
    assert gate["official_weight_mutated"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["real_book_signal_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"

    trials = read_csv(OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv")
    expected_windows = {row["forward_window"] for row in trials if row["trial_status"] == "VALID"}
    window_rows = read_csv(OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv")
    assert {row["forward_window"] for row in window_rows} == expected_windows

    families = {row["family_name"] for row in read_csv(OUT_DIR / "V20_202_WEIGHT_FAMILY_CORRELATION_DIAGNOSTICS.csv")}
    assert {"fundamental", "technical", "strategy", "risk", "market_regime"} <= families

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_202*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)

    avg_excess = float(gate["avg_excess_vs_etf_rotation"] or 0.0)
    if avg_excess < 0:
        assert gate["shadow_weight_change_recommended"] == "FALSE"
        assert gate["research_only"] == "TRUE"

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "FINAL_STATUS=" in result.stdout
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "OFFICIAL_WEIGHT_MUTATED=FALSE" in result.stdout


if __name__ == "__main__":
    test_v20_202_random_weight_effectiveness_aggregator()
    test_wrapper_parseable()
    print("PASS test_v20_202_random_weight_effectiveness_aggregator")
