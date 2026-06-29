from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.127_A1_PRIMARY_TRACKING_WITH_BC_DIAGNOSTIC_WATCH"
OUT = ROOT / "outputs/v21/V21.127_A1_PRIMARY_TRACKING_WITH_BC_DIAGNOSTIC_WATCH"

V126_R1 = ROOT / "outputs/v21/V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION"
V126 = ROOT / "outputs/v21/V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"
V125 = ROOT / "outputs/v21/V21.125_ABCD_VS_QQQ_FORWARD_WINRATE_SUMMARY"
V123 = ROOT / "outputs/v21/V21.123_CURRENT_A1_TOP20_CONFIRMATION_FILTER"
V122 = ROOT / "outputs/v21/V21.122_A1_BC_FORWARD_TRACKING_AND_D_R2C_FREEZE_MONITOR"
V121 = ROOT / "outputs/v21/V21.121_CANDIDATE_REBASE_REVIEW_A1_B_C_D_R2C"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"

V126_R1_MANIFEST = V126_R1 / "V21.126_R1_manifest.json"
V126_R1_CLEAN = V126_R1 / "b_clean_subset_forward_diagnostic.csv"
V126_R1_RISK = V126_R1 / "b_risk_review.csv"
V126_MANIFEST = V126 / "V21.126_manifest.json"
V125_SUMMARY = V125 / "abcd_vs_qqq_winrate_summary_all_matured.csv"
V123_MANIFEST = V123 / "V21.123_manifest.json"
V122_MANIFEST = V122 / "V21.122_manifest.json"
V121_MANIFEST = V121 / "V21.121_manifest.json"
FWD = V119_R1 / "forward_maturity_by_date_horizon_after_refresh.csv"
A1_FILE = V116 / "daily_A1_top50_full_ledger.csv"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "B_CLEAN_EX_REPEATED_LOSERS",
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


def missing_inputs() -> list[str]:
    required = [
        V126_R1_MANIFEST, V126_R1_CLEAN, V126_R1_RISK, V126_MANIFEST, V125_SUMMARY,
        V123_MANIFEST, V122_MANIFEST, V121_MANIFEST, FWD, A1_FILE,
    ]
    return [rel(path) for path in required if not path.is_file()]


