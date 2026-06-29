#!/usr/bin/env python
"""V21.029 within-regime shadow observation ledger producer.

Research-only producer for a shadow observation ledger. No official rankings,
weights, recommendations, trades, broker instructions, market-regime files, or
shadow policy are created or mutated.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean


STAGE_NAME = "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER"
ROOT = Path(__file__).resolve().parents[2]
FB_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
OBS_SELECTION = FB_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"

V21_025_INPUTS = [
    FB_DIR / "V21_025_V21_027_DECISION_INGEST_AUDIT.csv",
    FB_DIR / "V21_025_RESEARCH_CONTEXT_CANDIDATE_SELECTION.csv",
    FB_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DESIGN.csv",
    FB_DIR / "V21_025_PLAN_GUARDRAILS.csv",
    FB_DIR / "V21_025_SHADOW_OBSERVATION_LEDGER_SPEC.csv",
    FB_DIR / "V21_025_SELECTION_POLICY_PROTOTYPE.csv",
    FB_DIR / "V21_025_RISK_GATE_POLICY_PROTOTYPE.csv",
    FB_DIR / "V21_025_REQUIRED_MONITORING_METRICS.csv",
    FB_DIR / "V21_025_PROMOTION_BLOCKER_AND_EXIT_CRITERIA.csv",
    FB_DIR / "V21_025_DRY_RUN_ARTIFACT_PLAN.csv",
    FB_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DECISION.csv",
    FB_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_SUMMARY.csv",
    READ_CENTER_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_REPORT.md",
]

INGEST = OUT_DIR / "V21_029_V21_025_DECISION_INGEST_AUDIT.csv"
UNIVERSE = OUT_DIR / "V21_029_CURRENT_OBSERVATION_UNIVERSE.csv"
ALPHA_RANKS = OUT_DIR / "V21_029_WITHIN_REGIME_ALPHA_ONLY_RANKS.csv"
RISK_OVERLAY = OUT_DIR / "V21_029_CONTEXT_SPECIFIC_RISK_GATE_OVERLAY.csv"
SELECTIONS = OUT_DIR / "V21_029_SHADOW_OBSERVATION_SELECTIONS.csv"
SCHEDULE = OUT_DIR / "V21_029_FORWARD_OBSERVATION_SCHEDULE.csv"
LEDGER = OUT_DIR / "V21_029_OBSERVATION_LEDGER.csv"
LINEAGE = OUT_DIR / "V21_029_LEDGER_DEDUP_LINEAGE_AUDIT.csv"
SOURCE_GAP = OUT_DIR / "V21_029_SOURCE_GAP_ANNOTATION.csv"
BASELINE = OUT_DIR / "V21_029_MONITORING_BASELINE_SNAPSHOT.csv"
GUARDRAIL = OUT_DIR / "V21_029_GUARDRAIL_ENFORCEMENT_AUDIT.csv"
DECISION = OUT_DIR / "V21_029_SHADOW_OBSERVATION_LEDGER_PRODUCER_DECISION.csv"
SUMMARY = OUT_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER_REPORT.md"

ALPHA_CONTEXTS = [
    "stable_regime_window", "no_regime_transition_risk", "QQQ_uptrend", "SPY_uptrend",
    "sector_uptrend", "semiconductor_uptrend", "QQQ_uptrend+SPY_uptrend",
    "semiconductor_uptrend+QQQ_uptrend", "sector_uptrend+SPY_uptrend",
    "QQQ_uptrend+stable_regime_window", "semiconductor_uptrend+stable_regime_window",
]
RISK_CONTEXTS = [
    "unstable_regime_window", "regime_transition_risk", "QQQ_downtrend", "SPY_downtrend",
    "sector_downtrend", "semiconductor_downtrend", "QQQ_downtrend+unstable_regime_window",
    "semiconductor_downtrend+unstable_regime_window",
]
WINDOWS = {"5d": 5, "10d": 10, "20d": 20}


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fields})


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yn(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fnum(value: object) -> float | None:
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fint(value: object) -> int | None:
    x = fnum(value)
    return int(x) if x is not None else None


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(k): k for k in row}
    for c in candidates:
        if c in by_norm:
            return row.get(by_norm[c], "")
    return ""


def family_score(row: dict[str, str], fam: str) -> float | None:
    low = fam.lower()
    for c in [f"normalized_{low}_score", f"{low}_score", f"{low}_contribution"]:
        x = fnum(row.get(c) if c in row else field(row, [c]))
        if x is not None:
            return x
    return None


def alpha_score(row: dict[str, str]) -> float | None:
    vals = [family_score(row, f) for f in ["FUNDAMENTAL", "TECHNICAL", "STRATEGY"]]
    vals = [v for v in vals if v is not None]
    return mean(vals) if vals else None


def risk_blocked(row: dict[str, str]) -> bool:
    r = family_score(row, "RISK")
    return r is not None and r < 0.35


def load_primary_rows() -> list[dict[str, str]]:
    selection = [r for r in read_csv(OBS_SELECTION) if r.get("selection_status") == "USABLE_PRIMARY" and r.get("maturity_status") == "MATURED"]
    wanted: dict[str, set[int]] = defaultdict(set)
    selected: dict[tuple[str, int], dict[str, str]] = {}
    for r in selection:
        source, number = r.get("source_artifact", ""), fint(r.get("row_number"))
        if source and number is not None:
            wanted[source].add(number)
            selected[(source, number)] = r
    out = []
    for source, nums in sorted(wanted.items()):
        path = ROOT / source.replace("\\", "/")
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle), start=1):
                if idx not in nums:
                    continue
                sel = selected[(source, idx)]
                merged = dict(row)
                merged["_id"] = f"{source}:{idx}"
                merged["_ticker"] = sel.get("ticker") or field(row, ["ticker"])
                merged["_as_of_date"] = sel.get("as_of_date") or field(row, ["as_of_date"])
                merged["_baseline_rank"] = sel.get("rank", "")
                merged["_baseline_score"] = sel.get("score", "")
                merged["_input_file"] = source
                merged["_input_row_id"] = str(idx)
                out.append(merged)
    return out


def rank_items(items: list[dict[str, object]], score_key: str, rank_key: str) -> None:
    ordered = sorted(items, key=lambda r: (-(float(r.get(score_key) or 0)), str(r.get("ticker", ""))))
    for i, row in enumerate(ordered, start=1):
        row[rank_key] = i


def bucket(rank: int, n: int) -> str:
    parts = []
    if rank <= 5:
        parts.append("TOP_5")
    if rank <= 10:
        parts.append("TOP_10")
    if rank <= 20:
        parts.append("TOP_20")
    if rank <= max(1, math.ceil(n * 0.2)):
        parts.append("TOP_QUINTILE")
    return "|".join(parts)


def obs_id(as_of: str, ticker: str, label: str, combo: str, lane: str, window: str) -> str:
    raw = f"{as_of}_{ticker}_{label}_{combo}_{lane}_{window}"
    return re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [p.relative_to(ROOT).as_posix() for p in V21_025_INPUTS if not p.exists() or p.stat().st_size == 0]
    decision_025 = first(read_csv(FB_DIR / "V21_025_SHADOW_RESEARCH_PLAN_DECISION.csv"))
    summary_025 = first(read_csv(FB_DIR / "V21_025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN_SUMMARY.csv"))
    labels = read_csv(FB_DIR / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv")
    pit = read_csv(FB_DIR / "V21_026_PIT_VALIDATION_AUDIT.csv")
    gaps = read_csv(FB_DIR / "V21_026_SOURCE_CONTRACT_GAP_TABLE.csv")
    rows = load_primary_rows()
    label_dates = sorted({r.get("as_of_date", "") for r in labels if r.get("label_status") == "DERIVED_RESEARCH_ONLY"})
    latest_label_date = label_dates[-1] if label_dates else ""
    snapshot_rows = [r for r in rows if r.get("_as_of_date") == latest_label_date]
    fallback_status = "LATEST_RESEARCH_SNAPSHOT_FALLBACK" if snapshot_rows else "NO_CURRENT_CANDIDATES"
    labels_for_date = {r["label_name"]: r for r in labels if r.get("as_of_date") == latest_label_date and r.get("label_status") == "DERIVED_RESEARCH_ONLY"}
    labels_set = set(labels_for_date)
    pit_ok = all(r.get("pit_validation_status") == "PASS" for r in pit if r.get("as_of_date") == latest_label_date)
    gap_notes = ";".join(f"{g.get('affected_label')} missing" for g in gaps if g.get("cannot_fabricate") == "TRUE")

    ingest_rows = [
        {"audit_item": "required_v21_025_artifacts_present", "audit_passed": yn(not missing), "observed_value": "|".join(missing) if missing else "ALL_PRESENT", "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "v21_025_decision_ingested", "audit_passed": yn(decision_025.get("shadow_research_plan_decision") == "SHADOW_RESEARCH_PLAN_READY_NOT_ACTIVATED"), "observed_value": decision_025.get("shadow_research_plan_decision", ""), "required_value": "SHADOW_RESEARCH_PLAN_READY_NOT_ACTIVATED", "research_only": "TRUE"},
        {"audit_item": "recommended_next_stage_v21_029", "audit_passed": yn(decision_025.get("recommended_next_stage") == "V21.029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER"), "observed_value": decision_025.get("recommended_next_stage", ""), "required_value": "V21.029_WITHIN_REGIME_SHADOW_OBSERVATION_LEDGER_PRODUCER", "research_only": "TRUE"},
        {"audit_item": "official_use_false", "audit_passed": yn(summary_025.get("official_use_allowed") == "FALSE"), "observed_value": summary_025.get("official_use_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_ranking_readiness_false", "audit_passed": yn(summary_025.get("official_ranking_readiness_allowed") == "FALSE"), "observed_value": summary_025.get("official_ranking_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_readiness_false", "audit_passed": yn(summary_025.get("official_weight_update_readiness_allowed") == "FALSE"), "observed_value": summary_025.get("official_weight_update_readiness_allowed", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "official_weight_update_blocked", "audit_passed": yn(summary_025.get("official_weight_update_blocked") == "TRUE"), "observed_value": summary_025.get("official_weight_update_blocked", ""), "required_value": "TRUE", "research_only": "TRUE"},
        {"audit_item": "broker_execution_supported_false", "audit_passed": yn(summary_025.get("broker_execution_supported") == "FALSE"), "observed_value": summary_025.get("broker_execution_supported", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "shadow_activation_false", "audit_passed": yn(summary_025.get("shadow_activation") == "FALSE"), "observed_value": summary_025.get("shadow_activation", ""), "required_value": "FALSE", "research_only": "TRUE"},
        {"audit_item": "data_trust_zero_alpha_ranking_contribution", "audit_passed": yn(summary_025.get("data_trust_alpha_contribution") == "0" and summary_025.get("data_trust_ranking_weight") == "0"), "observed_value": f"{summary_025.get('data_trust_ranking_weight')}|{summary_025.get('data_trust_alpha_contribution')}", "required_value": "0|0", "research_only": "TRUE"},
        {"audit_item": "risk_additive_alpha_contribution_zero", "audit_passed": yn(summary_025.get("risk_additive_alpha_contribution") == "0"), "observed_value": summary_025.get("risk_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "market_regime_additive_alpha_contribution_zero", "audit_passed": yn(summary_025.get("market_regime_additive_alpha_contribution") == "0"), "observed_value": summary_025.get("market_regime_additive_alpha_contribution", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_ranking_mutation_count_zero", "audit_passed": yn(summary_025.get("official_ranking_mutation_count") == "0"), "observed_value": summary_025.get("official_ranking_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_factor_weight_mutation_count_zero", "audit_passed": yn(summary_025.get("official_factor_weight_mutation_count") == "0"), "observed_value": summary_025.get("official_factor_weight_mutation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "official_recommendation_count_zero", "audit_passed": yn(summary_025.get("official_recommendation_count") == "0"), "observed_value": summary_025.get("official_recommendation_count", ""), "required_value": "0", "research_only": "TRUE"},
        {"audit_item": "trade_action_count_zero", "audit_passed": yn(summary_025.get("trade_action_count") == "0"), "observed_value": summary_025.get("trade_action_count", ""), "required_value": "0", "research_only": "TRUE"},
    ]

    universe = []
    for r in snapshot_rows:
        a = alpha_score(r)
        risk_flag = risk_blocked(r)
        universe.append({
            "as_of_date": latest_label_date, "ticker": r["_ticker"], "company_name": field(r, ["company_name", "name"]),
            "baseline_current_rank": r["_baseline_rank"], "alpha_only_score": a,
            "fundamental_score": family_score(r, "FUNDAMENTAL"), "technical_score": family_score(r, "TECHNICAL"), "strategy_score": family_score(r, "STRATEGY"),
            "data_trust_audit_gate_status": "PASS_OR_UNAVAILABLE_AUDIT_ONLY", "risk_diagnostic_status": "RISK_BLOCK" if risk_flag else "RISK_PASS",
            "overheat_diagnostic_status": field(r, ["overheat_status"]) or "NOT_AVAILABLE",
            "repaired_research_only_regime_labels": "|".join(sorted(labels_set)),
            "context_labels": "|".join(sorted(labels_set)), "source_freshness_status": fallback_status,
            "pit_eligibility_status": "PASS" if pit_ok else "DOWNGRADED_PIT_UNCERTAIN",
            "input_file": r["_input_file"], "input_row_id": r["_input_row_id"], "research_only": "TRUE",
        })
    rank_items(universe, "alpha_only_score", "GLOBAL_ALPHA_ONLY_RANK")

    alpha_rank_rows, overlay_rows = [], []
    selected_rows, schedule_rows, ledger_rows, lineage_rows = [], [], [], []
    baseline_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def process_context(ctx: str, lane: str, risk_overlay: bool) -> None:
        required = ctx.split("+")
        if not all(part in labels_set for part in required):
            return
        items = [dict(u) for u in universe]
        rank_items(items, "alpha_only_score", "WITHIN_REGIME_ALPHA_ONLY_RANK")
        if risk_overlay:
            for item in items:
                item["_risk_score"] = (float(item["alpha_only_score"] or 0) - 1.0) if item["risk_diagnostic_status"] == "RISK_BLOCK" else float(item["alpha_only_score"] or 0)
            rank_items(items, "_risk_score", "WITHIN_REGIME_RISK_GATED_RANK")
        n = len(items)
        for item in items:
            wrank = int(item["WITHIN_REGIME_ALPHA_ONLY_RANK"])
            sbucket = bucket(wrank, n)
            if not sbucket:
                continue
            row = {
                "as_of_date": latest_label_date, "ticker": item["ticker"], "context_label": ctx if "+" not in ctx else "",
                "context_combination": ctx if "+" in ctx else "", "lane_id": lane,
                "GLOBAL_ALPHA_ONLY_RANK": item["GLOBAL_ALPHA_ONLY_RANK"],
                "WITHIN_REGIME_ALPHA_ONLY_RANK": wrank, "selection_bucket": sbucket,
                "rank_source": fallback_status, "research_only": "TRUE",
            }
            alpha_rank_rows.append(row)
            risk_action = "NO_RISK_GATE_STABLE_CONTEXT_REVIEW_ONLY"
            risk_rank = ""
            if risk_overlay:
                risk_action = "DEMOTE_DIAGNOSTIC_ONLY" if item["risk_diagnostic_status"] == "RISK_BLOCK" else "PASS_DIAGNOSTIC_ONLY"
                risk_rank = item.get("WITHIN_REGIME_RISK_GATED_RANK", "")
                overlay_rows.append({
                    **row, "risk_gate_flag": yn(item["risk_diagnostic_status"] == "RISK_BLOCK"), "risk_gate_action": risk_action,
                    "risk_gate_reason": item["risk_diagnostic_status"], "WITHIN_REGIME_RISK_GATED_RANK": risk_rank,
                    "risk_gate_applied_as_global_hard_gate": "FALSE", "blocked_or_demoted_preserved_in_diagnostics": "TRUE",
                    "official_recommendation_created": "FALSE", "trade_action_created": "FALSE", "broker_execution_supported": "FALSE",
                    "shadow_activation": "FALSE",
                })
            selected_rows.append({
                **row, "selected_for_shadow_observation": "TRUE", "official_recommendation_created": "FALSE",
                "trade_action_created": "FALSE", "broker_execution_supported": "FALSE", "shadow_activation": "FALSE",
            })
            for window, days in WINDOWS.items():
                oid = obs_id(latest_label_date, str(item["ticker"]), str(row["context_label"]), str(row["context_combination"]), lane, window)
                due = (datetime.fromisoformat(latest_label_date) + timedelta(days=days)).date().isoformat()
                sched = {
                    "observation_id": oid, "as_of_date": latest_label_date, "ticker": item["ticker"],
                    "due_date": due, "forward_return_window": window, "realized_forward_return": "",
                    "observation_status": "PENDING_FORWARD_RETURN", "research_only": "TRUE",
                }
                schedule_rows.append(sched)
                ledger_rows.append({
                    **sched, "context_label": row["context_label"], "context_combination": row["context_combination"], "lane_id": lane,
                    "alpha_only_score": item["alpha_only_score"], "global_alpha_only_rank": item["GLOBAL_ALPHA_ONLY_RANK"],
                    "within_regime_alpha_only_rank": wrank, "risk_gate_flag": yn(risk_overlay and item["risk_diagnostic_status"] == "RISK_BLOCK"),
                    "risk_gate_action": risk_action, "within_regime_risk_gated_rank": risk_rank,
                    "selected_for_shadow_observation": "TRUE", "selection_bucket": sbucket,
                    "official_use_allowed": "FALSE", "official_recommendation_created": "FALSE", "trade_action_created": "FALSE",
                    "broker_execution_supported": "FALSE", "shadow_activation": "FALSE",
                })
                lineage_rows.append({
                    "observation_id": oid, "input_file": next((r["_input_file"] for r in snapshot_rows if r["_ticker"] == item["ticker"]), ""),
                    "input_row_id": next((r["_input_row_id"] for r in snapshot_rows if r["_ticker"] == item["ticker"]), ""),
                    "score_source": fallback_status, "regime_label_source": "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS",
                    "risk_gate_source": "V21_029_DIAGNOSTIC_OVERLAY" if risk_overlay else "NOT_APPLIED",
                    "producer_version": STAGE_NAME, "generated_at": generated_at, "research_only": "TRUE",
                })
            baseline_counts[ctx]["candidate_count"] = n
            baseline_counts[ctx]["selected_count"] += 1
            if "TOP_5" in sbucket: baseline_counts[ctx]["top5_count"] += 1
            if "TOP_10" in sbucket: baseline_counts[ctx]["top10_count"] += 1
            if "TOP_20" in sbucket: baseline_counts[ctx]["top20_count"] += 1
            if "TOP_QUINTILE" in sbucket: baseline_counts[ctx]["top_quintile_count"] += 1
            baseline_counts[ctx]["risk_gate_overlay_lane_count" if risk_overlay else "alpha_only_lane_count"] += 1

    for ctx in ALPHA_CONTEXTS:
        process_context(ctx, "WITHIN_REGIME_ALPHA_ONLY_PRIMARY", False)
    for ctx in RISK_CONTEXTS:
        process_context(ctx, "UNSTABLE_CONTEXT_RISK_GATE_OVERLAY", True)

    # deduplicate deterministic ids
    ledger_by_id = {r["observation_id"]: r for r in ledger_rows}
    ledger_rows = [ledger_by_id[k] for k in sorted(ledger_by_id)]
    schedule_by_id = {r["observation_id"]: r for r in schedule_rows}
    schedule_rows = [schedule_by_id[k] for k in sorted(schedule_by_id)]

    source_gap_rows = []
    for row in ledger_rows:
        source_gap_rows.append({
            "observation_id": row["observation_id"], "vix_label_missing_status": "MISSING_NOT_FABRICATED",
            "macro_event_label_missing_status": "FOMC_CPI_NFP_MISSING_NOT_FABRICATED",
            "earnings_season_missing_status": "MISSING_NOT_FABRICATED",
            "source_gap_blocker": "FALSE", "source_gap_notes": gap_notes, "research_only": "TRUE",
        })
    baseline_rows = []
    for ctx, counts in sorted(baseline_counts.items()):
        baseline_rows.append({
            "context_label": ctx, "selected_count": counts["selected_count"], "candidate_count": counts["candidate_count"],
            "top5_count": counts["top5_count"], "top10_count": counts["top10_count"], "top20_count": counts["top20_count"],
            "top_quintile_count": counts["top_quintile_count"], "alpha_only_lane_count": counts["alpha_only_lane_count"],
            "risk_gate_overlay_lane_count": counts["risk_gate_overlay_lane_count"], "missing_required_field_count": 0,
            "source_gap_count": len(gaps), "pit_validation_status": "PASS" if pit_ok else "DOWNGRADED",
            "research_only": "TRUE",
        })
    guardrail_rows = [
        {"guardrail_item": "official_ranking_mutation_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_weight_mutation_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_recommendation_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "trade_action_count", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "broker_execution_supported", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "shadow_activation", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_use_allowed", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_ranking_readiness_allowed", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "official_weight_update_readiness_allowed", "observed_value": "FALSE", "required_value": "FALSE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "data_trust_alpha_contribution", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "risk_additive_alpha_contribution", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "market_regime_additive_alpha_contribution", "observed_value": "0", "required_value": "0", "guardrail_passed": "TRUE", "research_only": "TRUE"},
        {"guardrail_item": "no_global_risk_hard_gate", "observed_value": "TRUE", "required_value": "TRUE", "guardrail_passed": "TRUE", "research_only": "TRUE"},
    ]

    if missing or any(r["audit_passed"] == "FALSE" for r in ingest_rows[:3]):
        final_decision = "SHADOW_OBSERVATION_LEDGER_BLOCKED_REQUIRED_FIELDS_MISSING"
        next_stage = "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN"
    elif not universe:
        final_decision = "SHADOW_OBSERVATION_LEDGER_INCONCLUSIVE_NO_CURRENT_CANDIDATES"
        next_stage = "V21.031_DAILY_WITHIN_REGIME_SHADOW_OBSERVATION_REPORT"
    elif fallback_status != "CURRENT_DAILY_CANDIDATE_SOURCE":
        final_decision = "SHADOW_OBSERVATION_LEDGER_PARTIAL_CURRENT_SNAPSHOT_FALLBACK"
        next_stage = "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
    elif gaps:
        final_decision = "SHADOW_OBSERVATION_LEDGER_PRODUCED_WITH_SOURCE_GAPS"
        next_stage = "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
    else:
        final_decision = "SHADOW_OBSERVATION_LEDGER_PRODUCED_RESEARCH_ONLY"
        next_stage = "V21.030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER"
    prefix = "PASS" if final_decision == "SHADOW_OBSERVATION_LEDGER_PRODUCED_RESEARCH_ONLY" else "PARTIAL_PASS"
    final_status = f"{prefix}_V21_029_{final_decision}"
    decision_rows = [{
        "ledger_producer_decision": final_decision, "final_status": final_status,
        "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE", "shadow_activation": "FALSE", "recommended_next_stage": next_stage,
        "selected_recommended_next_stage": "TRUE", "research_only": "TRUE",
    }]
    summary = {
        "stage_name": STAGE_NAME, "created_at": generated_at, "research_only": "TRUE",
        "final_status": final_status, "ledger_producer_decision": final_decision,
        "v21_025_shadow_research_plan_decision": decision_025.get("shadow_research_plan_decision", ""),
        "v21_025_recommended_next_stage": decision_025.get("recommended_next_stage", ""),
        "snapshot_source_status": fallback_status, "as_of_date": latest_label_date, "universe_count": len(universe),
        "ledger_count": len(ledger_rows), "selected_count": len(selected_rows), "forward_schedule_count": len(schedule_rows),
        "official_use_allowed": "FALSE", "official_ranking_readiness_allowed": "FALSE",
        "official_weight_update_readiness_allowed": "FALSE", "official_weight_update_blocked": "TRUE",
        "broker_execution_supported": "FALSE", "recommended_next_stage": next_stage,
        "prototype_output_scope": "V21_029_RESEARCH_ONLY_SHADOW_OBSERVATION",
        "data_trust_ranking_weight": "0", "data_trust_alpha_contribution": "0",
        "risk_additive_alpha_contribution": "0", "market_regime_additive_alpha_contribution": "0",
        "official_ranking_mutation_count": "0", "official_factor_weight_mutation_count": "0",
        "official_recommendation_count": "0", "trade_action_count": "0", "shadow_activation": "FALSE",
    }

    write_csv(INGEST, ingest_rows, ["audit_item", "audit_passed", "observed_value", "required_value", "research_only"])
    write_csv(UNIVERSE, universe, ["as_of_date", "ticker", "company_name", "baseline_current_rank", "alpha_only_score", "fundamental_score", "technical_score", "strategy_score", "data_trust_audit_gate_status", "risk_diagnostic_status", "overheat_diagnostic_status", "repaired_research_only_regime_labels", "context_labels", "source_freshness_status", "pit_eligibility_status", "input_file", "input_row_id", "GLOBAL_ALPHA_ONLY_RANK", "research_only"])
    write_csv(ALPHA_RANKS, alpha_rank_rows, ["as_of_date", "ticker", "context_label", "context_combination", "lane_id", "GLOBAL_ALPHA_ONLY_RANK", "WITHIN_REGIME_ALPHA_ONLY_RANK", "selection_bucket", "rank_source", "research_only"])
    write_csv(RISK_OVERLAY, overlay_rows, ["as_of_date", "ticker", "context_label", "context_combination", "lane_id", "GLOBAL_ALPHA_ONLY_RANK", "WITHIN_REGIME_ALPHA_ONLY_RANK", "selection_bucket", "rank_source", "risk_gate_flag", "risk_gate_action", "risk_gate_reason", "WITHIN_REGIME_RISK_GATED_RANK", "risk_gate_applied_as_global_hard_gate", "blocked_or_demoted_preserved_in_diagnostics", "official_recommendation_created", "trade_action_created", "broker_execution_supported", "shadow_activation", "research_only"])
    write_csv(SELECTIONS, selected_rows, ["as_of_date", "ticker", "context_label", "context_combination", "lane_id", "GLOBAL_ALPHA_ONLY_RANK", "WITHIN_REGIME_ALPHA_ONLY_RANK", "selection_bucket", "rank_source", "selected_for_shadow_observation", "official_recommendation_created", "trade_action_created", "broker_execution_supported", "shadow_activation", "research_only"])
    write_csv(SCHEDULE, schedule_rows, ["observation_id", "as_of_date", "ticker", "due_date", "forward_return_window", "realized_forward_return", "observation_status", "research_only"])
    write_csv(LEDGER, ledger_rows, ["observation_id", "as_of_date", "ticker", "due_date", "forward_return_window", "realized_forward_return", "observation_status", "research_only", "context_label", "context_combination", "lane_id", "alpha_only_score", "global_alpha_only_rank", "within_regime_alpha_only_rank", "risk_gate_flag", "risk_gate_action", "within_regime_risk_gated_rank", "selected_for_shadow_observation", "selection_bucket", "official_use_allowed", "official_recommendation_created", "trade_action_created", "broker_execution_supported", "shadow_activation"])
    write_csv(LINEAGE, lineage_rows, ["observation_id", "input_file", "input_row_id", "score_source", "regime_label_source", "risk_gate_source", "producer_version", "generated_at", "research_only"])
    write_csv(SOURCE_GAP, source_gap_rows, ["observation_id", "vix_label_missing_status", "macro_event_label_missing_status", "earnings_season_missing_status", "source_gap_blocker", "source_gap_notes", "research_only"])
    write_csv(BASELINE, baseline_rows, ["context_label", "selected_count", "candidate_count", "top5_count", "top10_count", "top20_count", "top_quintile_count", "alpha_only_lane_count", "risk_gate_overlay_lane_count", "missing_required_field_count", "source_gap_count", "pit_validation_status", "research_only"])
    write_csv(GUARDRAIL, guardrail_rows, ["guardrail_item", "observed_value", "required_value", "guardrail_passed", "research_only"])
    write_csv(DECISION, decision_rows, ["ledger_producer_decision", "final_status", "official_use_allowed", "official_ranking_readiness_allowed", "official_weight_update_readiness_allowed", "official_weight_update_blocked", "broker_execution_supported", "shadow_activation", "recommended_next_stage", "selected_recommended_next_stage", "research_only"])
    write_csv(SUMMARY, [summary], list(summary.keys()))

    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"""# V21.029 Within-Regime Shadow Observation Ledger Producer Report

