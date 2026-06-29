#!/usr/bin/env python
"""Formal checks for V21.047-R5 QQQ MA50 observation policy dry-run."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r5_qqq_ma50_observation_policy_dry_run.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r5_qqq_ma50_observation_policy_dry_run.ps1"
REV = ROOT / "outputs/v21/review"
LEDGER = ROOT / "outputs/v21/ledger/V21_047_R5_QQQ_MA50_OBSERVATION_LEDGER.csv"
RC = ROOT / "outputs/v21/read_center"
OUTPUTS = [
    "V21_047_R5_UPSTREAM_REVIEW_PACKET_VALIDATION.csv",
    "V21_047_R5_OBSERVATION_POLICY_DEFINITION.csv",
    "V21_047_R5_CURRENT_OBSERVATION_STATE_DRY_RUN.csv",
    "V21_047_R5_OBSERVATION_LEDGER_SCHEMA.csv",
    "V21_047_R5_OBSERVATION_APPEND_DRY_RUN_AUDIT.csv",
    "V21_047_R5_MONITOR_CONTRACT.csv",
    "V21_047_R5_NEXT_STAGE_ROUTING.csv",
    "V21_047_R5_SCOPE_BOUNDARY_AUDIT.csv",
    "V21_047_R5_DECISION_SUMMARY.csv",
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

    # 2. Parse wrapper.
    parse = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
            "scripts/v21/run_v21_047_r5_qqq_ma50_observation_policy_dry_run.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official = [
        REV / "V21_047_R4_DECISION_SUMMARY.csv",
        REV / "V21_047_R3C_DECISION_SUMMARY.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
        ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
    ]
    before = {path: digest(path) for path in official}
    ledger_before = read_rows(LEDGER) if LEDGER.exists() else []

    # 3. Execute wrapper; repeated execution must be duplicate-safe.
    run = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    for key in [
        "final_status=", "decision=", "corrected_primary_candidate=",
        "latest_QQQ_date=", "QQQ_MA50_state=", "dry_run_target_exposure=",
        "ledger_append_status=", "recommended_next_stage=",
        "overlay_adoption_allowed=", "official_adoption_allowed=",
        "shadow_gate_allowed=",
    ]:
        assert key in run.stdout

    rows = {name: read_rows(REV / name) for name in OUTPUTS}

    # 4. R4 outputs are read.
    upstream = rows["V21_047_R5_UPSTREAM_REVIEW_PACKET_VALIDATION.csv"]
    for name in [
        "r4_decision", "r4_upstream", "r4_profile", "r4_comparison",
        "r4_attribution", "r4_rule", "r4_behavior", "r4_cost",
        "r4_subperiod", "r4_downside",
    ]:
        assert any(
            row.get("input_name") == name and row.get("check_passed") == "TRUE"
            for row in upstream
        ), f"R4 input not read: {name}"

    # 5-11. Required outputs.
    policy = rows["V21_047_R5_OBSERVATION_POLICY_DEFINITION.csv"][0]
    state = rows["V21_047_R5_CURRENT_OBSERVATION_STATE_DRY_RUN.csv"][0]
    schema = rows["V21_047_R5_OBSERVATION_LEDGER_SCHEMA.csv"]
    append = rows["V21_047_R5_OBSERVATION_APPEND_DRY_RUN_AUDIT.csv"][0]
    monitor = rows["V21_047_R5_MONITOR_CONTRACT.csv"][0]
    decision = rows["V21_047_R5_DECISION_SUMMARY.csv"][0]
    assert upstream and policy and state and schema and append and monitor and decision

    # 12. Ledger exists when current state is available and remains unique.
    if state.get("qqq_ma50_state") != "DATA_LIMITED":
        ledger = read_rows(LEDGER)
        keys = [(row.get("observation_date"), row.get("policy_id")) for row in ledger]
        assert len(keys) == len(set(keys)), "duplicate observation ledger key"
        assert len(ledger) in {len(ledger_before), len(ledger_before) + 1}
        assert append.get("ledger_append_status") in {
            "APPENDED_NEW_OBSERVATION", "DUPLICATE_SKIPPED"
        }

    # 13-16. Corrected identity, repaired turnover, observation-only.
    assert decision.get("corrected_primary_overlay") == "QQQ_MA50_RISK_OFF_SCALE"
    assert decision.get("valid_turnover_reduction") == "0.0000000000"
    assert_true(decision, "unsupported_turnover_claim_removed")
    assert_true(decision, "overlay_observation_enabled")
    assert_false(decision, "overlay_adoption_allowed")
    assert policy.get("observation_enabled") == "TRUE"
    assert policy.get("adoption_enabled") == "FALSE"

    # 17-34. No adoption and guardrails.
    assert_false(decision, "overlay_adopted")
    assert_false(decision, "portfolio_variant_adopted")
    assert_false(decision, "filter_adopted")
    assert_false(decision, "overlay_adoption_allowed")
    assert_false(decision, "portfolio_variant_adoption_allowed")
    assert_false(decision, "filter_adoption_allowed")
    assert_false(decision, "full_weight_result_available")
    assert_false(decision, "full_weight_rebacktest_allowed_now")
    assert_true(decision, "research_only")
    assert_true(decision, "observation_policy_dry_run_only")
    for key in [
        "official_adoption_allowed", "official_weight_mutation",
        "official_ranking_mutation", "official_recommendation_allowed",
        "real_book_action_allowed", "broker_execution_allowed",
        "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)

    # 35-37. No recommendation language, yfinance, or downloads.
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

    # 38. No prohibited paths.
    for root in [
        ROOT / "outputs/v22", ROOT / "outputs/v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action",
        ROOT / "official-recommendation", ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R5" in path.name
            ]
            assert not touched, f"forbidden output: {touched}"

    # 39. Existing upstream/official files unchanged.
    assert before == {path: digest(path) for path in official}

    # 40. Report boundary.
    report = RC / "V21_047_R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN_REPORT.md"
    current = RC / "CURRENT_V21_047_R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN_REPORT.md"
    text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == text
    assert (
        "Technical-only QQQ_MA50 observation policy results must not be interpreted "
        "as full-weight results" in text
    )
    assert "No overlay was adopted." in text
    assert "No portfolio variant was adopted." in text
    assert "Full-weight remains blocked: TRUE" in text

    print("V21_047_R5_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
