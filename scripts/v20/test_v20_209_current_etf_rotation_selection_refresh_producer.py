#!/usr/bin/env python
"""Tests for V20.209 current ETF rotation selection refresh producer."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_209_current_etf_rotation_selection_refresh_producer.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_209_current_etf_rotation_selection_refresh_producer.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
REPORTS_DIR = ROOT / "outputs" / "v20" / "reports"
REPORT = READ_CENTER / "V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH_REPORT.md"

OUTPUTS = [
    CONSOLIDATION / "V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH.csv",
    OUT_DIR / "V20_209_ETF_INPUT_SOURCE_AUDIT.csv",
    OUT_DIR / "V20_209_ETF_SIGNAL_COMPONENTS.csv",
    OUT_DIR / "V20_209_ETF_SELECTION_FRESHNESS_AUDIT.csv",
    OUT_DIR / "V20_209_ETF_SELECTION_REFRESH_GATE.csv",
    REPORT,
]
ALLOWED_STATUSES = {
    "PASS_V20_209_CURRENT_ETF_SELECTION_REFRESHED_SPY",
    "PASS_V20_209_CURRENT_ETF_SELECTION_REFRESHED_NON_SPY",
    "PARTIAL_PASS_V20_209_CURRENT_ETF_SELECTION_RESOLVED_STALE_WARN",
    "PARTIAL_PASS_V20_209_CURRENT_ETF_SELECTION_UNKNOWN_INPUT_UNAVAILABLE",
    "BLOCKED_V20_209_REFRESH_PRODUCER_FAILED",
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
                if "weight" in path.name.lower() and not path.name.startswith("V20_209_")
            )
    return sorted(files)


def daily_report_hashes() -> dict[Path, str]:
    roots = [REPORTS_DIR, READ_CENTER]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(path for path in root.glob("*.md") if "V20_209" not in path.name)
    return {path: sha(path) for path in sorted(files)}


def test_v20_209_current_etf_rotation_selection_refresh_producer() -> None:
    weight_before = {path: sha(path) for path in protected_weight_files()}
    daily_before = daily_report_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=" in result.stdout
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "OFFICIAL_WEIGHT_MUTATED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "REAL_BOOK_SIGNAL_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout
    assert "TRADE_ACTION_CREATED=FALSE" in result.stdout
    assert "SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE" in result.stdout

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"

    selection_rows = read_csv(CONSOLIDATION / "V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH.csv")
    assert len(selection_rows) == 1
    selection = selection_rows[0]
    if selection["current_selected_etf"] == "UNKNOWN":
        assert selection["observation_allowed_if_rule_v20_206_applied"] == "FALSE"
    if selection["current_selected_etf"] != "SPY":
        assert selection["observation_allowed_if_rule_v20_206_applied"] == "FALSE"
    if selection["current_selected_etf"] == "SPY":
        assert selection["observation_allowed_if_rule_v20_206_applied"] == "TRUE"
        assert selection["resolution_status"] == "RESOLVED"

    gate_rows = read_csv(OUT_DIR / "V20_209_ETF_SELECTION_REFRESH_GATE.csv")
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate["final_status"] in ALLOWED_STATUSES
    assert gate["research_only"] == "TRUE"
    assert gate["official_weight_mutated"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["real_book_signal_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["shadow_weight_change_recommended"] == "FALSE"

    components = read_csv(OUT_DIR / "V20_209_ETF_SIGNAL_COMPONENTS.csv")
    if any(row["component_status"] == "PASS" for row in components):
        assert "rank" in components[0]
        assert "final_score" in components[0]

    freshness = read_csv(OUT_DIR / "V20_209_ETF_SELECTION_FRESHNESS_AUDIT.csv")
    assert len(freshness) == 1
    assert freshness[0]["freshness_status"]

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("V20_209*")]
    forbidden_terms = ["official_recommendation", "real_book_signal", "trade_action", "broker_execution"]
    assert not any(any(term in name for term in forbidden_terms) for name in created_artifacts)
    assert weight_before == {path: sha(path) for path in protected_weight_files()}
    assert daily_before == daily_report_hashes()

    report_text = REPORT.read_text(encoding="utf-8")
    assert gate["final_status"] in report_text
    assert "official weights were not changed" in report_text
    assert "no official recommendation was created" in report_text
    assert "no real-book signal was created" in report_text
    assert "no broker execution was created" in report_text
    assert "no trade action was created" in report_text
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
    test_v20_209_current_etf_rotation_selection_refresh_producer()
    test_wrapper_parseable()
    print("PASS test_v20_209_current_etf_rotation_selection_refresh_producer")