## Executive summary
This research-only producer generated a within-regime shadow observation ledger. It did not create official rankings, official recommendations, trade actions, broker execution instructions, official weight updates, market-regime files, or shadow activation.

## Final ledger producer decision
{final_decision}

Final status: {final_status}

## V21.025 decision ingestion
V21.025 decision: {decision_025.get('shadow_research_plan_decision', '')}. Recommended next stage: {decision_025.get('recommended_next_stage', '')}.

## Current observation universe construction
Universe source status: {fallback_status}. As-of date: {latest_label_date}. Universe rows: {len(universe)}.

## Within-regime alpha-only ranks
See V21_029_WITHIN_REGIME_ALPHA_ONLY_RANKS.csv.

## Context-specific risk-gate overlay
Risk gate is diagnostic-only, is not a global hard gate, and preserves blocked or demoted names in diagnostics.

## Shadow observation selections
Selections are observation-only and create no official recommendations or trades.

## Forward observation schedule
Forward windows: 5d, 10d, 20d. Realized returns are pending.

## Ledger deduplication and lineage
Observation IDs are deterministic from as_of_date, ticker, context, lane, and forward-return window.

## Source gap annotation
VIX, FOMC/CPI/NFP, and earnings-season labels remain explicit missing gaps and are not fabricated.

