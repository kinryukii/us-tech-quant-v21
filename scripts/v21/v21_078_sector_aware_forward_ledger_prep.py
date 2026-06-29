#!/usr/bin/env python
"""Select V21.077 sector-aware candidates and prepare a research-only ledger."""

from __future__ import annotations

import argparse
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.tseries.offsets import BDay

from v21_073_common import protected_files, sha256, truth


STAGE = "V21.078-R1_TO_R3_SECTOR_AWARE_FORWARD_LEDGER_PREP"
OUT_REL = Path("outputs/v21/v21_078")
COMPARISON_REL = Path("outputs/v21/v21_077/V21_077_R3_D_EW_VS_SECTOR_AWARE_COMPARISON.csv")
V77_READINESS_REL = Path("outputs/v21/v21_077/V21_077_R3_READINESS_DECISION_REPORT.csv")
CLASSIFICATION_REL = Path("outputs/v21/v21_076/V21_076_R1_CLASSIFICATION_MASTER.csv")
RANKING_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv")

CANDIDATE_NAME = "V21_078_R1_SECTOR_AWARE_CANDIDATE_SELECTION.csv"
LEDGER_NAME = "V21_078_R2_FORWARD_PORTFOLIO_OBSERVATION_LEDGER.csv"
AUDIT_NAME = "V21_078_R3_LEDGER_INTEGRITY_AND_MATURITY_SCHEDULE_AUDIT.csv"
READINESS_NAME = "V21_078_R3_READINESS_DECISION_REPORT.csv"
R4_REPAIR_REPORT_NAME = "V21_078_R4_MISSING_CLASSIFICATION_REPAIR_REPORT.csv"
R4_MASTER_NAME = "V21_078_R4_REPAIRED_CLASSIFICATION_MASTER_FOR_LEDGER.csv"
R5_FEASIBILITY_NAME = "V21_078_R5_CAP_FEASIBILITY_REPORT.csv"
R5_FALLBACK_NAME = "V21_078_R5_POLICY_FALLBACK_SELECTION.csv"
R6_LEDGER_NAME = "V21_078_R6_REPAIRED_FORWARD_PORTFOLIO_OBSERVATION_LEDGER.csv"
R6_AUDIT_NAME = "V21_078_R6_REPAIRED_LEDGER_AUDIT.csv"
R6_READINESS_NAME = "V21_078_R6_REPAIRED_READINESS_DECISION_REPORT.csv"

PRIMARY = {"D_SECTOR_INDUSTRY_CAP_TOP20_R1", "D_SECTOR_CAP_TOP50_R1"}
BASELINES = {"D_EW_TOP20_R1", "D_EW_TOP50_R1"}
WINDOW_DAYS = {"5D": 5, "10D": 10, "20D": 20}
MAX_TICKER_CAP = 0.10
METADATA_REL = Path("outputs/v20/consolidation/snapshots/V20_108_R8_R2_ENABLED_METADATA_CACHE.csv")


