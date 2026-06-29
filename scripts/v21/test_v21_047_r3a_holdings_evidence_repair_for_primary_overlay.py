#!/usr/bin/env python
"""Formal checks for V21.047-R3A holdings evidence repair."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r3a_holdings_evidence_repair_for_primary_overlay.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r3a_holdings_evidence_repair_for_primary_overlay.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R3A_UPSTREAM_DECISION_AUDIT.csv",
    "V21_047_R3A_EVIDENCE_AVAILABILITY_AUDIT.csv",
    "V21_047_R3A_HOLDINGS_EQUALITY_AUDIT.csv",
    "V21_047_R3A_EXPOSURE_RECONSTRUCTION.csv",
    "V21_047_R3A_TURNOVER_EVIDENCE_RECONSTRUCTION.csv",
    "V21_047_R3A_RANK_BUFFER_EVIDENCE_AUDIT.csv",
    "V21_047_R3A_DAILY_RETURN_CONSISTENCY_AUDIT.csv",
    "V21_047_R3A_METRIC_RECONCILIATION_AUDIT.csv",
    "V21_047_R3A_CAVEAT_RESOLUTION_AUDIT.csv",
    "V21_047_R3A_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R3A_DECISION_SUMMARY.csv",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    assert path.exists(), f"missing {path}"
    assert path.stat().st_size > 0, f"empty {path}"
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, f"no rows {path}"
    return rows


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_true(row: dict[str, str], key: str) -> None:
    assert row.get(key, "").upper() == "TRUE", f"{key} must be TRUE"


def assert_false(row: dict[str, str], key: str) -> None:
    assert row.get(key, "").upper() == "FALSE", f"{key} must be FALSE"


def main() -> int:
    # 1. Production script compiles.
    py_compile.compile(str(SCRIPT), doraise=True)

    # 2. Wrapper parses.
    parse = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
            "scripts/v21/run_v21_047_r3a_holdings_evidence_repair_for_primary_overlay.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official = [
        REV / "V21_047_R3_DECISION_SUMMARY.csv",
        REV / "V21_047_R2A_DECISION_SUMMARY.csv",
        REV / "V21_047_R2_DECISION_SUMMARY.csv",
        REV / "V21_047_R1A_DECISION_SUMMARY.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    ]
    before = {path: digest(path) for path in official}

    # 3. Wrapper executes.
    run = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for key in [
        "final_status=", "decision=", "caveat_resolution=",
        "turnover_explanation=", "rank_buffer_evidence_status=",
        "metric_reconciliation_status=", "recommended_next_stage=",
        "overlay_adoption_allowed=", "official_adoption_allowed=",
        "shadow_gate_allowed=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4-13. R3 is read and all required audits exist.
    upstream = rows["V21_047_R3A_UPSTREAM_DECISION_AUDIT.csv"]
    assert any(
        row.get("input_name") == "r3_decision"
        and row.get("check_passed") == "TRUE"
        for row in upstream
    )
    availability = rows["V21_047_R3A_EVIDENCE_AVAILABILITY_AUDIT.csv"]
    holdings = rows["V21_047_R3A_HOLDINGS_EQUALITY_AUDIT.csv"]
    exposure = rows["V21_047_R3A_EXPOSURE_RECONSTRUCTION.csv"]
    turnover = rows["V21_047_R3A_TURNOVER_EVIDENCE_RECONSTRUCTION.csv"]
    rank_buffer = rows["V21_047_R3A_RANK_BUFFER_EVIDENCE_AUDIT.csv"]
    daily = rows["V21_047_R3A_DAILY_RETURN_CONSISTENCY_AUDIT.csv"]
    metrics = rows["V21_047_R3A_METRIC_RECONCILIATION_AUDIT.csv"]
    caveat = rows["V21_047_R3A_CAVEAT_RESOLUTION_AUDIT.csv"][0]
    assert availability and holdings and exposure and turnover and rank_buffer and daily and metrics and caveat

    # 14-15. Caveat and turnover explanation are explicit.
    assert caveat.get("caveat_resolution") in {
        "CAVEAT_RESOLVED_EXPLAINED_BY_EXPOSURE_SCALING",
        "CAVEAT_RESOLVED_HOLDINGS_EVIDENCE_REPAIRED",
        "CAVEAT_PARTIALLY_RESOLVED_RANK_BUFFER_EVIDENCE_MISSING",
        "CAVEAT_NOT_RESOLVED_REPAIR_REQUIRED",
        "CAVEAT_BLOCKS_PRIMARY_OVERLAY_REVIEW",
    }
    assert caveat.get("turnover_reduction_explanation") in {
        "EXPLAINED_BY_HOLDINGS_CHANGE",
        "EXPLAINED_BY_EXPOSURE_SCALING",
        "EXPLAINED_BY_COST_TURNOVER_DEFINITION",
        "NOT_EXPLAINED_REPAIR_REQUIRED",
        "DATA_LIMITED",
    }
    assert all(row.get("holdings_snapshot_same_as_baseline") == "TRUE" for row in holdings)
    assert all(row.get("existing_exposure_matches_inferred_MA50_rule") == "TRUE" for row in exposure)
    assert all(row.get("return_difference_explained_by_exposure") == "TRUE" for row in daily)

    # 16-34. Guardrails.
    decision = rows["V21_047_R3A_DECISION_SUMMARY.csv"][0]
    assert_false(decision, "overlay_adopted")
    assert_false(decision, "portfolio_variant_adopted")
    assert_false(decision, "filter_adopted")
    assert_false(decision, "any_overlay_adoptable_now")
    assert_false(decision, "overlay_adoption_allowed")
    assert_false(decision, "portfolio_variant_adoption_allowed")
    assert_false(decision, "filter_adoption_allowed")
    assert_false(decision, "full_weight_result_available")
    assert_false(decision, "full_weight_rebacktest_allowed_now")
    assert_true(decision, "research_only")
    assert_true(decision, "holdings_evidence_repair_only")
    assert_false(decision, "operator_decision_is_adoption")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)

    # 35-37. No recommendation language, yfinance, or network access.
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import|from)\s+yfinance\b", source, re.I | re.M)
    assert "requests." not in source.lower()
    assert "urlopen(" not in source.lower()
    assert "download(" not in source.lower()
    for name in OUTPUTS:
        text = (REV / name).read_text(encoding="utf-8", errors="ignore")
        assert not re.search(
            r"\b(?:BUY|SELL|HOLD)\s+(?:RECOMMENDATION|SIGNAL|ACTION)\b",
            text,
            re.I,
        ), f"recommendation language in {name}"

    # 38. No prohibited output paths.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R3A" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 39. Existing official/upstream files unchanged.
    assert before == {path: digest(path) for path in official}

    # 40. Report full-weight boundary.
    report = RC / "V21_047_R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY_REPORT.md"
    current = RC / "CURRENT_V21_047_R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only holdings evidence repair results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted" in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R3A_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