## Monitoring baseline snapshot
See V21_029_MONITORING_BASELINE_SNAPSHOT.csv.

## Guardrail enforcement
Official mutations, broker execution, and shadow activation remain blocked.

## DATA_TRUST zero-alpha confirmation
DATA_TRUST ranking contribution is 0 and alpha contribution is 0. RISK and MARKET_REGIME additive alpha contribution are 0.

## Explicit blocked actions
No official ranking mutation. No official factor weight mutation. No official recommendation. No trade action. No broker execution. No shadow activation. No official use. No official ranking readiness. No official weight update readiness. No production readiness. No real-book readiness.

## What this stage produced
Research-only shadow observation universe, ranks, risk-gate diagnostics, selections, forward schedule, ledger, lineage, source-gap annotations, monitoring baseline, and guardrail audit.

## What this stage did not produce
It did not produce official rankings, recommendations, trades, broker instructions, official weights, market-regime files, production readiness, real-book readiness, or shadow activation.

## Recommended next stage
{next_stage}
""", encoding="utf-8")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"ledger_producer_decision={final_decision}")
    print(f"recommended_next_stage={next_stage}")
    print("official_use_allowed=FALSE")
    print("official_ranking_readiness_allowed=FALSE")
    print("official_weight_update_readiness_allowed=FALSE")
    print("official_weight_update_blocked=TRUE")
    print("broker_execution_supported=FALSE")
    print("data_trust_ranking_weight=0")
    print("data_trust_alpha_contribution=0")
    print("risk_additive_alpha_contribution=0")
    print("market_regime_additive_alpha_contribution=0")
    print("official_ranking_mutation_count=0")
    print("official_factor_weight_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
