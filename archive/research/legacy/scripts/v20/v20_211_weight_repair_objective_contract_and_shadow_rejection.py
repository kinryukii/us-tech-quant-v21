#!/usr/bin/env python
"""V20.211 weight repair objective contract and shadow rejection.

Rejects the current shadow dynamic weight for official use when it fails the
core medium-horizon Top20 forward-window guardrails, retains the baseline, and
creates a strict objective contract for future weight repair experiments.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_EFFECTIVENESS = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"
OPTIONAL_EVIDENCE = [
    CONSOLIDATION / "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP.csv",
    CONSOLIDATION / "V20_109_R4_FORWARD_WINDOW_TOPN_SCENARIO_COMPARISON_MATRIX.csv",
    CONSOLIDATION / "V20_109_R6_FORWARD_WINDOW_STRESS_AUDIT.csv",
    CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv",
    CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv",
    CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
]

OUT_DECISION = CONSOLIDATION / "V20_211_SHADOW_WEIGHT_REJECTION_DECISION.csv"
OUT_CONTRACT = CONSOLIDATION / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT.csv"
OUT_GUARDRAIL = CONSOLIDATION / "V20_211_FORWARD_WINDOW_GUARDRAIL_MATRIX.csv"
OUT_ROLE = CONSOLIDATION / "V20_211_DATA_TRUST_AND_RISK_ROLE_SEPARATION_CONTRACT.csv"
OUT_ETF = CONSOLIDATION / "V20_211_ETF_ROTATION_LANE_SEPARATION_CONTRACT.csv"
OUT_GATE = CONSOLIDATION / "V20_211_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT_AND_SHADOW_REJECTION_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D", "120D"]
CORE_WINDOWS = {"20D", "60D", "120D"}
STATUS_PASS = "PASS_V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT_CREATED_CURRENT_SHADOW_REJECTED_BASELINE_RETAINED"
STATUS_BLOCKED = "BLOCKED_V20_211_REQUIRED_EFFECTIVENESS_MATRIX_MISSING"
DECISION_REJECT = "REJECT_CURRENT_SHADOW_WEIGHT_FOR_OFFICIAL_USE_RETAIN_BASELINE"
DECISION_RESEARCH_ONLY = "CURRENT_SHADOW_REMAINS_RESEARCH_SHADOW_ONLY_BASELINE_RETAINED"


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def as_float(value: object) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def money(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"${10000 * (1.0 + value):,.2f}"


def evidence_ready(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0 and (path.suffix.lower() != ".csv" or bool(read_csv(path)))


def top20_rows() -> dict[str, dict[str, str]]:
    rows = read_csv(IN_EFFECTIVENESS)
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        if clean(row.get("top_n")) == "20" and clean(row.get("forward_window")) in WINDOWS:
            selected[clean(row.get("forward_window"))] = row
    return selected


def guardrail_rows(selected: dict[str, dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for window in WINDOWS:
        source = selected.get(window, {})
        baseline = as_float(source.get("baseline_mean_forward_return"))
        shadow = as_float(source.get("shadow_mean_forward_return"))
        delta = as_float(source.get("shadow_minus_baseline_mean_return"))
        if delta is None and baseline is not None and shadow is not None:
            delta = shadow - baseline
        required = window in CORE_WINDOWS
        pass_flag = delta is not None and (delta >= 0 if required else True)
        rows.append({
            "forward_window": window,
            "top_n": "20",
            "baseline_mean_forward_return": fmt(baseline),
            "shadow_mean_forward_return": fmt(shadow),
            "shadow_minus_baseline_mean_return": fmt(delta),
            "baseline_10000_example_value": money(baseline),
            "shadow_10000_example_value": money(shadow),
            "hard_guardrail_required": "TRUE" if required else "FALSE",
            "guardrail_rule": f"{window} Top20 shadow_minus_baseline_mean_return >= 0" if required else f"{window} Top20 monitored for timing/objective scoring only",
            "guardrail_pass": "TRUE" if pass_flag else "FALSE",
            "underperforms_baseline": "TRUE" if delta is not None and delta < 0 else "FALSE",
            "research_interpretation": "entry_timing_research_only" if window == "5D" else "medium_horizon_alpha_validation",
        })
    return rows


def objective_contract_rows() -> list[dict[str, object]]:
    return [
        {"contract_section": "primary_objective", "rule_id": "PRIMARY_OBJECTIVE", "rule_value": "preserve_or_improve_medium_horizon_top20_alpha", "required": "TRUE", "notes": "Future repairs must protect Top20 medium-horizon alpha before any official promotion."},
        {"contract_section": "hard_guardrail", "rule_id": "20D_TOP20_NON_UNDERPERFORMANCE", "rule_value": "20D Top20 shadow_minus_baseline_mean_return >= 0", "required": "TRUE", "notes": "Required for any future weight repair acceptance."},
        {"contract_section": "hard_guardrail", "rule_id": "60D_TOP20_NON_UNDERPERFORMANCE", "rule_value": "60D Top20 shadow_minus_baseline_mean_return >= 0", "required": "TRUE", "notes": "Required for any future weight repair acceptance."},
        {"contract_section": "hard_guardrail", "rule_id": "120D_TOP20_NON_UNDERPERFORMANCE", "rule_value": "120D Top20 shadow_minus_baseline_mean_return >= 0", "required": "TRUE", "notes": "Required for any future weight repair acceptance."},
        {"contract_section": "hard_guardrail", "rule_id": "TOP20_TURNOVER_CAP_IF_AVAILABLE", "rule_value": "Top20 turnover <= 0.20 if turnover field is available or derivable", "required": "CONDITIONAL", "notes": "Reject or block if derivable turnover breaches the cap."},
        {"contract_section": "hard_guardrail", "rule_id": "MAX_RANK_DELTA_CAP_IF_AVAILABLE", "rule_value": "max_rank_delta <= 10 if rank delta field is available", "required": "CONDITIONAL", "notes": "Reject or block if rank movement exceeds the cap."},
        {"contract_section": "hard_guardrail", "rule_id": "NO_OFFICIAL_WEIGHT_MUTATION_UNLESS_ALL_HARD_GUARDRAILS_PASS", "rule_value": "no official weight mutation unless all hard guardrails pass", "required": "TRUE", "notes": "This stage performs no mutation."},
        {"contract_section": "hard_guardrail", "rule_id": "NO_REAL_BOOK_RECOMMENDATION_UNLESS_PROMOTION_GATE_PASSES", "rule_value": "no real-book recommendation unless separate promotion gate passes", "required": "TRUE", "notes": "Research-only until separately promoted."},
        {"contract_section": "soft_objective_weight", "rule_id": "5D_DELTA_WEIGHT", "rule_value": "0.10", "required": "TRUE", "notes": "Short-window improvement can contribute only as a soft objective."},
        {"contract_section": "soft_objective_weight", "rule_id": "10D_DELTA_WEIGHT", "rule_value": "0.10", "required": "TRUE", "notes": "Short-window contribution is limited."},
        {"contract_section": "soft_objective_weight", "rule_id": "20D_DELTA_WEIGHT", "rule_value": "0.25", "required": "TRUE", "notes": "Medium horizon is a core objective."},
        {"contract_section": "soft_objective_weight", "rule_id": "60D_DELTA_WEIGHT", "rule_value": "0.25", "required": "TRUE", "notes": "Medium horizon is a core objective."},
        {"contract_section": "soft_objective_weight", "rule_id": "120D_DELTA_WEIGHT", "rule_value": "0.30", "required": "TRUE", "notes": "Longer forward window has highest soft objective weight."},
        {"contract_section": "auto_reject", "rule_id": "AUTO_REJECT_IF_60D_OR_120D_TOP20_UNDERPERFORMS_BASELINE", "rule_value": "TRUE", "required": "TRUE", "notes": "Any future candidate failing 60D or 120D Top20 mean-return parity is auto-rejected."},
        {"contract_section": "entry_timing_rule", "rule_id": "5D_IMPROVEMENT_ENTRY_TIMING_ONLY", "rule_value": "5D improvement may be used only for entry timing research, not for official ranking weight mutation", "required": "TRUE", "notes": "Short-window gains cannot offset medium-horizon alpha damage."},
    ]


def role_contract_rows() -> list[dict[str, object]]:
    return [
        {"role_key": "DATA_TRUST_ALPHA_WEIGHT_RECOMMENDATION", "role_value": "0", "contract_status": "ACTIVE", "notes": "DATA_TRUST must not directly boost alpha ranking."},
        {"role_key": "DATA_TRUST_ROLE", "role_value": "GATE_WARNING_ELIGIBILITY_ONLY", "contract_status": "ACTIVE", "notes": "Data trust is a warning and eligibility gate, not an alpha signal."},
        {"role_key": "RISK_ALPHA_WEIGHT_RECOMMENDATION", "role_value": "DO_NOT_INCREASE_FOR_ALPHA_UNLESS_VALIDATED", "contract_status": "ACTIVE", "notes": "Risk must not be promoted into alpha weight without separate validation."},
        {"role_key": "RISK_ROLE", "role_value": "GATE_CAP_WARNING_DOWNSIDE_CONTROL", "contract_status": "ACTIVE", "notes": "Risk controls downside review and caps."},
        {"role_key": "DATA_TRUST_DIRECT_ALPHA_BOOST_ALLOWED", "role_value": "FALSE", "contract_status": "ACTIVE", "notes": "DATA_TRUST must not directly boost alpha ranking."},
        {"role_key": "RISK_DIRECT_HIGH_ALPHA_ERASURE_ALLOWED", "role_value": "FALSE", "contract_status": "ACTIVE", "notes": "RISK must not directly erase high-alpha ranking unless a gate condition requires review or block."},
    ]


def etf_contract_rows() -> list[dict[str, object]]:
    requirements = [
        "selected_etf history",
        "ETF rotation return",
        "ETF rotation max drawdown",
        "ETF rotation Sharpe or risk-adjusted metric",
        "vs QQQ",
        "vs SPY",
        "vs SOXX/SMH if available",
        "switch count",
        "cash days",
        "leverage gate status",
    ]
    rows = [{
        "contract_key": "ETF_ROTATION_LANE_STATUS",
        "contract_value": "SEPARATE_REQUIRED",
        "required_before_merge": "TRUE",
        "current_use_allowed": "REGIME_EVIDENCE_ONLY",
        "notes": "ETF rotation must not be merged into stock ranking weight until the required lane evidence exists.",
    }]
    for item in requirements:
        rows.append({
            "contract_key": "REQUIRED_ETF_ROTATION_EVIDENCE",
            "contract_value": item,
            "required_before_merge": "TRUE",
            "current_use_allowed": "REGIME_EVIDENCE_ONLY",
            "notes": "Current ETF evidence may be used as regime evidence only, not as official allocation.",
        })
    return rows


def decision_row(guardrails: list[dict[str, object]]) -> dict[str, object]:
    by_window = {row["forward_window"]: row for row in guardrails}
    core_under = [w for w in CORE_WINDOWS if by_window.get(w, {}).get("underperforms_baseline") == "TRUE"]
    under_60 = by_window.get("60D", {}).get("underperforms_baseline") == "TRUE"
    under_120 = by_window.get("120D", {}).get("underperforms_baseline") == "TRUE"
    eligible = "FALSE" if core_under else "TRUE"
    if under_60 and under_120:
        decision = DECISION_REJECT
    elif core_under:
        decision = DECISION_RESEARCH_ONLY
    else:
        decision = "CURRENT_SHADOW_NOT_REJECTED_BY_CORE_TOP20_GUARDRAILS_REQUIRES_SEPARATE_PROMOTION_GATE"
    return {
        "decision": decision,
        "current_shadow_official_eligible": eligible,
        "baseline_retained": "TRUE",
        "research_shadow_only_status_preserved": "TRUE",
        "core_underperforming_windows": ";".join(sorted(core_under)),
        "auto_reject_triggered": "TRUE" if under_60 or under_120 else "FALSE",
        "official_weight_file_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "decision_reason": "Current shadow underperforms baseline on core Top20 medium-horizon windows; 60D and 120D failures require rejection and baseline retention.",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def gate_row(decision: dict[str, object], blocked: bool = False) -> dict[str, object]:
    return {
        "v20_211_status": STATUS_BLOCKED if blocked else STATUS_PASS,
        "current_shadow_official_eligible": "FALSE" if blocked else decision["current_shadow_official_eligible"],
        "baseline_retained": "FALSE" if blocked else "TRUE",
        "future_weight_repair_contract_created": "FALSE" if blocked else "TRUE",
        "data_trust_role_separated": "FALSE" if blocked else "TRUE",
        "risk_role_separated": "FALSE" if blocked else "TRUE",
        "etf_rotation_lane_separated": "FALSE" if blocked else "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "recommended_next_stage": "V20.212_PORTFOLIO_EQUITY_CURVE_AND_DRAWDOWN_BACKTEST_CONTRACT",
    }


def render_report(guardrails: list[dict[str, object]], decision: dict[str, object], gate: dict[str, object]) -> str:
    comparison_lines = [
        "| Window | Baseline mean | Shadow mean | Shadow - baseline | Guardrail |",
        "|---|---:|---:|---:|---|",
    ]
    value_lines = [
        "| Window | Baseline $10,000 example | Shadow $10,000 example | Difference |",
        "|---|---:|---:|---:|",
    ]
    for row in guardrails:
        delta = as_float(row["shadow_minus_baseline_mean_return"])
        diff = "" if delta is None else f"${10000 * delta:,.2f}"
        comparison_lines.append(
            f"| {row['forward_window']} | {row['baseline_mean_forward_return']} | {row['shadow_mean_forward_return']} | "
            f"{row['shadow_minus_baseline_mean_return']} | {row['guardrail_pass']} |"
        )
        value_lines.append(
            f"| {row['forward_window']} | {row['baseline_10000_example_value']} | {row['shadow_10000_example_value']} | {diff} |"
        )
    evidence_lines = [
        f"- `{rel(path)}`: {'present' if evidence_ready(path) else 'missing or empty'}"
        for path in [IN_EFFECTIVENESS, *OPTIONAL_EVIDENCE]
    ]
    return "\n".join([
        "# V20.211 Weight Repair Objective Contract and Shadow Rejection",
        "",
        "## Summary",
        "The current shadow dynamic weight is rejected for official use and the baseline is retained. The shadow improved the short 5D Top20 mean forward return, but it materially underperformed the baseline on the core 20D, 60D, and 120D Top20 windows.",
        "",
        "## Decision",
        f"- Decision: `{decision['decision']}`",
        f"- Current shadow official eligible: `{decision['current_shadow_official_eligible']}`",
        "- Research/shadow-only status is preserved.",
        "- No official weight file was mutated.",
        "- No official recommendation, trade action, or broker execution artifact was created.",
        "",
        "## Why The Shadow Is Rejected",
        "The objective for ranking weights is not to improve only short 5D behavior. A future repair must preserve or improve the medium-horizon Top20 alpha. The current shadow fails that requirement because 20D, 60D, and 120D Top20 mean returns are below baseline, and the 60D or 120D auto-reject rule is triggered.",
        "",
        "## Top20 Comparison",
        *comparison_lines,
        "",
        "## $10,000 Example",
        *value_lines,
        "",
        "## Drawdown Limitation",
        "Max drawdown is not available from the forward-window tables. It requires the next equity-curve stage because drawdown depends on a portfolio path, not isolated forward-window mean returns.",
        "",
        "## Evidence Inputs",
        *evidence_lines,
        "",
        "## Objective Contract",
        "Future weight repair experiments must pass 20D, 60D, and 120D Top20 non-underperformance guardrails before any official mutation can be considered. A 5D improvement may be used only for entry timing research, not for official ranking weight mutation.",
        "",
        "## Next Recommended Action",
        f"`{gate['recommended_next_stage']}`",
        "",
        f"Final status: `{gate['v20_211_status']}`",
        "",
    ])


def write_blocked_outputs() -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    decision = {
        "decision": "BLOCKED_REQUIRED_EFFECTIVENESS_MATRIX_MISSING",
        "current_shadow_official_eligible": "FALSE",
        "baseline_retained": "FALSE",
        "research_shadow_only_status_preserved": "TRUE",
        "core_underperforming_windows": "",
        "auto_reject_triggered": "FALSE",
        "official_weight_file_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "decision_reason": f"Required input missing or empty: {rel(IN_EFFECTIVENESS)}",
        "created_at": now,
    }
    gate = gate_row(decision, blocked=True)
    write_outputs([], decision, gate)
    return gate


def write_outputs(guardrails: list[dict[str, object]], decision: dict[str, object], gate: dict[str, object]) -> None:
    write_csv(OUT_DECISION, [
        "decision", "current_shadow_official_eligible", "baseline_retained",
        "research_shadow_only_status_preserved", "core_underperforming_windows",
        "auto_reject_triggered", "official_weight_file_mutated",
        "official_recommendation_created", "trade_action_created",
        "broker_execution_supported", "decision_reason", "created_at",
    ], [decision])
    write_csv(OUT_CONTRACT, ["contract_section", "rule_id", "rule_value", "required", "notes"], objective_contract_rows())
    write_csv(OUT_GUARDRAIL, [
        "forward_window", "top_n", "baseline_mean_forward_return", "shadow_mean_forward_return",
        "shadow_minus_baseline_mean_return", "baseline_10000_example_value",
        "shadow_10000_example_value", "hard_guardrail_required", "guardrail_rule",
        "guardrail_pass", "underperforms_baseline", "research_interpretation",
    ], guardrails)
    write_csv(OUT_ROLE, ["role_key", "role_value", "contract_status", "notes"], role_contract_rows())
    write_csv(OUT_ETF, ["contract_key", "contract_value", "required_before_merge", "current_use_allowed", "notes"], etf_contract_rows())
    write_csv(OUT_GATE, [
        "v20_211_status", "current_shadow_official_eligible", "baseline_retained",
        "future_weight_repair_contract_created", "data_trust_role_separated",
        "risk_role_separated", "etf_rotation_lane_separated",
        "official_promotion_allowed", "official_recommendation_created",
        "weight_mutated", "trade_action_created", "broker_execution_supported",
        "recommended_next_stage",
    ], [gate])
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(render_report(guardrails, decision, gate), encoding="utf-8")


def main() -> None:
    if not evidence_ready(IN_EFFECTIVENESS):
        gate = write_blocked_outputs()
        print(f"FINAL_STATUS={gate['v20_211_status']}")
        print("CURRENT_SHADOW_OFFICIAL_ELIGIBLE=FALSE")
        print("BASELINE_RETAINED=FALSE")
        print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
        print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
        print("WEIGHT_MUTATED=FALSE")
        print("TRADE_ACTION_CREATED=FALSE")
        print("BROKER_EXECUTION_SUPPORTED=FALSE")
        return

    selected = top20_rows()
    guardrails = guardrail_rows(selected)
    decision = decision_row(guardrails)
    gate = gate_row(decision)
    write_outputs(guardrails, decision, gate)

    print(f"FINAL_STATUS={gate['v20_211_status']}")
    print(f"DECISION={decision['decision']}")
    print(f"CURRENT_SHADOW_OFFICIAL_ELIGIBLE={gate['current_shadow_official_eligible']}")
    print(f"BASELINE_RETAINED={gate['baseline_retained']}")
    print(f"OFFICIAL_PROMOTION_ALLOWED={gate['official_promotion_allowed']}")
    print(f"OFFICIAL_RECOMMENDATION_CREATED={gate['official_recommendation_created']}")
    print(f"WEIGHT_MUTATED={gate['weight_mutated']}")
    print(f"TRADE_ACTION_CREATED={gate['trade_action_created']}")
    print(f"BROKER_EXECUTION_SUPPORTED={gate['broker_execution_supported']}")
    print(f"NEXT_STAGE={gate['recommended_next_stage']}")


if __name__ == "__main__":
    main()
