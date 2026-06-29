#!/usr/bin/env python
"""Formal checks for V21.047-R3 operator review decision capture."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r3_operator_review_decision_capture.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r3_operator_review_decision_capture.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"
OPTIONAL_INPUT = REV / "V21_047_R3_OPERATOR_INPUT.csv"
OUTPUTS = [
    "V21_047_R3_OPERATOR_REVIEW_PACKET.csv",
    "V21_047_R3_ALLOWED_OPERATOR_DECISIONS.csv",
    "V21_047_R3_OPERATOR_DECISION_CAPTURE.csv",
    "V21_047_R3_CANDIDATE_WARNING_REGISTER.csv",
    "V21_047_R3_NEXT_STAGE_ROUTING.csv",
    "V21_047_R3_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R3_DECISION_SUMMARY.csv",
]
DEFAULT = "APPROVE_PRIMARY_WITH_HOLDINGS_EVIDENCE_REPAIR_REQUIRED"
ALLOWED = {
    "APPROVE_PRIMARY_FOR_REVIEW_PACKET_ONLY",
    DEFAULT,
    "REQUEST_COST_MODEL_RECHECK",
    "SELECT_SECONDARY_QQQ_MA50_REVIEW_ONLY",
    "SELECT_TERTIARY_QQQ_DRAWDOWN_REVIEW_ONLY",
    "REJECT_OVERLAY_KEEP_BASELINE_TECH_TOP20_10D",
    "WAIT_FOR_MATURED_OBSERVATION_BEFORE_OVERLAY_REVIEW",
}


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
            "scripts/v21/run_v21_047_r3_operator_review_decision_capture.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    # The formal default-path test requires no external operator input.
    assert not OPTIONAL_INPUT.exists(), (
        f"remove optional input before default-path test: {OPTIONAL_INPUT}"
    )
    official = [
        REV / "V21_047_R2A_DECISION_SUMMARY.csv",
        REV / "V21_047_R2_DECISION_SUMMARY.csv",
        REV / "V21_047_R1A_DECISION_SUMMARY.csv",
        REV / "V21_046_R4_DECISION_SUMMARY.csv",
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
        "final_status=", "decision=", "primary_candidate=",
        "operator_input_source=", "recommended_next_stage=",
        "overlay_adoption_allowed=", "official_adoption_allowed=",
        "shadow_gate_allowed=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R2A outputs are read by the stage and summarized in the packet.
    packet = rows["V21_047_R3_OPERATOR_REVIEW_PACKET.csv"][0]
    assert packet.get("primary_candidate") == "COMBINED_TURNOVER_BUFFER_25_PLUS_QQQ_MA50"
    assert packet.get("primary_candidate_score") == "0.9850000000"

    # 5-7. Core outputs.
    allowed_rows = rows["V21_047_R3_ALLOWED_OPERATOR_DECISIONS.csv"]
    capture = rows["V21_047_R3_OPERATOR_DECISION_CAPTURE.csv"][0]
    assert packet and allowed_rows and capture

    # 6. All seven allowed decisions.
    assert {row.get("operator_decision") for row in allowed_rows} == ALLOWED
    assert all(row.get("is_adoption_decision") == "FALSE" for row in allowed_rows)

    # 8-12. Default capture, caveats, and routing.
    assert capture.get("captured_operator_decision") == DEFAULT
    assert capture.get("operator_input_source") == "DEFAULT_SAFE_REVIEW_DECISION"
    assert capture.get("decision_used_default") == "TRUE"
    assert (
        capture.get("holdings_evidence_caveat")
        == "HOLDINGS_SNAPSHOTS_UNCHANGED_DESPITE_REPORTED_TURNOVER_REDUCTION"
    )
    assert capture.get("cost_warning_status") == "CARRIED_FORWARD_NOT_BLOCKING_OPERATOR_REVIEW"
    assert capture.get("downside_monitor_dependency") == "MATURED_EVIDENCE_REQUIRED_AFTER_2026_06_24"
    assert (
        capture.get("recommended_next_stage")
        == "V21.047-R3A_HOLDINGS_EVIDENCE_REPAIR_FOR_PRIMARY_OVERLAY"
    )

    # 13-31. Guardrails.
    decision = rows["V21_047_R3_DECISION_SUMMARY.csv"][0]
    assert_false(decision, "operator_decision_is_adoption")
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
    assert_true(decision, "operator_decision_capture_only")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)

    # 32-34. No recommendation language, yfinance, or online access.
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

    # 35. No prohibited paths.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R3" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 36. Existing official/upstream files unchanged.
    assert before == {path: digest(path) for path in official}

    # 37. Report boundary.
    report = RC / "V21_047_R3_OPERATOR_REVIEW_DECISION_CAPTURE_REPORT.md"
    current = RC / "CURRENT_V21_047_R3_OPERATOR_REVIEW_DECISION_CAPTURE_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only operator decision capture results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted." in text
    assert "No portfolio variant was adopted." in text
    assert "No filter was adopted." in text

    print("V21_047_R3_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
