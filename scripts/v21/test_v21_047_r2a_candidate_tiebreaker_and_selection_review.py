#!/usr/bin/env python
"""Formal checks for V21.047-R2A candidate tiebreaker review."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r2a_candidate_tiebreaker_and_selection_review.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r2a_candidate_tiebreaker_and_selection_review.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R2A_UPSTREAM_R2_READINESS_AUDIT.csv",
    "V21_047_R2A_CANDIDATE_METRIC_CONSOLIDATION.csv",
    "V21_047_R2A_TIEBREAKER_SCORE_REGISTER.csv",
    "V21_047_R2A_CANDIDATE_RANKING.csv",
    "V21_047_R2A_COMBINED_CANDIDATE_DEEP_REVIEW.csv",
    "V21_047_R2A_QQQ_SCALING_COMPARISON.csv",
    "V21_047_R2A_PORTFOLIO_DRAWDOWN_CANDIDATE_COMPARISON.csv",
    "V21_047_R2A_COST_WARNING_AUDIT.csv",
    "V21_047_R2A_DOWNSIDE_MONITOR_DEPENDENCY_AUDIT.csv",
    "V21_047_R2A_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R2A_DECISION_SUMMARY.csv",
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
            "scripts/v21/run_v21_047_r2a_candidate_tiebreaker_and_selection_review.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official = [
        REV / "V21_047_R2_DECISION_SUMMARY.csv",
        REV / "V21_047_R1A_DECISION_SUMMARY.csv",
        REV / "V21_047_DECISION_SUMMARY.csv",
        REV / "V21_046_R4_DECISION_SUMMARY.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
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
        "final_status=", "decision=", "primary_review_candidate=",
        "secondary_review_candidate=", "cost_warning_status=",
        "downside_monitor_dependency=", "recommended_next_stage=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R2 inputs explicitly read.
    upstream = rows["V21_047_R2A_UPSTREAM_R2_READINESS_AUDIT.csv"]
    read_inputs = {
        row.get("input_name") for row in upstream
        if row.get("audit_item") == "input_read" and row.get("check_passed") == "TRUE"
    }
    for name in [
        "r2_decision", "r2_upstream", "r2_eligibility", "r2_comparison",
        "r2_behavior", "r2_cost", "r2_alpha", "r2_subperiod",
        "r2_downside", "r2_classification",
    ]:
        assert name in read_inputs, f"R2 input not read: {name}"

    # 5-11. Required outputs.
    metrics = rows["V21_047_R2A_CANDIDATE_METRIC_CONSOLIDATION.csv"]
    scores = rows["V21_047_R2A_TIEBREAKER_SCORE_REGISTER.csv"]
    ranking = rows["V21_047_R2A_CANDIDATE_RANKING.csv"]
    combined = rows["V21_047_R2A_COMBINED_CANDIDATE_DEEP_REVIEW.csv"]
    cost = rows["V21_047_R2A_COST_WARNING_AUDIT.csv"]
    downside = rows["V21_047_R2A_DOWNSIDE_MONITOR_DEPENDENCY_AUDIT.csv"]
    decision = rows["V21_047_R2A_DECISION_SUMMARY.csv"][0]
    assert metrics and scores and ranking and combined and cost and downside and decision
    assert all(
        row.get("overlay_id") == row.get("metric_attribution_overlay_id")
        for row in metrics
    )
    assert all(row.get("same_overlay_scoring_only") == "TRUE" for row in scores)

    # 12. TURNOVER_BUFFER_RANK_30 remains rejected/quarantined.
    turn30 = [row for row in ranking if row.get("overlay_id") == "TURNOVER_BUFFER_RANK_30"]
    assert len(turn30) == 1
    assert turn30[0].get("selection_role") == "REJECTED_OR_QUARANTINED"
    assert "NO_OP_WARNING" in turn30[0].get("key_weaknesses", "")
    assert decision.get("rejected_no_op_overlay") == "TURNOVER_BUFFER_RANK_30"

    # 13-30. Guardrails.
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
    assert_true(decision, "candidate_tiebreaker_review_only")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)
    assert all(row.get("adoptable_now") == "FALSE" for row in ranking)

    # 31-33. No recommendation language, yfinance, or online access.
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

    # 34. No prohibited output paths.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R2A" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 35. Existing official/upstream files unchanged.
    assert before == {path: digest(path) for path in official}

    # 36. Report full-weight boundary.
    report = RC / "V21_047_R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW_REPORT.md"
    current = RC / "CURRENT_V21_047_R2A_CANDIDATE_TIEBREAKER_AND_SELECTION_REVIEW_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only candidate tiebreaker results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted." in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R2A_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
