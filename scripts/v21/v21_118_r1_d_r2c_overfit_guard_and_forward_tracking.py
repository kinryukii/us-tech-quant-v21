#!/usr/bin/env python
"""V21.118 R1 overfit guard and forward tracking for frozen D-R2C."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.118_R1_D_R2C_OVERFIT_GUARD_AND_FORWARD_TRACKING"
OUT = ROOT / "outputs/v21/V21.118_R1_D_R2C_OVERFIT_GUARD_AND_FORWARD_TRACKING"
V118 = ROOT / "outputs/v21/V21.118_D_R2_REPEATED_LOSER_AWARE_DESIGN"
V117 = ROOT / "outputs/v21/V21.117_EARLY_FORWARD_VALIDITY_EVALUATOR"
V117_R1 = ROOT / "outputs/v21/V21.117_R1_D_EARLY_EDGE_FAILURE_DECOMPOSITION"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

VARIANT = "D_R2C_BC_CONFIRMATION_OVERLAY"

REQ = {
    "v118_manifest": V118 / "V21.118_manifest.json",
    "v118_forward": V118 / "d_r2_forward_by_date_horizon.csv",
    "v118_pairwise": V118 / "d_r2_pairwise_winrate.csv",
    "v118_reduction": V118 / "d_r2_repeated_loser_reduction.csv",
    "v118_sanity": V118 / "d_r2_benchmark_sanity.csv",
    "v118_stability": V118 / "d_r2_turnover_stability.csv",
    "v118_membership": V118 / "d_r2_top20_top50_membership.csv",
    "v118_penalties": V118 / "d_r2_penalty_attribution.csv",
    "v117_manifest": V117 / "V21.117_manifest.json",
    "v117_forward": V117 / "early_forward_by_date_horizon.csv",
    "v117_r1_manifest": V117_R1 / "V21.117_R1_manifest.json",
    "v116_rankings": V116 / "daily_ABCD_top50_full_ledger.csv",
    "price": PRICE,
}


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
    return [rel(path) for path in REQ.values() if not path.is_file()]


def mean_or_nan(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    return float(vals.mean()) if len(vals) else math.nan


def pair_metric(pair: pd.DataFrame, suffix: str, field: str = "win_rate", top_n: int = 20) -> float:
    sub = pair[(pair["candidate_variant"].eq(VARIANT)) & (pair["comparison"].str.endswith(suffix)) & (pair["top_n"].eq(top_n))]
    sub = sub[pd.to_numeric(sub["available_observations"], errors="coerce") > 0]
    return mean_or_nan(sub[field]) if not sub.empty else math.nan


def classify_dependency(membership: pd.DataFrame, ranks: pd.DataFrame) -> tuple[str, list[dict[str, Any]]]:
    rows = []
    overlaps = []
    for as_of, group in membership[membership["candidate_variant"].eq(VARIANT)].groupby("as_of_date"):
        r = ranks[ranks["as_of_date"].astype(str).eq(str(as_of))]
        r2c20 = set(group[group["rank"].le(20)]["ticker"].astype(str))
        d20 = set(r[(r["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")) & (r["rank"].le(20))]["ticker"].astype(str))
        b20 = set(r[(r["strategy"].eq("B_STATIC_MOMENTUM_BLEND")) & (r["rank"].le(20))]["ticker"].astype(str))
        c20 = set(r[(r["strategy"].eq("C_DYNAMIC_MOMENTUM_BLEND")) & (r["rank"].le(20))]["ticker"].astype(str))
        bc = b20 | c20
        bc_overlap = len(r2c20 & bc) / 20 if r2c20 else math.nan
        d_overlap = len(r2c20 & d20) / 20 if r2c20 else math.nan
        overlaps.append((bc_overlap, d_overlap))
        rows.append({
            "as_of_date": as_of,
            "r2c_top20_overlap_with_B_or_C_top20": len(r2c20 & bc),
            "r2c_top20_overlap_with_original_D_top20": len(r2c20 & d20),
            "bc_dependency_ratio": bc_overlap,
            "d_retention_ratio": d_overlap,
        })
    avg_bc = sum(x[0] for x in overlaps) / len(overlaps) if overlaps else math.nan
    avg_d = sum(x[1] for x in overlaps) / len(overlaps) if overlaps else math.nan
    if math.isnan(avg_bc):
        cls = "INCONCLUSIVE"
    elif avg_bc >= 0.85 and avg_d < 0.65:
        cls = "MOSTLY_BC_CLONE"
    elif avg_bc >= 0.65 and avg_d >= 0.65:
        cls = "D_REPAIR_WITH_BC_CONFIRMATION"
    elif avg_bc >= 0.45:
        cls = "MIXED_DEPENDENCY"
    else:
        cls = "INCONCLUSIVE"
    for row in rows:
        row["dependency_classification"] = cls
    return cls, rows


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = missing_inputs()
    if missing:
        manifest = {
            "FINAL_STATUS": "BLOCKED_V21_118_R1_MISSING_REQUIRED_INPUTS",
            "DECISION": "DO_NOT_USE_D_R2C_OVERFIT_GUARD",
            "missing_inputs": missing,
            "protected_outputs_modified": False,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "research_only": True,
        }
        write_json(OUT / "V21.118_R1_manifest.json", manifest)
        (OUT / "V21.118_R1_D_R2C_overfit_guard_report.txt").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return manifest

    v118 = json.loads(REQ["v118_manifest"].read_text(encoding="utf-8"))
    v117 = json.loads(REQ["v117_manifest"].read_text(encoding="utf-8"))
    r1 = json.loads(REQ["v117_r1_manifest"].read_text(encoding="utf-8"))
    fwd = pd.read_csv(REQ["v118_forward"], low_memory=False)
    fwd = fwd[fwd["candidate_variant"].eq(VARIANT)].copy()
    pair = pd.read_csv(REQ["v118_pairwise"], low_memory=False)
    reduction = pd.read_csv(REQ["v118_reduction"], low_memory=False)
    sanity = pd.read_csv(REQ["v118_sanity"], low_memory=False)
    stability = pd.read_csv(REQ["v118_stability"], low_memory=False)
    membership = pd.read_csv(REQ["v118_membership"], low_memory=False)
    penalties = pd.read_csv(REQ["v118_penalties"], low_memory=False)
    ranks = pd.read_csv(REQ["v116_rankings"], low_memory=False)
    ranks["rank"] = pd.to_numeric(ranks["rank"], errors="coerce")

    frozen_rule = [{
        "frozen_variant_name": VARIANT,
        "read_from_v21_118_outputs": True,
        "source_forward_file": rel(REQ["v118_forward"]),
        "source_pairwise_file": rel(REQ["v118_pairwise"]),
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "penalty_thresholds_changed": False,
        "confirmation_logic_changed": False,
    }]
    write_csv(OUT / "d_r2c_frozen_rule_audit.csv", frozen_rule)

    matured = fwd[fwd["matured"].astype(str).str.upper().eq("TRUE")].copy()
    # V21.118 already used the full currently available V21.116/V21.117 evidence window.
    # A later ranking date is not out-of-sample unless it was not available to V21.118.
    source_dates = sorted(ranks["as_of_date"].astype(str).unique())
    v118_latest = str(v118.get("latest_price_date_used", ""))
    later_dates = [d for d in source_dates if v118_latest and d > v118_latest]
    out_of_sample_available = bool(later_dates)
    fwd["evidence_partition"] = fwd["as_of_date"].astype(str).apply(lambda d: "OUT_OF_SAMPLE_LATER" if d in later_dates else "DESIGN_EVIDENCE_IN_SAMPLE")

    # Tracking table with original D and baseline comparison columns.
    orig = pd.read_csv(REQ["v117_forward"], low_memory=False)
    base_cols = ["as_of_date", "top_n", "horizon", "equal_weight_return", "benchmark_QQQ_return", "benchmark_SOXX_return"]
    d_orig = orig[orig["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")][base_cols].rename(columns={"equal_weight_return": "original_D_return"})
    a1 = orig[orig["strategy"].eq("A1_BASELINE_CONTROL")][base_cols[:3] + ["equal_weight_return"]].rename(columns={"equal_weight_return": "A1_return"})
    b = orig[orig["strategy"].eq("B_STATIC_MOMENTUM_BLEND")][base_cols[:3] + ["equal_weight_return"]].rename(columns={"equal_weight_return": "B_return"})
    c = orig[orig["strategy"].eq("C_DYNAMIC_MOMENTUM_BLEND")][base_cols[:3] + ["equal_weight_return"]].rename(columns={"equal_weight_return": "C_return"})
    tracking = fwd.merge(d_orig, on=["as_of_date", "top_n", "horizon"], how="left")
    tracking = tracking.merge(a1, on=["as_of_date", "top_n", "horizon"], how="left")
    tracking = tracking.merge(b, on=["as_of_date", "top_n", "horizon"], how="left")
    tracking = tracking.merge(c, on=["as_of_date", "top_n", "horizon"], how="left")
    tracking["D_R2C_minus_original_D"] = tracking["equal_weight_return"] - tracking["original_D_return"]
    tracking["D_R2C_minus_A1"] = tracking["equal_weight_return"] - tracking["A1_return"]
    tracking["D_R2C_minus_B"] = tracking["equal_weight_return"] - tracking["B_return"]
    tracking["D_R2C_minus_C"] = tracking["equal_weight_return"] - tracking["C_return"]
    tracking.to_csv(OUT / "d_r2c_forward_tracking_by_date_horizon.csv", index=False)

    d_pair = pair[(pair["candidate_variant"].eq(VARIANT)) & (pair["comparison"].str.endswith("_vs_D_WEIGHT_OPTIMIZED_R1"))].copy()
    d_pair.to_csv(OUT / "d_r2c_vs_original_d_pairwise.csv", index=False)
    abc_pair = pair[(pair["candidate_variant"].eq(VARIANT)) & (pair["comparison"].str.endswith(("_vs_A1_BASELINE_CONTROL", "_vs_B_STATIC_MOMENTUM_BLEND", "_vs_C_DYNAMIC_MOMENTUM_BLEND")))].copy()
    abc_pair.to_csv(OUT / "d_r2c_vs_a1_b_c_pairwise.csv", index=False)
    bench_pair = pair[(pair["candidate_variant"].eq(VARIANT)) & (pair["comparison"].str.endswith(("_vs_QQQ", "_vs_SOXX")))].copy()
    bench_pair.to_csv(OUT / "d_r2c_benchmark_sanity.csv", index=False)

    rrow = reduction[reduction["candidate_variant"].eq(VARIANT)].iloc[0]
    repeated_reduction = int(rrow["reduction_amount"])
    original_count = int(rrow["original_D_repeated_loser_count"])
    variant_count = int(rrow["variant_repeated_loser_count"])
    meaningful_reduction = repeated_reduction >= max(3, int(original_count * 0.2))
    repeated_rows = [{
        "candidate_variant": VARIANT,
        "original_D_repeated_loser_count": original_count,
        "D_R2C_repeated_loser_count": variant_count,
        "repeated_loser_reduction": repeated_reduction,
        "repeated_loser_reduction_meaningful": meaningful_reduction,
        "repeated_loser_overlap_count": variant_count,
        "newly_introduced_losers": "",
        "removed_losers": rrow.get("worst_repeated_losers_removed_or_downranked", ""),
    }]
    write_csv(OUT / "d_r2c_repeated_loser_tracking.csv", repeated_rows)

    dependency, dep_rows = classify_dependency(membership[membership["candidate_variant"].eq(VARIANT)].copy(), ranks)
    write_csv(OUT / "d_r2c_bc_dependency_audit.csv", dep_rows)

    top20 = tracking[(tracking["top_n"].eq(20)) & (tracking["matured"].astype(str).str.upper().eq("TRUE"))].copy()
    improvement_by_date = top20.groupby("as_of_date")["D_R2C_minus_original_D"].mean()
    positive_date_rate = float((improvement_by_date > 0).sum() / len(improvement_by_date)) if len(improvement_by_date) else math.nan
    improvement_concentration = float(improvement_by_date.max() / improvement_by_date.abs().sum()) if len(improvement_by_date) and improvement_by_date.abs().sum() else math.nan
    d_vs_b = pair_metric(pair, "_vs_B_STATIC_MOMENTUM_BLEND")
    d_vs_c = pair_metric(pair, "_vs_C_DYNAMIC_MOMENTUM_BLEND")
    qqq_excess = pair_metric(pair, "_vs_QQQ", "average_excess_return")
    soxx_excess = pair_metric(pair, "_vs_SOXX", "average_excess_return")
    still_loses_bc = bool((not math.isnan(d_vs_b) and d_vs_b <= 0.5) or (not math.isnan(d_vs_c) and d_vs_c <= 0.5))
    still_loses_soxx = bool(not math.isnan(soxx_excess) and soxx_excess <= 0)
    one_extreme = bool(sanity[sanity["candidate_variant"].eq(VARIANT)]["improvement_only_one_extreme_loser_warning"].iloc[0])
    no_oos = not out_of_sample_available
    overfit_warning = bool(no_oos or one_extreme or positive_date_rate < 0.6 or still_loses_bc or still_loses_soxx or not meaningful_reduction)
    overfit_rows = [{
        "candidate_variant": VARIANT,
        "out_of_sample_observations_available": out_of_sample_available,
        "positive_improvement_date_rate": positive_date_rate,
        "improvement_concentration_ratio": improvement_concentration,
        "improvement_driven_by_one_extreme_loser": one_extreme,
        "improvement_consistent_across_dates": bool(positive_date_rate >= 0.6) if not math.isnan(positive_date_rate) else False,
        "still_loses_to_B_or_C": still_loses_bc,
        "still_loses_to_SOXX": still_loses_soxx,
        "repeated_loser_reduction_meaningful": meaningful_reduction,
        "overfit_warning": overfit_warning,
    }]
    write_csv(OUT / "d_r2c_overfit_diagnostics.csv", overfit_rows)

    soxx_alpha = bool(soxx_excess > 0 and not still_loses_soxx)
    d2c_vs_d = pair_metric(pair, "_vs_D_WEIGHT_OPTIMIZED_R1")
    d2c_vs_a1 = pair_metric(pair, "_vs_A1_BASELINE_CONTROL")
    if d2c_vs_d > 0.5 and meaningful_reduction and dependency != "MOSTLY_BC_CLONE" and not overfit_warning:
        final_status = "PASS_V21_118_R1_D_R2C_ROBUST_IMPROVEMENT"
        decision = "D_R2C_ROBUST_IMPROVEMENT_RESEARCH_ONLY"
    elif d2c_vs_d > 0.5 and (no_oos or overfit_warning):
        final_status = "PARTIAL_PASS_V21_118_R1_D_R2C_IN_SAMPLE_ONLY"
        decision = "D_R2C_IN_SAMPLE_ONLY_RESEARCH_TRACKING"
    else:
        final_status = "WARN_V21_118_R1_D_R2C_OVERFIT_LIKELY"
        decision = "DO_NOT_ADVANCE_D_R2C_OVERFIT_LIKELY"

    manifest = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "source_v21_118_status": v118.get("FINAL_STATUS", ""),
        "frozen_variant_name": VARIANT,
        "latest_price_date_used": v118.get("latest_price_date_used", ""),
        "matured_observations_analyzed": int(top20.shape[0]),
        "out_of_sample_observations_available": out_of_sample_available,
        "D_R2C_vs_original_D_Top20_win_rate": d2c_vs_d,
        "D_R2C_vs_A1_Top20_win_rate": d2c_vs_a1,
        "D_R2C_vs_B_Top20_win_rate": d_vs_b,
        "D_R2C_vs_C_Top20_win_rate": d_vs_c,
        "D_R2C_vs_QQQ_average_excess": qqq_excess,
        "D_R2C_vs_SOXX_average_excess": soxx_excess,
        "repeated_loser_count_original_D": original_count,
        "repeated_loser_count_D_R2C": variant_count,
        "repeated_loser_reduction_meaningful": meaningful_reduction,
        "B_C_dependency_classification": dependency,
        "overfit_warning": overfit_warning,
        "SOXX_alpha_confirmed": soxx_alpha,
        "D_R2C_official_adoption_allowed": False,
        "broker_action_allowed": False,
        "further_maturity_tracking_required": bool(no_oos or overfit_warning),
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "no_parameter_optimization_performed": True,
        "new_variant_generated": False,
    }
    write_json(OUT / "V21.118_R1_manifest.json", manifest)

    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"source V21.118 status={v118.get('FINAL_STATUS', '')}",
        f"frozen variant name={VARIANT}",
        f"latest_price_date_used={v118.get('latest_price_date_used', '')}",
        f"matured observations analyzed={int(top20.shape[0])}",
        f"out_of_sample_observations_available={out_of_sample_available}",
        f"D_R2C vs original D Top20 win rate={d2c_vs_d}",
        f"D_R2C vs A1/B/C Top20 win rates={d2c_vs_a1}/{d_vs_b}/{d_vs_c}",
        f"D_R2C vs QQQ/SOXX average excess={qqq_excess}/{soxx_excess}",
        f"repeated loser count original D vs D_R2C={original_count}->{variant_count}",
        f"repeated loser reduction meaningful={meaningful_reduction}",
        f"B/C dependency classification={dependency}",
        f"overfit warning={overfit_warning}",
        f"SOXX alpha confirmed={soxx_alpha}",
        "D-R2C official adoption allowed=false",
        "broker action allowed=false",
        f"further maturity tracking required={bool(no_oos or overfit_warning)}",
        "",
        "No parameter optimization, new variant generation, official adoption, or broker action was performed.",
    ]
    (OUT / "V21.118_R1_D_R2C_overfit_guard_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=str))
    return manifest


if __name__ == "__main__":
    run()
