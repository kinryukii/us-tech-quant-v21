#!/usr/bin/env python
"""Tests for V20.206 10D SPY conditional overlay validation."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_206_10d_spy_conditional_overlay_validation.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_206_10d_spy_conditional_overlay_validation.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_206_10D_SPY_CONDITIONAL_OVERLAY_VALIDATION_REPORT.md"

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
    OUT_DIR / "V20_205_SELECTED_ETF_CLUSTER_EFFECTIVENESS.csv",
    OUT_DIR / "V20_205_SELECTED_ETF_LEAVE_ONE_OUT_DIAGNOSTICS.csv",
    OUT_DIR / "V20_205_SELECTED_ETF_CONTRIBUTION_DECOMPOSITION.csv",
    OUT_DIR / "V20_205_CLUSTER_WEIGHT_BIAS_DIAGNOSTICS.csv",
    OUT_DIR / "V20_205_CLUSTER_DEPENDENCY_RISK_AUDIT.csv",
    OUT_DIR / "V20_205_10D_OBSERVATION_CONTINUATION_GATE.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_206_SPY_CONDITIONAL_EFFECTIVENESS.csv",
    OUT_DIR / "V20_206_SPY_VS_NON_SPY_COMPARISON.csv",
    OUT_DIR / "V20_206_SPY_CONDITIONAL_BOOTSTRAP.csv",
    OUT_DIR / "V20_206_SPY_CONDITIONAL_TRIMMED_WINSORIZED.csv",
    OUT_DIR / "V20_206_SPY_ASOF_DATE_STABILITY.csv",
    OUT_DIR / "V20_206_SPY_WEIGHT_BIAS_REPEATABILITY.csv",
    OUT_DIR / "V20_206_CONDITIONAL_OVERLAY_RULE_CANDIDATE.csv",
    OUT_DIR / "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "PASS_V20_206_SPY_CONDITIONAL_OVERLAY_OBSERVATION_CANDIDATE",
    "PARTIAL_PASS_V20_206_SPY_CONDITIONAL_EDGE_MIXED_ROBUSTNESS",
    "PASS_V20_206_NO_SPY_CONDITIONAL_EDGE_FOUND",
    "PARTIAL_PASS_V20_206_INSUFFICIENT_SPY_CONDITION_SAMPLE",
    "BLOCKED_V20_206_REQUIRED_INPUT_MISSING",
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
                if "weight" in path.name.lower() and not path.name.startswith("V20_206_")
            )
    return sorted(files)


def test_v20_206_10d_spy_conditional_overlay_validation() -> None:
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
        gate_rows = read_csv(OUT_DIR / "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv")
        assert len(gate_rows) == 1
        assert gate_rows[0]["shadow_weight_change_recommended"] == "FALSE"
        return

    for path in INPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing or empty input {path}"
        assert read_csv(path), f"input has no rows {path}"
    assert input_before == {path: sha(path) for path in INPUTS if path.exists()}
    assert weight_before == {path: sha(path) for path in protected_weight_files()}

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"

    effectiveness = read_csv(OUT_DIR / "V20_206_SPY_CONDITIONAL_EFFECTIVENESS.csv")
    assert {"selected_etf_eq_SPY", "selected_etf_not_SPY", "all_10D_trials"} <= {row["condition_name"] for row in effectiveness}

    rule_rows = read_csv(OUT_DIR / "V20_206_CONDITIONAL_OVERLAY_RULE_CANDIDATE.csv")
    assert len(rule_rows) == 1
    assert rule_rows[0]["condition_expression"] == "selected_etf == SPY"

    gate_rows = read_csv(OUT_DIR / "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    assert gate["shadow_weight_change_recommended"] == "FALSE"

    spy_effect = next(row for row in effectiveness if row["condition_name"] == "selected_etf_eq_SPY")
    if int(spy_effect["trial_count"]) < 30:
        assert gate["final_status"] != "PASS_V20_206_SPY_CONDITIONAL_OVERLAY_OBSERVATION_CANDIDATE"

    boot_rows = read_csv(OUT_DIR / "V20_206_SPY_CONDITIONAL_BOOTSTRAP.csv")
    assert {"selected_etf_eq_SPY", "selected_etf_not_SPY"} <= {row["condition_name"] for row in boot_rows}
    for column in [
        "mean_excess_ci_lower_95",
        "mean_excess_ci_upper_95",
        "median_excess_ci_lower_95",
        "median_excess_ci_upper_95",
    ]:
        assert column in boot_rows[0]

    trim_rows = read_csv(OUT_DIR / "V20_206_SPY_CONDITIONAL_TRIMMED_WINSORIZED.csv")
    spy_scenarios = {row["scenario_name"] for row in trim_rows if row["condition_name"] == "selected_etf_eq_SPY"}
    assert REQUIRED_SCENARIOS <= spy_scenarios

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_206*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text
    assert "shadow weight change is not recommended in V20.206" in report_text


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
    test_v20_206_10d_spy_conditional_overlay_validation()
    test_wrapper_parseable()
    print("PASS test_v20_206_10d_spy_conditional_overlay_validation")
