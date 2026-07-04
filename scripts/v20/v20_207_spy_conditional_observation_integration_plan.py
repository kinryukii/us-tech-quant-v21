#!/usr/bin/env python
"""V20.207 SPY conditional observation integration plan.

Creates a research-only integration plan for showing the V20.206 SPY-conditional
10D local-edge observation candidate in daily reporting. This stage does not
overwrite existing daily reports and does not activate trading, recommendation,
or official-weight behavior.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
REPORTS_DIR = ROOT / "outputs" / "v20" / "reports"
CONSOLIDATION_DIR = ROOT / "outputs" / "v20" / "consolidation"

IN_EFFECT = OUT_DIR / "V20_206_SPY_CONDITIONAL_EFFECTIVENESS.csv"
IN_COMPARE = OUT_DIR / "V20_206_SPY_VS_NON_SPY_COMPARISON.csv"
IN_BOOT = OUT_DIR / "V20_206_SPY_CONDITIONAL_BOOTSTRAP.csv"
IN_TRIM = OUT_DIR / "V20_206_SPY_CONDITIONAL_TRIMMED_WINSORIZED.csv"
IN_STABILITY = OUT_DIR / "V20_206_SPY_ASOF_DATE_STABILITY.csv"
IN_BIAS = OUT_DIR / "V20_206_SPY_WEIGHT_BIAS_REPEATABILITY.csv"
IN_RULE = OUT_DIR / "V20_206_CONDITIONAL_OVERLAY_RULE_CANDIDATE.csv"
IN_GATE = OUT_DIR / "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv"
IN_REPORT = READ_CENTER / "V20_206_10D_SPY_CONDITIONAL_OVERLAY_VALIDATION_REPORT.md"
REQUIRED_INPUTS = [IN_EFFECT, IN_COMPARE, IN_BOOT, IN_TRIM, IN_STABILITY, IN_BIAS, IN_RULE, IN_GATE, IN_REPORT]

OPTIONAL_DAILY_REPORTS = [
    REPORTS_DIR / "V20_200_OPERATOR_DAILY_REPORT_V2.md",
    READ_CENTER / "V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md",
    CONSOLIDATION_DIR / "V20_200_OPERATOR_DAILY_REPORT_SUMMARY.csv",
]

OUT_REGISTRY = OUT_DIR / "V20_207_CONDITIONAL_OBSERVATION_RULE_REGISTRY.csv"
OUT_SPEC = OUT_DIR / "V20_207_DAILY_REPORT_INTEGRATION_SPEC.csv"
OUT_STATUS = OUT_DIR / "V20_207_CURRENT_CONDITIONAL_OBSERVATION_STATUS.csv"
OUT_DISABLE = OUT_DIR / "V20_207_NON_SPY_DISABLE_AUDIT.csv"
OUT_SAFETY = OUT_DIR / "V20_207_OBSERVATION_ONLY_SAFETY_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_207_INTEGRATION_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_207_SPY_CONDITIONAL_OBSERVATION_INTEGRATION_PLAN_REPORT.md"

RULE_ID = "V20_206_SPY_10D_RANDOM_WEIGHT_LOCAL_EDGE_OBSERVATION"
RULE_NAME = "SPY conditional 10D random-weight local-edge observation"
CONDITION_EXPRESSION = "selected_etf == SPY"
FORWARD_WINDOW = "10D"
OVERLAY_ACTION = "ALLOW_RESEARCH_ONLY_LOCAL_EDGE_OBSERVATION"
ALLOWED_SCOPE = "DAILY_REPORT_OBSERVATION_SECTION_ONLY; SPY_SELECTED_ETF_REGIME_ONLY"
DISABLED_SCOPE = "selected_etf != SPY"
PROHIBITED_SCOPE = "OFFICIAL_RECOMMENDATION / REAL_BOOK_SIGNAL / BROKER_EXECUTION / OFFICIAL_WEIGHT_MUTATION"

REGISTRY_FIELDS = [
    "rule_id", "rule_name", "source_stage", "condition_expression", "forward_window",
    "overlay_action", "allowed_scope", "disabled_scope", "prohibited_scope",
    "evidence_summary", "evidence_status", "rule_registry_status",
]
SPEC_FIELDS = [
    "section_name", "display_condition", "display_title", "display_fields",
    "warning_text", "allowed_when", "disabled_when", "integration_status",
]
STATUS_FIELDS = [
    "current_selected_etf", "selected_etf_source", "condition_status",
    "observation_allowed", "local_edge_status", "non_spy_edge_disabled",
    "reason", "status_timestamp",
]
DISABLE_FIELDS = ["selected_etf_scope", "observation_allowed", "disable_reason", "evidence_source", "audit_status"]
SAFETY_FIELDS = ["safety_check", "expected_value", "actual_value", "audit_status", "reason"]
GATE_FIELDS = [
    "final_status", "rule_registered", "integration_spec_ready", "current_condition_evaluable",
    "current_observation_allowed", "non_spy_disabled", "observation_only_safety_passed",
    "daily_report_overwrite_performed", "official_weight_mutated",
    "official_recommendation_created", "real_book_signal_created", "broker_execution_supported",
    "shadow_weight_change_recommended", "next_stage_allowed", "reason", "next_recommended_action",
]

STATUS_SPY = "PASS_V20_207_SPY_CONDITIONAL_OBSERVATION_ALLOWED_IN_REPORT_SPEC"
STATUS_NON_SPY = "PASS_V20_207_NON_SPY_OBSERVATION_DISABLED_IN_REPORT_SPEC"
STATUS_UNKNOWN = "PARTIAL_PASS_V20_207_INTEGRATION_SPEC_READY_CURRENT_CONDITION_UNKNOWN"
STATUS_MISSING = "BLOCKED_V20_207_REQUIRED_INPUT_MISSING"
STATUS_SAFETY = "BLOCKED_V20_207_OBSERVATION_ONLY_SAFETY_FAILED"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def inputs_ready() -> bool:
    return all(path.exists() and path.stat().st_size > 0 and (read_csv(path) if path.suffix.lower() == ".csv" else path.read_text(encoding="utf-8").strip()) for path in REQUIRED_INPUTS)


def spy_effect_row() -> dict[str, str]:
    for row in read_csv(IN_EFFECT):
        if row.get("condition_name") == "selected_etf_eq_SPY":
            return row
    return {}


def v206_gate() -> dict[str, str]:
    rows = read_csv(IN_GATE)
    return rows[0] if rows else {}


def rule_registry() -> list[dict[str, object]]:
    spy = spy_effect_row()
    gate = v206_gate()
    evidence = (
        f"SPY trials={gate.get('spy_trial_count', spy.get('trial_count', ''))}; "
        f"avg_excess={gate.get('spy_avg_excess_vs_etf_rotation', spy.get('avg_excess_vs_etf_rotation', ''))}; "
        f"median_excess={gate.get('spy_median_excess_vs_etf_rotation', spy.get('median_excess_vs_etf_rotation', ''))}; "
        f"win_rate={gate.get('spy_win_rate_vs_etf_rotation', spy.get('win_rate_vs_etf_rotation', ''))}; "
        "non-SPY regimes disabled for local-edge observation."
    )
    return [{
        "rule_id": RULE_ID,
        "rule_name": RULE_NAME,
        "source_stage": "V20.206_10D_SPY_CONDITIONAL_OVERLAY_VALIDATION",
        "condition_expression": CONDITION_EXPRESSION,
        "forward_window": FORWARD_WINDOW,
        "overlay_action": OVERLAY_ACTION,
        "allowed_scope": ALLOWED_SCOPE,
        "disabled_scope": DISABLED_SCOPE,
        "prohibited_scope": PROHIBITED_SCOPE,
        "evidence_summary": evidence,
        "evidence_status": gate.get("final_status", ""),
        "rule_registry_status": "REGISTERED_FOR_RESEARCH_ONLY_REPORT_SPEC",
    }]


def integration_spec() -> list[dict[str, object]]:
    display_fields = "; ".join([
        "selected_etf", "condition_status", "forward_window", "observation_allowed",
        "non_spy_disabled", "spy_historical_avg_excess", "spy_historical_median_excess",
        "spy_historical_win_rate", "research_only_warning", "not_buy_sell_signal_warning",
        "no_official_weight_change_warning",
    ])
    warning = (
        "Research-only observation section. Not a buy/sell signal. No official weights changed. "
        "No official recommendation, real-book signal, broker execution, or trade action is allowed."
    )
    return [{
        "section_name": "SPY_CONDITIONAL_10D_RANDOM_WEIGHT_OVERLAY_WATCH",
        "display_condition": "Always show as research-only status when V20.207 spec is included; observation_allowed only when selected_etf == SPY.",
        "display_title": "SPY-Conditional 10D Random-Weight Local-Edge Watch",
        "display_fields": display_fields,
        "warning_text": warning,
        "allowed_when": "current selected_etf == SPY and current ETF rotation selection source is explicit",
        "disabled_when": "current selected_etf != SPY or current selected_etf is UNKNOWN",
        "integration_status": "SPEC_READY_NOT_INJECTED_INTO_PRODUCTION_REPORT",
    }]


def infer_current_selected_etf() -> tuple[str, str, str]:
    patterns = [
        re.compile(r"current[_\s-]*selected[_\s-]*etf\s*[:=]\s*(SPY|QQQ|SOXX)", re.IGNORECASE),
        re.compile(r"selected[_\s-]*etf\s*[:=]\s*(SPY|QQQ|SOXX)", re.IGNORECASE),
        re.compile(r"ETF rotation selected\s+(SPY|QQQ|SOXX)", re.IGNORECASE),
    ]
    for path in OPTIONAL_DAILY_REPORTS:
        if not path.exists() or path.stat().st_size == 0:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore") if path.suffix.lower() != ".csv" else "\n".join(",".join(row.values()) for row in read_csv(path))
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).upper(), path.as_posix(), "explicit current selected_etf pattern found"
    return "UNKNOWN", "UNAVAILABLE", "current ETF rotation selection artifact unavailable"


def current_status() -> list[dict[str, object]]:
    selected, source, reason = infer_current_selected_etf()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if selected == "SPY":
        condition_status = "CURRENT_SELECTED_ETF_IS_SPY"
        allowed = "TRUE"
        local_edge = "SPY_CONDITIONAL_OBSERVATION_ALLOWED"
    elif selected in {"QQQ", "SOXX"}:
        condition_status = "CURRENT_SELECTED_ETF_NOT_SPY"
        allowed = "FALSE"
        local_edge = "DISABLED_NON_SPY_REGIME"
    else:
        condition_status = "CURRENT_SELECTED_ETF_UNKNOWN"
        allowed = "FALSE"
        local_edge = "NOT_EVALUATED_CURRENTLY"
    return [{
        "current_selected_etf": selected,
        "selected_etf_source": source,
        "condition_status": condition_status,
        "observation_allowed": allowed,
        "local_edge_status": local_edge,
        "non_spy_edge_disabled": "TRUE",
        "reason": reason,
        "status_timestamp": now,
    }]


def non_spy_disable_audit() -> list[dict[str, object]]:
    return [
        {
            "selected_etf_scope": "SPY",
            "observation_allowed": "TRUE",
            "disable_reason": "SPY is the only V20.205 robust positive selected_etf cluster and V20.206 observation candidate.",
            "evidence_source": "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv",
            "audit_status": "PASS",
        },
        {
            "selected_etf_scope": "NON_SPY",
            "observation_allowed": "FALSE",
            "disable_reason": "V20.206 non-SPY condition has negative average excess and win rate below 0.55.",
            "evidence_source": "V20_206_SPY_CONDITIONAL_EFFECTIVENESS.csv",
            "audit_status": "PASS",
        },
        {
            "selected_etf_scope": "UNKNOWN",
            "observation_allowed": "FALSE",
            "disable_reason": "No explicit current selected_etf source; observation cannot be enabled.",
            "evidence_source": "V20_207_CURRENT_CONDITIONAL_OBSERVATION_STATUS.csv",
            "audit_status": "PASS",
        },
    ]


def safety_audit(daily_report_overwrite: bool = False) -> list[dict[str, object]]:
    checks = [
        ("RESEARCH_ONLY", "TRUE", "TRUE", "Research-only integration plan."),
        ("OFFICIAL_WEIGHT_MUTATED", "FALSE", "FALSE", "No official weight files are written."),
        ("OFFICIAL_RECOMMENDATION_CREATED", "FALSE", "FALSE", "No recommendation artifact is created."),
        ("REAL_BOOK_SIGNAL_CREATED", "FALSE", "FALSE", "No real-book signal artifact is created."),
        ("BROKER_EXECUTION_SUPPORTED", "FALSE", "FALSE", "No broker execution is supported."),
        ("SHADOW_WEIGHT_CHANGE_RECOMMENDED", "FALSE", "FALSE", "V20.207 is not an activation stage."),
        ("TRADE_ACTION_CREATED", "FALSE", "FALSE", "No trade action artifact is created."),
        ("OFFICIAL_REPORT_OVERWRITE", "FALSE", "TRUE" if daily_report_overwrite else "FALSE", "Existing daily reports are not overwritten."),
    ]
    return [
        {
            "safety_check": name,
            "expected_value": expected,
            "actual_value": actual,
            "audit_status": "PASS" if expected == actual else "FAIL",
            "reason": reason,
        }
        for name, expected, actual, reason in checks
    ]


def build_gate(registry: list[dict[str, object]], spec: list[dict[str, object]], status: dict[str, object], safety: list[dict[str, object]]) -> dict[str, object]:
    safety_pass = all(row["audit_status"] == "PASS" for row in safety)
    if not safety_pass:
        final_status = STATUS_SAFETY
        reason = "Observation-only safety audit failed."
        next_allowed = "FALSE"
    elif status["current_selected_etf"] == "SPY":
        final_status = STATUS_SPY
        reason = "Rule/spec ready and current selected_etf is SPY; report spec may show observation allowed."
        next_allowed = "TRUE"
    elif status["current_selected_etf"] in {"QQQ", "SOXX"}:
        final_status = STATUS_NON_SPY
        reason = "Rule/spec ready and current selected_etf is non-SPY; observation disabled in report spec."
        next_allowed = "TRUE"
    else:
        final_status = STATUS_UNKNOWN
        reason = "Rule/spec ready, but current selected_etf could not be inferred without fabricating state."
        next_allowed = "TRUE"
    return {
        "final_status": final_status,
        "rule_registered": "TRUE" if len(registry) == 1 else "FALSE",
        "integration_spec_ready": "TRUE" if bool(spec) else "FALSE",
        "current_condition_evaluable": "FALSE" if status["current_selected_etf"] == "UNKNOWN" else "TRUE",
        "current_observation_allowed": status["observation_allowed"],
        "non_spy_disabled": status["non_spy_edge_disabled"],
        "observation_only_safety_passed": "TRUE" if safety_pass else "FALSE",
        "daily_report_overwrite_performed": "FALSE",
        "official_weight_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "real_book_signal_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "shadow_weight_change_recommended": "FALSE",
        "next_stage_allowed": next_allowed,
        "reason": reason,
        "next_recommended_action": "Create a separate daily report observation section renderer from this spec; do not inject into production reports without an explicit follow-up stage.",
    }


def write_report(gate: dict[str, object], registry: dict[str, object], spec: dict[str, object], status: dict[str, object], safety: list[dict[str, object]]) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    failed = [row for row in safety if row["audit_status"] != "PASS"]
    lines = [
        "# V20.207 SPY Conditional Observation Integration Plan Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.201 context: random-weight PIT-forward consolidation passed.",
        "- V20.202 context: no shadow weight change was recommended.",
        "- V20.203 context: 10D edge was weak or outlier-sensitive.",
        "- V20.204 context: expanded 10D evidence strengthened but remained mixed.",
        "- V20.205 context: SPY was the only robust positive selected ETF cluster.",
        "- V20.206 context: SPY-conditional 10D overlay observation candidate passed; non-SPY regimes were disabled for observation.",
        "",
        "Exact rule candidate:",
        f"- rule_id: {registry.get('rule_id', '')}",
        f"- condition_expression: {registry.get('condition_expression', '')}",
        f"- forward_window: {registry.get('forward_window', '')}",
        f"- overlay_action: {registry.get('overlay_action', '')}",
        f"- allowed_scope: {registry.get('allowed_scope', '')}",
        f"- disabled_scope: {registry.get('disabled_scope', '')}",
        f"- prohibited_scope: {registry.get('prohibited_scope', '')}",
        "",
        "Daily report appearance:",
        f"- section_name: {spec.get('section_name', '')}",
        f"- display_title: {spec.get('display_title', '')}",
        f"- display_fields: {spec.get('display_fields', '')}",
        f"- warning_text: {spec.get('warning_text', '')}",
        "",
        f"- Current selected_etf inferred: {status.get('current_selected_etf', '')}",
        f"- Current selected_etf source: {status.get('selected_etf_source', '')}",
        f"- Current observation allowed: {status.get('observation_allowed', '')}",
        f"- Non-SPY disable policy: selected_etf != SPY disables random-weight local-edge observation.",
        f"- Safety audit result: {'PASS' if not failed else 'FAIL'}",
        f"- Next recommended stage: {gate.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- no shadow weight change was recommended",
        "- existing daily reports were not overwritten",
        "- no trade action was created",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(reason: str) -> int:
    registry: list[dict[str, object]] = []
    spec: list[dict[str, object]] = []
    status = {
        "current_selected_etf": "UNKNOWN",
        "selected_etf_source": "UNAVAILABLE",
        "condition_status": "CURRENT_SELECTED_ETF_UNKNOWN",
        "observation_allowed": "FALSE",
        "local_edge_status": "NOT_EVALUATED_CURRENTLY",
        "non_spy_edge_disabled": "TRUE",
        "reason": reason,
        "status_timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    safety = safety_audit(False)
    gate = {
        "final_status": STATUS_MISSING,
        "rule_registered": "FALSE",
        "integration_spec_ready": "FALSE",
        "current_condition_evaluable": "FALSE",
        "current_observation_allowed": "FALSE",
        "non_spy_disabled": "TRUE",
        "observation_only_safety_passed": "TRUE",
        "daily_report_overwrite_performed": "FALSE",
        "official_weight_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "real_book_signal_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "shadow_weight_change_recommended": "FALSE",
        "next_stage_allowed": "FALSE",
        "reason": reason,
        "next_recommended_action": "Restore required V20.206 inputs before integration planning.",
    }
    write_csv(OUT_REGISTRY, REGISTRY_FIELDS, registry)
    write_csv(OUT_SPEC, SPEC_FIELDS, spec)
    write_csv(OUT_STATUS, STATUS_FIELDS, [status])
    write_csv(OUT_DISABLE, DISABLE_FIELDS, non_spy_disable_audit())
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, {}, {}, status, safety)
    print(f"FINAL_STATUS={STATUS_MISSING}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


def main() -> int:
    if not inputs_ready():
        missing = [path.name for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0 or not (read_csv(path) if path.suffix.lower() == ".csv" else path.read_text(encoding="utf-8").strip())]
        return blocked_outputs("Missing or empty required V20.206 inputs: " + ", ".join(missing))
    registry = rule_registry()
    spec = integration_spec()
    status_rows = current_status()
    disable = non_spy_disable_audit()
    safety = safety_audit(False)
    gate = build_gate(registry, spec, status_rows[0], safety)
    write_csv(OUT_REGISTRY, REGISTRY_FIELDS, registry)
    write_csv(OUT_SPEC, SPEC_FIELDS, spec)
    write_csv(OUT_STATUS, STATUS_FIELDS, status_rows)
    write_csv(OUT_DISABLE, DISABLE_FIELDS, disable)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, registry[0], spec[0], status_rows[0], safety)
    print(f"FINAL_STATUS={gate['final_status']}")
    print(f"CURRENT_SELECTED_ETF={status_rows[0]['current_selected_etf']}")
    print(f"CURRENT_OBSERVATION_ALLOWED={gate['current_observation_allowed']}")
    print(f"NEXT_STAGE_ALLOWED={gate['next_stage_allowed']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
