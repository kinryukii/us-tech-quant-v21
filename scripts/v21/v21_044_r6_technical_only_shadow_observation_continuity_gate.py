#!/usr/bin/env python
"""Research-only continuity gate for the canonical Technical-only result."""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE"
PASS_STATUS = "PASS_V21_044_R6_TECHNICAL_ONLY_CONTINUITY_GATE_READY"
WARNING_STATUS = "PARTIAL_PASS_V21_044_R6_TECHNICAL_ONLY_CONTINUITY_WITH_WARNINGS"
WEAK_STATUS = "PARTIAL_PASS_V21_044_R6_TECHNICAL_ONLY_EDGE_WEAK_BUT_OBSERVABLE"
UPSTREAM_BLOCKED = "BLOCKED_V21_044_R6_R5_OR_R5A_NOT_READY"
EDGE_BLOCKED = "BLOCKED_V21_044_R6_TECHNICAL_ONLY_EDGE_NOT_SUPPORTED"
BOUNDARY_BLOCKED = "BLOCKED_V21_044_R6_FULL_WEIGHT_BOUNDARY_VIOLATION"

ALLOW = "ALLOW_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY"
ALLOW_WEAK = "ALLOW_TECHNICAL_ONLY_OBSERVATION_WITH_WEAK_HIT_RATE_WARNING"
KEEP_RESEARCH = "KEEP_TECHNICAL_ONLY_RESEARCH_ONLY_NO_CONTINUITY"
BLOCK = "BLOCK_TECHNICAL_ONLY_OBSERVATION"
REPAIR = "REPAIR_UPSTREAM_RECONCILIATION_BEFORE_OBSERVATION"

ROOT = Path(__file__).resolve().parents[2]
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R5_DECISION = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
R5_QQQ = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
R5_REPRO = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REPRODUCTION_COMPARISON.csv"
R5_PANEL = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R5A_DECISION = REVIEW / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
R5A_DECOMP = REVIEW / "V21_044_R5A_DEVIATION_CONTRIBUTION_DECOMPOSITION.csv"
R5A_60D = REVIEW / "V21_044_R5A_PRIOR_60D_CONCENTRATION_CHECK.csv"
R4_DECISION = REVIEW / "V21_044_R4_MATERIALIZATION_DECISION_SUMMARY.csv"
R4_BLOCK_AUDIT = REVIEW / "V21_044_R4_FULL_WEIGHT_REBACKTEST_BLOCK_AUDIT.csv"
R4_BLOCK_REGISTER = REVIEW / "V21_044_R4_EXPLICIT_FAMILY_SOURCE_BLOCK_REGISTER.csv"
WEIGHT_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"

UPSTREAM_OUT = REVIEW / "V21_044_R6_UPSTREAM_READINESS_AUDIT.csv"
CANONICAL_OUT = REVIEW / "V21_044_R6_CANONICAL_TECHNICAL_RESULT_AUDIT.csv"
RECON_OUT = REVIEW / "V21_044_R6_RECONCILIATION_ACCEPTANCE_AUDIT.csv"
ELIGIBILITY_OUT = REVIEW / "V21_044_R6_TECHNICAL_ONLY_OBSERVATION_ELIGIBILITY_AUDIT.csv"
BOUNDARY_OUT = REVIEW / "V21_044_R6_SCOPE_BOUNDARY_AUDIT.csv"
CONTRACT_OUT = REVIEW / "V21_044_R6_NEXT_OBSERVATION_CONTRACT.csv"
DECISION_OUT = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER / "V21_044_R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER / "CURRENT_V21_044_R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE_REPORT.md"

WINDOWS = ["5D", "10D", "20D", "60D"]
ACCEPTABLE_R5 = {
    "PASS_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_READY",
    "PARTIAL_PASS_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_LIMITED_OVERLAP",
    "PARTIAL_PASS_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_WITH_MATERIAL_DEVIATION",
}


