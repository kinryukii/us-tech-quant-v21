#!/usr/bin/env python
"""V21.121 research-only candidate rebase review for A1/B/C/D/D-R2C."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"
OUT = ROOT / "outputs/v21/V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"

SOURCES = {
    "V21.117": ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR/V21.117_manifest.json",
    "V21.117_R1": ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION/V21.117_R1_manifest.json",
    "V21.118": ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN/V21.118_manifest.json",
    "V21.118_R1": ROOT / "outputs/v21/V21.118_R1_D_R2C_OVERFIT_GUARD_AND_FORWARD_TRACKING/V21.118_R1_manifest.json",
    "V21.119": ROOT / "outputs/v21/V21.119_FORWARD_MATURITY_UPDATE_FOR_ABCD_AND_D_R2C/V21.119_manifest.json",
    "V21.119_R1": ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH/V21.119_R1_manifest.json",
    "V21.119_R2": ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON/V21.119_R2_manifest.json",
    "V21.120": ROOT / "outputs/v21/V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE/V21.120_manifest.json",
}

V116_SUMMARY = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST/V21.116_daily_top50_full_data_ledger_summary.json"
R1_PANEL = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH/forward_maturity_by_date_horizon_after_refresh.csv"
R1_PAIR_NEW = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH/pairwise_winrate_new_maturity_only_after_refresh.csv"
R2_BC = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON/bc_superiority_audit.csv"
R2_CONCENTRATION = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON/new_maturity_concentration_diagnostics.csv"
R2_REPEATED = ROOT / "outputs/v21/V21.119_R2_NEW_MATURITY_ATTRIBUTION_AND_BC_COMPARISON/d_r2c_repeated_loser_new_maturity_update.csv"

CANDIDATES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
    "D_R2C_BC_CONFIRMATION_OVERLAY",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def missing_inputs() -> list[str]:
    required = list(SOURCES.values()) + [V116_SUMMARY, R1_PANEL, R1_PAIR_NEW, R2_BC, R2_CONCENTRATION, R2_REPEATED]
    return [rel(path) for path in required if not path.is_file()]


def get_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key, math.nan)
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def pair_metric(pair: pd.DataFrame, comparison: str, topn: int, field: str = "win_rate") -> float:
    sub = pair[(pair["comparison"].eq(comparison)) & (pair["top_n"].eq(topn)) & (pair["available_observations"] > 0)]
    return float(sub[field].mean()) if not sub.empty else math.nan


def blocked(missing: list[str]) -> dict[str, Any]:
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_121_MISSING_REQUIRED_INPUTS",
        "DECISION": "BLOCKED_MISSING_REQUIRED_INPUTS",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "V21.121_manifest.json", manifest)
    (OUT / "V21.121_candidate_rebase_review_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def evidence_type(stage: str) -> str:
    if stage in {"V21.117", "V21.118", "V21.118_R1", "V21.119"}:
        return "IN_SAMPLE_OR_DESIGN_WINDOW"
    if stage in {"V21.119_R1"}:
        return "NEWLY_MATURED_AFTER_REFRESH"
    if stage in {"V21.119_R2"}:
        return "ATTRIBUTION_ONLY_NEW_MATURITY"
    if stage == "V21.120":
        return "DATA_REFRESH_AND_MATURITY_GATE"
    return "DIAGNOSTIC"


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        return blocked(missing)

    manifests = {name: load_json(path) for name, path in SOURCES.items()}
    v116 = load_json(V116_SUMMARY)
    r1 = manifests["V21.119_R1"]
    r2 = manifests["V21.119_R2"]
    v117 = manifests["V21.117"]
    v117r1 = manifests["V21.117_R1"]
    v118 = manifests["V21.118"]
    v118r1 = manifests["V21.118_R1"]

    evidence_rows = []
    for name, payload in manifests.items():
        status_text = str(payload.get("FINAL_STATUS", ""))
        warning_value = payload.get("overfit_warning", "WARN" in status_text)
        evidence_rows.append({
            "source_stage": name,
            "source_path": rel(SOURCES[name]),
            "evidence_type": evidence_type(name),
            "FINAL_STATUS": payload.get("FINAL_STATUS", ""),
            "DECISION": payload.get("DECISION", ""),
            "latest_price_date": payload.get("latest_price_date_used", payload.get("latest_price_date_after_refresh", "")),
            "matured_observations": payload.get("matured_observation_count", payload.get("all_matured_observation_count", "")),
            "newly_matured_observations": payload.get("newly_matured_observation_count", payload.get("newly_matured_observation_count_analyzed", "")),
            "key_metric_1": payload.get("D_R2C_vs_original_D_Top20_win_rate_newly_matured_only", payload.get("D_vs_A1_Top20_win_rate", "")),
            "key_metric_2": payload.get("D_R2C_vs_SOXX_average_excess_newly_matured_only", payload.get("D_vs_SOXX_Top20_excess_average", "")),
            "warning": bool(warning_value),
            "protected_outputs_modified": payload.get("protected_outputs_modified", False),
            "official_adoption_allowed": payload.get("official_adoption_allowed", False),
            "broker_action_allowed": payload.get("broker_action_allowed", False),
            "research_only": payload.get("research_only", True),
        })
    write_csv(OUT / "evidence_ledger_v21_117_to_v21_120.csv", evidence_rows)

    panel = pd.read_csv(R1_PANEL, low_memory=False)
    new_top20 = panel[panel["observation_bucket"].eq("NEWLY_MATURED_AFTER_V21_120_REFRESH") & panel["top_n"].eq(20)]
    avg_return = new_top20.groupby("strategy")["equal_weight_return"].mean().to_dict()
    avg_soxx_excess = new_top20.groupby("strategy")["excess_vs_SOXX"].mean().to_dict()
    avg_qqq_excess = new_top20.groupby("strategy")["excess_vs_QQQ"].mean().to_dict()
    pair_new = pd.read_csv(R1_PAIR_NEW, low_memory=False)
    concentration = pd.read_csv(R2_CONCENTRATION, low_memory=False).iloc[0].to_dict()
    bc = pd.read_csv(R2_BC, low_memory=False).iloc[0].to_dict()

    d2c_vs = {
        "A1_BASELINE_CONTROL": get_float(r1, "D_R2C_vs_A1_Top20_win_rate_newly_matured_only"),
        "B_STATIC_MOMENTUM_BLEND": get_float(r1, "D_R2C_vs_B_Top20_win_rate_newly_matured_only"),
        "C_DYNAMIC_MOMENTUM_BLEND": get_float(r1, "D_R2C_vs_C_Top20_win_rate_newly_matured_only"),
        "D_WEIGHT_OPTIMIZED_R1": get_float(r1, "D_R2C_vs_original_D_Top20_win_rate_newly_matured_only"),
    }
    scorecard_rows = []
    for candidate in CANDIDATES:
        if candidate == "D_WEIGHT_OPTIMIZED_R1":
            repeated = int(v117.get("D_Top20_repeated_loser_count", 0))
            overfit = True
            role = "FROZEN_OR_DOWNGRADED_RESEARCH_REFERENCE"
            stability = v117.get("D_Top50_stability_assessment", "unknown")
        elif candidate == "D_R2C_BC_CONFIRMATION_OVERLAY":
            repeated = int(v118r1.get("repeated_loser_count_D_R2C", 0))
            overfit = bool(r2.get("overfit_warning", True))
            role = "SECONDARY_RESEARCH_CANDIDATE_TRACKING_ONLY"
            stability = "Top50 stable, Top20 overfit/concentration unresolved"
        else:
            repeated = ""
            overfit = False
            role = "PRIMARY_CONTROL_AND_CURRENT_EVIDENCE_LEADER" if candidate == "A1_BASELINE_CONTROL" and r2.get("evidence_favors") == "A1" else "RESEARCH_CANDIDATE_TRACKING"
            stability = "stable enough for continued tracking"
        scorecard_rows.append({
            "candidate": candidate,
            "new_maturity_top20_average_return": avg_return.get(candidate, math.nan),
            "new_maturity_top20_excess_vs_QQQ": avg_qqq_excess.get(candidate, math.nan),
            "new_maturity_top20_excess_vs_SOXX": avg_soxx_excess.get(candidate, math.nan),
            "D_R2C_pairwise_win_rate_vs_candidate_new_maturity": d2c_vs.get(candidate, math.nan) if candidate != "D_R2C_BC_CONFIRMATION_OVERLAY" else "",
            "repeated_loser_exposure": repeated,
            "concentration_warning": bool(concentration.get("concentrated_improvement", False)) if candidate == "D_R2C_BC_CONFIRMATION_OVERLAY" else False,
            "overfit_warning": overfit,
            "maturity_sufficiency": "partial_new_maturity_available_30_observations",
            "stability": stability,
            "interpretability": "baseline control" if candidate == "A1_BASELINE_CONTROL" else "momentum blend" if candidate.startswith(("B_", "C_")) else "weight optimized repair overlay" if candidate.startswith("D_R2C") else "original optimized D",
            "eligible_for_further_tracking": True,
            "eligible_for_official_adoption": False,
            "research_role": role,
        })
    write_csv(OUT / "candidate_scorecard_a1_b_c_d_d_r2c.csv", scorecard_rows)

    d_review = [{
        "D_original_status": "DOWNGRADED_OR_FROZEN_RESEARCH_REFERENCE",
        "D_original_failure_mode": v117r1.get("primary_D_weakness_classification", ""),
        "D_original_top20_should_be_downgraded_or_frozen": True,
        "D_R2C_status": "FROZEN_SECONDARY_TRACKING_ONLY_NOT_ADOPTABLE",
        "D_R2C_improves_original_D": bool(get_float(r1, "D_R2C_vs_original_D_Top20_win_rate_newly_matured_only") > 0.5),
        "D_R2C_overfit_reduced_but_not_resolved": r2.get("overfit_status") == "REDUCED_BUT_NOT_RESOLVED",
        "concentrated_SOXX_alpha_blocks_adoption": r2.get("SOXX_alpha_broad_based_or_concentrated") == "concentrated",
        "repeated_loser_issue_unresolved": not bool(r2.get("repeated_loser_problem_meaningfully_improved", False)),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }]
    write_csv(OUT / "d_and_d_r2c_downgrade_review.csv", d_review)

    evidence_favors = str(r2.get("evidence_favors", "NO_CLEAR_WINNER"))
    primary_control = "A1_BASELINE_CONTROL"
    if evidence_favors == "A1":
        primary_research = "A1_BASELINE_CONTROL"
        secondary_research = "B_STATIC_MOMENTUM_BLEND;C_DYNAMIC_MOMENTUM_BLEND;D_R2C_BC_CONFIRMATION_OVERLAY_TRACKING_ONLY"
        matrix_decision = "KEEP_A1_PRIMARY_CONTROL_BC_RESEARCH_D_R2C_SECONDARY"
        a1_status = "PRIMARY_CONTROL_AND_CURRENT_EVIDENCE_LEADER"
        b_status = "SECONDARY_RESEARCH_CANDIDATE"
        c_status = "SECONDARY_RESEARCH_CANDIDATE"
    elif evidence_favors == "B":
        primary_research = "B_STATIC_MOMENTUM_BLEND"
        secondary_research = "A1_BASELINE_CONTROL;C_DYNAMIC_MOMENTUM_BLEND;D_R2C_BC_CONFIRMATION_OVERLAY_TRACKING_ONLY"
        matrix_decision = "PROMOTE_B_PRIMARY_RESEARCH_CANDIDATE"
        a1_status = "PRIMARY_CONTROL"
        b_status = "PRIMARY_RESEARCH_CANDIDATE"
        c_status = "SECONDARY_RESEARCH_CANDIDATE"
    elif evidence_favors == "C":
        primary_research = "C_DYNAMIC_MOMENTUM_BLEND"
        secondary_research = "A1_BASELINE_CONTROL;B_STATIC_MOMENTUM_BLEND;D_R2C_BC_CONFIRMATION_OVERLAY_TRACKING_ONLY"
        matrix_decision = "PROMOTE_C_PRIMARY_RESEARCH_CANDIDATE"
        a1_status = "PRIMARY_CONTROL"
        b_status = "SECONDARY_RESEARCH_CANDIDATE"
        c_status = "PRIMARY_RESEARCH_CANDIDATE"
    else:
        primary_research = "NONE"
        secondary_research = "A1_BASELINE_CONTROL;B_STATIC_MOMENTUM_BLEND;C_DYNAMIC_MOMENTUM_BLEND;D_R2C_BC_CONFIRMATION_OVERLAY_TRACKING_ONLY"
        matrix_decision = "NO_CLEAR_WINNER_WAIT_MORE_MATURITY"
        a1_status = "PRIMARY_CONTROL"
        b_status = "TRACKING"
        c_status = "TRACKING"

    abc_rows = [{
        "evidence_favors": evidence_favors,
        "primary_control": primary_control,
        "primary_research_candidate": primary_research,
        "secondary_research_candidate": secondary_research,
        "A1_status": a1_status,
        "B_status": b_status,
        "C_status": c_status,
        "A1_new_maturity_top20_average_return": avg_return.get("A1_BASELINE_CONTROL", math.nan),
        "B_new_maturity_top20_average_return": avg_return.get("B_STATIC_MOMENTUM_BLEND", math.nan),
        "C_new_maturity_top20_average_return": avg_return.get("C_DYNAMIC_MOMENTUM_BLEND", math.nan),
        "D_R2C_new_maturity_top20_average_return": avg_return.get("D_R2C_BC_CONFIRMATION_OVERLAY", math.nan),
        "more_maturity_required": True,
    }]
    write_csv(OUT / "a1_b_c_primary_candidate_review.csv", abc_rows)

    matrix_rows = [{
        "candidate_decision": matrix_decision,
        "reason": "V21.119_R2 evidence favors A1; D_R2C improvement is concentrated and repeated-loser reduction is not meaningful.",
        "primary_control": primary_control,
        "primary_research_candidate": primary_research,
        "secondary_research_candidate": secondary_research,
        "D_original_status": d_review[0]["D_original_status"],
        "D_R2C_status": d_review[0]["D_R2C_status"],
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }]
    write_csv(OUT / "candidate_decision_matrix.csv", matrix_rows)

    mixed = matrix_decision == "NO_CLEAR_WINNER_WAIT_MORE_MATURITY"
    if evidence_favors == "A1" and bool(r2.get("overfit_warning", True)):
        final_status = "WARN_V21_121_D_R2C_NOT_ADOPTABLE_A1_FAVORED"
        decision = matrix_decision
    elif mixed:
        final_status = "PARTIAL_PASS_V21_121_REBASE_REVIEW_INCOMPLETE"
        decision = matrix_decision
    else:
        final_status = "PASS_V21_121_REBASE_DECISION_READY"
        decision = matrix_decision

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": r1.get("latest_price_date_used", manifests["V21.120"].get("latest_price_date_after_refresh", "")),
        "evidence_sources_loaded": sorted(SOURCES),
        "evidence_favors": evidence_favors,
        "primary_control": primary_control,
        "primary_research_candidate": primary_research,
        "secondary_research_candidate": secondary_research,
        "D_original_status": d_review[0]["D_original_status"],
        "D_R2C_status": d_review[0]["D_R2C_status"],
        "B_status": b_status,
        "C_status": c_status,
        "A1_status": a1_status,
        "candidate_decision": matrix_decision,
        "next_recommended_stage": "V21.122_FORWARD_MATURITY_MONITOR_FOR_A1_B_C_AND_FROZEN_D_R2C",
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
        "historical_rankings_recomputed": False,
        "prior_stage_outputs_read_as_frozen_evidence": True,
        "v116_reference_processed_dates": v116.get("processed_dates", []),
    }
    write_json(OUT / "V21.121_manifest.json", manifest)

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={manifest['latest_price_date_used']}",
        f"evidence_sources_loaded={', '.join(manifest['evidence_sources_loaded'])}",
        f"evidence_favors={evidence_favors}",
        f"primary_control={primary_control}",
        f"primary_research_candidate={primary_research}",
        f"secondary_research_candidate={secondary_research}",
        f"D_original_status={d_review[0]['D_original_status']}",
        f"D_R2C_status={d_review[0]['D_R2C_status']}",
        f"B_status={b_status}",
        f"C_status={c_status}",
        f"A1_status={a1_status}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        f"next recommended stage={manifest['next_recommended_stage']}",
    ]
    (OUT / "V21.121_candidate_rebase_review_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
