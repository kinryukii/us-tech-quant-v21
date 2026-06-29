#!/usr/bin/env python
"""Formal checks for V21.047-R1 overlay review gate."""

from __future__ import annotations

import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_047_r1_overlay_review_gate.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_047_r1_overlay_review_gate.ps1"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"


def read_rows(path: Path) -> list[dict[str, str]]:
    assert path.exists(), f"missing {path}"
    assert path.stat().st_size > 0, f"empty {path}"
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows, f"no rows {path}"
    return rows


def first(path: Path) -> dict[str, str]:
    return read_rows(path)[0]


def assert_false(row: dict[str, str], key: str) -> None:
    assert str(row.get(key, "")).upper() == "FALSE", f"{key} must be FALSE"


def assert_true(row: dict[str, str], key: str) -> None:
    assert str(row.get(key, "")).upper() == "TRUE", f"{key} must be TRUE"


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)

    parse = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw scripts/v21/run_v21_047_r1_overlay_review_gate.ps1), [ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    run = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "final_status=" in run.stdout

    for required in [
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
        ROOT / "outputs/v21/review/V21_047_DECISION_SUMMARY.csv",
    ]:
        read_rows(required)

    outputs = [
        "V21_047_R1_UPSTREAM_READINESS_AUDIT.csv",
        "V21_047_R1_OVERLAY_METRIC_ATTRIBUTION_AUDIT.csv",
        "V21_047_R1_BEST_BALANCED_OVERLAY_AUDIT.csv",
        "V21_047_R1_TURNOVER_OVERLAY_AUDIT.csv",
        "V21_047_R1_DRAWDOWN_OVERLAY_AUDIT.csv",
        "V21_047_R1_COST_AWARE_AUDIT.csv",
        "V21_047_R1_SUBPERIOD_STABILITY_AUDIT.csv",
        "V21_047_R1_HOLDINGS_CONCENTRATION_AUDIT.csv",
        "V21_047_R1_LEAKAGE_AND_RULE_AUDIT.csv",
        "V21_047_R1_SCOPE_BOUNDARY_AUDIT.csv",
        "V21_047_R1_DECISION_SUMMARY.csv",
    ]
    for name in outputs:
        read_rows(REV / name)

    dec = first(REV / "V21_047_R1_DECISION_SUMMARY.csv")
    assert dec.get("metric_attribution_status"), "metric attribution status not written"
    assert_false(dec, "overlay_adoption_allowed")
    assert_false(dec, "portfolio_variant_adoption_allowed")
    assert_false(dec, "filter_adoption_allowed")
    assert_false(dec, "full_weight_result_available")
    assert_false(dec, "full_weight_rebacktest_allowed_now")
    assert_true(dec, "research_only")
    assert_true(dec, "overlay_review_gate_only")
    for key in [
        "official_adoption_allowed",
        "official_weight_mutation",
        "official_ranking_mutation",
        "official_recommendation_allowed",
        "real_book_action_allowed",
        "broker_execution_allowed",
        "trade_action_allowed",
        "shadow_gate_allowed",
        "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(dec, key)
    assert dec.get("overlay_adopted", "FALSE").upper() == "FALSE"
    assert dec.get("any_overlay_adoptable_now", "FALSE").upper() == "FALSE"

    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import|from)\s+yfinance\b", source, flags=re.IGNORECASE | re.MULTILINE)
    assert "download(" not in source.lower()
    assert "requests." not in source.lower()

    csv_text = ""
    for path in REV.glob("V21_047_R1_*.csv"):
        csv_text += path.read_text(encoding="utf-8", errors="ignore") + "\n"
    assert not re.search(r"\b(?:buy|sell|hold)\b", csv_text, flags=re.IGNORECASE)

    forbidden_roots = [
        ROOT / "outputs/v22",
        ROOT / "outputs/v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
    ]
    for path in forbidden_roots:
        if path.exists():
            touched = [p for p in path.rglob("*") if p.is_file() and "V21_047_R1" in p.name]
            assert not touched, f"forbidden output written: {touched}"

    report = RC / "V21_047_R1_OVERLAY_REVIEW_GATE_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert "Technical-only overlay results must not be interpreted as full-weight results" in text

    print("V21_047_R1_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
