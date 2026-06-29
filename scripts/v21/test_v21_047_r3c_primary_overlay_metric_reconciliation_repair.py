#!/usr/bin/env python
"""Formal checks for V21.047-R3C metric reconciliation repair."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r3c_primary_overlay_metric_reconciliation_repair.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r3c_primary_overlay_metric_reconciliation_repair.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R3C_UPSTREAM_R3A_RECONCILIATION_AUDIT.csv",
    "V21_047_R3C_CANDIDATE_COMPONENT_ATTRIBUTION_AUDIT.csv",
    "V21_047_R3C_REPAIRED_METRIC_TABLE.csv",
    "V21_047_R3C_COMBINED_VS_SIMPLE_EQUIVALENCE_AUDIT.csv",
    "V21_047_R3C_TURNOVER_CLAIM_REPAIR_AUDIT.csv",
    "V21_047_R3C_CANDIDATE_RELABEL_DEMOTION_AUDIT.csv",
    "V21_047_R3C_COST_WARNING_RECHECK.csv",
    "V21_047_R3C_REVIEW_CONTINUATION_AUDIT.csv",
    "V21_047_R3C_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R3C_DECISION_SUMMARY.csv",
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
            "scripts/v21/run_v21_047_r3c_primary_overlay_metric_reconciliation_repair.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official = [
        REV / "V21_047_R3A_DECISION_SUMMARY.csv",
        REV / "V21_047_R3_DECISION_SUMMARY.csv",
        REV / "V21_047_R2A_DECISION_SUMMARY.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
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
        "final_status=", "decision=", "corrected_primary_candidate=",
        "turnover_claim_repair_result=", "equivalence_status=",
        "cost_warning_status=", "review_continuation_status=",
        "recommended_next_stage=", "overlay_adoption_allowed=",
        "official_adoption_allowed=", "shadow_gate_allowed=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R3A outputs read.
    upstream = rows["V21_047_R3C_UPSTREAM_R3A_RECONCILIATION_AUDIT.csv"]
    for name in [
        "r3a_decision", "r3a_upstream", "r3a_availability", "r3a_holdings",
        "r3a_exposure", "r3a_turnover", "r3a_rank", "r3a_returns",
        "r3a_metrics", "r3a_caveat",
    ]:
        assert any(
            row.get("input_name") == name and row.get("check_passed") == "TRUE"
            for row in upstream
        ), f"R3A input not read: {name}"

    # 5-12. Required audits.
    attribution = rows["V21_047_R3C_CANDIDATE_COMPONENT_ATTRIBUTION_AUDIT.csv"]
    metrics = rows["V21_047_R3C_REPAIRED_METRIC_TABLE.csv"]
    equivalence = rows["V21_047_R3C_COMBINED_VS_SIMPLE_EQUIVALENCE_AUDIT.csv"]
    turnover = rows["V21_047_R3C_TURNOVER_CLAIM_REPAIR_AUDIT.csv"][0]
    relabel = rows["V21_047_R3C_CANDIDATE_RELABEL_DEMOTION_AUDIT.csv"][0]
    cost = rows["V21_047_R3C_COST_WARNING_RECHECK.csv"][0]
    continuation = rows["V21_047_R3C_REVIEW_CONTINUATION_AUDIT.csv"][0]
    assert attribution and metrics and equivalence and turnover and relabel and cost and continuation

    # 13-15. Explicit claim repair and corrected candidate.
    assert turnover.get("turnover_claim_repair_result") in {
        "TURNOVER_REDUCTION_CLAIM_REMOVED",
        "TURNOVER_REDUCTION_CLAIM_RELABELED_AS_EXPOSURE_SCALING",
        "TURNOVER_REDUCTION_CLAIM_REQUIRES_RANK_BUFFER_EVIDENCE_REPAIR",
        "TURNOVER_REDUCTION_CLAIM_VALIDATED",
    }
    assert relabel.get("corrected_primary_review_candidate")
    assert turnover.get("valid_turnover_reduction_for_review") == "0.0000000000"
    assert turnover.get("exposure_scaling_is_not_holdings_turnover_reduction") == "TRUE"
    repaired = {
        row.get("repaired_label"): row for row in metrics
    }
    assert repaired["REPAIRED_COMBINED_EXPOSURE_ONLY"]["holdings_turnover_reduction"] == "0.0000000000"
    assert repaired["SIMPLE_QQQ_MA50_RISK_OFF_SCALE"]["holdings_turnover_reduction"] == "0.0000000000"
    assert repaired["ORIGINAL_COMBINED_REPORTED"]["holdings_turnover_reduction_supported"] == "FALSE"

    # 16-34. Guardrails.
    decision = rows["V21_047_R3C_DECISION_SUMMARY.csv"][0]
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
    assert_true(decision, "metric_reconciliation_repair_only")
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
                if path.is_file() and "V21_047_R3C" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 39. Existing files unchanged.
    assert before == {path: digest(path) for path in official}

    # 40. Report boundary.
    report = RC / "V21_047_R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR_REPORT.md"
    current = RC / "CURRENT_V21_047_R3C_PRIMARY_OVERLAY_METRIC_RECONCILIATION_REPAIR_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only metric reconciliation repair results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted" in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R3C_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
