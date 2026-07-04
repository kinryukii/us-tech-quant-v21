#!/usr/bin/env python
"""Tests for V20.205 selected ETF cluster dependency attribution."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_205_10d_selected_etf_cluster_dependency_attribution.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_205_10d_selected_etf_cluster_dependency_attribution.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_205_10D_SELECTED_ETF_CLUSTER_DEPENDENCY_ATTRIBUTION_REPORT.md"

INPUTS = [
    OUT_DIR / "V20_204_10D_EXPANDED_TRIALS.csv",
    OUT_DIR / "V20_204_10D_EXPANDED_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_204_10D_EXPANDED_ETF_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_204_10D_ROBUSTNESS_SUMMARY.csv",
    OUT_DIR / "V20_204_10D_BOOTSTRAP_CONFIDENCE.csv",
    OUT_DIR / "V20_204_10D_TRIMMED_WINSORIZED_ANALYSIS.csv",
    OUT_DIR / "V20_204_10D_LEAVE_ONE_CLUSTER_OUT.csv",
    OUT_DIR / "V20_204_10D_WEIGHT_BIAS_REPEATABILITY.csv",
    OUT_DIR / "V20_204_10D_ROBUSTNESS_GATE.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_205_SELECTED_ETF_CLUSTER_EFFECTIVENESS.csv",
    OUT_DIR / "V20_205_SELECTED_ETF_LEAVE_ONE_OUT_DIAGNOSTICS.csv",
    OUT_DIR / "V20_205_SELECTED_ETF_CONTRIBUTION_DECOMPOSITION.csv",
    OUT_DIR / "V20_205_CLUSTER_WEIGHT_BIAS_DIAGNOSTICS.csv",
    OUT_DIR / "V20_205_CLUSTER_DEPENDENCY_RISK_AUDIT.csv",
    OUT_DIR / "V20_205_10D_OBSERVATION_CONTINUATION_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "PASS_V20_205_10D_EDGE_CLUSTER_DISTRIBUTION_ACCEPTABLE_FOR_OBSERVATION",
    "PARTIAL_PASS_V20_205_10D_EDGE_CLUSTER_DEPENDENCY_MODERATE",
    "PARTIAL_PASS_V20_205_10D_EDGE_CLUSTER_DEPENDENCY_HIGH",
    "PARTIAL_PASS_V20_205_INSUFFICIENT_CLUSTER_EVIDENCE",
    "BLOCKED_V20_205_REQUIRED_INPUT_MISSING",
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
                if "weight" in path.name.lower() and not path.name.startswith("V20_205_")
            )
    return sorted(files)


def test_v20_205_selected_etf_cluster_dependency_attribution() -> None:
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

    gate_rows = read_csv(OUT_DIR / "V20_205_10D_OBSERVATION_CONTINUATION_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    assert gate["shadow_weight_change_recommended"] == "FALSE"

    expected_etfs = {
        row["selected_etf"]
        for row in read_csv(OUT_DIR / "V20_204_10D_EXPANDED_ETF_BENCHMARK_OUTCOMES.csv")
        if row["benchmark_status"] == "PASS" and row["selected_etf"]
    }
    observed_etfs = {row["selected_etf"] for row in read_csv(OUT_DIR / "V20_205_SELECTED_ETF_CLUSTER_EFFECTIVENESS.csv")}
    assert expected_etfs <= observed_etfs

    if expected_etfs:
        assert read_csv(OUT_DIR / "V20_205_SELECTED_ETF_LEAVE_ONE_OUT_DIAGNOSTICS.csv")

    risk_rows = read_csv(OUT_DIR / "V20_205_CLUSTER_DEPENDENCY_RISK_AUDIT.csv")
    assert any(row["metric_name"] == "cluster_dependency_risk_level" for row in risk_rows)

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_205*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text
    assert "shadow weight change is not recommended in V20.205" in report_text


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
    test_v20_205_selected_etf_cluster_dependency_attribution()
    test_wrapper_parseable()
    print("PASS test_v20_205_10d_selected_etf_cluster_dependency_attribution")