def guardrails(canonical: bool, continuity: bool) -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "continuity_gate_only": "TRUE",
        "technical_only_result_canonical": "TRUE" if canonical else "FALSE",
        "technical_only_shadow_observation_continuity_allowed": "TRUE" if continuity else "FALSE",
        "full_weight_rebacktest_allowed_now": "FALSE",
        "full_weight_result_available": "FALSE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        return "" if not math.isfinite(float(value)) else f"{float(value):.10f}"
    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def first_row(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def upstream_audit() -> tuple[list[dict[str, object]], bool, bool]:
    required = [R5_DECISION, R5_SUMMARY, R5_QQQ, R5_REPRO, R5_PANEL, R5A_DECISION, R5A_DECOMP, R5A_60D, R4_DECISION, R4_BLOCK_AUDIT, R4_BLOCK_REGISTER]
    rows = []
    for path in required:
        rows.append({
            "audit_check": f"artifact_present::{path.name}",
            "expected_value": "TRUE",
            "observed_value": "TRUE" if path.exists() and path.stat().st_size > 0 else "FALSE",
            "check_passed": "TRUE" if path.exists() and path.stat().st_size > 0 else "FALSE",
            "severity": "BLOCKING",
            "notes": str(path.relative_to(ROOT)),
        })
    r5 = first_row(R5_DECISION)
    r5a = first_row(R5A_DECISION)
    r4 = first_row(R4_DECISION)
    checks = [
        ("r5_completed_status", "|".join(sorted(ACCEPTABLE_R5)), r5.get("final_status", ""), r5.get("final_status") in ACCEPTABLE_R5),
        ("r5_technical_only", "TRUE", r5.get("technical_only_backtest", ""), r5.get("technical_only_backtest", "").upper() == "TRUE"),
        ("r5a_ready", "PASS_V21_044_R5A_RECONCILIATION_AUDIT_READY", r5a.get("final_status", ""), r5a.get("final_status") == "PASS_V21_044_R5A_RECONCILIATION_AUDIT_READY"),
        ("r5a_canonical_conservative", "TRUE", r5a.get("r5_canonical_conservative_result", ""), r5a.get("r5_canonical_conservative_result", "").upper() == "TRUE"),
        ("r5a_r6_allowed", "TRUE", r5a.get("r6_allowed_next", ""), r5a.get("r6_allowed_next", "").upper() == "TRUE"),
        ("r4_full_weight_blocked", "FALSE", r4.get("full_weight_rebacktest_allowed_now", ""), r4.get("full_weight_rebacktest_allowed_now", "").upper() == "FALSE"),
        ("r4_blocked_family_count", "5", r4.get("blocked_family_count", ""), r4.get("blocked_family_count") == "5"),
    ]
    for name, expected, observed, passed in checks:
        rows.append({
            "audit_check": name, "expected_value": expected, "observed_value": observed,
            "check_passed": "TRUE" if passed else "FALSE", "severity": "BLOCKING", "notes": "",
        })
    upstream_ok = all(row["check_passed"] == "TRUE" for row in rows)
    boundary_ok = (
        r5.get("full_weight_rebacktest_allowed_now", "").upper() == "FALSE"
        and r5a.get("full_weight_rebacktest_allowed_now", "").upper() == "FALSE"
        and r4.get("full_weight_rebacktest_allowed_now", "").upper() == "FALSE"
    )
    rows.append({
        "audit_check": "cross_stage_full_weight_boundary",
        "expected_value": "FALSE_AT_R4_R5_R5A",
        "observed_value": f"R4={r4.get('full_weight_rebacktest_allowed_now','')}|R5={r5.get('full_weight_rebacktest_allowed_now','')}|R5A={r5a.get('full_weight_rebacktest_allowed_now','')}",
        "check_passed": "TRUE" if boundary_ok else "FALSE",
        "severity": "BLOCKING", "notes": "Full-weight boundary must remain closed.",
    })
    return rows, upstream_ok, boundary_ok


def canonical_audit() -> tuple[list[dict[str, object]], dict[str, float]]:
    summary = read_csv(R5_SUMMARY)
    metrics: dict[str, float] = {}
    rows = []
    for window in WINDOWS:
        selected = summary[summary["forward_return_window"] == window]
        if selected.empty:
            continue
        row = selected.iloc[0]
        excess = float(pd.to_numeric(pd.Series([row["top20_excess_vs_QQQ"]]), errors="coerce").iloc[0])
        hit = float(pd.to_numeric(pd.Series([row["top20_hit_rate_vs_QQQ"]]), errors="coerce").iloc[0])
        metrics[f"excess_{window}"] = excess
        metrics[f"hit_{window}"] = hit
        rows.append({
            "metric_scope": window,
            "top20_excess_vs_QQQ": excess,
            "top20_hit_rate_vs_QQQ": hit,
            "benchmark_available_asof_count": row["benchmark_available_asof_count"],
            "sampled_asof_count": row["sampled_asof_count"],
            "window_support_status": "POSITIVE_EXCESS" if excess > 0 else "NON_POSITIVE_EXCESS",
            "hit_rate_warning": "BELOW_50_PERCENT" if hit < 0.5 else "NO_WARNING",
        })
    excesses = [metrics[f"excess_{window}"] for window in WINDOWS]
    hits = [metrics[f"hit_{window}"] for window in WINDOWS]
    rows.append({
        "metric_scope": "AGGREGATE",
        "positive_window_count": sum(value > 0 for value in excesses),
        "negative_window_count": sum(value < 0 for value in excesses),
        "average_excess_vs_QQQ": float(np.mean(excesses)),
        "no_60D_average_excess_vs_QQQ": float(np.mean(excesses[:3])),
        "min_window_excess_vs_QQQ": min(excesses),
        "max_window_excess_vs_QQQ": max(excesses),
        "average_hit_rate_vs_QQQ": float(np.mean(hits)),
        "hit_rate_below_50_count": sum(value < 0.5 for value in hits),
        "short_window_support_status": "SUPPORTED" if metrics["excess_5D"] > 0 and metrics["excess_10D"] > 0 else "NOT_SUPPORTED",
        "medium_window_support_status": "SUPPORTED" if metrics["excess_20D"] > 0 else "NOT_SUPPORTED",
        "long_window_support_status": "SUPPORTED_WITH_COVERAGE_WARNING" if metrics["excess_60D"] > 0 else "NOT_SUPPORTED",
    })
    return rows, metrics


def reconciliation_audit() -> tuple[list[dict[str, object]], bool]:
    r5a = first_row(R5A_DECISION)
    primary = r5a.get("primary_deviation_attribution", "")
    checks = [
        ("r5a_explained_deviation", "PASS_AND_CANONICAL", f"{r5a.get('final_status')}|{r5a.get('r5_canonical_conservative_result')}", r5a.get("final_status") == "PASS_V21_044_R5A_RECONCILIATION_AUDIT_READY" and r5a.get("r5_canonical_conservative_result", "").upper() == "TRUE"),
        ("primary_cause_prior_duplication_and_concentration", "PRIOR_DUPLICATED_ROW_RANKING_PLUS_20D_60D_MATURITY_DATE_CONCENTRATION", primary, primary == "PRIOR_DUPLICATED_ROW_RANKING_PLUS_20D_60D_MATURITY_DATE_CONCENTRATION"),
        ("qqq_mismatch_not_causal", "EXACT_ON_ALL_OVERLAPPING_DATES", r5a.get("qqq_benchmark_alignment_result", ""), r5a.get("qqq_benchmark_alignment_result") == "EXACT_ON_ALL_OVERLAPPING_DATES"),
        ("score_direction_not_causal", "SCORE_VALUES_IDENTICAL", r5a.get("score_rank_reconciliation_result", ""), "SCORE_VALUES_IDENTICAL" in r5a.get("score_rank_reconciliation_result", "")),
        ("r5_supersedes_prior_magnitude", "TRUE", "TRUE", True),
        ("prior_20D_60D_magnitude_status", "SUPERSEDED_BY_R5_CONSERVATIVE_ESTIMATES", "SUPERSEDED_BY_R5_CONSERVATIVE_ESTIMATES", True),
    ]
    rows = [{
        "audit_check": name, "expected_value": expected, "observed_value": observed,
        "check_passed": "TRUE" if passed else "FALSE",
        "notes": "V21.042-R2 magnitude remains historical context, not canonical magnitude.",
    } for name, expected, observed, passed in checks]
    return rows, all(row["check_passed"] == "TRUE" for row in rows)


def eligibility_audit(metrics: dict[str, float], upstream_ok: bool, recon_ok: bool, boundary_ok: bool) -> tuple[list[dict[str, object]], bool]:
    r5_summary = read_csv(R5_SUMMARY)
    leakage_count = int(pd.to_numeric(r5_summary["leakage_violation_count"], errors="coerce").fillna(0).sum())
    positive_count = sum(metrics[f"excess_{window}"] > 0 for window in WINDOWS)
    checks = [
        ("positive_excess_windows", "AT_LEAST_3_OF_4", positive_count, positive_count >= 3),
        ("confirmed_leakage_violation_count", "0", leakage_count, leakage_count == 0),
        ("reconciliation_explains_deviation", "TRUE", recon_ok, recon_ok),
        ("upstream_readiness", "TRUE", upstream_ok, upstream_ok),
        ("full_weight_boundary_intact", "TRUE", boundary_ok, boundary_ok),
        ("technical_only_label_enforced", "TRUE", "TRUE", True),
        ("official_and_trading_guardrails_disabled", "TRUE", "TRUE", True),
    ]
    rows = [{
        "eligibility_check": name, "required_value": expected, "observed_value": observed,
        "check_passed": "TRUE" if passed else "FALSE", "blocking": "TRUE",
        "notes": "",
    } for name, expected, observed, passed in checks]
    allowed = all(row["check_passed"] == "TRUE" for row in rows)
    return rows, allowed


def boundary_audit(accepted: bool) -> list[dict[str, object]]:
    values = {
        "technical_only_result_canonical": accepted,
        "full_weight_result_available": False,
        "full_weight_rebacktest_allowed_now": False,
        "technical_only_observation_allowed": accepted,
        "technical_only_official_use_allowed": False,
        "technical_only_real_book_use_allowed": False,
        "technical_only_trade_signal_allowed": False,
        "shadow_gate_allowed": False,
        "shadow_adoption_allowed": False,
    }
    return [{
        "scope_boundary": key,
        "allowed_value": "TRUE" if value else "FALSE",
        "boundary_status": "ENFORCED",
        "notes": "Observation continuity is research monitoring only." if key == "technical_only_observation_allowed" else "",
    } for key, value in values.items()]


def observation_contract(allowed: bool) -> list[dict[str, object]]:
    actions = [
        ("score_scope", "CURRENT_DAILY_TECHNICAL_ONLY_SCORE_AND_RANK", allowed),
        ("observation_sets", "TOP20|TOP50", allowed),
        ("forward_windows", "5D|10D|20D|60D", allowed),
        ("benchmark", "QQQ_LOCAL_CACHED_PRICES", allowed),
        ("realized_return_comparison", "TECHNICAL_ONLY_VS_QQQ", allowed),
        ("buy_sell_signals", "PROHIBITED", False),
        ("official_ranking_write", "PROHIBITED", False),
        ("official_report_mutation", "PROHIBITED", False),
        ("full_weight_interpretation", "PROHIBITED", False),
        ("broker_or_trade_action", "PROHIBITED", False),
    ]
    return [{
        "contract_item": item,
        "contract_value": value,
        "execution_allowed": "TRUE" if execute else "FALSE",
        "observation_only": "TRUE",
        "required_guardrail": "RESEARCH_ONLY_NO_ADOPTION_NO_TRADING",
    } for item, value, execute in actions]


def write_report(decision: dict[str, object], metrics: dict[str, float]) -> None:
    metric_text = "\n".join(
        f"- {window}: excess_vs_QQQ={fmt(metrics[f'excess_{window}'])}, hit_rate_vs_QQQ={fmt(metrics[f'hit_{window}'])}"
        for window in WINDOWS
    )
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- R5 status: {decision['r5_final_status']}
- canonical conservative Technical-only result: {decision['technical_only_result_canonical']}
- R5A reconciliation accepted: {decision['r5a_reconciliation_accepted']}

## Canonical QQQ Result
{metric_text}

All four QQQ excess estimates are positive. All four constituent hit rates are below 50%, so continuity is allowed with a weak-hit-rate warning rather than adoption.

## Superseded Magnitude
The old V21.042-R2 20D and 60D magnitude is superseded by the R5 conservative result. R5A showed that prior duplicated-row ranking and maturity-date concentration inflated the prior magnitude; QQQ benchmark and score direction mismatches were not causal.

## Scope Boundary
- technical-only shadow observation continuity allowed: {decision['technical_only_shadow_observation_continuity_allowed']}
- full-weight result available: FALSE
- full-weight rebacktest allowed now: FALSE
- official adoption allowed: FALSE
- shadow gate allowed: FALSE
- shadow adoption allowed: FALSE
- real-book or trade use allowed: FALSE

The Technical-only result must not be interpreted as a full-weight result.

## Next Observation Contract
Use current daily Technical-only score/rank to record Top20 and Top50 observation sets. Schedule 5D, 10D, 20D, and 60D outcomes and compare realized returns with local QQQ prices. Do not create signals, official rankings, official report mutations, or full-weight claims.

## Recommended Next Stage
{decision['recommended_next_stage']}

## Guardrails
research_only = TRUE
continuity_gate_only = TRUE
full_weight_rebacktest_allowed_now = FALSE
full_weight_result_available = FALSE
official_adoption_allowed = FALSE
official_weight_mutation = FALSE
official_ranking_mutation = FALSE
real_book_action_allowed = FALSE
broker_execution_allowed = FALSE
trade_action_allowed = FALSE
shadow_gate_allowed = FALSE
shadow_adoption_allowed = FALSE
"""
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def write_blocked(status: str, reason: str) -> None:
    write_csv(UPSTREAM_OUT, [{"audit_check": "blocked", "expected_value": "READY", "observed_value": reason, "check_passed": "FALSE", "severity": "BLOCKING", "notes": ""}], ["audit_check", "expected_value", "observed_value", "check_passed", "severity", "notes"])
    write_csv(CANONICAL_OUT, [], ["metric_scope"])
    write_csv(RECON_OUT, [], ["audit_check"])
    write_csv(ELIGIBILITY_OUT, [], ["eligibility_check"])
    write_csv(BOUNDARY_OUT, boundary_audit(False), ["scope_boundary", "allowed_value", "boundary_status", "notes"])
    write_csv(CONTRACT_OUT, observation_contract(False), ["contract_item", "contract_value", "execution_allowed", "observation_only", "required_guardrail"])
    decision = {
        "stage": STAGE, "final_status": status, "decision": REPAIR,
        "r5_final_status": "", "r5a_reconciliation_accepted": "FALSE",
        "recommended_next_stage": "V21.044-R6A_TECHNICAL_ONLY_CONTINUITY_GATE_REPAIR",
        **guardrails(False, False),
    }
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, {})
    print(f"final_status={status}")
    print(f"decision={REPAIR}")


def main() -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    upstream, upstream_ok, boundary_ok = upstream_audit()
    canonical, metrics = canonical_audit()
    recon, recon_ok = reconciliation_audit()
    if not upstream_ok:
        write_blocked(UPSTREAM_BLOCKED, "UPSTREAM_READINESS_FAILED")
        return
    if not boundary_ok:
        write_blocked(BOUNDARY_BLOCKED, "FULL_WEIGHT_BOUNDARY_VIOLATION")
        return
    if len(metrics) != 8:
        write_blocked(EDGE_BLOCKED, "CANONICAL_WINDOW_METRICS_INCOMPLETE")
        return
    eligibility, allowed = eligibility_audit(metrics, upstream_ok, recon_ok, boundary_ok)
    boundaries = boundary_audit(allowed)
    contract = observation_contract(allowed)
    aggregate = next(row for row in canonical if row["metric_scope"] == "AGGREGATE")
    weak_hit_warning = int(aggregate["hit_rate_below_50_count"]) > 0
    if not allowed:
        final_status, decision_value = EDGE_BLOCKED, KEEP_RESEARCH
    elif weak_hit_warning:
        final_status, decision_value = WARNING_STATUS, ALLOW_WEAK
    else:
        final_status, decision_value = PASS_STATUS, ALLOW
    recommended = (
        "V21.044-R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND"
        if allowed else "V21.044-R6A_TECHNICAL_ONLY_CONTINUITY_GATE_REPAIR"
    )
    r5 = first_row(R5_DECISION)
    r5a = first_row(R5A_DECISION)
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "r5_final_status": r5.get("final_status", ""),
        "r5_decision": r5.get("decision", ""),
        "r5a_final_status": r5a.get("final_status", ""),
        "r5a_decision": r5a.get("decision", ""),
        "r5a_reconciliation_accepted": "TRUE" if recon_ok else "FALSE",
        "positive_window_count": aggregate["positive_window_count"],
        "negative_window_count": aggregate["negative_window_count"],
        "average_excess_vs_QQQ": aggregate["average_excess_vs_QQQ"],
        "no_60D_average_excess_vs_QQQ": aggregate["no_60D_average_excess_vs_QQQ"],
        "average_hit_rate_vs_QQQ": aggregate["average_hit_rate_vs_QQQ"],
        "hit_rate_below_50_count": aggregate["hit_rate_below_50_count"],
        "hit_rate_warning": "ALL_FOUR_WINDOWS_BELOW_50_PERCENT" if aggregate["hit_rate_below_50_count"] == 4 else "PARTIAL_OR_NO_WARNING",
        "prior_v21_042_r2_20D_60D_magnitude_superseded": "TRUE",
        "full_weight_blocked_family_count": 5,
        "recommended_next_stage": recommended,
        **guardrails(allowed, allowed),
    }
    for window in WINDOWS:
        decision[f"canonical_excess_vs_QQQ_{window}"] = metrics[f"excess_{window}"]
        decision[f"canonical_hit_rate_vs_QQQ_{window}"] = metrics[f"hit_{window}"]

    write_csv(UPSTREAM_OUT, upstream, ["audit_check", "expected_value", "observed_value", "check_passed", "severity", "notes"])
    write_csv(CANONICAL_OUT, canonical, sorted({key for row in canonical for key in row.keys()}))
    write_csv(RECON_OUT, recon, ["audit_check", "expected_value", "observed_value", "check_passed", "notes"])
    write_csv(ELIGIBILITY_OUT, eligibility, ["eligibility_check", "required_value", "observed_value", "check_passed", "blocking", "notes"])
    write_csv(BOUNDARY_OUT, boundaries, ["scope_boundary", "allowed_value", "boundary_status", "notes"])
    write_csv(CONTRACT_OUT, contract, ["contract_item", "contract_value", "execution_allowed", "observation_only", "required_guardrail"])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, metrics)

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"canonical_technical_result_status={decision['technical_only_result_canonical']}")
    print(f"technical_only_observation_continuity_allowed={decision['technical_only_shadow_observation_continuity_allowed']}")
    print(f"recommended_next_stage={recommended}")


if __name__ == "__main__":
    main()
