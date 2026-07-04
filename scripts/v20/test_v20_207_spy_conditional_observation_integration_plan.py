#!/usr/bin/env python
"""Tests for V20.207 SPY conditional observation integration plan."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_207_spy_conditional_observation_integration_plan.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_207_spy_conditional_observation_integration_plan.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
REPORTS_DIR = ROOT / "outputs" / "v20" / "reports"
CONSOLIDATION_DIR = ROOT / "outputs" / "v20" / "consolidation"
REPORT = READ_CENTER / "V20_207_SPY_CONDITIONAL_OBSERVATION_INTEGRATION_PLAN_REPORT.md"

INPUTS = [
    OUT_DIR / "V20_206_SPY_CONDITIONAL_EFFECTIVENESS.csv",
    OUT_DIR / "V20_206_SPY_VS_NON_SPY_COMPARISON.csv",
    OUT_DIR / "V20_206_SPY_CONDITIONAL_BOOTSTRAP.csv",
    OUT_DIR / "V20_206_SPY_CONDITIONAL_TRIMMED_WINSORIZED.csv",
    OUT_DIR / "V20_206_SPY_ASOF_DATE_STABILITY.csv",
    OUT_DIR / "V20_206_SPY_WEIGHT_BIAS_REPEATABILITY.csv",
    OUT_DIR / "V20_206_CONDITIONAL_OVERLAY_RULE_CANDIDATE.csv",
    OUT_DIR / "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv",
    READ_CENTER / "V20_206_10D_SPY_CONDITIONAL_OVERLAY_VALIDATION_REPORT.md",
]
OPTIONAL_DAILY_REPORTS = [
    REPORTS_DIR / "V20_200_OPERATOR_DAILY_REPORT_V2.md",
    READ_CENTER / "V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md",
    CONSOLIDATION_DIR / "V20_200_OPERATOR_DAILY_REPORT_SUMMARY.csv",
]
OUTPUTS = [
    OUT_DIR / "V20_207_CONDITIONAL_OBSERVATION_RULE_REGISTRY.csv",
    OUT_DIR / "V20_207_DAILY_REPORT_INTEGRATION_SPEC.csv",
    OUT_DIR / "V20_207_CURRENT_CONDITIONAL_OBSERVATION_STATUS.csv",
    OUT_DIR / "V20_207_NON_SPY_DISABLE_AUDIT.csv",
    OUT_DIR / "V20_207_OBSERVATION_ONLY_SAFETY_AUDIT.csv",
    OUT_DIR / "V20_207_INTEGRATION_GATE.csv",
    REPORT,
]
REQUIRED_SAFETY = {
    "RESEARCH_ONLY",
    "OFFICIAL_WEIGHT_MUTATED",
    "OFFICIAL_RECOMMENDATION_CREATED",
    "REAL_BOOK_SIGNAL_CREATED",
    "BROKER_EXECUTION_SUPPORTED",
    "SHADOW_WEIGHT_CHANGE_RECOMMENDED",
    "TRADE_ACTION_CREATED",
    "OFFICIAL_REPORT_OVERWRITE",
}
ALLOWED_STATUSES = {
    "PASS_V20_207_SPY_CONDITIONAL_OBSERVATION_ALLOWED_IN_REPORT_SPEC",
    "PASS_V20_207_NON_SPY_OBSERVATION_DISABLED_IN_REPORT_SPEC",
    "PARTIAL_PASS_V20_207_INTEGRATION_SPEC_READY_CURRENT_CONDITION_UNKNOWN",
    "BLOCKED_V20_207_REQUIRED_INPUT_MISSING",
    "BLOCKED_V20_207_OBSERVATION_ONLY_SAFETY_FAILED",
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
                if "weight" in path.name.lower() and not path.name.startswith("V20_207_")
            )
    return sorted(files)


def existing_daily_report_hashes() -> dict[Path, str]:
    return {path: sha(path) for path in OPTIONAL_DAILY_REPORTS if path.exists()}


def test_v20_207_spy_conditional_observation_integration_plan() -> None:
    input_before = {path: sha(path) for path in INPUTS if path.exists()}
    weight_before = {path: sha(path) for path in protected_weight_files()}
    daily_before = existing_daily_report_hashes()
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
        assert daily_before == existing_daily_report_hashes()
        for path in OUTPUTS:
            assert path.exists() and path.stat().st_size > 0, f"missing blocked output {path}"
        return

    for path in INPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing or empty input {path}"
        if path.suffix.lower() == ".csv":
            assert read_csv(path), f"input has no rows {path}"
    assert input_before == {path: sha(path) for path in INPUTS if path.exists()}
    assert weight_before == {path: sha(path) for path in protected_weight_files()}
    assert daily_before == existing_daily_report_hashes()

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"

    registry = read_csv(OUT_DIR / "V20_207_CONDITIONAL_OBSERVATION_RULE_REGISTRY.csv")
    assert len(registry) == 1
    assert registry[0]["rule_id"] == "V20_206_SPY_10D_RANDOM_WEIGHT_LOCAL_EDGE_OBSERVATION"

    gate_rows = read_csv(OUT_DIR / "V20_207_INTEGRATION_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    assert gate["shadow_weight_change_recommended"] == "FALSE"
    assert gate["daily_report_overwrite_performed"] == "FALSE"
    assert gate["official_weight_mutated"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["real_book_signal_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"

    safety = read_csv(OUT_DIR / "V20_207_OBSERVATION_ONLY_SAFETY_AUDIT.csv")
    assert REQUIRED_SAFETY <= {row["safety_check"] for row in safety}
    assert all(row["audit_status"] == "PASS" for row in safety)
    assert next(row for row in safety if row["safety_check"] == "SHADOW_WEIGHT_CHANGE_RECOMMENDED")["actual_value"] == "FALSE"

    status = read_csv(OUT_DIR / "V20_207_CURRENT_CONDITIONAL_OBSERVATION_STATUS.csv")[0]
    if status["current_selected_etf"] == "UNKNOWN":
        assert status["observation_allowed"] == "FALSE"
    if status["current_selected_etf"] != "SPY":
        assert status["observation_allowed"] == "FALSE"

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_207*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text
    assert "existing daily reports were not overwritten" in report_text


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
    test_v20_207_spy_conditional_observation_integration_plan()
    test_wrapper_parseable()
    print("PASS test_v20_207_spy_conditional_observation_integration_plan")
