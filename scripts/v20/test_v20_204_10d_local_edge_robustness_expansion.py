#!/usr/bin/env python
"""Tests for V20.204 10D local edge robustness expansion."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_204_10d_local_edge_robustness_expansion.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_204_10d_local_edge_robustness_expansion.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"
REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_204_10D_LOCAL_EDGE_ROBUSTNESS_EXPANSION_REPORT.md"

INPUTS = [
    OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv",
    OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv",
    OUT_DIR / "V20_203_LOCAL_EDGE_OBSERVATION_GATE.csv",
    OUT_DIR / "V20_203_OUTLIER_SENSITIVITY_CHECK.csv",
    PRICE_DIR / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_204_10D_EXPANDED_TRIALS.csv",
    OUT_DIR / "V20_204_10D_EXPANDED_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_204_10D_EXPANDED_ETF_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_204_10D_ROBUSTNESS_SUMMARY.csv",
    OUT_DIR / "V20_204_10D_BOOTSTRAP_CONFIDENCE.csv",
    OUT_DIR / "V20_204_10D_TRIMMED_WINSORIZED_ANALYSIS.csv",
    OUT_DIR / "V20_204_10D_LEAVE_ONE_CLUSTER_OUT.csv",
    OUT_DIR / "V20_204_10D_WEIGHT_BIAS_REPEATABILITY.csv",
    OUT_DIR / "V20_204_10D_ROBUSTNESS_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "PASS_V20_204_10D_LOCAL_EDGE_ROBUST_FOR_OBSERVATION",
    "PARTIAL_PASS_V20_204_10D_EDGE_MIXED_ROBUSTNESS",
    "PARTIAL_PASS_V20_204_INSUFFICIENT_EXPANDED_10D_SAMPLE",
    "PASS_V20_204_NO_EXPANDED_10D_EDGE_FOUND",
    "BLOCKED_V20_204_PIT_VALIDATION_FAILED",
    "BLOCKED_V20_204_REQUIRED_INPUT_MISSING",
}
REQUIRED_SCENARIOS = {
    "no_exclusion",
    "exclude_bottom_1pct",
    "exclude_bottom_5pct",
    "exclude_top_1pct",
    "exclude_top_5pct",
    "exclude_top_bottom_1pct",
    "exclude_top_bottom_5pct",
    "winsorize_1pct",
    "winsorize_5pct",
}


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
                if "weight" in path.name.lower() and not path.name.startswith("V20_204_")
            )
    return sorted(files)


def test_v20_204_10d_local_edge_robustness_expansion() -> None:
    input_before = {path: sha(path) for path in INPUTS if path.exists()}
    weight_before = {path: sha(path) for path in protected_weight_files()}
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=" in result.stdout
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "OFFICIAL_WEIGHT_MUTATED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "REAL_BOOK_SIGNAL_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout
    assert "SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE" in result.stdout
    if "FINAL_STATUS=BLOCKED_" in result.stdout:
        assert input_before == {path: sha(path) for path in INPUTS if path.exists()}
        assert weight_before == {path: sha(path) for path in protected_weight_files()}
        for path in OUTPUTS:
            assert path.exists() and path.stat().st_size > 0, f"missing blocked output {path}"
        return

    for path in INPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing or empty input {path}"
        assert read_csv(path), f"input has no rows {path}"
    assert input_before == {path: sha(path) for path in INPUTS if path.exists()}
    assert weight_before == {path: sha(path) for path in protected_weight_files()}

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"

    trials = read_csv(OUT_DIR / "V20_204_10D_EXPANDED_TRIALS.csv")
    valid_trials = [row for row in trials if row["trial_status"] == "VALID"]
    assert valid_trials
    assert all(row["forward_window"] == "10D" for row in valid_trials)
    for row in valid_trials:
        weight_sum = sum(float(row[f"{name}_weight"]) for name in ["fundamental", "technical", "strategy", "risk", "market_regime"])
        assert abs(weight_sum - 1.0) < 1e-8
        assert row["data_trust_weight"] == "0.0000000000"
        assert row["data_trust_used_in_ranking"] == "FALSE"
        assert row["data_trust_used_as_audit_gate"] == "TRUE"

    forward = read_csv(OUT_DIR / "V20_204_10D_EXPANDED_FORWARD_OUTCOMES.csv")
    valid_trial_ids = {row["trial_id"] for row in valid_trials}
    for row in forward:
        if row["trial_id"] in valid_trial_ids and row["outcome_status"] == "PASS":
            assert row["forward_window"] == "10D"
            assert row["as_of_date"] < row["exit_date"]

    gate_rows = read_csv(OUT_DIR / "V20_204_10D_ROBUSTNESS_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    assert gate["shadow_weight_change_recommended"] == "FALSE"

    boot_rows = read_csv(OUT_DIR / "V20_204_10D_BOOTSTRAP_CONFIDENCE.csv")
    assert len(boot_rows) == 1
    for column in [
        "mean_excess_ci_lower_95",
        "mean_excess_ci_upper_95",
        "median_excess_ci_lower_95",
        "median_excess_ci_upper_95",
    ]:
        assert column in boot_rows[0]

    scenarios = {row["scenario_name"] for row in read_csv(OUT_DIR / "V20_204_10D_TRIMMED_WINSORIZED_ANALYSIS.csv")}
    assert REQUIRED_SCENARIOS <= scenarios

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_204*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text
    assert "shadow weight change is not recommended in V20.204" in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "FINAL_STATUS=" in result.stdout
    assert "SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE" in result.stdout
    assert "RESEARCH_ONLY=TRUE" in result.stdout


if __name__ == "__main__":
    test_v20_204_10d_local_edge_robustness_expansion()
    test_wrapper_parseable()
    print("PASS test_v20_204_10d_local_edge_robustness_expansion")
