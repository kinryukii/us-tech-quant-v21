#!/usr/bin/env python
"""Formal checks for V21.047-R6 observation maturity bridge."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r6_qqq_ma50_observation_ledger_maturity_bridge.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r6_qqq_ma50_observation_ledger_maturity_bridge.ps1"
REV = ROOT / "outputs/v21/review"
LEDGER = ROOT / "outputs/v21/ledger/V21_047_R5_QQQ_MA50_OBSERVATION_LEDGER.csv"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R6_UPSTREAM_R5_VALIDATION.csv",
    "V21_047_R6_QQQ_OBSERVATION_LEDGER_INTEGRITY_AUDIT.csv",
    "V21_047_R6_TECHNICAL_MATURITY_DEPENDENCY_AUDIT.csv",
    "V21_047_R6_OVERLAY_TECHNICAL_ALIGNMENT_AUDIT.csv",
    "V21_047_R6_FUTURE_MATURED_EVALUATION_SCHEMA.csv",
    "V21_047_R6_MONITOR_BRIDGE_CONTRACT.csv",
    "V21_047_R6_NEXT_STAGE_ROUTING.csv",
    "V21_047_R6_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R6_DECISION_SUMMARY.csv",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    assert path.exists(), f"missing {path}"
    assert path.stat().st_size > 0, f"empty {path}"
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
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

    # 2. Parse.
    parsed = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
            "scripts/v21/run_v21_047_r6_qqq_ma50_observation_ledger_maturity_bridge.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    assert "PARSE_OK" in parsed.stdout

    official = [
        REV / "V21_047_R5_DECISION_SUMMARY.csv",
        REV / "V21_047_R4_DECISION_SUMMARY.csv",
        REV / "V21_047_R3C_DECISION_SUMMARY.csv",
        LEDGER,
        ROOT / "outputs/v21/ledger/V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv",
        ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
    ]
    before = {path: digest(path) for path in official}

    # 3. Execute.
    run = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    for key in [
        "final_status=", "decision=", "corrected_overlay=", "latest_QQQ_state=",
        "technical_first_maturity_date=", "bridge_readiness=",
        "recommended_next_stage=", "overlay_adoption_allowed=",
        "official_adoption_allowed=", "shadow_gate_allowed=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R5 outputs read.
    upstream = rows["V21_047_R6_UPSTREAM_R5_VALIDATION.csv"]
    for name in [
        "r5_decision", "r5_upstream", "r5_policy", "r5_state", "r5_schema",
        "r5_append", "r5_monitor", "r5_routing", "r5_ledger",
    ]:
        assert any(
            row.get("input_name") == name and row.get("check_passed") == "TRUE"
            for row in upstream
        ), f"R5 input not read: {name}"

    # 5-10. Required outputs.
    integrity = rows["V21_047_R6_QQQ_OBSERVATION_LEDGER_INTEGRITY_AUDIT.csv"][0]
    maturity = rows["V21_047_R6_TECHNICAL_MATURITY_DEPENDENCY_AUDIT.csv"][0]
    alignment = rows["V21_047_R6_OVERLAY_TECHNICAL_ALIGNMENT_AUDIT.csv"]
    schema = rows["V21_047_R6_FUTURE_MATURED_EVALUATION_SCHEMA.csv"]
    contract = rows["V21_047_R6_MONITOR_BRIDGE_CONTRACT.csv"][0]
    decision = rows["V21_047_R6_DECISION_SUMMARY.csv"][0]
    assert integrity and maturity and alignment and schema and contract and decision

    # 11. Ledger uniqueness.
    ledger = read_rows(LEDGER)
    keys = [(row.get("observation_date"), row.get("policy_id")) for row in ledger]
    assert len(keys) == len(set(keys))
    assert integrity.get("duplicate_count") == "0"
    assert integrity.get("ledger_integrity_status") == "VALID"

    # 12-15. Identity, turnover repair, observation-only.
    assert decision.get("corrected_overlay") == "QQQ_MA50_RISK_OFF_SCALE"
    assert decision.get("valid_turnover_reduction") == "0.0000000000"
    assert_true(decision, "unsupported_turnover_claim_removed")
    assert_true(decision, "overlay_observation_enabled")
    assert_false(decision, "overlay_adoption_allowed")
    assert all(row.get("future_returns_filled_now") == "FALSE" for row in schema)
    assert all(row.get("future_value") == "" for row in schema)

    # 16-33. Guardrails.
    assert_false(decision, "overlay_adopted")
    assert_false(decision, "portfolio_variant_adopted")
    assert_false(decision, "filter_adopted")
    assert_false(decision, "overlay_adoption_allowed")
    assert_false(decision, "portfolio_variant_adoption_allowed")
    assert_false(decision, "filter_adoption_allowed")
    assert_false(decision, "full_weight_result_available")
    assert_false(decision, "full_weight_rebacktest_allowed_now")
    assert_true(decision, "research_only")
    assert_true(decision, "observation_maturity_bridge_only")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)

    # 34-36. No recommendation language, imports, or online access.
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import|from)\s+yfinance\b", source, re.I | re.M)
    assert "requests." not in source.lower()
    assert "urlopen(" not in source.lower()
    assert "download(" not in source.lower()
    for name in OUTPUTS:
        text = (REV / name).read_text(encoding="utf-8", errors="ignore")
        assert not re.search(
            r"\b(?:BUY|SELL|HOLD)\s+(?:RECOMMENDATION|SIGNAL|ACTION)\b",
            text, re.I,
        ), f"recommendation language in {name}"

    # 37. Prohibited output roots.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R6" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 38. Existing files unchanged.
    assert before == {path: digest(path) for path in official}

    # 39. Report boundary.
    report = RC / "V21_047_R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE_REPORT.md"
    current = RC / "CURRENT_V21_047_R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only QQQ_MA50 observation bridge results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted." in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R6_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
