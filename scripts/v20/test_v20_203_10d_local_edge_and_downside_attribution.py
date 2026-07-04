#!/usr/bin/env python
"""Tests for V20.203 10D local edge and downside attribution."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_203_10d_local_edge_and_downside_attribution.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_203_10d_local_edge_and_downside_attribution.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_203_10D_LOCAL_EDGE_AND_DOWNSIDE_ATTRIBUTION_REPORT.md"

INPUTS = [
    OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv",
    OUT_DIR / "V20_202_WEIGHT_FAMILY_CORRELATION_DIAGNOSTICS.csv",
    OUT_DIR / "V20_202_WEIGHT_BUCKET_EFFECTIVENESS.csv",
    OUT_DIR / "V20_202_TOP_BOTTOM_TRIAL_DIAGNOSTICS.csv",
    OUT_DIR / "V20_202_ETF_EXCESS_RETURN_DISTRIBUTION.csv",
    OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_203_10D_LOCAL_EDGE_SUMMARY.csv",
    OUT_DIR / "V20_203_DOWNSIDE_TAIL_ATTRIBUTION.csv",
    OUT_DIR / "V20_203_ASOF_DATE_CLUSTER_ATTRIBUTION.csv",
    OUT_DIR / "V20_203_10D_WEIGHT_BIAS_DIAGNOSTICS.csv",
    OUT_DIR / "V20_203_OUTLIER_SENSITIVITY_CHECK.csv",
    OUT_DIR / "V20_203_LOCAL_EDGE_OBSERVATION_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "PASS_V20_203_10D_LOCAL_EDGE_OBSERVATION_CANDIDATE",
    "PARTIAL_PASS_V20_203_10D_EDGE_WEAK_OR_OUTLIER_SENSITIVE",
    "PASS_V20_203_NO_ROBUST_LOCAL_EDGE_FOUND",
    "BLOCKED_V20_203_REQUIRED_INPUT_MISSING",
}
REQUIRED_SCENARIOS = {
    "no_exclusion",
    "exclude_bottom_1pct",
    "exclude_bottom_5pct",
    "exclude_top_1pct",
    "exclude_top_5pct",
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
                if "weight" in path.name.lower() and not path.name.startswith("V20_203_")
            )
    return sorted(files)


def test_v20_203_10d_local_edge_and_downside_attribution() -> None:
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

    gate_rows = read_csv(OUT_DIR / "V20_203_LOCAL_EDGE_OBSERVATION_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    assert gate["shadow_weight_change_recommended"] == "FALSE"
    assert gate["research_only"] == "TRUE"
    assert gate["official_weight_mutated"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["real_book_signal_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"

    ten_d_rows = [row for row in read_csv(OUT_DIR / "V20_203_10D_LOCAL_EDGE_SUMMARY.csv") if row["forward_window"] == "10D"]
    if not ten_d_rows:
        assert "10D_LOCAL_EDGE_OBSERVATION_CANDIDATE" not in gate["final_status"]

    scenarios = {row["scenario_name"] for row in read_csv(OUT_DIR / "V20_203_OUTLIER_SENSITIVITY_CHECK.csv")}
    assert REQUIRED_SCENARIOS <= scenarios

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_203*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text
    assert "V20.203 is not authorized to recommend immediate shadow weight activation" in report_text


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
    test_v20_203_10d_local_edge_and_downside_attribution()
    test_wrapper_parseable()
    print("PASS test_v20_203_10d_local_edge_and_downside_attribution")
