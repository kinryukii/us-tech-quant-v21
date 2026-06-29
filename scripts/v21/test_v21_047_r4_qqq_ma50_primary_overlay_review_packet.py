#!/usr/bin/env python
"""Formal checks for V21.047-R4 QQQ MA50 primary overlay review packet."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r4_qqq_ma50_primary_overlay_review_packet.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r4_qqq_ma50_primary_overlay_review_packet.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R4_UPSTREAM_RECONCILIATION_VALIDATION.csv",
    "V21_047_R4_CORRECTED_CANDIDATE_PROFILE.csv",
    "V21_047_R4_BASELINE_COMPARISON.csv",
    "V21_047_R4_ATTRIBUTION_INTEGRITY_AUDIT.csv",
    "V21_047_R4_QQQ_MA50_RULE_AUDIT.csv",
    "V21_047_R4_RISK_OFF_BEHAVIOR_AUDIT.csv",
    "V21_047_R4_COST_WARNING_REVIEW.csv",
    "V21_047_R4_SUBPERIOD_STABILITY_REVIEW.csv",
    "V21_047_R4_DOWNSIDE_MONITOR_DEPENDENCY.csv",
    "V21_047_R4_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R4_DECISION_SUMMARY.csv",
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
    # 1. Compile.
    py_compile.compile(str(SCRIPT), doraise=True)

    # 2. Wrapper parse.
    parse = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
            "scripts/v21/run_v21_047_r4_qqq_ma50_primary_overlay_review_packet.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official = [
        REV / "V21_047_R3C_DECISION_SUMMARY.csv",
        REV / "V21_047_R3A_DECISION_SUMMARY.csv",
        REV / "V21_047_R2A_DECISION_SUMMARY.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
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
        "final_status=", "decision=", "corrected_primary_candidate=",
        "valid_turnover_reduction=", "cost_warning_status=",
        "maturity_dependency=", "recommended_next_stage=",
        "overlay_adoption_allowed=", "official_adoption_allowed=",
        "shadow_gate_allowed=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R3C outputs read.
    upstream = rows["V21_047_R4_UPSTREAM_RECONCILIATION_VALIDATION.csv"]
    for name in [
        "r3c_decision", "r3c_upstream", "r3c_attribution", "r3c_metrics",
        "r3c_equivalence", "r3c_turnover", "r3c_relabel", "r3c_cost",
        "r3c_continuation",
    ]:
        assert any(
            row.get("input_name") == name and row.get("check_passed") == "TRUE"
            for row in upstream
        ), f"R3C input not read: {name}"

    # 5-14. Required outputs.
    profile = rows["V21_047_R4_CORRECTED_CANDIDATE_PROFILE.csv"][0]
    comparison = rows["V21_047_R4_BASELINE_COMPARISON.csv"][0]
    attribution = rows["V21_047_R4_ATTRIBUTION_INTEGRITY_AUDIT.csv"]
    rule = rows["V21_047_R4_QQQ_MA50_RULE_AUDIT.csv"][0]
    behavior = rows["V21_047_R4_RISK_OFF_BEHAVIOR_AUDIT.csv"][0]
    cost = rows["V21_047_R4_COST_WARNING_REVIEW.csv"][0]
    subperiod = rows["V21_047_R4_SUBPERIOD_STABILITY_REVIEW.csv"]
    downside = rows["V21_047_R4_DOWNSIDE_MONITOR_DEPENDENCY.csv"][0]
    decision = rows["V21_047_R4_DECISION_SUMMARY.csv"][0]
    assert profile and comparison and attribution and rule and behavior and cost and subperiod and downside and decision

    # 15-18. Corrected identity and repaired turnover.
    assert decision.get("corrected_primary_review_candidate") == "QQQ_MA50_RISK_OFF_SCALE"
    assert decision.get("original_demoted_candidate_label") == "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
    assert_true(decision, "original_combined_label_demoted")
    assert decision.get("valid_turnover_reduction") == "0.0000000000"
    assert_true(decision, "unsupported_turnover_claim_removed")
    assert profile.get("valid_turnover_reduction") == "0.0000000000"
    assert any(
        row.get("attribution_item") == "unsupported_30pct_not_valid"
        and row.get("check_passed") == "TRUE"
        for row in attribution
    )

    # 19-37. Guardrails.
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
    assert_true(decision, "qqq_ma50_primary_overlay_review_packet_only")
    assert_false(decision, "operator_decision_is_adoption")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)

    # 38-40. No recommendation language, yfinance, or network access.
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

    # 41. No prohibited paths.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R4" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 42. Existing files unchanged.
    assert before == {path: digest(path) for path in official}

    # 43. Report boundary.
    report = RC / "V21_047_R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET_REPORT.md"
    current = RC / "CURRENT_V21_047_R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only QQQ_MA50 overlay review results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted" in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R4_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