def blocked(missing: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_127_MISSING_REQUIRED_INPUTS",
        "DECISION": "BLOCKED_MISSING_REQUIRED_INPUTS",
        "missing_inputs": missing,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.127_manifest.json", manifest)
    (OUT / "V21.127_A1_primary_tracking_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def summary_row(summary: pd.DataFrame, strategy: str, topn: int) -> dict[str, Any]:
    sub = summary[summary["strategy"].eq(strategy) & summary["topN"].eq(topn)]
    return sub.iloc[0].to_dict() if not sub.empty else {}


def soxx_stats(fwd: pd.DataFrame, strategy: str, topn: int) -> dict[str, Any]:
    sub = fwd[
        fwd["strategy"].eq(strategy)
        & fwd["top_n"].eq(topn)
        & fwd["matured"].astype(str).str.upper().eq("TRUE")
    ].copy()
    vals = pd.to_numeric(sub["excess_vs_SOXX"], errors="coerce").dropna()
    return {
        "win_rate_vs_SOXX": float((vals > 0).mean()) if len(vals) else math.nan,
        "avg_excess_vs_SOXX": float(vals.mean()) if len(vals) else math.nan,
    }


def clean_stats(clean: pd.DataFrame, topn: int) -> dict[str, Any]:
    sub = clean[clean["topN"].eq(topn)].copy()
    q = pd.to_numeric(sub["QQQ_excess"], errors="coerce").dropna()
    s = pd.to_numeric(sub["SOXX_excess"], errors="coerce").dropna()
    return {
        "win_rate_vs_QQQ": float((q > 0).mean()) if len(q) else math.nan,
        "avg_excess_vs_QQQ": float(q.mean()) if len(q) else math.nan,
        "median_excess_vs_QQQ": float(q.median()) if len(q) else math.nan,
        "worst_excess_vs_QQQ": float(q.min()) if len(q) else math.nan,
        "win_rate_vs_SOXX": float((s > 0).mean()) if len(s) else math.nan,
        "avg_excess_vs_SOXX": float(s.mean()) if len(s) else math.nan,
        "matured_observation_count": int(len(sub)),
        "member_count_min": int(pd.to_numeric(sub["member_count"], errors="coerce").min()) if not sub.empty else 0,
        "member_count_avg": float(pd.to_numeric(sub["member_count"], errors="coerce").mean()) if not sub.empty else math.nan,
    }


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        return blocked(missing)

    v126r1 = json.loads(V126_R1_MANIFEST.read_text(encoding="utf-8"))
    v126 = json.loads(V126_MANIFEST.read_text(encoding="utf-8"))
    v123 = json.loads(V123_MANIFEST.read_text(encoding="utf-8"))
    v122 = json.loads(V122_MANIFEST.read_text(encoding="utf-8"))
    v121 = json.loads(V121_MANIFEST.read_text(encoding="utf-8"))
    summary = pd.read_csv(V125_SUMMARY, low_memory=False)
    summary["topN"] = pd.to_numeric(summary["topN"], errors="coerce")
    fwd = pd.read_csv(FWD, low_memory=False)
    clean = pd.read_csv(V126_R1_CLEAN, low_memory=False)
    clean["topN"] = pd.to_numeric(clean["topN"], errors="coerce")
    risk = pd.read_csv(V126_R1_RISK, low_memory=False).iloc[0].to_dict()

    latest_a1_date = str(pd.read_csv(A1_FILE, usecols=["as_of_date"], low_memory=False)["as_of_date"].astype(str).max())
    newly_matured_count = int(v122.get("newly_matured_observation_count", 0))
    still_unmatured_count = int(v122.get("still_unmatured_observation_count", 0))
    all_matured_count = int(v122.get("all_matured_observation_count", 0))

    clean20 = clean_stats(clean, 20)
    clean50 = clean_stats(clean, 50)
    clean_top20_count = clean20["member_count_min"]
    clean_top50_count = clean50["member_count_min"]
    clean_breadth_sufficient = bool(clean_top20_count >= 10 and clean_top50_count >= 25)

    hierarchy_rows = [{
        "A1_status": "PRIMARY_CONTROL_CURRENT_MAIN_RESEARCH_LINE",
        "B_status": "DIAGNOSTIC_WATCH_ONLY_NOT_SUPPORTED_FOR_PROMOTION",
        "B_clean_status": "DIAGNOSTIC_ONLY_INSUFFICIENT_TOP20_BREADTH",
        "C_status": "SECONDARY_RESEARCH_CANDIDATE",
        "D_original_status": "DOWNGRADED_FROZEN_REFERENCE_ONLY",
        "D_R2C_status": "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE",
        "source_v21_121_decision": v121.get("DECISION", ""),
        "source_v21_126_decision": v126.get("DECISION", ""),
        "source_v21_126_r1_decision": v126r1.get("DECISION", ""),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }]
    write_csv(OUT / "hierarchy_audit.csv", hierarchy_rows)

    forward_rows = []
    for strategy in STRATEGIES:
        if strategy == "B_CLEAN_EX_REPEATED_LOSERS":
            top20, top50 = clean20, clean50
            for topn, stats in [(20, top20), (50, top50)]:
                forward_rows.append({
                    "strategy": strategy,
                    "topN": topn,
                    "role": "diagnostic_only_subset_not_official_variant",
                    "win_rate_vs_QQQ": stats["win_rate_vs_QQQ"],
                    "avg_excess_vs_QQQ": stats["avg_excess_vs_QQQ"],
                    "median_excess_vs_QQQ": stats["median_excess_vs_QQQ"],
                    "worst_excess_vs_QQQ": stats["worst_excess_vs_QQQ"],
                    "win_rate_vs_SOXX": stats["win_rate_vs_SOXX"],
                    "avg_excess_vs_SOXX": stats["avg_excess_vs_SOXX"],
                    "matured_observation_count": stats["matured_observation_count"],
                    "newly_matured_observation_count": newly_matured_count,
                    "still_unmatured_count": still_unmatured_count,
                })
            continue
        role = {
            "A1_BASELINE_CONTROL": "primary_control_current_main_research_line",
            "B_STATIC_MOMENTUM_BLEND": "diagnostic_watch_only",
            "C_DYNAMIC_MOMENTUM_BLEND": "secondary_research_candidate",
            "D_WEIGHT_OPTIMIZED_R1": "downgraded_reference_only",
            "D_R2C_BC_CONFIRMATION_OVERLAY": "frozen_tracking_only",
        }[strategy]
        for topn in [20, 50]:
            row = summary_row(summary, strategy, topn)
            soxx = soxx_stats(fwd, strategy, topn)
            forward_rows.append({
                "strategy": strategy,
                "topN": topn,
                "role": role,
                "win_rate_vs_QQQ": row.get("win_rate_vs_QQQ", math.nan),
                "avg_excess_vs_QQQ": row.get("avg_excess_vs_QQQ", math.nan),
                "median_excess_vs_QQQ": row.get("median_excess_vs_QQQ", math.nan),
                "worst_excess_vs_QQQ": row.get("worst_excess_vs_QQQ", math.nan),
                "win_rate_vs_SOXX": soxx["win_rate_vs_SOXX"],
                "avg_excess_vs_SOXX": soxx["avg_excess_vs_SOXX"],
                "matured_observation_count": int(row.get("observations", 0)) if row else 0,
                "newly_matured_observation_count": newly_matured_count,
                "still_unmatured_count": still_unmatured_count,
            })
    write_csv(OUT / "forward_tracking_summary.csv", forward_rows)

    def qqq(strategy: str, topn: int, field: str = "win_rate_vs_QQQ") -> float:
        if strategy == "B_CLEAN_EX_REPEATED_LOSERS":
            return clean20[field] if topn == 20 else clean50[field]
        row = summary_row(summary, strategy, topn)
        return float(row.get(field, math.nan)) if row else math.nan

    a1_top20 = qqq("A1_BASELINE_CONTROL", 20)
    b_top20 = qqq("B_STATIC_MOMENTUM_BLEND", 20)
    clean_top20 = qqq("B_CLEAN_EX_REPEATED_LOSERS", 20)
    c_top20 = qqq("C_DYNAMIC_MOMENTUM_BLEND", 20)
    b_risk_high = str(v126.get("B_repeated_loser_risk_level", "")).upper() == "HIGH"
    c_challenge = bool(c_top20 > a1_top20 and qqq("C_DYNAMIC_MOMENTUM_BLEND", 50) > qqq("A1_BASELINE_CONTROL", 50))
    b_clean_challenge = bool(clean_breadth_sufficient and clean_top20 > a1_top20 and qqq("B_CLEAN_EX_REPEATED_LOSERS", 50) > qqq("A1_BASELINE_CONTROL", 50))
    if newly_matured_count == 0:
        leadership_status = "WAIT_MORE_MATURITY"
    elif c_challenge:
        leadership_status = "A1_CHALLENGED_BY_C"
    elif b_clean_challenge:
        leadership_status = "A1_CHALLENGED_BY_B_CLEAN"
    elif not bool(v122.get("A1_remains_evidence_leader", True)):
        leadership_status = "ROLE_REVIEW_REQUIRED"
    else:
        leadership_status = "A1_REMAINS_PRIMARY"
    role_review_required = leadership_status in {"A1_CHALLENGED_BY_C", "A1_CHALLENGED_BY_B_CLEAN", "ROLE_REVIEW_REQUIRED"}
    write_csv(OUT / "a1_leadership_check.csv", [{
        "A1_Top20_win_rate_vs_QQQ": a1_top20,
        "B_Top20_win_rate_vs_QQQ": b_top20,
        "B_clean_Top20_win_rate_vs_QQQ": clean_top20,
        "C_Top20_win_rate_vs_QQQ": c_top20,
        "A1_remains_most_reliable_after_risk_adjustment": not role_review_required,
        "A1_leadership_status": leadership_status,
        "reason": "B raw win-rate lead is not clean due to HIGH repeated-loser risk; B-clean has insufficient Top20 breadth.",
    }])

    write_csv(OUT / "b_diagnostic_watch.csv", [{
        "B_status": "DIAGNOSTIC_WATCH_ONLY_NOT_SUPPORTED_FOR_PROMOTION",
        "B_Top20_win_rate_vs_QQQ": b_top20,
        "B_Top50_win_rate_vs_QQQ": qqq("B_STATIC_MOMENTUM_BLEND", 50),
        "B_repeated_loser_risk_level": v126.get("B_repeated_loser_risk_level", ""),
        "B_Top20_repeated_loser_overlap_count": v126r1.get("B_Top20_repeated_loser_overlap_count", ""),
        "B_Top50_repeated_loser_overlap_count": v126r1.get("B_Top50_repeated_loser_overlap_count", ""),
        "B_clean_status": "DIAGNOSTIC_ONLY_INSUFFICIENT_TOP20_BREADTH",
        "B_clean_Top20_win_rate_vs_QQQ": clean_top20,
        "B_clean_Top50_win_rate_vs_QQQ": qqq("B_CLEAN_EX_REPEATED_LOSERS", 50),
        "B_clean_member_count": clean_top20_count,
        "B_clean_top50_member_count": clean_top50_count,
        "sufficient_clean_breadth": clean_breadth_sufficient,
        "clean_subset_performance_retained": bool(v126r1.get("clean_subset_performance_retained", False)),
        "diagnostic_only": True,
        "official_variant": False,
    }])

    write_csv(OUT / "c_secondary_watch.csv", [{
        "C_status": "SECONDARY_RESEARCH_CANDIDATE",
        "C_Top20_win_rate_vs_QQQ": c_top20,
        "C_Top50_win_rate_vs_QQQ": qqq("C_DYNAMIC_MOMENTUM_BLEND", 50),
        "C_Top20_avg_excess_vs_QQQ": qqq("C_DYNAMIC_MOMENTUM_BLEND", 20, "avg_excess_vs_QQQ"),
        "A1_Top20_avg_excess_vs_QQQ": qqq("A1_BASELINE_CONTROL", 20, "avg_excess_vs_QQQ"),
        "C_challenge_detected": c_challenge,
        "C_stronger_secondary_than_B": bool(not b_clean_challenge and not b_risk_high),
        "promotion_allowed_now": False,
    }])

    write_csv(OUT / "d_and_d_r2c_freeze_monitor.csv", [{
        "D_original_status": "DOWNGRADED_FROZEN_REFERENCE_ONLY",
        "D_R2C_status": "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE",
        "D_Top20_win_rate_vs_QQQ": qqq("D_WEIGHT_OPTIMIZED_R1", 20),
        "D_R2C_Top20_win_rate_vs_QQQ": qqq("D_R2C_BC_CONFIRMATION_OVERLAY", 20),
        "D_R2C_overfit_status": v122.get("D_R2C_overfit_status", "REDUCED_BUT_NOT_RESOLVED"),
        "D_R2C_overfit_unresolved": True,
        "D_R2C_modified": False,
        "official_adoption_allowed": False,
    }])

    if newly_matured_count == 0:
        next_gate = "WAIT_MORE_MATURITY"
    elif b_clean_challenge:
        next_gate = "RUN_B_CLEAN_DIAGNOSTIC_REVIEW"
    elif c_challenge:
        next_gate = "RUN_C_CHALLENGER_REVIEW"
    elif role_review_required:
        next_gate = "RUN_REBASE_REVIEW"
    else:
        next_gate = "KEEP_CURRENT_HIERARCHY"
    write_csv(OUT / "next_action_gate.csv", [{
        "next_action_gate": next_gate,
        "no_new_maturity": newly_matured_count == 0,
        "A1_remains_leader": not role_review_required,
        "B_clean_has_sufficient_breadth_and_edge": b_clean_challenge,
        "C_materially_challenges_A1": c_challenge,
        "role_review_required": role_review_required,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }])

    if role_review_required:
        final_status = "WARN_V21_127_ROLE_REVIEW_REQUIRED"
        decision = "ROLE_REVIEW_REQUIRED_RESEARCH_ONLY"
    elif clean_top20 > a1_top20 and not clean_breadth_sufficient:
        final_status = "WARN_V21_127_B_CLEAN_INSUFFICIENT_BREADTH"
        decision = "B_CLEAN_INSUFFICIENT_BREADTH_RESEARCH_ONLY"
    elif newly_matured_count == 0:
        final_status = "PARTIAL_PASS_V21_127_TRACKING_UPDATED_WAIT_MORE_MATURITY"
        decision = "WAIT_MORE_MATURITY_RESEARCH_ONLY"
    else:
        final_status = "PASS_V21_127_KEEP_CURRENT_HIERARCHY"
        decision = "KEEP_CURRENT_HIERARCHY_RESEARCH_ONLY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": v126r1.get("latest_price_date_used", ""),
        "source_v21_126_r1_status": v126r1.get("FINAL_STATUS", ""),
        "A1_status": "PRIMARY_CONTROL_CURRENT_MAIN_RESEARCH_LINE",
        "B_status": "DIAGNOSTIC_WATCH_ONLY_NOT_SUPPORTED_FOR_PROMOTION",
        "B_clean_status": "DIAGNOSTIC_ONLY_INSUFFICIENT_TOP20_BREADTH",
        "C_status": "SECONDARY_RESEARCH_CANDIDATE",
        "D_original_status": "DOWNGRADED_FROZEN_REFERENCE_ONLY",
        "D_R2C_status": "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE",
        "A1_Top20_win_rate_vs_QQQ": a1_top20,
        "B_Top20_win_rate_vs_QQQ": b_top20,
        "B_clean_Top20_win_rate_vs_QQQ": clean_top20,
        "C_Top20_win_rate_vs_QQQ": c_top20,
        "A1_leadership_status": leadership_status,
        "B_repeated_loser_risk_level": v126.get("B_repeated_loser_risk_level", ""),
        "B_clean_member_count": clean_top20_count,
        "B_clean_breadth_sufficient": clean_breadth_sufficient,
        "C_challenge_detected": c_challenge,
        "role_review_required": role_review_required,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "model_parameters_changed": False,
        "rankings_recomputed": False,
        "official_new_strategy_variants_created": False,
        "diagnostic_subsets_only": True,
        "next_recommended_stage": "V21.128_PRICE_REFRESH_AND_FORWARD_MATURITY_GATE" if next_gate == "WAIT_MORE_MATURITY" else next_gate,
        "latest_A1_ranking_date_used": latest_a1_date,
        "source_v21_123_status": v123.get("FINAL_STATUS", ""),
    }
    write_json(OUT / "V21.127_manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={manifest['latest_price_date_used']}",
        f"source V21.126_R1 status={v126r1.get('FINAL_STATUS', '')}",
        f"A1_status={manifest['A1_status']}",
        f"B_status={manifest['B_status']}",
        f"B_clean_status={manifest['B_clean_status']}",
        f"C_status={manifest['C_status']}",
        f"D_original_status={manifest['D_original_status']}",
        f"D_R2C_status={manifest['D_R2C_status']}",
        f"A1 Top20 win rate vs QQQ={a1_top20}",
        f"B Top20 win rate vs QQQ={b_top20}",
        f"B-clean Top20 win rate vs QQQ={clean_top20}",
        f"C Top20 win rate vs QQQ={c_top20}",
        f"A1_leadership_status={leadership_status}",
        f"B_repeated_loser_risk_level={manifest['B_repeated_loser_risk_level']}",
        f"B_clean_member_count={clean_top20_count}",
        f"B_clean_breadth_sufficient={clean_breadth_sufficient}",
        f"C_challenge_detected={c_challenge}",
        f"role_review_required={role_review_required}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        f"next recommended stage={manifest['next_recommended_stage']}",
    ]
    (OUT / "V21.127_A1_primary_tracking_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
