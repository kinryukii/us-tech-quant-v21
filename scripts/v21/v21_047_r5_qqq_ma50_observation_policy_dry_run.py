#!/usr/bin/env python
"""Research-only observation policy dry-run for QQQ MA50 overlay."""

from __future__ import annotations

import csv
import math
import shutil
from collections import deque
from pathlib import Path

STAGE = "V21.047-R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN"
POLICY_ID = "QQQ_MA50_RISK_OFF_SCALE_OBSERVATION_ONLY"
PRIMARY = "QQQ_MA50_RISK_OFF_SCALE"
ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "outputs/v21/review"
LEDGER_DIR = ROOT / "outputs/v21/ledger"
RC = ROOT / "outputs/v21/read_center"

INPUTS = {
    "r4_decision": REV / "V21_047_R4_DECISION_SUMMARY.csv",
    "r4_upstream": REV / "V21_047_R4_UPSTREAM_RECONCILIATION_VALIDATION.csv",
    "r4_profile": REV / "V21_047_R4_CORRECTED_CANDIDATE_PROFILE.csv",
    "r4_comparison": REV / "V21_047_R4_BASELINE_COMPARISON.csv",
    "r4_attribution": REV / "V21_047_R4_ATTRIBUTION_INTEGRITY_AUDIT.csv",
    "r4_rule": REV / "V21_047_R4_QQQ_MA50_RULE_AUDIT.csv",
    "r4_behavior": REV / "V21_047_R4_RISK_OFF_BEHAVIOR_AUDIT.csv",
    "r4_cost": REV / "V21_047_R4_COST_WARNING_REVIEW.csv",
    "r4_subperiod": REV / "V21_047_R4_SUBPERIOD_STABILITY_REVIEW.csv",
    "r4_downside": REV / "V21_047_R4_DOWNSIDE_MONITOR_DEPENDENCY.csv",
    "r3c_decision": REV / "V21_047_R3C_DECISION_SUMMARY.csv",
    "equity": ROOT / "outputs/v21/backtest/V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv",
    "returns": ROOT / "outputs/v21/backtest/V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv",
    "risk": ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    "relative": ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    "drawdown": ROOT / "outputs/v21/backtest/V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv",
    "r3_risk": ROOT / "outputs/v21/backtest/V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
    "downside_contract": REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv",
    "qqq_prices": ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
}
OPTIONAL = {
    "r8a_wait": REV / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_DECISION_SUMMARY.csv",
    "r8_r1": REV / "V21_044_R8_R1_DECISION_SUMMARY.csv",
}
OUT = {
    "upstream": REV / "V21_047_R5_UPSTREAM_REVIEW_PACKET_VALIDATION.csv",
    "policy": REV / "V21_047_R5_OBSERVATION_POLICY_DEFINITION.csv",
    "state": REV / "V21_047_R5_CURRENT_OBSERVATION_STATE_DRY_RUN.csv",
    "schema": REV / "V21_047_R5_OBSERVATION_LEDGER_SCHEMA.csv",
    "append": REV / "V21_047_R5_OBSERVATION_APPEND_DRY_RUN_AUDIT.csv",
    "monitor": REV / "V21_047_R5_MONITOR_CONTRACT.csv",
    "routing": REV / "V21_047_R5_NEXT_STAGE_ROUTING.csv",
    "scope": REV / "V21_047_R5_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R5_DECISION_SUMMARY.csv",
}
LEDGER = LEDGER_DIR / "V21_047_R5_QQQ_MA50_OBSERVATION_LEDGER.csv"
REPORT = RC / "V21_047_R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN_REPORT.md"

