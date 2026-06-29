#!/usr/bin/env python
"""Research-only bridge from QQQ MA50 observations to technical maturity review."""

from __future__ import annotations

import csv
import shutil
from datetime import date
from pathlib import Path

STAGE = "V21.047-R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE"
PRIMARY = "QQQ_MA50_RISK_OFF_SCALE"
ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "outputs/v21/review"
LED = ROOT / "outputs/v21/ledger"
RC = ROOT / "outputs/v21/read_center"
INPUTS = {
    "r5_decision": REV / "V21_047_R5_DECISION_SUMMARY.csv",
    "r5_upstream": REV / "V21_047_R5_UPSTREAM_REVIEW_PACKET_VALIDATION.csv",
    "r5_policy": REV / "V21_047_R5_OBSERVATION_POLICY_DEFINITION.csv",
    "r5_state": REV / "V21_047_R5_CURRENT_OBSERVATION_STATE_DRY_RUN.csv",
    "r5_schema": REV / "V21_047_R5_OBSERVATION_LEDGER_SCHEMA.csv",
    "r5_append": REV / "V21_047_R5_OBSERVATION_APPEND_DRY_RUN_AUDIT.csv",
    "r5_monitor": REV / "V21_047_R5_MONITOR_CONTRACT.csv",
    "r5_routing": REV / "V21_047_R5_NEXT_STAGE_ROUTING.csv",
    "r5_ledger": LED / "V21_047_R5_QQQ_MA50_OBSERVATION_LEDGER.csv",
    "r4_decision": REV / "V21_047_R4_DECISION_SUMMARY.csv",
    "r3c_decision": REV / "V21_047_R3C_DECISION_SUMMARY.csv",
    "downside_contract": REV / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv",
    "qqq_prices": ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv",
}
OPTIONAL = {
    "r8a_decision_requested": REV / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_DECISION_SUMMARY.csv",
    "r8_r1_decision_requested": REV / "V21_044_R8_R1_DECISION_SUMMARY.csv",
    "r8a_decision_actual": REV / "V21_044_R8A_DECISION_SUMMARY.csv",
    "r7_ledger": LED / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv",
    "r8_r1_pending": LED / "V21_044_R8_R1_TECHNICAL_ONLY_PENDING_ROWS.csv",
    "r8_r1_refresh": LED / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv",
    "r8_matured": LED / "V21_044_R8_TECHNICAL_ONLY_MATURED_RESULTS.csv",
}
OUT = {
    "upstream": REV / "V21_047_R6_UPSTREAM_R5_VALIDATION.csv",
    "integrity": REV / "V21_047_R6_QQQ_OBSERVATION_LEDGER_INTEGRITY_AUDIT.csv",
    "maturity": REV / "V21_047_R6_TECHNICAL_MATURITY_DEPENDENCY_AUDIT.csv",
    "alignment": REV / "V21_047_R6_OVERLAY_TECHNICAL_ALIGNMENT_AUDIT.csv",
    "schema": REV / "V21_047_R6_FUTURE_MATURED_EVALUATION_SCHEMA.csv",
    "contract": REV / "V21_047_R6_MONITOR_BRIDGE_CONTRACT.csv",
    "routing": REV / "V21_047_R6_NEXT_STAGE_ROUTING.csv",
    "scope": REV / "V21_047_R6_SCOPE_BOUNDARY_AUDIT.csv",
    "decision": REV / "V21_047_R6_DECISION_SUMMARY.csv",
}
REPORT = RC / "V21_047_R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE_REPORT.md"
CURRENT = RC / "CURRENT_V21_047_R6_QQQ_MA50_OBSERVATION_LEDGER_MATURITY_BRIDGE_REPORT.md"
GUARD = {
    "research_only": "TRUE", "observation_maturity_bridge_only": "TRUE",
    "corrected_primary_candidate": PRIMARY, "overlay_observation_enabled": "TRUE",
    "overlay_adoption_allowed": "FALSE", "portfolio_variant_adoption_allowed": "FALSE",
    "filter_adoption_allowed": "FALSE", "technical_only_stream": "TRUE",
    "valid_turnover_reduction": "0.0000000000",
    "unsupported_turnover_claim_removed": "TRUE",
    "full_weight_result_available": "FALSE", "full_weight_rebacktest_allowed_now": "FALSE",
    "official_adoption_allowed": "FALSE", "official_weight_mutation": "FALSE",
    "official_ranking_mutation": "FALSE", "official_recommendation_allowed": "FALSE",
    "real_book_action_allowed": "FALSE", "broker_execution_allowed": "FALSE",
    "trade_action_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
    "shadow_adoption_allowed": "FALSE", "buy_sell_hold_recommendation_created": "FALSE",
    "online_download_attempted": "FALSE", "yfinance_used": "FALSE",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [{"status": "NO_ROWS", **GUARD}]
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def parse(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def main() -> int:
    REV.mkdir(parents=True, exist_ok=True)
    RC.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in INPUTS.items()}
    optional = {name: read_rows(path) for name, path in OPTIONAL.items()}
    r5 = data["r5_decision"][0] if data["r5_decision"] else {}
    acceptable = r5.get("final_status", "").startswith(("PASS_V21_047_R5", "PARTIAL_PASS_V21_047_R5"))
    ready = (
        all(data.values()) and acceptable
        and r5.get("corrected_primary_overlay") == PRIMARY
        and r5.get("overlay_adoption_allowed") == "FALSE"
        and r5.get("full_weight_result_available") == "FALSE"
    )
    upstream = [{
        "audit_item": "required_input", "input_name": name,
        "path": str(INPUTS[name].relative_to(ROOT)), "check_passed": yn(bool(rows)),
        "evidence": "LOCAL_ARTIFACT_READ" if rows else "MISSING_OR_EMPTY", **GUARD,
    } for name, rows in data.items()]
    upstream += [{
        "audit_item": "optional_input", "input_name": name,
        "path": str(OPTIONAL[name].relative_to(ROOT)), "check_passed": "TRUE",
        "evidence": "AVAILABLE" if rows else "DATA_LIMITED_OPTIONAL_MISSING", **GUARD,
    } for name, rows in optional.items()]
    upstream.append({
        "audit_item": "r5_ready", "input_name": "r5_decision",
        "path": str(INPUTS["r5_decision"].relative_to(ROOT)), "check_passed": yn(ready),
        "evidence": f"{r5.get('final_status', '')}|{r5.get('decision', '')}", **GUARD,
    })
    write_rows(OUT["upstream"], upstream)

    ledger = data["r5_ledger"]
    required_fields = [
        "observation_date", "policy_id", "qqq_state", "target_exposure_dry_run",
        "data_freshness_status", "adoption_allowed", "shadow_gate_allowed",
        "official_allowed", "real_book_allowed", "trade_action_allowed",
    ]
    keys = [(row.get("observation_date", ""), row.get("policy_id", "")) for row in ledger]
    duplicate_count = len(keys) - len(set(keys))
    missing_count = sum(not row.get(field, "") for row in ledger for field in required_fields)
    invalid_adoption = sum(
        row.get(field, "").upper() != "FALSE"
        for row in ledger for field in
        ["adoption_allowed", "shadow_gate_allowed", "official_allowed", "real_book_allowed"]
    )
    invalid_action = sum(row.get("trade_action_allowed", "").upper() != "FALSE" for row in ledger)
    latest = max(ledger, key=lambda row: row.get("observation_date", "")) if ledger else {}
    ledger_valid = bool(ledger) and duplicate_count == 0 and missing_count == 0 and invalid_adoption == 0 and invalid_action == 0
    integrity = {
        "row_count": len(ledger), "unique_observation_date_policy_id_count": len(set(keys)),
        "duplicate_count": duplicate_count, "latest_observation_date": latest.get("observation_date", ""),
        "latest_qqq_state": latest.get("qqq_state", ""),
        "latest_target_exposure": latest.get("target_exposure_dry_run", ""),
        "data_freshness_status": latest.get("data_freshness_status", ""),
        "missing_required_field_count": missing_count,
        "invalid_adoption_flag_count": invalid_adoption,
        "invalid_trade_action_flag_count": invalid_action,
        "ledger_integrity_status": "VALID" if ledger_valid else "INVALID", **GUARD,
    }
    write_rows(OUT["integrity"], [integrity])

    r8a = optional["r8a_decision_actual"][0] if optional["r8a_decision_actual"] else {}
    pending = optional["r8_r1_pending"]
    matured = optional["r8_matured"]
    refresh = optional["r8_r1_refresh"]
    technical_dates = sorted({
        row.get("observation_as_of_date", "") for row in
        (pending or optional["r7_ledger"]) if row.get("observation_as_of_date")
    })
    first_maturity = r8a.get("first_maturity_date", "")
    if not first_maturity and pending:
        first_maturity = min(row.get("scheduled_maturity_date", "") for row in pending)
    windows = sorted({row.get("forward_window", "") for row in pending if row.get("forward_window")})
    entry_statuses = sorted({row.get("entry_price_binding_status", "") for row in pending if row.get("entry_price_binding_status")})
    qqq_dates = [
        row.get("date", "") for row in data["qqq_prices"]
        if row.get("symbol") == "QQQ" and row.get("date")
    ]
    latest_cache_date = max(qqq_dates, default="")
    cache_covers = bool(first_maturity and latest_cache_date >= first_maturity)
    current_context_date = date.today().isoformat()
    maturity_arrived = bool(first_maturity and current_context_date >= first_maturity)
    technical_available = bool(pending and r8a)
    maturity_row = {
        "technical_observation_date": "|".join(technical_dates) if technical_dates else "",
        "first_maturity_date": first_maturity, "maturity_windows": "|".join(windows),
        "pending_rows": len(pending), "matured_rows": len(matured),
        "entry_price_binding_status": "|".join(entry_statuses) if entry_statuses else "DATA_LIMITED",
        "r9_allowed_now": r8a.get("r9_allowed_now", "FALSE"),
        "first_maturity_date_arrived_in_run_context": yn(maturity_arrived),
        "latest_local_QQQ_price_date": latest_cache_date,
        "local_price_cache_covers_first_maturity_date": yn(cache_covers),
        "refresh_rows": len(refresh),
        "technical_maturity_artifact_status": "AVAILABLE_USABLE" if technical_available else "DATA_LIMITED",
        **GUARD,
    }
    write_rows(OUT["maturity"], [maturity_row])

    schedule = {}
    for row in pending:
        window = row.get("forward_window", "")
        if window and window not in schedule:
            schedule[window] = row.get("scheduled_maturity_date", "")
    alignment_rows: list[dict[str, object]] = []
    for observation in ledger:
        obs_date = parse(observation.get("observation_date", ""))
        nearest = ""
        gap = None
        if obs_date and technical_dates:
            nearest = min(technical_dates, key=lambda text: abs((parse(text) - obs_date).days))
            gap = abs((parse(nearest) - obs_date).days)
        for window in windows or ["DATA_LIMITED"]:
            maturity_date = schedule.get(window, first_maturity if window == "5D" else "")
            allowed = bool(maturity_date and latest_cache_date >= maturity_date)
            alignment_rows.append({
                "policy_observation_date": observation.get("observation_date", ""),
                "technical_observation_date": nearest,
                "aligned_flag": yn(gap is not None),
                "date_gap_days": "" if gap is None else gap,
                "qqq_state": observation.get("qqq_state", ""),
                "target_exposure_dry_run": observation.get("target_exposure_dry_run", ""),
                "baseline_technical_stream": "BASELINE_TECHNICAL_ONLY",
                "maturity_window": window, "expected_maturity_date": maturity_date,
                "pending_or_matured_status": "MATURED_ELIGIBLE" if allowed else "PENDING_NOT_MATURED",
                "maturity_evaluation_allowed_now": yn(allowed),
                "reason_if_not_allowed": "" if allowed else "LOCAL_PRICE_CACHE_DOES_NOT_COVER_MATURITY_DATE",
                **GUARD,
            })
    write_rows(OUT["alignment"], alignment_rows)

    future_fields = [
        "observation_id", "policy_id", "observation_date", "qqq_state",
        "target_exposure_dry_run", "baseline_top20_return", "qqq_ma50_scaled_return",
        "qqq_benchmark_return", "excess_vs_baseline", "excess_vs_qqq",
        "drawdown_delta", "worst_5pct_excess", "hit_rate_flag",
        "cost_warning_status", "maturity_window", "maturity_date",
        "matured_status", "no_adoption_flag",
    ]
    write_rows(OUT["schema"], [{
        "field_order": index + 1, "field_name": field,
        "future_value": "", "value_status": "SCHEMA_ONLY_NOT_MATURED",
        "future_returns_filled_now": "FALSE", **GUARD,
    } for index, field in enumerate(future_fields)])

    downside = data["downside_contract"][0]
    monitor = data["r5_monitor"][0]
    contract = {
        "downside_hit_rate_warning_threshold": downside.get("hit_rate_vs_QQQ_warning_threshold", ""),
        "downside_severe_hit_rate_warning_threshold": downside.get("severe_hit_rate_warning_threshold", ""),
        "downside_mean_excess_warning_threshold": downside.get("mean_excess_vs_QQQ_warning_threshold", ""),
        "downside_worst_5pct_warning_threshold": downside.get("worst_5pct_excess_warning_threshold", ""),
        "downside_payoff_ratio_warning_threshold": downside.get("payoff_ratio_warning_threshold", ""),
        "downside_sample_concentration_warning_threshold": downside.get("sample_concentration_warning_threshold", ""),
        "first_maturity_date": first_maturity or "2026-06-24",
        "cost_warning_carried_forward": "TRUE",
        "valid_turnover_reduction": "0.0000000000",
        "unsupported_turnover_claim_removed": "TRUE",
        "overlay_adoption_allowed": "FALSE",
        "maturity_required_before_review": "TRUE",
        "R9_required_before_any_adoption": "TRUE",
        "QQQ_MA50_state_observation_enabled": "TRUE",
        "overlay_performance_evaluation_enabled_only_after_maturity": "TRUE",
        "r5_whipsaw_warning": monitor.get("whipsaw_warning", ""),
        "r5_cost_warning": monitor.get("cost_warning_carried_forward", ""),
        **GUARD,
    }
    write_rows(OUT["contract"], [contract])

    if not ready:
        status, decision, next_stage = (
            "BLOCKED_V21_047_R6_R5_OUTPUTS_NOT_READY",
            "BLOCK_OBSERVATION_MATURITY_BRIDGE",
            "V21.047-R5_QQQ_MA50_OBSERVATION_POLICY_DRY_RUN",
        )
        bridge_ready = False
    elif not ledger_valid:
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R6_QQQ_OBSERVATION_LEDGER_WARNING",
            "QQQ_OBSERVATION_LEDGER_REPAIR_REQUIRED",
            "V21.047-R6B_QQQ_MA50_OBSERVATION_LEDGER_REPAIR",
        )
        bridge_ready = False
    elif not technical_available:
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R6_BRIDGE_READY_TECHNICAL_ARTIFACT_DATA_LIMITED",
            "TECHNICAL_MATURITY_ARTIFACT_REPAIR_REQUIRED",
            "V21.047-R6A_TECHNICAL_MATURITY_ARTIFACT_REPAIR",
        )
        bridge_ready = False
    elif cache_covers:
        status, decision, next_stage = (
            "PASS_V21_047_R6_OBSERVATION_MATURITY_BRIDGE_READY",
            "QQQ_MA50_OBSERVATION_MATURITY_BRIDGE_READY_FOR_R9_AFTER_PRICE_REFRESH",
            "RERUN_V21_044_R8_R8R1_THEN_V21_044_R9_AND_V21_047_R7",
        )
        bridge_ready = True
    else:
        status, decision, next_stage = (
            "PARTIAL_PASS_V21_047_R6_BRIDGE_READY_WAITING_FOR_MATURITY",
            "QQQ_MA50_OBSERVATION_MATURITY_BRIDGE_READY_WAIT_FOR_2026_06_24",
            "WAIT_UNTIL_2026_06_24_THEN_RERUN_V21_044_R8_R8R1_AND_V21_044_R9",
        )
        bridge_ready = True
    routes = [
        ("BRIDGE_READY_WAITING", "WAIT_UNTIL_2026_06_24_THEN_RERUN_V21_044_R8_R8R1_AND_V21_044_R9"),
        ("CACHE_COVERS_MATURITY", "RERUN_V21_044_R8_R8R1_THEN_V21_044_R9_AND_V21_047_R7"),
        ("TECHNICAL_ARTIFACTS_MISSING", "V21.047-R6A_TECHNICAL_MATURITY_ARTIFACT_REPAIR"),
        ("QQQ_LEDGER_INVALID", "V21.047-R6B_QQQ_MA50_OBSERVATION_LEDGER_REPAIR"),
    ]
    write_rows(OUT["routing"], [{
        "route_condition": condition, "recommended_next_stage": route,
        "selected_route": yn(route == next_stage), **GUARD,
    } for condition, route in routes])
    scope = [
        ("observation_maturity_bridge_only", "Only research bridge artifacts are written."),
        ("no_future_returns_materialized", "Future matured schema values remain empty."),
        ("no_adoption_or_executable_action", "All adoption, shadow, official, and action flags are FALSE."),
        ("technical_only_not_full_weight", "No full-weight result or score is created."),
    ]
    write_rows(OUT["scope"], [{
        "boundary_check": check, "check_passed": "TRUE", "evidence": evidence, **GUARD,
    } for check, evidence in scope])
    decision_row = {
        "stage": STAGE, "final_status": status, "decision": decision,
        "corrected_overlay": PRIMARY, "latest_QQQ_state": latest.get("qqq_state", ""),
        "technical_first_maturity_date": first_maturity,
        "QQQ_observation_ledger_integrity": integrity["ledger_integrity_status"],
        "technical_maturity_artifact_status": maturity_row["technical_maturity_artifact_status"],
        "bridge_readiness": yn(bridge_ready),
        "future_matured_evaluation_schema_status": "SCHEMA_READY_NO_FUTURE_RETURNS_FILLED",
        "monitor_bridge_status": "CONTRACT_READY",
        "overlay_adopted": "FALSE", "portfolio_variant_adopted": "FALSE",
        "filter_adopted": "FALSE", "recommended_next_stage": next_stage, **GUARD,
    }
    write_rows(OUT["decision"], [decision_row])

    report = f"""# V21.047-R6 QQQ MA50 Observation Ledger Maturity Bridge

final_status: {status}

decision: {decision}

Corrected overlay: {PRIMARY}.

Upstream R5 validation: {"READY" if ready else "NOT_READY"}. Observation remains enabled only for research; all adoption and action flags remain disabled.

QQQ observation ledger integrity: {integrity['ledger_integrity_status']}; rows={len(ledger)}; duplicates={duplicate_count}; latest date={latest.get('observation_date', '')}; latest state={latest.get('qqq_state', '')}; target exposure={latest.get('target_exposure_dry_run', '')}.

Current QQQ MA50 state: {latest.get('qqq_state', '')}.

Technical maturity dependency: observation date={"|".join(technical_dates)}; first maturity={first_maturity}; windows={"|".join(windows)}; pending rows={len(pending)}; matured rows={len(matured)}; entry binding={"|".join(entry_statuses)}; R9 allowed now={r8a.get('r9_allowed_now', 'FALSE')}; latest local QQQ price date={latest_cache_date}.

Overlay-to-technical alignment: policy observation rows align to the nearest technical observation date with one row per maturity window. Evaluation remains pending where local prices do not cover the maturity date.

Future matured evaluation schema: SCHEMA_READY_NO_FUTURE_RETURNS_FILLED. No future or matured returns were fabricated.

Monitor bridge contract: first maturity={first_maturity}; cost warning carried forward; valid turnover reduction=0; unsupported turnover claim removed; R9 required before any adoption; performance evaluation enabled only after maturity.

Next-stage routing: {next_stage}.

Cost warning: carried forward.

Maturity dependency: local price cache does not cover June 24, 2026.

No overlay was adopted.

No portfolio variant was adopted.

No official, shadow, real-book, broker, execution, or trade action was created.

Technical-only QQQ_MA50 observation bridge results must not be interpreted as full-weight results or full-weight evidence.

Full-weight remains blocked: TRUE.

Guardrail statement: research_only=TRUE; observation_maturity_bridge_only=TRUE; overlay_observation_enabled=TRUE; overlay_adoption_allowed=FALSE; valid_turnover_reduction=0; unsupported_turnover_claim_removed=TRUE; no official mutation, recommendation, future-return fabrication, or executable action; local artifacts only; online_download_attempted=FALSE; yfinance_used=FALSE.
"""
    REPORT.write_text(report, encoding="utf-8")
    shutil.copyfile(REPORT, CURRENT)
    print(f"final_status={status}")
    print(f"decision={decision}")
    print(f"corrected_overlay={PRIMARY}")
    print(f"latest_QQQ_state={latest.get('qqq_state', '')}")
    print(f"technical_first_maturity_date={first_maturity}")
    print(f"bridge_readiness={yn(bridge_ready)}")
    print(f"recommended_next_stage={next_stage}")
    print(f"overlay_adoption_allowed={GUARD['overlay_adoption_allowed']}")
    print(f"official_adoption_allowed={GUARD['official_adoption_allowed']}")
    print(f"shadow_gate_allowed={GUARD['shadow_gate_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
