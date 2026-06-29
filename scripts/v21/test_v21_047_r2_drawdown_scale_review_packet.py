#!/usr/bin/env python
"""Formal checks for V21.047-R2 drawdown scale review packet."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r2_drawdown_scale_review_packet.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r2_drawdown_scale_review_packet.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R2_UPSTREAM_ATTRIBUTION_REPAIR_AUDIT.csv",
    "V21_047_R2_CANDIDATE_ELIGIBILITY_AUDIT.csv",
    "V21_047_R2_BASELINE_VS_CANDIDATE_COMPARISON.csv",
    "V21_047_R2_DRAWDOWN_RISK_OFF_BEHAVIOR_AUDIT.csv",
    "V21_047_R2_TURNOVER_COST_AUDIT.csv",
    "V21_047_R2_ALPHA_PRESERVATION_AUDIT.csv",
    "V21_047_R2_SUBPERIOD_STABILITY_AUDIT.csv",
    "V21_047_R2_DOWNSIDE_MONITOR_COMPATIBILITY_AUDIT.csv",
    "V21_047_R2_CANDIDATE_CLASSIFICATION.csv",
    "V21_047_R2_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R2_DECISION_SUMMARY.csv",
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

    # 2. PowerShell wrapper parses.
    parse = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
            "scripts/v21/run_v21_047_r2_drawdown_scale_review_packet.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official = [
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
        "final_status=", "decision=", "surviving_review_only_candidates=",
        "rejected_no_op_overlays=", "alpha_preservation_status=",
        "turnover_cost_status=", "recommended_next_stage=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R1A outputs are read.
    upstream = rows["V21_047_R2_UPSTREAM_ATTRIBUTION_REPAIR_AUDIT.csv"]
    read_inputs = {
        row.get("input_name") for row in upstream
        if row.get("audit_item") == "input_read" and row.get("check_passed") == "TRUE"
    }
    for name in [
        "r1a_decision", "r1a_metrics", "r1a_preservation", "r1a_noop",
        "r1a_score", "r1a_selection", "r1a_review", "r1a_scope",
    ]:
        assert name in read_inputs, f"R1A input not read: {name}"

    # 5-11. Required substantive outputs are non-empty.
    eligibility = rows["V21_047_R2_CANDIDATE_ELIGIBILITY_AUDIT.csv"]
    comparison = rows["V21_047_R2_BASELINE_VS_CANDIDATE_COMPARISON.csv"]
    behavior = rows["V21_047_R2_DRAWDOWN_RISK_OFF_BEHAVIOR_AUDIT.csv"]
    cost = rows["V21_047_R2_TURNOVER_COST_AUDIT.csv"]
    alpha = rows["V21_047_R2_ALPHA_PRESERVATION_AUDIT.csv"]
    classification = rows["V21_047_R2_CANDIDATE_CLASSIFICATION.csv"]
    decision = rows["V21_047_R2_DECISION_SUMMARY.csv"][0]
    assert eligibility and comparison and behavior and cost and alpha and classification and decision

    # 12. No-op candidates are rejected or quarantined.
    no_ops = [row for row in eligibility if row.get("no_op_status") == "NO_OP_WARNING"]
    assert no_ops
    assert all(
        row.get("eligibility_for_R2_packet") == "REJECTED_OR_QUARANTINED"
        for row in no_ops
    )
    turn30 = [row for row in eligibility if row.get("overlay_id") == "TURNOVER_BUFFER_RANK_30"]
    assert len(turn30) == 1
    assert turn30[0].get("candidate_scope") == "QUARANTINE"
    assert turn30[0].get("eligibility_for_R2_packet") == "REJECTED_OR_QUARANTINED"

    # 13-30. No adoption and all guardrails.
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
    assert_true(decision, "drawdown_scale_review_packet_only")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)
    assert all(row.get("adoptable_now") == "FALSE" for row in classification)

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

    # 34. No stage outputs in prohibited roots.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R2" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 35. Existing official and upstream files remain unchanged.
    assert before == {path: digest(path) for path in official}

    # 36. Report states the full-weight boundary.
    report = RC / "V21_047_R2_DRAWDOWN_SCALE_REVIEW_PACKET_REPORT.md"
    current = RC / "CURRENT_V21_047_R2_DRAWDOWN_SCALE_REVIEW_PACKET_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only overlay review results must not be interpreted as "
        "full-weight results" in text
    )
    assert "No overlay was adopted." in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R2_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