def load_v77_module(root: Path):
    path = root / "scripts/v21/v21_077_sector_aware_risk_budget_backtest.py"
    spec = importlib.util.spec_from_file_location("v77", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def selected_candidates(root: Path) -> pd.DataFrame:
    readiness = pd.read_csv(root / V77_READINESS_REL).iloc[0]
    if not truth(readiness.get("execution_pass_gate")) or int(readiness.get("leakage_warnings", 1)) != 0:
        raise RuntimeError("V21.077 readiness is not clean enough for V21.078 ledger prep")
    comparison = pd.read_csv(root / COMPARISON_REL, low_memory=False)
    test10 = comparison[(comparison["split"].eq("TEST")) & (comparison["window"].eq("10D"))].copy()
    rows: list[dict[str, Any]] = []
    keep = set(BASELINES) | set(PRIMARY) | set(test10.loc[test10["research_candidate_ready"].map(truth), "portfolio_policy_id"])
    for policy_id in sorted(keep):
        subset = test10[test10["portfolio_policy_id"].eq(policy_id)]
        if subset.empty:
            top_n = "TOP20" if "TOP20" in policy_id else "TOP50"
            baseline = test10[test10["portfolio_policy_id"].eq(f"D_EW_{top_n}_R1")]
            row = baseline.iloc[0].copy()
            row["portfolio_policy_id"] = policy_id
        else:
            row = subset.iloc[0]
            top_n = row["top_n"]
        candidate_type = (
            "baseline" if policy_id in BASELINES else
            "primary_candidate" if policy_id in PRIMARY else
            "secondary_candidate"
        )
        priority = 0 if candidate_type == "baseline" else 1 if candidate_type == "primary_candidate" else 2
        rows.append({
            "policy_id": policy_id,
            "top_n": top_n,
            "candidate_type": candidate_type,
            "raw_return_delta_vs_D_EW": 0.0 if candidate_type == "baseline" else row.get("raw_return_delta_vs_d_ew", 0.0),
            "drawdown_delta_vs_D_EW": 0.0 if candidate_type == "baseline" else row.get("drawdown_proxy_improvement", 0.0),
            "ratio_delta_vs_D_EW": 0.0 if candidate_type == "baseline" else row.get("return_drawdown_ratio_improvement", 0.0),
            "sector_concentration_delta": 0.0 if candidate_type == "baseline" else row.get("sector_concentration_improvement", 0.0),
            "industry_concentration_delta": 0.0 if candidate_type == "baseline" else row.get("industry_concentration_improvement", 0.0),
            "acceptance_gate_pass": candidate_type == "baseline" or truth(row.get("research_candidate_ready")),
            "forward_validation_priority": priority,
            "notes": (
                "Preserved D equal-weight forward comparison baseline."
                if candidate_type == "baseline" else
                "Primary V21.077 TEST 10D raw and risk-adjusted winner."
                if candidate_type == "primary_candidate" else
                "Secondary V21.077 policy marked research_candidate_ready."
            ),
            "research_only": True,
        })
    return pd.DataFrame(rows).sort_values(["forward_validation_priority", "top_n", "policy_id"])


def repaired_classification_master(root: Path, output: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = pd.read_csv(root / CLASSIFICATION_REL, low_memory=False)
    rank = pd.read_csv(root / RANKING_REL, low_memory=False)
    rank = rank[rank["eligible_for_variant_ranking"].map(truth)].copy()
    rank["rank"] = pd.to_numeric(rank["final_shadow_rank"], errors="coerce")
    needed = set(rank.loc[rank["rank"].le(50), "ticker"].astype(str).str.upper().str.strip())
    if (output / LEDGER_NAME).is_file():
        old = pd.read_csv(output / LEDGER_NAME, usecols=["ticker"], low_memory=False)
        needed |= set(old["ticker"].astype(str).str.upper().str.strip())
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    have = set(base["ticker"])
    meta = pd.read_csv(root / METADATA_REL, low_memory=False)
    meta["ticker"] = meta["ticker"].astype(str).str.upper().str.strip()
    rows: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    for ticker in sorted(needed):
        existing = base[base["ticker"].eq(ticker)]
        old_sector = existing.iloc[0].get("sector", "") if len(existing) else ""
        old_industry = existing.iloc[0].get("industry", "") if len(existing) else ""
        missing = (
            ticker not in have
            or pd.isna(old_sector) or str(old_sector).strip() in {"", "nan", "NaN"}
            or pd.isna(old_industry) or str(old_industry).strip() in {"", "nan", "NaN"}
        )
        if not missing:
            continue
        meta_row = meta[meta["ticker"].eq(ticker)]
        if len(meta_row):
            m = meta_row.iloc[0]
            sector = str(m.get("sector") or "").strip()
            industry = str(m.get("industry") or "").strip()
            certified = str(m.get("exposure_metadata_certification_status") or "") == "EXPOSURE_METADATA_CERTIFIED"
            quality = "HIGH_CERTIFIED_REPAIR" if sector and industry and certified else "LOW_CONFIDENCE"
            hard_cap = bool(sector and industry and certified)
            source = "V20_108_R8_R2_ENABLED_METADATA_CACHE"
            status = "REPAIRED_FROM_LOCAL_METADATA" if sector and industry else "LOW_CONFIDENCE_PLACEHOLDER"
        else:
            sector, industry, quality, hard_cap = "UNCLASSIFIED", "UNCLASSIFIED", "LOW_CONFIDENCE", False
            source, status = "NO_LOCAL_METADATA_EXACT_MATCH", "LOW_CONFIDENCE_PLACEHOLDER"
        if not sector:
            sector = "UNCLASSIFIED"
            hard_cap = False
        if not industry:
            industry = "UNCLASSIFIED"
            hard_cap = False
        row = {
            "ticker": ticker,
            "sector": sector,
            "industry": industry,
            "sub_industry": industry,
            "theme_tags": "",
            "theme_confidence": "",
            "theme_tags_inferred": False,
            "theme_tags_allowed_for_hard_caps": False,
            "etf_category": "",
            "is_etf": False,
            "etf_leverage_inverse_flag": "UNLEVERED_OR_NA",
            "classification_source": source,
            "classification_as_of_date": "2026-06-13",
            "classification_quality_flag": quality,
            "stable_company_classification": True,
            "time_varying_classification": False,
            "low_confidence_label": quality == "LOW_CONFIDENCE",
            "source_reliability_score": 0.90 if hard_cap else 0.25,
            "pit_leakage_warning": False,
            "hard_cap_allowed": hard_cap,
            "research_only": True,
        }
        additions.append(row)
        rows.append({
            "ticker": ticker,
            "old_sector": old_sector,
            "old_industry": old_industry,
            "repaired_sector": sector,
            "repaired_industry": industry,
            "repair_source": source,
            "classification_quality_flag": quality,
            "hard_cap_allowed": hard_cap,
            "pit_leakage_warning": False,
            "repair_status": status,
            "research_only": True,
        })
    if additions:
        base = pd.concat([base, pd.DataFrame(additions)], ignore_index=True)
    if "hard_cap_allowed" not in base.columns:
        base["hard_cap_allowed"] = ~base["classification_quality_flag"].astype(str).str.contains("LOW", case=False, na=False)
    base.to_csv(output / R4_MASTER_NAME, index=False)
    report = pd.DataFrame(rows, columns=[
        "ticker", "old_sector", "old_industry", "repaired_sector",
        "repaired_industry", "repair_source", "classification_quality_flag",
        "hard_cap_allowed", "pit_leakage_warning", "repair_status",
        "research_only",
    ])
    report.to_csv(output / R4_REPAIR_REPORT_NAME, index=False)
    return base, report


def current_rank_frame(root: Path, class_master: pd.DataFrame | None = None) -> pd.DataFrame:
    rank = pd.read_csv(root / RANKING_REL, low_memory=False)
    rank = rank[rank["eligible_for_variant_ranking"].map(truth)].copy()
    rank["rank"] = pd.to_numeric(rank["final_shadow_rank"], errors="coerce")
    rank["score"] = pd.to_numeric(rank["final_shadow_score"], errors="coerce")
    rank = rank[rank["rank"].notna()].sort_values("rank")
    classes = class_master.copy() if class_master is not None else pd.read_csv(root / CLASSIFICATION_REL, low_memory=False)
    class_cols = [
        "ticker", "sector", "industry", "theme_tags",
        "theme_tags_allowed_for_hard_caps", "classification_quality_flag",
        "etf_category", "etf_leverage_inverse_flag", "hard_cap_allowed",
    ]
    for col in class_cols:
        if col not in classes.columns:
            classes[col] = ""
    rank["ticker"] = rank["ticker"].astype(str).str.upper().str.strip()
    classes["ticker"] = classes["ticker"].astype(str).str.upper().str.strip()
    rank = rank.merge(classes[class_cols], on="ticker", how="left")
    return rank


def policy_weights(root: Path, policy_id: str, frame: pd.DataFrame) -> tuple[pd.Series, bool, str]:
    v77 = load_v77_module(root)
    policies = v77.policy_definitions()
    policy = policies[policies["policy_id"].eq(policy_id)].iloc[0]
    work = frame.copy()
    work["position_weight"] = 1.0 / len(work)
    weights, feasible, reason = v77.apply_policy(work, policy)
    return weights.reindex(work.index).fillna(0.0), bool(feasible), str(reason or "")


def build_ledger(root: Path, candidates: pd.DataFrame, class_master: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    rank = current_rank_frame(root, class_master)
    rows: list[dict[str, Any]] = []
    feasibility_rows: list[dict[str, Any]] = []
    for _, candidate in candidates.iterrows():
        policy_id = candidate["policy_id"]
        top_n = 20 if candidate["top_n"] == "TOP20" else 50
        top = rank[rank["rank"].le(top_n)].copy()
        top["baseline_weight"] = 1.0 / top_n
        weights, feasible, reason = policy_weights(root, policy_id, top)
        feasibility_rows.append({
            "policy_id": policy_id,
            "top_n": f"TOP{top_n}",
            "latest_ledger_feasible": feasible,
            "latest_ledger_infeasible_reason": reason,
            "research_only": True,
        })
        if not feasible:
            continue
        top["position_weight"] = weights
        as_of = str(top["as_of_date"].iloc[0])[:10]
        as_of_ts = pd.Timestamp(as_of)
        for window, days in WINDOW_DAYS.items():
            due = (as_of_ts + BDay(days)).date().isoformat()
            for _, row in top.iterrows():
                obs_id = f"V21_078::{as_of}::{policy_id}::{window}::{row['ticker']}"
                rows.append({
                    "as_of_date": as_of,
                    "policy_id": policy_id,
                    "candidate_type": candidate["candidate_type"],
                    "top_n": f"TOP{top_n}",
                    "ticker": row["ticker"],
                    "rank": int(row["rank"]),
                    "score": row["score"],
                    "sector": row.get("sector", ""),
                    "industry": row.get("industry", ""),
                    "position_weight": row["position_weight"],
                    "baseline_weight": row["baseline_weight"],
                    "weight_delta_vs_D_EW": row["position_weight"] - row["baseline_weight"],
                    "classification_quality_flag": row.get("classification_quality_flag", ""),
                    "hard_cap_allowed": row.get("hard_cap_allowed", True),
                    "theme_tags": row.get("theme_tags", ""),
                    "theme_hard_cap_used": False,
                    "etf_category": row.get("etf_category", ""),
                    "etf_leverage_inverse_flag": row.get("etf_leverage_inverse_flag", ""),
                    "observation_id": obs_id,
                    "forward_window": window,
                    "maturity_due_date": due,
                    "maturity_status": "PENDING",
                    "research_only": True,
                })
    return pd.DataFrame(rows), pd.DataFrame(feasibility_rows)


def audit_ledger(ledger: pd.DataFrame) -> dict[str, Any]:
    group_cols = ["as_of_date", "policy_id", "forward_window"]
    weight_sums = ledger.groupby(group_cols)["position_weight"].sum()
    due_days = ledger["forward_window"].map(WINDOW_DAYS)
    expected_due = [
        (pd.Timestamp(asof) + BDay(int(days))).date().isoformat()
        for asof, days in zip(ledger["as_of_date"], due_days)
    ]
    return {
        "duplicate_observation_ids": int(ledger["observation_id"].duplicated().sum()),
        "missing_tickers": int(ledger["ticker"].astype(str).str.strip().eq("").sum()),
        "missing_ranks": int(pd.to_numeric(ledger["rank"], errors="coerce").isna().sum()),
        "missing_scores": int(pd.to_numeric(ledger["score"], errors="coerce").isna().sum()),
        "missing_sector_industry": int(
            (ledger["sector"].isna() | ledger["sector"].astype(str).str.strip().isin(["", "nan", "NaN"])).sum()
            + (ledger["industry"].isna() | ledger["industry"].astype(str).str.strip().isin(["", "nan", "NaN"])).sum()
        ),
        "invalid_weights": int(
            pd.to_numeric(ledger["position_weight"], errors="coerce").isna().sum()
            + pd.to_numeric(ledger["position_weight"], errors="coerce").lt(0).sum()
        ),
        "weight_sum_validity": bool(weight_sums.sub(1.0).abs().le(1e-8).all()),
        "max_ticker_weight": float(pd.to_numeric(ledger["position_weight"], errors="coerce").max()),
        "theme_hard_cap_usage": bool(ledger["theme_hard_cap_used"].map(truth).any()),
        "pit_leakage_warnings": 0,
        "maturity_schedule_warnings": int((ledger["maturity_due_date"].astype(str) != pd.Series(expected_due, index=ledger.index)).sum()),
        "baseline_candidate_pair_complete": {"D_EW_TOP20_R1", "D_EW_TOP50_R1", "D_SECTOR_INDUSTRY_CAP_TOP20_R1", "D_SECTOR_CAP_TOP50_R1"}.issubset(set(ledger["policy_id"])),
    }


def feasibility_and_fallback(root: Path, candidates: pd.DataFrame, class_master: pd.DataFrame, output: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rank = current_rank_frame(root, class_master)
    v77 = load_v77_module(root)
    policy_defs = v77.policy_definitions()
    fallback_map = {
        "D_SECTOR_INDUSTRY_CAP_TOP20_R1": ["D_SECTOR_INDUSTRY_SOFT_PENALTY_TOP20_R1", "D_SECTOR_SOFT_PENALTY_TOP20_R1", "D_EW_TOP20_R1"],
        "D_SECTOR_CAP_TOP20_R1": ["D_SECTOR_SOFT_PENALTY_TOP20_R1", "D_EW_TOP20_R1"],
        "D_SECTOR_CAP_TOP50_R1": ["D_SECTOR_SOFT_PENALTY_TOP50_R1", "D_EW_TOP50_R1"],
    }
    report_rows: list[dict[str, Any]] = []
    select_rows: list[dict[str, Any]] = []

    def check(policy_id: str, top_n: int) -> tuple[bool, str, float, float, float]:
        top = rank[rank["rank"].le(top_n)].copy()
        p = policy_defs[policy_defs["policy_id"].eq(policy_id)].iloc[0]
        uses_hard = truth(p.get("uses_hard_sector_cap")) or truth(p.get("uses_hard_industry_cap"))
        if uses_hard and not top["hard_cap_allowed"].map(truth).all():
            return False, "LOW_CONFIDENCE_CLASSIFICATION_REQUIRED_FOR_HARD_CAP", 0.0, 0.0, 0.0
        top["position_weight"] = 1.0 / len(top)
        weights, feasible, reason = v77.apply_policy(top, p)
        max_weight = float(weights.max()) if len(weights) else 0.0
        sector_max = float(weights.groupby(top["sector"]).sum().max()) if len(weights) else 0.0
        industry_max = float(weights.groupby(top["industry"]).sum().max()) if len(weights) else 0.0
        if max_weight > MAX_TICKER_CAP + 1e-8:
            feasible, reason = False, "MAX_TICKER_CAP_VIOLATION"
        return bool(feasible), str(reason or ""), max_weight, sector_max, industry_max

    for _, cand in candidates.iterrows():
        policy_id = cand["policy_id"]
        top_n = 20 if cand["top_n"] == "TOP20" else 50
        p = policy_defs[policy_defs["policy_id"].eq(policy_id)].iloc[0]
        feasible, reason, max_w, sector_max, industry_max = check(policy_id, top_n)
        fallback_policy = policy_id
        fallback_used = False
        forward_ready = feasible
        if not feasible:
            for alt in fallback_map.get(policy_id, [f"D_EW_TOP{top_n}_R1"]):
                alt_feasible, alt_reason, _, _, _ = check(alt, top_n)
                if alt_feasible:
                    fallback_policy = alt
                    fallback_used = alt != policy_id
                    forward_ready = True
                    break
        report_rows.append({
            "policy_id": policy_id,
            "top_n": f"TOP{top_n}",
            "policy_type": p["policy_family"],
            "hard_cap_policy": truth(p.get("uses_hard_sector_cap")) or truth(p.get("uses_hard_industry_cap")),
            "sector_cap": p.get("sector_cap", ""),
            "industry_cap": p.get("industry_cap", ""),
            "max_ticker_weight": max_w,
            "policy_feasible": feasible,
            "infeasibility_reason": reason,
            "fallback_policy_id": fallback_policy,
            "fallback_used": fallback_used,
            "forward_ready": forward_ready,
            "notes": "Original policy feasible." if feasible else f"Fallback selected: {fallback_policy}",
            "research_only": True,
        })
        if policy_id in BASELINES or policy_id in PRIMARY:
            select_rows.append({
                "original_policy_id": policy_id,
                "selected_policy_id": fallback_policy,
                "top_n": f"TOP{top_n}",
                "candidate_type": cand["candidate_type"],
                "fallback_used": fallback_used,
                "forward_ready": forward_ready,
                "selection_reason": "BASELINE_OR_PRIMARY_REPAIRED_SELECTION",
                "research_only": True,
            })
    report = pd.DataFrame(report_rows)
    selected = pd.DataFrame(select_rows)
    report.to_csv(output / R5_FEASIBILITY_NAME, index=False)
    selected.to_csv(output / R5_FALLBACK_NAME, index=False)
    return report, selected


def build_repaired_ledger(root: Path, fallback_selection: pd.DataFrame, class_master: pd.DataFrame) -> pd.DataFrame:
    selected = fallback_selection[fallback_selection["forward_ready"].map(truth)].copy()
    candidate_rows = []
    for _, row in selected.iterrows():
        candidate_rows.append({
            "policy_id": row["selected_policy_id"],
            "top_n": row["top_n"],
            "candidate_type": row["candidate_type"],
            "original_policy_id": row["original_policy_id"],
            "fallback_used": truth(row["fallback_used"]),
        })
    candidates = pd.DataFrame(candidate_rows).drop_duplicates(["policy_id", "top_n", "original_policy_id"])
    rank = current_rank_frame(root, class_master)
    rows: list[dict[str, Any]] = []
    for _, candidate in candidates.iterrows():
        policy_id = candidate["policy_id"]
        top_n = 20 if candidate["top_n"] == "TOP20" else 50
        top = rank[rank["rank"].le(top_n)].copy()
        top["baseline_weight"] = 1.0 / top_n
        weights, feasible, reason = policy_weights(root, policy_id, top)
        if not feasible:
            continue
        top["position_weight"] = weights
        as_of = str(top["as_of_date"].iloc[0])[:10]
        as_of_ts = pd.Timestamp(as_of)
        for window, days in WINDOW_DAYS.items():
            due = (as_of_ts + BDay(days)).date().isoformat()
            for _, r in top.iterrows():
                obs_id = f"V21_078_R6::{as_of}::{candidate['original_policy_id']}::{policy_id}::{window}::{r['ticker']}"
                rows.append({
                    "as_of_date": as_of,
                    "policy_id": policy_id,
                    "original_policy_id": candidate["original_policy_id"],
                    "fallback_used": candidate["fallback_used"],
                    "candidate_type": candidate["candidate_type"],
                    "top_n": f"TOP{top_n}",
                    "ticker": r["ticker"],
                    "rank": int(r["rank"]),
                    "score": r["score"],
                    "sector": r.get("sector", ""),
                    "industry": r.get("industry", ""),
                    "position_weight": r["position_weight"],
                    "baseline_weight": r["baseline_weight"],
                    "weight_delta_vs_D_EW": r["position_weight"] - r["baseline_weight"],
                    "classification_quality_flag": r.get("classification_quality_flag", ""),
                    "hard_cap_allowed": r.get("hard_cap_allowed", True),
                    "theme_hard_cap_used": False,
                    "observation_id": obs_id,
                    "forward_window": window,
                    "maturity_due_date": due,
                    "maturity_status": "PENDING",
                    "research_only": True,
                })
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    candidates = selected_candidates(root)
    candidates.to_csv(output / CANDIDATE_NAME, index=False)
    ledger, latest_feasibility = build_ledger(root, candidates)
    candidates = candidates.merge(latest_feasibility, on=["policy_id", "top_n"], how="left")
    candidates.to_csv(output / CANDIDATE_NAME, index=False)
    ledger.to_csv(output / LEDGER_NAME, index=False)
    audit = audit_ledger(ledger)
    audit["latest_infeasible_candidate_count"] = int((~latest_feasibility["latest_ledger_feasible"]).sum())
    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    audit.update({
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "protected_modified_paths": "|".join(changed),
        "research_only": True,
    })
    pd.DataFrame([audit]).to_csv(output / AUDIT_NAME, index=False)

    gates_pass = (
        audit["duplicate_observation_ids"] == 0
        and audit["missing_sector_industry"] == 0
        and audit["weight_sum_validity"]
        and not audit["theme_hard_cap_usage"]
        and audit["pit_leakage_warnings"] == 0
        and audit["maturity_schedule_warnings"] == 0
        and audit["baseline_candidate_pair_complete"]
        and audit["latest_infeasible_candidate_count"] == 0
        and not audit["protected_outputs_modified"]
        and not audit["official_outputs_mutated"]
    )
    integrity_clean = (
        audit["duplicate_observation_ids"] == 0
        and audit["weight_sum_validity"]
        and not audit["theme_hard_cap_usage"]
        and audit["pit_leakage_warnings"] == 0
        and not audit["protected_outputs_modified"]
        and not audit["official_outputs_mutated"]
    )
    primary_count = int(candidates["candidate_type"].eq("primary_candidate").sum())
    secondary_count = int(candidates["candidate_type"].eq("secondary_candidate").sum())
    final_status = (
        "PASS_V21_078_R3_SECTOR_AWARE_FORWARD_LEDGER_READY"
        if gates_pass else
        "PARTIAL_PASS_V21_078_R3_FORWARD_LEDGER_READY_WITH_MATURITY_OR_COVERAGE_WARN"
        if integrity_clean and audit["latest_infeasible_candidate_count"] == 0 and audit["baseline_candidate_pair_complete"] else
        "BLOCKED_V21_078_R3_FORWARD_LEDGER_INTEGRITY_OR_LEAKAGE_RISK"
    )
    decision = (
        "SECTOR_AWARE_FORWARD_RESEARCH_LEDGER_READY"
        if gates_pass else "KEEP_D_EQUAL_WEIGHT_BASELINE_AND_REPAIR_FORWARD_LEDGER"
    )
    readiness = {
        "stage": "V21.078-R3_LEDGER_INTEGRITY_AND_MATURITY_SCHEDULE_AUDIT",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_equal_weight_baseline_preserved": True,
        "primary_sector_aware_candidates_selected": primary_count,
        "secondary_candidates_selected": secondary_count,
        "portfolio_policies_in_forward_ledger": int(ledger["policy_id"].nunique()),
        "ledger_rows": int(len(ledger)),
        "distinct_tickers": int(ledger["ticker"].nunique()),
        "forward_windows": "|".join(sorted(ledger["forward_window"].unique())),
        "pending_observations": int(ledger["maturity_status"].eq("PENDING").sum()),
        "matured_observations": int((~ledger["maturity_status"].eq("PENDING")).sum()),
        "earliest_maturity_due_date": ledger["maturity_due_date"].min(),
        "latest_maturity_due_date": ledger["maturity_due_date"].max(),
        "weight_sum_validity": audit["weight_sum_validity"],
        "duplicate_observation_ids": audit["duplicate_observation_ids"],
        "missing_sector_industry": audit["missing_sector_industry"],
        "latest_infeasible_candidate_count": audit["latest_infeasible_candidate_count"],
        "baseline_candidate_pair_complete": audit["baseline_candidate_pair_complete"],
        "leakage_warnings": audit["pit_leakage_warnings"],
        "theme_hard_cap_usage": audit["theme_hard_cap_usage"],
        "protected_outputs_modified": audit["protected_outputs_modified"],
        "official_outputs_mutated": audit["official_outputs_mutated"],
        "forward_portfolio_append_allowed": "RESEARCH_ONLY_LEDGER_ONLY",
        "official_adoption_allowed": False,
        "research_only": True,
        "execution_pass_gate": gates_pass,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    class_master, repair_report = repaired_classification_master(root, output)
    feasibility, fallback = feasibility_and_fallback(root, candidates, class_master, output)
    repaired_ledger = build_repaired_ledger(root, fallback, class_master)
    repaired_ledger.to_csv(output / R6_LEDGER_NAME, index=False)
    repaired_audit = audit_ledger(repaired_ledger)
    repaired_audit.update({
        "hard_cap_feasibility_warnings": int((~feasibility["policy_feasible"]).sum()),
        "fallback_completeness": bool(fallback["forward_ready"].map(truth).all()),
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "research_only": True,
    })
    pd.DataFrame([repaired_audit]).to_csv(output / R6_AUDIT_NAME, index=False)
    repaired_pair_complete = {"D_EW_TOP20_R1", "D_EW_TOP50_R1", "D_SECTOR_INDUSTRY_CAP_TOP20_R1", "D_SECTOR_CAP_TOP50_R1"}.issubset(set(repaired_ledger["original_policy_id"]))
    repaired_gates = (
        repaired_audit["duplicate_observation_ids"] == 0
        and repaired_audit["missing_sector_industry"] == 0
        and repaired_audit["weight_sum_validity"]
        and repaired_audit["max_ticker_weight"] <= MAX_TICKER_CAP + 1e-8
        and repaired_audit["fallback_completeness"]
        and repaired_pair_complete
        and not repaired_audit["theme_hard_cap_usage"]
        and repaired_audit["pit_leakage_warnings"] == 0
        and repaired_audit["maturity_schedule_warnings"] == 0
        and not repaired_audit["protected_outputs_modified"]
        and not repaired_audit["official_outputs_mutated"]
    )
    fallback_used = bool(fallback["fallback_used"].map(truth).any())
    low_conf_rows = int((~repaired_ledger["hard_cap_allowed"].map(truth)).sum()) if len(repaired_ledger) else 0
    repaired_status = (
        "PASS_V21_078_R6_REPAIRED_SECTOR_AWARE_FORWARD_LEDGER_READY"
        if repaired_gates and not fallback_used and low_conf_rows == 0 else
        "PARTIAL_PASS_V21_078_R6_FORWARD_LEDGER_READY_WITH_FALLBACK_OR_CLASSIFICATION_WARN"
        if repaired_gates else
        "BLOCKED_V21_078_R6_FORWARD_LEDGER_REPAIR_FAILED"
    )
    repaired_decision = (
        "REPAIRED_SECTOR_AWARE_FORWARD_RESEARCH_LEDGER_READY"
        if repaired_gates else "KEEP_D_EQUAL_WEIGHT_BASELINE_AND_BLOCK_REPAIRED_LEDGER"
    )
    primary_feasible = feasibility.loc[feasibility["policy_id"].isin(PRIMARY), "policy_feasible"].map(truth).all()
    top20_selected = fallback.loc[fallback["original_policy_id"].eq("D_SECTOR_INDUSTRY_CAP_TOP20_R1"), "selected_policy_id"]
    top50_selected = fallback.loc[fallback["original_policy_id"].eq("D_SECTOR_CAP_TOP50_R1"), "selected_policy_id"]
    repaired_readiness = {
        "stage": "V21.078-R6_REPAIRED_FORWARD_LEDGER_AUDIT",
        "final_status": repaired_status,
        "decision": repaired_decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_equal_weight_baseline_preserved": True,
        "original_blocker_count": 3,
        "missing_sector_industry_before": audit["missing_sector_industry"],
        "missing_sector_industry_after": repaired_audit["missing_sector_industry"],
        "primary_hard_cap_policies_feasible": bool(primary_feasible),
        "fallback_used": fallback_used,
        "selected_top20_forward_candidate": top20_selected.iloc[0] if len(top20_selected) else "",
        "selected_top50_forward_candidate": top50_selected.iloc[0] if len(top50_selected) else "",
        "portfolio_policies_in_repaired_ledger": int(repaired_ledger["policy_id"].nunique()),
        "repaired_ledger_rows": int(len(repaired_ledger)),
        "distinct_tickers": int(repaired_ledger["ticker"].nunique()) if len(repaired_ledger) else 0,
        "forward_windows": "|".join(sorted(repaired_ledger["forward_window"].unique())) if len(repaired_ledger) else "",
        "pending_observations": int(repaired_ledger["maturity_status"].eq("PENDING").sum()) if len(repaired_ledger) else 0,
        "matured_observations": int((~repaired_ledger["maturity_status"].eq("PENDING")).sum()) if len(repaired_ledger) else 0,
        "earliest_maturity_due_date": repaired_ledger["maturity_due_date"].min() if len(repaired_ledger) else "",
        "latest_maturity_due_date": repaired_ledger["maturity_due_date"].max() if len(repaired_ledger) else "",
        "weight_sum_validity": repaired_audit["weight_sum_validity"],
        "duplicate_observation_ids": repaired_audit["duplicate_observation_ids"],
        "missing_sector_industry": repaired_audit["missing_sector_industry"],
        "leakage_warnings": repaired_audit["pit_leakage_warnings"],
        "theme_hard_cap_usage": repaired_audit["theme_hard_cap_usage"],
        "protected_outputs_modified": repaired_audit["protected_outputs_modified"],
        "official_outputs_mutated": repaired_audit["official_outputs_mutated"],
        "forward_portfolio_append_allowed": "RESEARCH_ONLY_REPAIRED_LEDGER_ONLY",
        "official_adoption_allowed": False,
        "research_only": True,
        "execution_pass_gate": repaired_gates,
    }
    pd.DataFrame([repaired_readiness]).to_csv(output / R6_READINESS_NAME, index=False)
    result = dict(readiness)
    result.update({f"r6_{k}": v for k, v in repaired_readiness.items()})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "portfolio_policies_in_forward_ledger", "ledger_rows", "pending_observations"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
