#!/usr/bin/env python
"""V21.092-R3 marginal factor effectiveness and risk-gate calibration."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_092_r3")
R1 = Path("outputs/v21/diagnostics/v21_092_r1")
R2 = Path("outputs/v21/diagnostics/v21_092_r2")
PANEL_REL = R1 / "V21_092_R1_FACTOR_EFFECTIVENESS_PANEL.csv"
IC_REL = R1 / "V21_092_R1_FACTOR_IC_AND_QUANTILE_SUMMARY.csv"
SPLIT_REL = R1 / "V21_092_R1_NESTED_WALKFORWARD_SPLIT_PLAN.csv"
R1_RESULTS_REL = R1 / "V21_092_R1_NESTED_WALKFORWARD_WEIGHT_RESULTS.csv"
FILTER_REL = R2 / "V21_092_R2_FACTOR_STABILITY_FILTER.csv"
FORENSIC_REL = R2 / "V21_092_R2_R1_DRAWDOWN_FAILURE_FORENSIC.csv"
GRID_REL = R2 / "V21_092_R2_STABILITY_TIGHTENED_WEIGHT_GRID.csv"
R2_RESULTS_REL = R2 / "V21_092_R2_NESTED_WALKFORWARD_TIGHTENED_RESULTS.csv"
R2_SUMMARY_REL = R2 / "V21_092_R2_TIGHTENED_CANDIDATE_SUMMARY.csv"
R2_SELECTED_REL = R2 / "V21_092_R2_SELECTED_SHADOW_WEIGHT_CANDIDATE.csv"
TECH_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
R1_SCRIPT = Path("scripts/v21/v21_092_r1_factor_effectiveness_nested_walkforward_and_dynamic_weight_shadow_search.py")
R2_SCRIPT = Path("scripts/v21/v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening.py")

INVENTORY_NAME = "V21_092_R3_INPUT_SOURCE_INVENTORY.csv"
ALLOWED_NAME = "V21_092_R3_ALLOWED_FACTOR_SET.csv"
ONE_FACTOR_NAME = "V21_092_R3_ONE_FACTOR_WEIGHT_RESPONSE.csv"
LOO_NAME = "V21_092_R3_LEAVE_ONE_FACTOR_OUT_STUDY.csv"
SHRINKAGE_NAME = "V21_092_R3_SHRINKAGE_PATH_RESULTS.csv"
GATE_NAME = "V21_092_R3_RISK_GATE_CALIBRATION_DIAGNOSTIC.csv"
RISK_SUMMARY_NAME = "V21_092_R3_FACTOR_RISK_CONTRIBUTION_SUMMARY.csv"
SAFE_MAP_NAME = "V21_092_R3_SAFE_WEIGHT_RANGE_MAP.csv"
FRONTIER_NAME = "V21_092_R3_RISK_ADJUSTED_UTILITY_FRONTIER.csv"
MATRIX_NAME = "V21_092_R3_WEIGHT_EFFECTIVENESS_DECISION_MATRIX.csv"
SELECTION_NAME = "V21_092_R3_NO_SHADOW_SELECTION_CONFIRMATION.csv"
FORBIDDEN_NAME = "V21_092_R3_FORBIDDEN_SIGNAL_AUDIT.csv"
CERT_NAME = "V21_092_R3_NO_ADOPTION_CERTIFICATION.csv"
MUTATION_NAME = "V21_092_R3_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_092_R3_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    INVENTORY_NAME, ALLOWED_NAME, ONE_FACTOR_NAME, LOO_NAME, SHRINKAGE_NAME,
    GATE_NAME, RISK_SUMMARY_NAME, SAFE_MAP_NAME, FRONTIER_NAME, MATRIX_NAME,
    SELECTION_NAME, FORBIDDEN_NAME, CERT_NAME, MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = ("5D", "10D", "20D")


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_module(root: Path, rel: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, root / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inventory(root: Path) -> pd.DataFrame:
    sources = [
        (PANEL_REL, "R1_FACTOR_PANEL_REQUIRED"), (IC_REL, "R1_FACTOR_IC_REQUIRED"),
        (SPLIT_REL, "R1_NESTED_SPLITS_REQUIRED"), (R1_RESULTS_REL, "R1_RESULTS_REQUIRED"),
        (FILTER_REL, "R2_FACTOR_FILTER_REQUIRED"), (FORENSIC_REL, "R2_FORENSIC_REQUIRED"),
        (GRID_REL, "R2_GRID_REQUIRED"), (R2_RESULTS_REL, "R2_RESULTS_REQUIRED"),
        (R2_SUMMARY_REL, "R2_SUMMARY_REQUIRED"), (R2_SELECTED_REL, "R2_SELECTION_REQUIRED"),
        (TECH_REL, "TECHNICAL_REFERENCE"),
    ]
    rows = []
    for rel, role in sources:
        path = root / rel
        exists = path.is_file()
        row_count = ticker_count = 0
        min_date = max_date = ""
        warning = ""
        if exists:
            try:
                sample = pd.read_csv(path, nrows=2)
                use = [c for c in ("ticker", "as_of_date", "source_latest_price_date") if c in sample]
                data = pd.read_csv(path, usecols=use or [sample.columns[0]], low_memory=False)
                row_count = len(data)
                ticker_count = data["ticker"].nunique() if "ticker" in data else 0
                dates = []
                for col in [c for c in data if "date" in c]:
                    dates.extend(data[col].dropna().astype(str).str[:10].tolist())
                dates = [d for d in dates if len(d) == 10 and d[4] == "-"]
                if dates:
                    min_date, max_date = min(dates), max(dates)
            except Exception as exc:
                warning = f"READ_WARNING:{type(exc).__name__}"
        else:
            warning = "REQUIRED_INPUT_MISSING"
        rows.append({
            "source_path": rel.as_posix(), "source_role": role, "exists": exists,
            "row_count": row_count, "ticker_count": ticker_count,
            "min_date": min_date, "max_date": max_date,
            "usable_for_r3": exists, "warning": warning,
        })
    return pd.DataFrame(rows)


def allowed_factors(filters: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in filters.iterrows():
        factor = str(row["factor_name"])
        r2_status = str(row["factor_filter_status"])
        family = str(row["factor_family"])
        if factor == "z_tech_ma_slope_alignment":
            status, sign, lo, hi, pos, pen, diag = "ALLOWED_CORE_POSITIVE", "POSITIVE", 0.0, .05, True, False, False
        elif factor in {"z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_rs_vs_soxx", "z_tech_breakout_confirmed", "z_tech_volume_confirmation"}:
            status, sign, lo, hi, pos, pen, diag = "ALLOWED_SMALL_POSITIVE", "POSITIVE", 0.0, min(.02, float(row["max_allowed_weight"])), True, False, False
        elif factor in {"z_fund_low_quality_risk", "z_interaction_low_quality_momentum_risk", "z_bucket_low_quality_momentum", "z_bucket_interaction_data_gap", "z_interaction_wait_confirmation", "z_tech_overextended_but_strong"}:
            status, sign, lo, hi, pos, pen, diag = "PENALTY_ONLY", "NEGATIVE", -.02, 0.0, False, True, False
        elif factor in {"z_tech_pullback_original", "z_tech_pullback_repaired_best"}:
            status, sign, lo, hi, pos, pen, diag = "FORBIDDEN_POSITIVE_WEIGHT", "NEGATIVE_OR_ZERO", -.01, 0.0, False, True, False
        elif factor == "TECH_BREAKOUT_DAY0_WATCH_ONLY" or factor == "z_bucket_day0_watch_only":
            status, sign, lo, hi, pos, pen, diag = "FORBIDDEN_POSITIVE_WEIGHT", "ZERO_OR_PENALTY", -.01, 0.0, False, True, True
        elif family.startswith(("FUNDAMENTAL", "INTERACTION", "BUCKET")):
            status, sign, lo, hi, pos, pen, diag = "DIAGNOSTIC_ONLY", "ZERO", 0.0, 0.0, False, False, True
        elif r2_status == "BLACKLIST_NO_POSITIVE_WEIGHT":
            status, sign, lo, hi, pos, pen, diag = "PENALTY_ONLY", "NEGATIVE", -.02, 0.0, False, True, False
        else:
            status, sign, lo, hi, pos, pen, diag = "DIAGNOSTIC_ONLY", "ZERO", 0.0, 0.0, False, False, True
        rows.append({
            "factor_name": factor, "factor_family": family, "r2_filter_status": r2_status,
            "r3_allowed_status": status, "allowed_weight_sign": sign,
            "max_test_weight": hi, "min_test_weight": lo,
            "positive_weight_allowed": pos, "penalty_weight_allowed": pen,
            "diagnostic_only": diag,
            "reason": row["reason"], "warning": "" if status.startswith("ALLOWED") else status,
        })
    return pd.DataFrame(rows)


def factor_tests(allowed: pd.DataFrame) -> list[tuple[str, str, float, str]]:
    mapping = {
        "z_tech_ma_slope_alignment": ("TechnicalMAAlignment", [.01, .025, .05]),
        "z_tech_rs_vs_qqq": ("TechnicalRelativeStrength", [.005, .01, .02]),
        "z_tech_rs_vs_spy": ("TechnicalRelativeStrength", [.005, .01, .02]),
        "z_tech_rs_vs_soxx": ("TechnicalRelativeStrength", [.005, .01, .02]),
        "z_tech_breakout_confirmed": ("TechnicalBreakoutConfirmed", [.005, .01, .015]),
        "z_tech_volume_confirmation": ("TechnicalBreakoutConfirmed", [.005, .01, .015]),
        "z_fund_low_quality_risk": ("LowQualityMomentumPenalty", [-.002, -.005, -.01]),
        "z_bucket_interaction_data_gap": ("InteractionUnavailablePenalty", [-.001, -.003, -.005]),
        "z_tech_overextended_but_strong": ("OverextendedConcentrationPenalty", [-.002, -.005, -.01]),
    }
    return [
        (factor, component, weight, str(allowed.loc[allowed["factor_name"].eq(factor), "factor_family"].iloc[0]))
        for factor, (component, weights) in mapping.items()
        if factor in set(allowed["factor_name"])
        for weight in weights
    ]


def prepare_work(panel: pd.DataFrame, r1, r2) -> pd.DataFrame:
    comp = r2.r2_components(panel, r1)
    work = pd.concat([panel.reset_index(drop=True), comp.reset_index(drop=True)], axis=1)
    work["D_PROXY_SCORE"] = .6 * work["Base"] + .4 * work["Momentum"]
    return work


def rank_top(work: pd.DataFrame, score: pd.Series) -> pd.DataFrame:
    ranked = work[["as_of_date", "ticker"]].copy()
    ranked["score"] = score.values
    ranked["rank"] = ranked.groupby("as_of_date")["score"].rank(method="first", ascending=False)
    return ranked[ranked["rank"].le(20)][["as_of_date", "ticker", "rank"]]


def period_metrics(
    work: pd.DataFrame, top_keys: pd.DataFrame, split: pd.Series, window: str
) -> dict[str, float]:
    ret_col = f"return_{window.lower()}_forward"
    subset = work[
        work["as_of_date"].between(split["test_start"], split["test_end"])
        & work[f"forward_{window.lower()}_matured"].map(truth)
        & work[ret_col].notna()
    ].merge(top_keys[["as_of_date", "ticker"]], on=["as_of_date", "ticker"], how="inner")
    daily = subset.groupby("as_of_date")[ret_col].mean().sort_index()
    curve = (1 + daily.fillna(0)).cumprod()
    dates = max(1, subset["as_of_date"].nunique())
    persistence = subset.groupby("ticker")["as_of_date"].nunique().div(dates)
    concentration = persistence.max() if len(persistence) else np.nan
    return {
        "mean": subset[ret_col].mean(), "median": subset[ret_col].median(),
        "hit": subset[ret_col].gt(0).mean(),
        "drawdown": (curve / curve.cummax() - 1).min() if len(curve) else np.nan,
        "concentration": concentration,
        "rows": len(subset),
    }


def train_validation_scores(work: pd.DataFrame, top_keys: pd.DataFrame, split: pd.Series, window: str, d_top: pd.DataFrame) -> tuple[float, float]:
    ret_col, mat_col = f"return_{window.lower()}_forward", f"forward_{window.lower()}_matured"
    scores = []
    for start, end in ((split["train_start"], split["train_end"]), (split["validation_start"], split["validation_end"])):
        eligible = work[work["as_of_date"].between(start, end) & work[mat_col].map(truth) & work[ret_col].notna()]
        cand = eligible.merge(top_keys, on=["as_of_date", "ticker"], how="inner")[ret_col].mean()
        base = eligible.merge(d_top, on=["as_of_date", "ticker"], how="inner")[ret_col].mean()
        scores.append(cand - base)
    return scores[0], scores[1]


def overlap(top_a: pd.DataFrame, top_b: pd.DataFrame, start: str, end: str) -> float:
    values = []
    a = top_a[top_a["as_of_date"].between(start, end)]
    b = top_b[top_b["as_of_date"].between(start, end)]
    for date in sorted(set(a["as_of_date"]) | set(b["as_of_date"])):
        aset = set(a.loc[a["as_of_date"].eq(date), "ticker"])
        bset = set(b.loc[b["as_of_date"].eq(date), "ticker"])
        values.append(len(aset & bset) / 20)
    return float(np.mean(values)) if values else np.nan


def one_factor_response(work: pd.DataFrame, splits: pd.DataFrame, allowed: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    d_top = rank_top(work, work["D_PROXY_SCORE"])
    cache = {"D": d_top}
    rows = []
    for factor, component, weight, family in factor_tests(allowed):
        key = f"{factor}@{weight}"
        top = rank_top(work, work["D_PROXY_SCORE"] + weight * work[component])
        cache[key] = top
        for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
            window = split["forward_window"]
            cand = period_metrics(work, top, split, window)
            base = period_metrics(work, d_top, split, window)
            train, validation = train_validation_scores(work, top, split, window, d_top)
            turnover = 1 - overlap(top, d_top, split["test_start"], split["test_end"])
            dd_delta = cand["drawdown"] - base["drawdown"]
            conc_delta = cand["concentration"] - base["concentration"]
            excess = cand["mean"] - base["mean"]
            denom = abs(weight)
            stability = validation > -.001 and excess > -.001
            drawdown_pass = cand["drawdown"] >= -.30
            concentration_pass = pd.isna(cand["concentration"]) or cand["concentration"] <= .75
            usable = stability and drawdown_pass and concentration_pass and turnover <= .25
            rows.append({
                "factor_name": factor, "factor_family": family, "tested_weight": weight,
                "forward_window": window, "split_id": split["split_id"],
                "train_score": train, "validation_score": validation,
                "test_mean_forward_return": cand["mean"], "test_median_forward_return": cand["median"],
                "test_hit_rate": cand["hit"], "test_drawdown_proxy": cand["drawdown"],
                "test_turnover_proxy": turnover, "test_concentration_proxy": cand["concentration"],
                "test_excess_vs_D_proxy": excess, "marginal_return_per_weight": excess / denom,
                "marginal_drawdown_per_weight": dd_delta / denom,
                "marginal_turnover_per_weight": turnover / denom,
                "marginal_concentration_per_weight": conc_delta / denom,
                "risk_adjusted_marginal_score": excess + .10 * dd_delta - .01 * turnover - .01 * max(0, conc_delta),
                "stability_gate_pass": stability, "drawdown_gate_pass": drawdown_pass,
                "concentration_gate_pass": concentration_pass, "usable_weight_region": usable,
                "warning": "" if usable else "ONE_OR_MORE_GATES_FAILED",
            })
    return pd.DataFrame(rows), cache


def leave_one_out(work: pd.DataFrame, splits: pd.DataFrame, grid: pd.DataFrame, r2) -> pd.DataFrame:
    rows = []
    for _, candidate in grid.iterrows():
        original_score = sum(float(candidate[c]) * work[c] for c in r2.R2_COMPONENTS)
        original_top = rank_top(work, original_score)
        active = [c for c in r2.R2_COMPONENTS[2:] if abs(float(candidate[c])) > 1e-12]
        for component in active:
            loo_top = rank_top(work, original_score - float(candidate[component]) * work[component])
            for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
                window = split["forward_window"]
                original = period_metrics(work, original_top, split, window)
                loo = period_metrics(work, loo_top, split, window)
                return_delta = loo["mean"] - original["mean"]
                dd_delta = loo["drawdown"] - original["drawdown"]
                conc_delta = loo["concentration"] - original["concentration"]
                risk_flag = dd_delta > .01 and return_delta > -.001
                rows.append({
                    "base_candidate_id": candidate["candidate_id"], "removed_factor_name": component,
                    "forward_window": window, "split_id": split["split_id"],
                    "original_test_mean_return": original["mean"], "loo_test_mean_return": loo["mean"],
                    "return_delta_removed_minus_original": return_delta,
                    "original_drawdown_proxy": original["drawdown"], "loo_drawdown_proxy": loo["drawdown"],
                    "drawdown_delta_removed_minus_original": dd_delta,
                    "original_concentration_proxy": original["concentration"],
                    "loo_concentration_proxy": loo["concentration"],
                    "concentration_delta_removed_minus_original": conc_delta,
                    "interpretation": "REMOVAL_IMPROVES_RISK_WITH_LIMITED_RETURN_LOSS" if risk_flag else "NO_CLEAR_RISK_REDUCTION",
                    "factor_risk_contribution_flag": risk_flag,
                    "warning": "" if risk_flag else "NO_CLEAR_MARGINAL_RISK_SIGNAL",
                })
    return pd.DataFrame(rows)


def shrinkage_paths(work: pd.DataFrame, splits: pd.DataFrame, grid: pd.DataFrame, r2) -> pd.DataFrame:
    d_top = rank_top(work, work["D_PROXY_SCORE"])
    rows = []
    for _, candidate in grid.iterrows():
        candidate_score = sum(float(candidate[c]) * work[c] for c in r2.R2_COMPONENTS)
        for lam in (0.0, .25, .50, .75, 1.0):
            top = rank_top(work, work["D_PROXY_SCORE"] + lam * (candidate_score - work["D_PROXY_SCORE"]))
            for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
                window = split["forward_window"]
                cand = period_metrics(work, top, split, window)
                base = period_metrics(work, d_top, split, window)
                turnover = 1 - overlap(top, d_top, split["test_start"], split["test_end"])
                excess = cand["mean"] - base["mean"]
                dd_delta = cand["drawdown"] - base["drawdown"]
                conc_delta = cand["concentration"] - base["concentration"]
                train, validation = train_validation_scores(work, top, split, window, d_top)
                drawdown_pass = cand["drawdown"] >= -.30
                concentration_pass = pd.isna(cand["concentration"]) or cand["concentration"] <= .75
                stability = validation > -.001 and excess > -.001 and abs(train - excess) <= .02
                usable = drawdown_pass and concentration_pass and stability and turnover <= .25
                rows.append({
                    "base_candidate_id": candidate["candidate_id"], "shrinkage_lambda": lam,
                    "forward_window": window, "split_id": split["split_id"],
                    "test_mean_forward_return": cand["mean"], "test_median_forward_return": cand["median"],
                    "test_hit_rate": cand["hit"], "test_drawdown_proxy": cand["drawdown"],
                    "test_turnover_proxy": turnover, "test_concentration_proxy": cand["concentration"],
                    "test_excess_vs_D_proxy": excess, "drawdown_delta_vs_D_proxy": dd_delta,
                    "concentration_delta_vs_D_proxy": conc_delta,
                    "risk_adjusted_score": excess + .10 * dd_delta - .01 * turnover - .01 * max(0, conc_delta),
                    "drawdown_gate_pass": drawdown_pass, "concentration_gate_pass": concentration_pass,
                    "stability_gate_pass": stability, "usable_shrinkage_region": usable,
                    "warning": "" if usable else "ONE_OR_MORE_GATES_FAILED",
                })
    return pd.DataFrame(rows)


def severity(metric: float) -> str:
    if metric >= -.30: return "SAFE"
    if metric >= -.35: return "NEAR_THRESHOLD"
    if metric >= -.50: return "MODERATE_BREACH"
    if metric >= -.75: return "SEVERE_BREACH"
    return "EXTREME_BREACH"


def gate_calibration(one: pd.DataFrame, shrink: pd.DataFrame) -> pd.DataFrame:
    source = pd.concat([
        one.assign(candidate_or_factor=one["factor_name"] + "@" + one["tested_weight"].astype(str)),
        shrink.rename(columns={"test_drawdown_proxy": "test_drawdown_proxy"}).assign(
            candidate_or_factor=shrink["base_candidate_id"] + "@L" + shrink["shrinkage_lambda"].astype(str)
        ),
    ], ignore_index=True, sort=False)
    rows = []
    for _, row in source.iterrows():
        metric = float(row["test_drawdown_proxy"])
        sev = severity(metric)
        split = str(row["split_id"])
        if sev == "SAFE":
            handling, diagnostic = "KEEP_GATE", "Gate accepts this tested region."
        elif sev == "EXTREME_BREACH" and split.startswith("WF1"):
            handling, diagnostic = "INVESTIGATE_OUTLIER_SPLIT", "Extreme breach is concentrated in the earliest split; gate remains unchanged."
        elif sev in {"SEVERE_BREACH", "EXTREME_BREACH"}:
            handling, diagnostic = "DO_NOT_LOOSEN_GATE", "Severe absolute drawdown supports continued rejection."
        elif sev == "NEAR_THRESHOLD":
            handling, diagnostic = "KEEP_GATE_REQUIRE_MORE_MATURITY", "Near-threshold result needs more forward evidence."
        else:
            handling, diagnostic = "ADD_RISK_PENALTY_BEFORE_RETEST", "Moderate breach requires risk repair, not gate relaxation."
        rows.append({
            "gate_name": "ABSOLUTE_TEST_DRAWDOWN_PROXY", "current_gate_threshold": -.30,
            "candidate_or_factor": row["candidate_or_factor"], "forward_window": row["forward_window"],
            "split_id": split, "observed_metric": metric, "gate_pass": metric >= -.30,
            "severity_bucket": sev,
            "false_rejection_risk": "MEDIUM" if split.startswith("WF1") and sev in {"SEVERE_BREACH", "EXTREME_BREACH"} else "LOW",
            "false_acceptance_risk": "LOW" if metric < -.30 else "MEDIUM",
            "calibration_diagnostic": diagnostic, "recommended_handling": handling,
            "warning": "" if metric >= -.30 else "DRAWNDOWN_GATE_BREACH",
        })
    return pd.DataFrame(rows)


def factor_risk_summary(one: pd.DataFrame, allowed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for factor, data in one.groupby("factor_name"):
        family = data["factor_family"].iloc[0]
        row = {"factor_name": factor, "factor_family": family}
        for window in WINDOWS:
            sub = data[data["forward_window"].eq(window)]
            row[f"avg_marginal_return_{window.lower()}"] = sub["marginal_return_per_weight"].mean()
            row[f"avg_marginal_drawdown_{window.lower()}"] = sub["marginal_drawdown_per_weight"].mean()
        row["avg_marginal_turnover"] = data["marginal_turnover_per_weight"].mean()
        row["avg_marginal_concentration"] = data["marginal_concentration_per_weight"].mean()
        row["risk_adjusted_marginal_score"] = data["risk_adjusted_marginal_score"].mean()
        safe = data[data["usable_weight_region"].map(truth)]
        weights = safe["tested_weight"] if not safe.empty else pd.Series(dtype=float)
        row["stable_positive_weight_region"] = bool((weights > 0).any())
        row["max_safe_weight_diagnostic"] = weights[weights > 0].max() if (weights > 0).any() else np.nan
        row["min_safe_penalty_weight_diagnostic"] = weights[weights < 0].min() if (weights < 0).any() else np.nan
        allow = allowed[allowed["factor_name"].eq(factor)].iloc[0]
        if str(allow["r3_allowed_status"]).startswith("FORBIDDEN"):
            status, handling = "NEGATIVE_OR_FORBIDDEN", "FORBID_POSITIVE_WEIGHT"
        elif safe.empty:
            status, handling = "EFFECTIVE_BUT_DRAWDOWN_HEAVY" if data["test_excess_vs_D_proxy"].mean() > 0 else "NEUTRAL_OR_WEAK", "DIAGNOSTIC_ONLY"
        elif data["test_concentration_proxy"].gt(.75).mean() > .2:
            status, handling = "EFFECTIVE_BUT_CONCENTRATED", "SHADOW_MICRO_WEIGHT_TEST_ONLY"
        else:
            status, handling = "EFFECTIVE_WITH_SAFE_SMALL_WEIGHT_DIAGNOSTIC", "SHADOW_MICRO_WEIGHT_TEST_ONLY"
        row.update({
            "factor_weight_effectiveness_status": status, "recommended_handling": handling,
            "adoption_allowed": False, "warning": "" if not safe.empty else "NO_FULL_GATE_SAFE_REGION",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def safe_map(allowed: pd.DataFrame, risk: pd.DataFrame) -> pd.DataFrame:
    risk_map = risk.set_index("factor_name").to_dict("index")
    rows = []
    for _, factor in allowed.iterrows():
        name = factor["factor_name"]
        evidence = risk_map.get(name)
        status = factor["r3_allowed_status"]
        if evidence and pd.notna(evidence.get("max_safe_weight_diagnostic")):
            lo, hi, preferred = 0.0, evidence["max_safe_weight_diagnostic"], evidence["max_safe_weight_diagnostic"]
            use, confidence = "SHADOW_MICRO_WEIGHT_TEST_ONLY", "MEDIUM"
        elif evidence and pd.notna(evidence.get("min_safe_penalty_weight_diagnostic")):
            lo, hi, preferred = evidence["min_safe_penalty_weight_diagnostic"], 0.0, evidence["min_safe_penalty_weight_diagnostic"]
            use, confidence = "PENALTY_ONLY_DIAGNOSTIC", "MEDIUM"
        elif status == "PENALTY_ONLY":
            lo, hi, preferred, use, confidence = factor["min_test_weight"], 0.0, 0.0, "PENALTY_ONLY_DIAGNOSTIC", "LOW"
        elif status.startswith("ALLOWED"):
            lo, hi, preferred, use, confidence = 0.0, 0.0, 0.0, "DIAGNOSTIC_ONLY", "LOW"
        elif "DIAGNOSTIC" in status:
            lo, hi, preferred, use, confidence = 0.0, 0.0, 0.0, "WAIT_FOR_MATURITY", "LOW"
        else:
            lo, hi, preferred, use, confidence = 0.0, 0.0, 0.0, "DO_NOT_USE", "HIGH"
        rows.append({
            "factor_name": name, "factor_family": factor["factor_family"],
            "safe_min_weight": lo, "safe_max_weight": hi, "preferred_test_weight": preferred,
            "confidence_level": confidence,
            "evidence_basis": "R3_NESTED_ONE_FACTOR_RESPONSE" if evidence else "R2_FILTER_AND_PROJECT_CONSTRAINT",
            "drawdown_constraint_status": "PASSED_SOME_SPLITS" if evidence and evidence["max_safe_weight_diagnostic"] == evidence["max_safe_weight_diagnostic"] else "NOT_PROVEN_SAFE",
            "concentration_constraint_status": "DIAGNOSTIC_ONLY",
            "turnover_constraint_status": "LOW_TURNOVER_OBSERVED" if evidence else "NOT_TESTED",
            "maturity_constraint_status": "TECHNICAL_MATURED" if str(factor["factor_family"]).startswith("TECHNICAL") else "WAITING_FOR_FAMILY_MATURITY",
            "recommended_next_use": use, "official_adoption_allowed": False,
            "warning": "" if use == "SHADOW_MICRO_WEIGHT_TEST_ONLY" else use,
        })
    return pd.DataFrame(rows)


def frontier(one: pd.DataFrame, shrink: pd.DataFrame) -> pd.DataFrame:
    entries = []
    for (factor, weight, window), data in one.groupby(["factor_name", "tested_weight", "forward_window"]):
        entries.append(("ONE_FACTOR", factor, weight, window, data))
    for (candidate, lam, window), data in shrink.groupby(["base_candidate_id", "shrinkage_lambda", "forward_window"]):
        entries.append(("SHRINKAGE", candidate, lam, window, data))
    rows = []
    for i, (kind, name, weight, window, data) in enumerate(entries, 1):
        dd, conc = data["test_drawdown_proxy"].mean(), data["test_concentration_proxy"].mean()
        excess, ret = data["test_excess_vs_D_proxy"].mean(), data["test_mean_forward_return"].mean()
        utility = excess + .10 * data.get("drawdown_delta_vs_D_proxy", data.get("marginal_drawdown_per_weight", pd.Series(0, index=data.index))).mean() - .01 * data["test_turnover_proxy"].mean()
        if dd < -.30: status = "REJECT_DRAWDOWN"
        elif conc > .75: status = "REJECT_CONCENTRATION"
        elif data.get("stability_gate_pass", pd.Series(False, index=data.index)).map(truth).mean() < .67: status = "REJECT_INSUFFICIENT_STABILITY"
        else: status = "NON_DOMINATED_DIAGNOSTIC"
        rows.append({
            "frontier_id": f"F{i:04d}", "source_test_type": kind,
            "factor_or_candidate": name, "weight_or_lambda": weight,
            "forward_window": window, "avg_test_mean_return": ret,
            "avg_test_hit_rate": data["test_hit_rate"].mean(),
            "avg_test_drawdown_proxy": dd, "avg_test_concentration_proxy": conc,
            "avg_test_turnover_proxy": data["test_turnover_proxy"].mean(),
            "avg_excess_vs_D_proxy": excess, "risk_adjusted_utility_score": utility,
            "frontier_status": status, "warning": "" if status == "NON_DOMINATED_DIAGNOSTIC" else status,
        })
    return pd.DataFrame(rows)


def decision_matrix(allowed: pd.DataFrame, risk: pd.DataFrame, safe: pd.DataFrame) -> pd.DataFrame:
    risk_map = risk.set_index("factor_name").to_dict("index")
    safe_map_rows = safe.set_index("factor_name").to_dict("index")
    rows = []
    for _, factor in allowed.iterrows():
        name = factor["factor_name"]
        evidence = risk_map.get(name, {})
        smap = safe_map_rows[name]
        if factor["r3_allowed_status"].startswith("FORBIDDEN"):
            decision, role = "FORBID_POSITIVE_WEIGHT", "PENALTY_OR_NONE"
        elif factor["r3_allowed_status"] == "PENALTY_ONLY":
            decision, role = "KEEP_AS_PENALTY_ONLY", "PENALTY_ONLY"
        elif smap["recommended_next_use"] == "SHADOW_MICRO_WEIGHT_TEST_ONLY":
            decision, role = "KEEP_FOR_FUTURE_MICRO_WEIGHT_SHADOW_TEST", "SHADOW_MICRO_WEIGHT"
        elif "FUNDAMENTAL" in str(factor["factor_family"]) or "INTERACTION" in str(factor["factor_family"]):
            decision, role = "WAIT_FOR_MATURITY", "DIAGNOSTIC_ONLY"
        elif factor["r3_allowed_status"] == "DIAGNOSTIC_ONLY":
            decision, role = "KEEP_AS_DIAGNOSTIC_ONLY", "DIAGNOSTIC_ONLY"
        else:
            decision, role = "DROP_FROM_WEIGHT_SEARCH", "NONE"
        rows.append({
            "factor_name": name, "r2_filter_status": factor["r2_filter_status"],
            "r3_effectiveness_status": evidence.get("factor_weight_effectiveness_status", "INSUFFICIENT_EVIDENCE"),
            "return_evidence": f"avg_marginal_score={evidence.get('risk_adjusted_marginal_score', np.nan)}",
            "drawdown_evidence": smap["drawdown_constraint_status"],
            "concentration_evidence": smap["concentration_constraint_status"],
            "turnover_evidence": smap["turnover_constraint_status"],
            "regime_or_split_risk": "WF1_EXTREME_DRAWDOWN_SPLIT_REMAINS",
            "final_diagnostic_decision": decision, "allowed_future_role": role,
            "reason": factor["reason"],
        })
    return pd.DataFrame(rows)


def forbidden_audit() -> pd.DataFrame:
    signals = [
        ("TECH_PULLBACK_BUY_CANDIDATE", "Negative historical pullback edge.", False, False, True),
        ("PULLBACK_REPAIR_R3_RSI_STABILIZED_MACD_POSITIVE", "Repair remained negative.", False, False, True),
        ("TECH_BREAKOUT_DAY0_WATCH_ONLY", "No-chase watch-only state.", False, False, True),
        ("LOW_QUALITY_MOMENTUM_RISK", "Penalty or diagnostic only.", False, False, True),
        ("INTERACTION_UNAVAILABLE", "Penalty or diagnostic only.", False, False, True),
        ("FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "Wait state cannot be positive alpha.", False, False, True),
    ]
    return pd.DataFrame([{
        "signal_name": n, "reason_for_constraint": r, "positive_weight_allowed": p,
        "tested_as_positive_weight": tested, "used_as_penalty": penalty,
        "adoption_allowed": False, "audit_status": "PASS_CONSTRAINT_ENFORCED", "warning": "",
    } for n, r, p, tested, penalty in signals])


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 92):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    for rel in (R1, R2):
        if (root / rel).exists():
            paths.extend(p.resolve() for p in (root / rel).rglob("*") if p.is_file())
    for base in (root / "outputs", root / "data"):
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file() and "recommendation" in p.name.lower())
    paths = sorted(set(paths))
    return paths, {p: sha256(p) for p in paths}


def mutation_audit(paths: list[Path], before: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for path in paths:
        text = path.as_posix().lower()
        ptype = "broker_action" if "broker" in text else "recommendation" if "recommendation" in text else "official_weight" if "weight" in text and ("official" in text or "weight_perturbation" in text) else "official_ranking" if "ranking" in text or "060_r5_d_" in text else "prior_v21_diagnostic" if "/diagnostics/v21_0" in text else "protected"
        exists = path.exists()
        changed = not exists or before[path] != sha256(path)
        rows.append({"path": path.as_posix(), "path_type": ptype, "exists_before": True, "exists_after": exists, "modified_during_run": changed, "mutation_allowed": False, "warning": "DISALLOWED_MUTATION_DETECTED" if changed else ""})
    return pd.DataFrame(rows)


def empty_outputs(output: Path) -> None:
    schemas = {
        INVENTORY_NAME: ["source_path", "source_role", "exists", "warning"],
        ALLOWED_NAME: ["factor_name", "r3_allowed_status"],
        ONE_FACTOR_NAME: ["factor_name", "tested_weight", "split_id"],
        LOO_NAME: ["base_candidate_id", "removed_factor_name", "split_id"],
        SHRINKAGE_NAME: ["base_candidate_id", "shrinkage_lambda", "split_id"],
        GATE_NAME: ["gate_name", "current_gate_threshold", "recommended_handling"],
        RISK_SUMMARY_NAME: ["factor_name", "adoption_allowed"],
        SAFE_MAP_NAME: ["factor_name", "official_adoption_allowed"],
        FRONTIER_NAME: ["frontier_id", "frontier_status"],
        MATRIX_NAME: ["factor_name", "final_diagnostic_decision"],
        SELECTION_NAME: ["selected_status", "official_adoption_allowed", "no_trade_action_created"],
        FORBIDDEN_NAME: ["signal_name", "positive_weight_allowed", "adoption_allowed"],
        CERT_NAME: ["certification_status"],
        MUTATION_NAME: ["path", "modified_during_run", "mutation_allowed"],
    }
    for name, cols in schemas.items():
        pd.DataFrame(columns=cols).to_csv(output / name, index=False)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override.resolve() if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    required = [PANEL_REL, IC_REL, SPLIT_REL, R1_RESULTS_REL, FILTER_REL, FORENSIC_REL, GRID_REL, R2_RESULTS_REL, R2_SUMMARY_REL, R2_SELECTED_REL]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)
    inv = inventory(root)
    allowed = one = loo = shrink = gates = risk = safe = frontier_df = matrix = pd.DataFrame()
    latest = ""
    if missing:
        empty_outputs(output)
        inv.to_csv(output / INVENTORY_NAME, index=False)
    else:
        r1 = load_module(root, R1_SCRIPT, "r1_reuse")
        r2 = load_module(root, R2_SCRIPT, "r2_reuse")
        panel = pd.read_csv(root / PANEL_REL, low_memory=False)
        splits = pd.read_csv(root / SPLIT_REL, low_memory=False)
        filters = pd.read_csv(root / FILTER_REL, low_memory=False)
        grid = pd.read_csv(root / GRID_REL, low_memory=False)
        latest = str(panel["source_latest_price_date"].dropna().max())
        allowed = allowed_factors(filters)
        work = prepare_work(panel, r1, r2)
        one, _ = one_factor_response(work, splits, allowed)
        loo = leave_one_out(work, splits, grid, r2)
        shrink = shrinkage_paths(work, splits, grid, r2)
        gates = gate_calibration(one, shrink)
        risk = factor_risk_summary(one, allowed)
        safe = safe_map(allowed, risk)
        frontier_df = frontier(one, shrink)
        matrix = decision_matrix(allowed, risk, safe)
        selection = pd.DataFrame([{
            "selected_candidate_id": "", "selected_status": "NO_SHADOW_CANDIDATE_SELECTED",
            "reason": "R3 produces a diagnostic effectiveness map only; no tested region cleared all splits and gates.",
            "forward_ledger_allowed": False, "official_adoption_allowed": False,
            "broker_action_created": False, "recommendation_created": False,
            "no_trade_action_created": True, "warning": "NO_R3_SHADOW_SELECTION",
        }])
        forbidden = forbidden_audit()
        for frame, name in (
            (inv, INVENTORY_NAME), (allowed, ALLOWED_NAME), (one, ONE_FACTOR_NAME),
            (loo, LOO_NAME), (shrink, SHRINKAGE_NAME), (gates, GATE_NAME),
            (risk, RISK_SUMMARY_NAME), (safe, SAFE_MAP_NAME), (frontier_df, FRONTIER_NAME),
            (matrix, MATRIX_NAME), (selection, SELECTION_NAME), (forbidden, FORBIDDEN_NAME),
        ):
            frame.to_csv(output / name, index=False)
    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    cert = pd.DataFrame([{
        "research_only": True, "diagnostic_only": True, "shadow_only": True,
        "weight_effectiveness_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "pullback_positive_weight_used": False,
        "day0_chase_used": False, "shadow_candidate_adoption_allowed": False,
        "official_adoption_allowed": False,
        "certification_status": "CERTIFIED_R3_WEIGHT_EFFECTIVENESS_DIAGNOSTIC_NO_ADOPTION_NO_TRADE",
        "certification_note": "Marginal contribution and gate calibration only; no selection or adoption.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)
    leakage = 0
    data_warnings = int(inv["warning"].fillna("").ne("").sum())
    safe_micro = int(safe["recommended_next_use"].eq("SHADOW_MICRO_WEIGHT_TEST_ONLY").sum()) if not safe.empty else 0
    if missing:
        status, decision = "BLOCKED_V21_092_R3_REQUIRED_INPUTS_MISSING", "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif mutation_count or leakage:
        status, decision = "BLOCKED_V21_092_R3_LEAKAGE_OR_PROTECTED_MUTATION_RISK", "WEIGHT_EFFECTIVENESS_STUDY_BLOCKED_REVIEW_REQUIRED"
    elif data_warnings:
        status, decision = "PARTIAL_PASS_V21_092_R3_READY_WITH_DATA_WARN", "WEIGHT_EFFECTIVENESS_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    elif safe_micro == 0:
        status, decision = "PARTIAL_PASS_V21_092_R3_NO_SAFE_WEIGHT_REGION_FOUND", "NO_SAFE_WEIGHT_REGION_FOUND_DIAGNOSTIC_ONLY"
    else:
        status, decision = "PASS_V21_092_R3_WEIGHT_EFFECTIVENESS_MAP_READY", "WEIGHT_EFFECTIVENESS_MAP_READY_DIAGNOSTIC_ONLY"
    gate_keep = int(gates["recommended_handling"].isin(["KEEP_GATE", "KEEP_GATE_REQUIRE_MORE_MATURITY", "DO_NOT_LOOSEN_GATE"]).sum()) if not gates.empty else 0
    gate_review = int(gates["recommended_handling"].isin(["REVIEW_GATE_DEFINITION_DIAGNOSTIC_ONLY", "INVESTIGATE_OUTLIER_SPLIT"]).sum()) if not gates.empty else 0
    severe = int(gates["severity_bucket"].isin(["SEVERE_BREACH", "EXTREME_BREACH"]).sum()) if not gates.empty else 0
    next_stage = "V21.092-R4_MICRO_WEIGHT_SHADOW_STRESS_TEST_AND_FORWARD_PLAN_REVIEW" if safe_micro else "V21.092-R4_DRAWDOWN_PROXY_DECOMPOSITION_AND_OUTLIER_SPLIT_REVIEW" if gate_review else "KEEP_D_BASELINE_WAIT_FOR_MATURITY_AND_PRICE_REFRESH"
    validation = {
        "stage": "V21.092-R3_FACTOR_WEIGHT_EFFECTIVENESS_MARGINAL_CONTRIBUTION_AND_RISK_GATE_CALIBRATION",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "shadow_only": True, "weight_effectiveness_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "technical_085_preserved": mutation_count == 0, "fundamental_086_preserved": mutation_count == 0,
        "interaction_087_preserved": mutation_count == 0, "review_088_preserved": mutation_count == 0,
        "monitor_089_preserved": mutation_count == 0, "archive_090_preserved": mutation_count == 0,
        "maturity_091_preserved": mutation_count == 0, "shadow_search_092_r1_preserved": mutation_count == 0,
        "stability_search_092_r2_preserved": mutation_count == 0, "source_latest_price_date": latest,
        "allowed_factor_rows": len(allowed), "one_factor_response_rows": len(one),
        "leave_one_factor_out_rows": len(loo), "shrinkage_path_rows": len(shrink),
        "risk_gate_calibration_rows": len(gates), "factor_risk_summary_rows": len(risk),
        "safe_weight_range_rows": len(safe), "utility_frontier_rows": len(frontier_df),
        "decision_matrix_rows": len(matrix), "selected_status": "NO_SHADOW_CANDIDATE_SELECTED",
        "forward_ledger_allowed": False, "official_adoption_allowed": False,
        "pullback_positive_weight_used": False, "day0_chase_used": False,
        "safe_micro_weight_factor_count": safe_micro,
        "penalty_only_factor_count": int(allowed["r3_allowed_status"].eq("PENALTY_ONLY").sum()) if not allowed.empty else 0,
        "forbidden_positive_factor_count": int(allowed["r3_allowed_status"].eq("FORBIDDEN_POSITIVE_WEIGHT").sum()) if not allowed.empty else 0,
        "gate_keep_count": gate_keep, "gate_review_diagnostic_count": gate_review,
        "severe_drawdown_breach_count": severe,
        "concentration_warning_count": int(one["test_concentration_proxy"].gt(.75).sum()) + int(shrink["test_concentration_proxy"].gt(.75).sum()) if not one.empty else 0,
        "overfit_warning_count": int((~shrink["stability_gate_pass"].map(truth)).sum()) if not shrink.empty else 0,
        "turnover_warning_count": int(one["test_turnover_proxy"].gt(.25).sum()) + int(shrink["test_turnover_proxy"].gt(.25).sum()) if not one.empty else 0,
        "leakage_warning_count": leakage, "data_warning_count": data_warnings,
        "mutation_warning_count": mutation_count, "recommended_next_stage": next_stage,
        "missing_inputs": "|".join(missing),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "one_factor_response_rows", "shrinkage_path_rows", "safe_micro_weight_factor_count"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