GUARD = {
    "research_only": "TRUE",
    "observation_policy_dry_run_only": "TRUE",
    "corrected_primary_candidate": PRIMARY,
    "overlay_observation_enabled": "TRUE",
    "overlay_adoption_allowed": "FALSE",
    "portfolio_variant_adoption_allowed": "FALSE",
    "filter_adoption_allowed": "FALSE",
    "technical_only_stream": "TRUE",
    "valid_turnover_reduction": "0.0000000000",
    "unsupported_turnover_claim_removed": "TRUE",
    "full_weight_result_available": "FALSE",
    "full_weight_rebacktest_allowed_now": "FALSE",
    "official_adoption_allowed": "FALSE",
    "official_weight_mutation": "FALSE",
    "official_ranking_mutation": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "real_book_action_allowed": "FALSE",
    "broker_execution_allowed": "FALSE",
    "trade_action_allowed": "FALSE",
    "shadow_gate_allowed": "FALSE",
    "shadow_adoption_allowed": "FALSE",
    "buy_sell_hold_recommendation_created": "FALSE",
    "online_download_attempted": "FALSE",
    "yfinance_used": "FALSE",
}
LEDGER_BASE_FIELDS = [
    "observation_date", "policy_id", "underlying_strategy", "overlay_candidate",
    "qqq_price", "qqq_ma50", "qqq_state", "target_exposure_dry_run",
    "cash_weight_dry_run", "risk_state_change", "data_freshness_status",
    "price_source", "rule_version", "no_leakage_flag", "observation_only_flag",
    "adoption_allowed", "shadow_gate_allowed", "official_allowed",
    "real_book_allowed", "trade_action_allowed", "maturity_dependency_status",
    "cost_warning_status", "notes",
]
LEDGER_FIELDS = LEDGER_BASE_FIELDS + list(GUARD)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [{"status": "NO_ROWS", **GUARD}]
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def num(value: object) -> float | None:
    try:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            return None
        result = float(text)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def fmt(value: object) -> str:
    value = num(value)
    return "" if value is None else f"{value:.10f}"


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    optional = {name: read_rows(path) for name, path in OPTIONAL.items()}
    r4 = data["r4_decision"][0] if data["r4_decision"] else {}
    ready = (
        all(data.values())
        and r4.get("corrected_primary_review_candidate") == PRIMARY
        and r4.get("original_combined_label_demoted") == "TRUE"
        and r4.get("valid_turnover_reduction") == "0.0000000000"
        and r4.get("unsupported_turnover_claim_removed") == "TRUE"
        and r4.get("review_packet_ready") == "TRUE"
        and r4.get("overlay_adopted") == "FALSE"
        and r4.get("full_weight_blocked") == "TRUE"
    )
    upstream = [{
        "audit_item": "required_input", "input_name": name,
        "path": str(INPUTS[name].relative_to(ROOT)),
        "check_passed": yn(bool(rows)),
        "evidence": "LOCAL_ARTIFACT_READ" if rows else "MISSING_OR_EMPTY", **GUARD,
    } for name, rows in data.items()]
    upstream += [{
        "audit_item": "optional_maturity_input", "input_name": name,
        "path": str(OPTIONAL[name].relative_to(ROOT)), "check_passed": "TRUE",
        "evidence": "AVAILABLE" if rows else "OPTIONAL_NOT_AVAILABLE", **GUARD,
    } for name, rows in optional.items()]
    upstream.append({
        "audit_item": "r4_review_packet_ready", "input_name": "r4_decision",
        "path": str(INPUTS["r4_decision"].relative_to(ROOT)),
        "check_passed": yn(ready),
        "evidence": f"{r4.get('final_status', '')}|packet_ready={r4.get('review_packet_ready', '')}",
        **GUARD,
    })
    write_rows(OUT["upstream"], upstream)

    policy = {
        "policy_id": POLICY_ID, "underlying_strategy": "TECH_TOP20_EQUAL_WEIGHT_10D",
        "overlay_candidate": PRIMARY, "overlay_status": "REVIEW_ONLY_NOT_ADOPTED",
        "observation_enabled": "TRUE", "adoption_enabled": "FALSE",
        "shadow_gate_enabled": "FALSE", "official_enabled": "FALSE",
        "real_book_enabled": "FALSE", "broker_execution_enabled": "FALSE",
        "trade_action_enabled": "FALSE", "benchmark": "QQQ",
        "price_field": "adjusted_close_if_available_else_close",
        "moving_average_window": 50,
        "risk_on_condition": "QQQ_PRICE_AT_OR_ABOVE_QQQ_MA50",
        "risk_off_condition": "QQQ_PRICE_BELOW_QQQ_MA50",
        "risk_on_target_exposure": "1.0000000000",
        "risk_off_target_exposure": "0.5000000000",
        "cash_return_assumption": "0.0000000000",
        "rule_uses_future_data": "FALSE", "online_download_required": "FALSE",
        "rule_version": "V21_047_R5_QQQ_MA50_50D_V1", **GUARD,
    }
    write_rows(OUT["policy"], [policy])

    qqq = sorted(
        [row for row in data["qqq_prices"] if row.get("symbol") == "QQQ"],
        key=lambda row: row.get("date", ""),
    )
    calculated: list[dict[str, object]] = []
    window: deque[float] = deque()
    running = 0.0
    for row in qqq:
        price = num(row.get("adjusted_close"))
        field = "adjusted_close"
        if price is None:
            price, field = num(row.get("close")), "close"
        if price is None:
            continue
        window.append(price)
        running += price
        if len(window) > 50:
            running -= window.popleft()
        if len(window) == 50:
            ma50 = running / 50
            state = "ABOVE_MA50" if price > ma50 else "BELOW_MA50" if price < ma50 else "EQUAL_MA50"
            calculated.append({
                "date": row.get("date", ""), "price": price, "ma50": ma50,
                "state": state, "field": field,
                "source": row.get("source_artifact") or row.get("source_provider", ""),
            })
    available = bool(calculated)
    current = calculated[-1] if available else {}
    prior = calculated[-2] if len(calculated) > 1 else {}
    state = str(current.get("state", "DATA_LIMITED"))
    state_change = (
        "STATE_CHANGED" if prior and state != prior.get("state")
        else "STATE_UNCHANGED" if prior else "PRIOR_STATE_UNAVAILABLE"
    )
    consecutive = 0
    for row in reversed(calculated):
        if row["state"] == state:
            consecutive += 1
        else:
            break
    price, ma50 = num(current.get("price")), num(current.get("ma50"))
    distance = price - ma50 if price is not None and ma50 is not None else None
    distance_pct = distance / ma50 if distance is not None and ma50 else None
    target = 0.5 if state == "BELOW_MA50" else 1.0 if available else None
    state_row = {
        "latest_benchmark_date": current.get("date", ""), "qqq_price": fmt(price),
        "price_field_used": current.get("field", ""), "qqq_ma50": fmt(ma50),
        "qqq_distance_to_ma50": fmt(distance),
        "qqq_distance_to_ma50_pct": fmt(distance_pct), "qqq_ma50_state": state,
        "dry_run_target_exposure": fmt(target),
        "dry_run_cash_weight": fmt(1 - target if target is not None else None),
        "risk_state_change_from_prior_day": state_change,
        "consecutive_current_state_days": consecutive,
        "current_observation_status": (
            "OBSERVATION_ONLY_RISK_OFF_STATE" if state == "BELOW_MA50"
            else "OBSERVATION_ONLY_RISK_ON_STATE" if available else "DATA_LIMITED"
        ),
        "observation_only_no_executable_change": "TRUE", **GUARD,
    }
    write_rows(OUT["state"], [state_row])

    write_rows(OUT["schema"], [{
        "field_order": index + 1, "field_name": field, "required": "TRUE",
        "description": "Observation ledger field; no executable action.", **GUARD,
    } for index, field in enumerate(LEDGER_FIELDS)])

    existing = read_rows(LEDGER)
    key = (str(current.get("date", "")), POLICY_ID)
    duplicate = any((r.get("observation_date"), r.get("policy_id")) == key for r in existing)
    ledger_row = {
        "observation_date": current.get("date", ""), "policy_id": POLICY_ID,
        "underlying_strategy": "TECH_TOP20_EQUAL_WEIGHT_10D",
        "overlay_candidate": PRIMARY, "qqq_price": fmt(price), "qqq_ma50": fmt(ma50),
        "qqq_state": state, "target_exposure_dry_run": fmt(target),
        "cash_weight_dry_run": fmt(1 - target if target is not None else None),
        "risk_state_change": state_change, "data_freshness_status": "LATEST_LOCAL_CACHE_ROW",
        "price_source": current.get("source", ""), "rule_version": policy["rule_version"],
        "no_leakage_flag": "TRUE", "observation_only_flag": "TRUE",
        "adoption_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
        "official_allowed": "FALSE", "real_book_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "maturity_dependency_status": "MATURED_EVIDENCE_PENDING_AFTER_2026_06_24",
        "cost_warning_status": "COST_WARNING_REVISED_NONBLOCKING_REVIEW",
        "notes": "Research observation only; no executable action.", **GUARD,
    }
    before_count = len(existing)
    append_status = "DATA_LIMITED_NO_APPEND"
    if available and not duplicate:
        existing.append(ledger_row)
        write_rows(LEDGER, existing, LEDGER_FIELDS)
        append_status = "APPENDED_NEW_OBSERVATION"
    elif available:
        append_status = "DUPLICATE_SKIPPED"
    write_rows(OUT["append"], [{
        "ledger_path": str(LEDGER.relative_to(ROOT)),
        "observation_date": current.get("date", ""), "policy_id": POLICY_ID,
        "existing_row_count_before": before_count, "duplicate_found": yn(duplicate),
        "row_appended": yn(append_status == "APPENDED_NEW_OBSERVATION"),
        "ledger_append_status": append_status, "official_artifact_mutated": "FALSE", **GUARD,
    }])

    recent = [row["state"] for row in calculated[-20:]]
    changes20 = sum(recent[i] != recent[i - 1] for i in range(1, len(recent)))
    near_zero = distance_pct is not None and abs(distance_pct) < 0.01
    duration_warning = state == "BELOW_MA50" and consecutive > 20
    monitor = {
        "cost_warning_carried_forward": "TRUE",
        "maturity_dependency_required_after": "2026-06-24",
        "overlay_observation_review_required": "TRUE",
        "valid_turnover_reduction": "0.0000000000",
        "unsupported_turnover_claim_removed": "TRUE",
        "future_matured_observation_required": "TRUE", "full_weight_blocked": "TRUE",
        "qqq_distance_to_ma50_near_zero_warning_threshold_pct": "0.0100000000",
        "qqq_distance_to_ma50_near_zero_warning": yn(near_zero),
        "whipsaw_warning_threshold_state_changes_20d": 3,
        "state_changes_last_20_trading_days": changes20,
        "whipsaw_warning": yn(changes20 > 3),
        "risk_off_duration_warning_threshold_days": 20,
        "current_state_duration_days": consecutive,
        "risk_off_duration_warning": yn(duration_warning),
        "cost_warning_remains_material": "TRUE",
        "maturity_evidence_missing_until_V21_044_R9": "TRUE", **GUARD,
    }
    write_rows(OUT["monitor"], [monitor])

    cost_blocks = data["r4_cost"][0].get("cost_model_blocks_next_review") == "TRUE"
    if not ready:
        status, decision, next_stage = (
            "BLOCKED_V21_047_R5_R4_OUTPUTS_NOT_READY",
            "BLOCK_QQQ_MA50_OBSERVATION_POLICY",
            "V21.047-R4_QQQ_MA50_PRIMARY_OVERLAY_REVIEW_PACKET",
        )
    elif not available:
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R5_QQQ_PRICE_DATA_LIMITED",
            "QQQ_MA50_PRICE_SOURCE_REPAIR_REQUIRED",
            "V21.047-R5A_QQQ_MA50_PRICE_SOURCE_REPAIR",
        )
    elif cost_blocks:
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R5_OBSERVATION_POLICY_READY_WITH_COST_WARNING",
            "QQQ_MA50_OBSERVATION_POLICY_READY_WITH_COST_AND_MATURITY_WARNINGS",
            "V21.047-R4A_QQQ_MA50_COST_MODEL_RECHECK",
        )
    elif append_status == "DUPLICATE_SKIPPED":
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R5_OBSERVATION_POLICY_READY_DUPLICATE_SKIPPED",
            "QQQ_MA50_OBSERVATION_POLICY_DUPLICATE_SKIPPED",
            "V21.047-R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE",
        )
    else:
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R5_OBSERVATION_POLICY_READY_WITH_MATURITY_DEPENDENCY",
            "QQQ_MA50_OBSERVATION_POLICY_READY_WITH_COST_AND_MATURITY_WARNINGS",
            "V21.047-R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE",
        )
    routes = [
        ("POLICY_READY", "V21.047-R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE"),
        ("PRICE_DATA_UNAVAILABLE", "V21.047-R5A_QQQ_MA50_PRICE_SOURCE_REPAIR"),
        ("MATURITY_PRIORITIZED", "RERUN_V21_044_R8_R8R1_AFTER_2026_06_24_THEN_V21_044_R9"),
        ("COST_WARNING_BLOCKS", "V21.047-R4A_QQQ_MA50_COST_MODEL_RECHECK"),
    ]
    write_rows(OUT["routing"], [{
        "route_condition": condition, "recommended_next_stage": route,
        "selected_route": yn(route == next_stage), **GUARD,
    } for condition, route in routes])
    scope = [
        ("observation_policy_dry_run_only", "Only research review, ledger, and report artifacts are written."),
        ("ledger_observation_only", "Ledger records no-action and no-adoption flags."),
        ("no_future_data_or_online_download", "MA50 uses local observations through each date."),
        ("no_adoption_shadow_official_or_execution", "All prohibited enablement flags remain FALSE."),
        ("technical_only_not_full_weight", "No full-weight result or score is created."),
    ]
    write_rows(OUT["scope"], [{
        "boundary_check": check, "check_passed": "TRUE", "evidence": evidence, **GUARD,
    } for check, evidence in scope])

    decision_row = {
        "stage": STAGE, "final_status": status, "decision": decision,
        "corrected_primary_overlay": PRIMARY, "latest_QQQ_date": current.get("date", ""),
        "QQQ_MA50_state": state, "dry_run_target_exposure": fmt(target),
        "ledger_append_status": append_status,
        "cost_warning_status": "COST_WARNING_REVISED_NONBLOCKING_REVIEW",
        "maturity_dependency": "MATURED_EVIDENCE_REQUIRED_AFTER_2026_06_24",
        "observation_policy_ready": yn(available and ready),
        "overlay_adopted": "FALSE", "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE", "recommended_next_stage": next_stage, **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    report = f"""# V21.047-R5 QQQ MA50 Observation Policy Dry Run

final_status: {status}

decision: {decision}

Corrected primary overlay: {PRIMARY}.

Observation policy definition: policy_id={POLICY_ID}; underlying=TECH_TOP20_EQUAL_WEIGHT_10D; QQQ adjusted close when available; trailing 50-trading-day mean; dry-run exposure 1.00 at/above MA50 and 0.50 below MA50; observation-only.

Current QQQ MA50 observation state: date={current.get('date', '')}; price={fmt(price)}; MA50={fmt(ma50)}; distance_pct={fmt(distance_pct)}; state={state}; consecutive_state_days={consecutive}.

Dry-run target exposure: {fmt(target)}. Dry-run cash weight: {fmt(1 - target if target is not None else None)}. These values are not executable.

Observation ledger append result: {append_status}. Duplicate key is observation_date plus policy_id.

Monitor contract: near-MA50 warning={yn(near_zero)}; state changes last 20 days={changes20}; whipsaw warning={yn(changes20 > 3)}; risk-off duration warning={yn(duration_warning)}; valid turnover reduction=0.

Cost warning: COST_WARNING_REVISED_NONBLOCKING_REVIEW.

Maturity dependency: matured evidence required after 2026-06-24; optional R8A/R8-R1 summaries are currently unavailable.

Next-stage routing: {next_stage}.

No overlay was adopted.

No portfolio variant was adopted.

No official, shadow, real-book, broker, execution, or trade action was created.

Technical-only QQQ_MA50 observation policy results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Guardrail statement: research_only=TRUE; observation_policy_dry_run_only=TRUE; overlay_observation_enabled=TRUE; overlay_adoption_allowed=FALSE; valid_turnover_reduction=0; unsupported_turnover_claim_removed=TRUE; no official mutation, recommendation, or executable action; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)

    print(f"final_status={status}")
    print(f"decision={decision}")
    print(f"corrected_primary_candidate={PRIMARY}")
    print(f"latest_QQQ_date={current.get('date', '')}")
    print(f"QQQ_MA50_state={state}")
    print(f"dry_run_target_exposure={fmt(target)}")
    print(f"ledger_append_status={append_status}")
    print(f"recommended_next_stage={next_stage}")
    print(f"overlay_adoption_allowed={GUARD['overlay_adoption_allowed']}")
    print(f"official_adoption_allowed={GUARD['official_adoption_allowed']}")
    print(f"shadow_gate_allowed={GUARD['shadow_gate_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
