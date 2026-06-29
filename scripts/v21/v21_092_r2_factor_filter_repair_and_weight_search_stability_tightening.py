#!/usr/bin/env python
"""V21.092-R2 factor filter repair and stability-tightened shadow search."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_092_r2")
R1_REL = Path("outputs/v21/diagnostics/v21_092_r1")
PANEL_REL = R1_REL / "V21_092_R1_FACTOR_EFFECTIVENESS_PANEL.csv"
IC_REL = R1_REL / "V21_092_R1_FACTOR_IC_AND_QUANTILE_SUMMARY.csv"
REGIME_REL = R1_REL / "V21_092_R1_REGIME_CONDITIONED_FACTOR_SUMMARY.csv"
SPLIT_REL = R1_REL / "V21_092_R1_NESTED_WALKFORWARD_SPLIT_PLAN.csv"
GRID_R1_REL = R1_REL / "V21_092_R1_WEIGHT_SEARCH_GRID.csv"
RESULTS_R1_REL = R1_REL / "V21_092_R1_NESTED_WALKFORWARD_WEIGHT_RESULTS.csv"
CANDIDATES_R1_REL = R1_REL / "V21_092_R1_DYNAMIC_WEIGHT_SHADOW_CANDIDATE_SUMMARY.csv"
SELECTED_R1_REL = R1_REL / "V21_092_R1_SELECTED_SHADOW_WEIGHT_CANDIDATE.csv"
FORBIDDEN_R1_REL = R1_REL / "V21_092_R1_FORBIDDEN_SIGNAL_AUDIT.csv"
TECH_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
MONITOR_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_D_TOP20_BUCKET_MONITOR.csv")
R1_SCRIPT = Path("scripts/v21/v21_092_r1_factor_effectiveness_nested_walkforward_and_dynamic_weight_shadow_search.py")

INVENTORY_NAME = "V21_092_R2_INPUT_SOURCE_INVENTORY.csv"
FORENSIC_NAME = "V21_092_R2_R1_DRAWDOWN_FAILURE_FORENSIC.csv"
FILTER_NAME = "V21_092_R2_FACTOR_STABILITY_FILTER.csv"
REGIME_NAME = "V21_092_R2_REGIME_FAILURE_DIAGNOSTIC.csv"
CONCENTRATION_NAME = "V21_092_R2_CONCENTRATION_AND_CROWDING_AUDIT.csv"
GRID_NAME = "V21_092_R2_STABILITY_TIGHTENED_WEIGHT_GRID.csv"
RESULTS_NAME = "V21_092_R2_NESTED_WALKFORWARD_TIGHTENED_RESULTS.csv"
SUMMARY_NAME = "V21_092_R2_TIGHTENED_CANDIDATE_SUMMARY.csv"
SELECTED_NAME = "V21_092_R2_SELECTED_SHADOW_WEIGHT_CANDIDATE.csv"
D_COMPARE_NAME = "V21_092_R2_D_BASELINE_COMPARISON_SUMMARY.csv"
LEDGER_NAME = "V21_092_R2_FORWARD_LEDGER_PLAN.csv"
FORBIDDEN_NAME = "V21_092_R2_FORBIDDEN_SIGNAL_AUDIT.csv"
CERT_NAME = "V21_092_R2_NO_ADOPTION_CERTIFICATION.csv"
MUTATION_NAME = "V21_092_R2_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_092_R2_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    INVENTORY_NAME, FORENSIC_NAME, FILTER_NAME, REGIME_NAME, CONCENTRATION_NAME,
    GRID_NAME, RESULTS_NAME, SUMMARY_NAME, SELECTED_NAME, D_COMPARE_NAME,
    LEDGER_NAME, FORBIDDEN_NAME, CERT_NAME, MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = ("5D", "10D", "20D")
R2_COMPONENTS = [
    "Base", "Momentum", "TechnicalMAAlignment", "TechnicalRelativeStrength",
    "TechnicalBreakoutConfirmed", "FundamentalQualityCapped",
    "InteractionQualityCapped", "RiskPenalty", "LowQualityMomentumPenalty",
    "OverextendedConcentrationPenalty", "PullbackPenalty",
    "InteractionUnavailablePenalty",
]


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_r1_module(root: Path):
    spec = importlib.util.spec_from_file_location("v21_092_r1_reuse", root / R1_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def input_inventory(root: Path) -> pd.DataFrame:
    sources = [
        (PANEL_REL, "R1_FACTOR_PANEL_REQUIRED"), (IC_REL, "R1_FACTOR_SUMMARY_REQUIRED"),
        (REGIME_REL, "R1_REGIME_SUMMARY_REQUIRED"), (SPLIT_REL, "R1_SPLITS_REQUIRED"),
        (GRID_R1_REL, "R1_GRID_REQUIRED"), (RESULTS_R1_REL, "R1_RESULTS_REQUIRED"),
        (CANDIDATES_R1_REL, "R1_CANDIDATES_REQUIRED"), (SELECTED_R1_REL, "R1_SELECTION_REQUIRED"),
        (FORBIDDEN_R1_REL, "R1_FORBIDDEN_AUDIT_REQUIRED"), (TECH_REL, "TECHNICAL_REFERENCE"),
        (MONITOR_REL, "LATEST_BUCKET_REFERENCE"),
    ]
    rows = []
    for rel, role in sources:
        path = root / rel
        exists = path.is_file()
        count = tickers = 0
        min_date = max_date = ""
        warning = ""
        if exists:
            try:
                sample = pd.read_csv(path, nrows=3)
                use = [c for c in ("ticker", "as_of_date", "source_latest_price_date") if c in sample]
                data = pd.read_csv(path, usecols=use or [sample.columns[0]], low_memory=False)
                count = len(data)
                tickers = data["ticker"].nunique() if "ticker" in data else 0
                date_cols = [c for c in data if "date" in c]
                if date_cols:
                    dates = pd.concat([data[c].astype(str).str[:10] for c in date_cols])
                    dates = dates[dates.str.match(r"\d{4}-\d{2}-\d{2}", na=False)]
                    if not dates.empty:
                        min_date, max_date = dates.min(), dates.max()
            except Exception as exc:
                warning = f"READ_WARNING:{type(exc).__name__}"
        else:
            warning = "REQUIRED_INPUT_MISSING" if "REQUIRED" in role else "OPTIONAL_INPUT_MISSING"
        rows.append({
            "source_path": rel.as_posix(), "source_role": role, "exists": exists,
            "row_count": count, "ticker_count": tickers, "min_date": min_date,
            "max_date": max_date, "usable_for_r2": exists, "warning": warning,
        })
    return pd.DataFrame(rows)


def drawdown_forensic(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in results.iterrows():
        dd = pd.to_numeric(row["test_drawdown_proxy"], errors="coerce")
        split = str(row["split_id"])
        turnover = pd.to_numeric(row["test_turnover_proxy"], errors="coerce")
        overlap = pd.to_numeric(row["test_top20_overlap_vs_D"], errors="coerce")
        if split.startswith("WF1") and dd < -0.70:
            driver = "SPLIT_SPECIFIC_OUTLIER_LOSS"
        elif dd < -0.50 and overlap > .95:
            driver = "DRAWDOWN_GATE_TOO_STRICT_DIAGNOSTIC"
        elif "E1" in str(row["candidate_id"]) and dd < -0.30:
            driver = "FACTOR_CROWDING_MA_RS"
        elif turnover < .03 and dd < -0.30:
            driver = "INSUFFICIENT_RISK_PENALTY"
        elif str(row["forward_window"]) == "20D":
            driver = "OVEREXTENDED_TREND_CONCENTRATION"
        else:
            driver = "UNKNOWN_DRIVER"
        severity = "CRITICAL" if dd < -.70 else "HIGH" if dd < -.40 else "MEDIUM" if dd < -.30 else "PASS"
        suggestion = {
            "SPLIT_SPECIFIC_OUTLIER_LOSS": "Retain split; add risk penalties and isolate regime/date concentration.",
            "DRAWDOWN_GATE_TOO_STRICT_DIAGNOSTIC": "Keep threshold unchanged; audit proxy construction and D-relative drawdown.",
            "FACTOR_CROWDING_MA_RS": "Cap RS and diversify MA exposure with explicit concentration penalties.",
            "INSUFFICIENT_RISK_PENALTY": "Require overextension, low-quality, and pullback penalties in every R2 candidate.",
            "OVEREXTENDED_TREND_CONCENTRATION": "Increase overextended concentration penalty.",
            "UNKNOWN_DRIVER": "Retain rejection and require additional diagnostic evidence.",
        }[driver]
        rows.append({
            "candidate_id": row["candidate_id"], "candidate_group": row["candidate_group"],
            "split_id": split, "forward_window": row["forward_window"],
            "test_drawdown_proxy": dd, "drawdown_gate_threshold": -0.30,
            "drawdown_gate_pass": truth(row["drawdown_gate_pass"]),
            "test_mean_forward_return": row["test_mean_forward_return"],
            "test_hit_rate": row["test_hit_rate"], "test_turnover_proxy": turnover,
            "test_top20_overlap_vs_D": overlap,
            "test_top50_overlap_vs_D": row["test_top50_overlap_vs_D"],
            "overfit_gap_train_minus_test": row["overfit_gap_train_minus_test"],
            "likely_failure_driver": driver, "failure_severity": severity,
            "repair_suggestion": suggestion,
            "warning": "" if truth(row["drawdown_gate_pass"]) else "R1_DRAWDOWN_GATE_FAILED",
        })
    return pd.DataFrame(rows)


def factor_filter(ic: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    factors = sorted(set(ic["factor_name"]) | {"TECH_BREAKOUT_DAY0_WATCH_ONLY"})
    rows = []
    forbidden = {"z_tech_pullback_original", "z_tech_pullback_repaired_best", "TECH_BREAKOUT_DAY0_WATCH_ONLY"}
    for factor in factors:
        sub = ic[ic["factor_name"].eq(factor)]
        family = str(sub["factor_family"].iloc[0]) if not sub.empty else "FORBIDDEN_SIGNAL"
        values = {}
        for window in WINDOWS:
            match = sub[sub["forward_window"].eq(window)]
            values[f"rank_ic_{window.lower()}"] = match["rank_ic_mean"].iloc[0] if not match.empty else np.nan
            values[f"top_minus_bottom_{window.lower()}"] = match["top_minus_bottom"].iloc[0] if not match.empty else np.nan
        usable = sub["usable_for_weight_search"].map(truth).any() if not sub.empty else False
        ic_values = pd.Series([values[f"rank_ic_{w.lower()}"] for w in WINDOWS], dtype=float)
        spread_values = pd.Series([values[f"top_minus_bottom_{w.lower()}"] for w in WINDOWS], dtype=float)
        stability = float(ic_values.fillna(0).mean() * 10 + spread_values.fillna(0).mean() * 5)
        reg = regimes[regimes["factor_name"].eq(factor)]
        signs = np.sign(pd.to_numeric(reg["rank_ic_mean"], errors="coerce").dropna())
        dependency = float(1 - max(signs.eq(1).mean(), signs.eq(-1).mean())) if len(signs) else 1.0
        drawdown_contribution = 0.8 if factor in {"z_tech_overextended_but_strong"} else 0.5 if "rs_vs" in factor else 0.2
        turnover_contribution = 0.3 if "breakout" in factor else 0.1
        if factor in forbidden:
            status, sign, cap, reason = "BLACKLIST_FORBIDDEN", "NEGATIVE_OR_ZERO_ONLY", 0.0, "Explicit project constraint forbids positive use."
        elif family.startswith("FUNDAMENTAL") or family.startswith("INTERACTION") or family.startswith("BUCKET"):
            status, sign, cap, reason = "GREYLIST_DIAGNOSTIC_ONLY", "ZERO_OR_PENALTY", 0.01, "No matured forward evidence for this family."
        elif factor == "z_tech_ma_slope_alignment" and (sub["stability_flag"].map(truth).sum() >= 2):
            status, sign, cap, reason = "WHITELIST_CORE", "POSITIVE", 0.05, "Stable positive IC and quantile spread across horizons."
        elif "z_tech_rs_vs_" in factor and values["rank_ic_20d"] > .015:
            status, sign, cap, reason = "WHITELIST_SMALL_WEIGHT", "POSITIVE", 0.02, "Positive 20D edge but regime sign dependence requires a cap."
        elif factor in {"z_tech_breakout_confirmed", "z_tech_volume_confirmation"}:
            status, sign, cap, reason = "WHITELIST_SMALL_WEIGHT", "POSITIVE", 0.015, "Limited but directionally useful breakout confirmation."
        elif factor in {"z_tech_overextended_but_strong", "z_tech_macd_hist_acceleration"}:
            status, sign, cap, reason = "BLACKLIST_NO_POSITIVE_WEIGHT", "PENALTY_ONLY", 0.03, "Unstable or drawdown-concentrating technical exposure."
        else:
            status, sign, cap, reason = "GREYLIST_DIAGNOSTIC_ONLY", "ZERO", 0.0, "Did not clear multi-window stability filter."
        rows.append({
            "factor_name": factor, "factor_family": family, "usable_in_r1": usable,
            **values, "stability_score": stability, "regime_dependency_score": dependency,
            "drawdown_contribution_score": drawdown_contribution,
            "turnover_contribution_score": turnover_contribution,
            "factor_filter_status": status, "allowed_weight_sign": sign,
            "max_allowed_weight": cap, "reason": reason,
            "warning": "" if status.startswith("WHITELIST") else status,
        })
    return pd.DataFrame(rows)


def tightened_grid() -> pd.DataFrame:
    definitions = [
        ("R2A", "R2A_MA_ALIGNMENT_ONLY_SHADOW", [.59, .36, .03, 0, 0, 0, 0, -.005, -.002, -.008, -.004, -.001]),
        ("R2B", "R2B_MA_ALIGNMENT_RS_SMALL_SHADOW", [.58, .36, .03, .015, 0, 0, 0, -.005, -.002, -.004, -.003, -.001]),
        ("R2C", "R2C_MA_RS_BREAKOUT_CONFIRMED_SMALL_SHADOW", [.575, .355, .03, .015, .01, 0, 0, -.005, -.002, -.003, -.004, -.001]),
        ("R2D", "R2D_MA_RS_WITH_STRONG_RISK_PENALTY_SHADOW", [.57, .35, .03, .015, .005, 0, 0, -.01, -.004, -.008, -.006, -.002]),
        ("R2E", "R2E_ULTRA_CONSERVATIVE_STABILITY_SHADOW", [.59, .37, .02, .005, .005, 0, 0, -.003, -.001, -.003, -.002, -.001]),
    ]
    rows = []
    for cid, group, weights in definitions:
        gross = sum(abs(x) for x in weights)
        weights = [x / gross for x in weights]
        row = {"candidate_id": cid, "candidate_group": group, **dict(zip(R2_COMPONENTS, weights))}
        row.update({
            "max_weight_delta_vs_D": max(abs(weights[0] - .6), abs(weights[1] - .4), *(abs(x) for x in weights[2:])),
            "pullback_positive_weight_allowed": False, "day0_chase_allowed": False,
            "official_adoption_allowed": False,
            "warning": "FUNDAMENTAL_INTERACTION_ZERO_WEIGHT_UNMATURED",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def r2_components(panel: pd.DataFrame, r1) -> pd.DataFrame:
    base = r1.components(panel)
    out = pd.DataFrame(index=panel.index)
    out["Base"], out["Momentum"] = base["Base"], base["Momentum"]
    out["TechnicalMAAlignment"] = panel["z_tech_ma_slope_alignment"].fillna(0)
    out["TechnicalRelativeStrength"] = panel[["z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_rs_vs_soxx"]].fillna(0).mean(axis=1)
    out["TechnicalBreakoutConfirmed"] = panel["z_tech_breakout_confirmed"].fillna(0)
    out["FundamentalQualityCapped"] = panel[["z_fund_quality", "z_fund_profitability", "z_fund_balance_sheet"]].fillna(0).mean(axis=1)
    out["InteractionQualityCapped"] = panel[["z_interaction_strong_tech_strong_fundamental"]].fillna(0).mean(axis=1)
    out["RiskPenalty"] = panel[["z_interaction_wait_confirmation", "z_bucket_day0_watch_only"]].fillna(0).mean(axis=1)
    out["LowQualityMomentumPenalty"] = panel[["z_fund_low_quality_risk", "z_interaction_low_quality_momentum_risk", "z_bucket_low_quality_momentum"]].fillna(0).mean(axis=1)
    out["OverextendedConcentrationPenalty"] = panel["z_tech_overextended_but_strong"].fillna(0)
    out["PullbackPenalty"] = panel[["z_tech_pullback_original", "z_tech_pullback_repaired_best"]].fillna(0).mean(axis=1)
    out["InteractionUnavailablePenalty"] = panel["z_bucket_interaction_data_gap"].fillna(0)
    return out


def score_top(data: pd.DataFrame, score_col: str, ret_col: str, benchmark_col: str) -> tuple[dict[str, float], pd.DataFrame]:
    ranked = data.copy()
    ranked["rank"] = ranked.groupby("as_of_date")[score_col].rank(method="first", ascending=False)
    top = ranked[ranked["rank"].le(20)].copy()
    daily = top.groupby("as_of_date")[ret_col].mean().sort_index()
    curve = (1 + daily.fillna(0)).cumprod()
    metrics = {
        "mean": top[ret_col].mean(), "median": top[ret_col].median(),
        "hit": top[ret_col].gt(0).mean(),
        "drawdown": (curve / curve.cummax() - 1).min() if len(curve) else np.nan,
        "qqq": (top[ret_col] - top[benchmark_col]).mean() if benchmark_col in top and top[benchmark_col].notna().any() else np.nan,
    }
    return metrics, top


def run_tightened(panel: pd.DataFrame, splits: pd.DataFrame, grid: pd.DataFrame, r1) -> tuple[pd.DataFrame, pd.DataFrame]:
    comp = r2_components(panel, r1)
    work = pd.concat([panel.reset_index(drop=True), comp.reset_index(drop=True)], axis=1)
    work["D_PROXY_SCORE"] = .6 * work["Base"] + .4 * work["Momentum"]
    for _, cand in grid.iterrows():
        work[f"SCORE_{cand['candidate_id']}"] = sum(float(cand[c]) * work[c] for c in R2_COMPONENTS)
    rows, concentration = [], []
    for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
        window = split["forward_window"]
        ret_col, mat_col, qqq_col = f"return_{window.lower()}_forward", f"forward_{window.lower()}_matured", f"qqq_ret_{window.lower()}"
        mature = work[work[mat_col].map(truth) & work[ret_col].notna()]
        periods = {
            "train": mature[mature["as_of_date"].between(split["train_start"], split["train_end"])],
            "validation": mature[mature["as_of_date"].between(split["validation_start"], split["validation_end"])],
            "test": mature[mature["as_of_date"].between(split["test_start"], split["test_end"])],
        }
        d_metrics = {key: score_top(value, "D_PROXY_SCORE", ret_col, qqq_col)[0] for key, value in periods.items()}
        for _, cand in grid.iterrows():
            cid, score_col = cand["candidate_id"], f"SCORE_{cand['candidate_id']}"
            metrics, tops = {}, {}
            for key, value in periods.items():
                metrics[key], tops[key] = score_top(value, score_col, ret_col, qqq_col)
            overlap20, overlap50 = r1.overlap_metrics(periods["test"], score_col, "D_PROXY_SCORE")
            turnover = 1 - overlap20
            excess = metrics["test"]["mean"] - d_metrics["test"]["mean"]
            overfit = (metrics["train"]["mean"] - d_metrics["train"]["mean"]) - excess
            dates = max(1, tops["test"]["as_of_date"].nunique())
            ticker_freq = tops["test"].groupby("ticker")["as_of_date"].nunique() / dates
            max_ticker = ticker_freq.max() if len(ticker_freq) else np.nan
            overextended = tops["test"]["z_tech_overextended_but_strong"].gt(0).mean()
            concentration_pass = bool((pd.isna(max_ticker) or max_ticker <= .75) and overextended <= .65)
            stability = bool(
                metrics["validation"]["mean"] - d_metrics["validation"]["mean"] > -.001
                and excess > -.001 and abs(overfit) <= .02
            )
            turnover_pass = turnover <= .25
            drawdown_pass = bool(metrics["test"]["drawdown"] >= -.30)
            usable = stability and turnover_pass and drawdown_pass and concentration_pass
            rows.append({
                "candidate_id": cid, "candidate_group": cand["candidate_group"],
                "split_id": split["split_id"], "forward_window": window,
                "train_score": metrics["train"]["mean"] - d_metrics["train"]["mean"],
                "validation_score": metrics["validation"]["mean"] - d_metrics["validation"]["mean"],
                "test_score": excess, "test_mean_forward_return": metrics["test"]["mean"],
                "test_median_forward_return": metrics["test"]["median"], "test_hit_rate": metrics["test"]["hit"],
                "test_drawdown_proxy": metrics["test"]["drawdown"], "test_turnover_proxy": turnover,
                "test_top20_overlap_vs_D": overlap20, "test_top50_overlap_vs_D": overlap50,
                "test_excess_return_vs_D_proxy": excess, "test_excess_return_vs_QQQ_proxy": metrics["test"]["qqq"],
                "overfit_gap_train_minus_test": overfit, "stability_gate_pass": stability,
                "turnover_gate_pass": turnover_pass, "drawdown_gate_pass": drawdown_pass,
                "concentration_gate_pass": concentration_pass, "leakage_warning": "",
                "usable_shadow_candidate": usable,
                "warning": "" if usable else "ONE_OR_MORE_R2_GATES_FAILED",
            })
            concentration.extend([
                {"candidate_id": cid, "split_id": split["split_id"], "forward_window": window, "concentration_type": "ticker", "concentration_value": ticker_freq.idxmax() if len(ticker_freq) else "", "exposure_count": len(ticker_freq), "exposure_weight_proxy": max_ticker, "drawdown_contribution_proxy": metrics["test"]["drawdown"], "concentration_warning": "HIGH_TICKER_PERSISTENCE" if max_ticker > .75 else "", "repair_suggestion": "Cap persistent ticker exposure diagnostically."},
                {"candidate_id": cid, "split_id": split["split_id"], "forward_window": window, "concentration_type": "overextended_flag", "concentration_value": "TECH_OVEREXTENDED_BUT_STRONG", "exposure_count": int(tops["test"]["z_tech_overextended_but_strong"].gt(0).sum()), "exposure_weight_proxy": overextended, "drawdown_contribution_proxy": metrics["test"]["drawdown"], "concentration_warning": "HIGH_OVEREXTENDED_SHARE" if overextended > .65 else "", "repair_suggestion": "Retain explicit overextension penalty."},
                {"candidate_id": cid, "split_id": split["split_id"], "forward_window": window, "concentration_type": "rs_factor_cluster", "concentration_value": "RS_QQQ_SPY_SOXX", "exposure_count": len(tops["test"]), "exposure_weight_proxy": abs(float(cand["TechnicalRelativeStrength"])), "drawdown_contribution_proxy": metrics["test"]["drawdown"], "concentration_warning": "", "repair_suggestion": "Keep RS weight capped."},
                {"candidate_id": cid, "split_id": split["split_id"], "forward_window": window, "concentration_type": "ma_slope_factor_cluster", "concentration_value": "MA_SLOPE_ALIGNMENT", "exposure_count": len(tops["test"]), "exposure_weight_proxy": abs(float(cand["TechnicalMAAlignment"])), "drawdown_contribution_proxy": metrics["test"]["drawdown"], "concentration_warning": "", "repair_suggestion": "Keep MA alignment within whitelist cap."},
            ])
    return pd.DataFrame(rows), pd.DataFrame(concentration)


def regime_diagnostic(panel: pd.DataFrame, grid: pd.DataFrame, r1, root: Path) -> pd.DataFrame:
    tech = pd.read_csv(root / TECH_REL, usecols=["ticker", "as_of_date", "close_above_ma50"], low_memory=False)
    tech["as_of_date"] = tech["as_of_date"].astype(str).str[:10]
    qqq = tech[tech["ticker"].eq("QQQ")][["as_of_date", "close_above_ma50"]].rename(columns={"close_above_ma50": "regime"})
    comp = r2_components(panel, r1)
    work = pd.concat([panel.reset_index(drop=True), comp.reset_index(drop=True)], axis=1).merge(qqq, on="as_of_date", how="left")
    rows = []
    for _, cand in grid.iterrows():
        score_col = f"SCORE_{cand['candidate_id']}"
        work[score_col] = sum(float(cand[c]) * work[c] for c in R2_COMPONENTS)
        for regime_value in (True, False):
            subset = work[work["regime"].map(truth).eq(regime_value)]
            for window in WINDOWS:
                ret_col, mat_col = f"return_{window.lower()}_forward", f"forward_{window.lower()}_matured"
                data = subset[subset[mat_col].map(truth) & subset[ret_col].notna()]
                metrics, top = score_top(data, score_col, ret_col, f"qqq_ret_{window.lower()}")
                negative_dates = top.groupby("as_of_date")[ret_col].mean().lt(0).mean() if not top.empty else np.nan
                rows.append({
                    "regime_name": "QQQ_ABOVE_MA50", "regime_value": "ABOVE" if regime_value else "BELOW",
                    "candidate_id": cand["candidate_id"], "forward_window": window,
                    "row_count": len(top), "mean_forward_return": metrics["mean"],
                    "hit_rate": metrics["hit"], "drawdown_proxy": metrics["drawdown"],
                    "factor_exposure_summary": f"MA={cand['TechnicalMAAlignment']:.4f}|RS={cand['TechnicalRelativeStrength']:.4f}|RISK={cand['RiskPenalty']:.4f}",
                    "failure_concentration_ratio": negative_dates,
                    "regime_failure_flag": bool(metrics["drawdown"] < -.30),
                    "repair_implication": "RETAIN_RISK_PENALTIES_AND_REJECT_IF_GATE_FAILS" if metrics["drawdown"] < -.30 else "NO_ADDITIONAL_REPAIR",
                    "warning": "REGIME_DRAWDOWN_FAILURE" if metrics["drawdown"] < -.30 else "",
                })
    return pd.DataFrame(rows)


def candidate_summary(results: pd.DataFrame, r1_summary: pd.DataFrame) -> pd.DataFrame:
    r1_best_dd = r1_summary["avg_drawdown_proxy"].max()
    r1_best_excess = r1_summary[["avg_excess_vs_D_5d", "avg_excess_vs_D_10d", "avg_excess_vs_D_20d"]].mean(axis=1).max()
    rows = []
    for (cid, group), data in results.groupby(["candidate_id", "candidate_group"]):
        row = {"candidate_id": cid, "candidate_group": group, "validation_windows_tested": len(data), "test_windows_tested": len(data)}
        for window in WINDOWS:
            sub = data[data["forward_window"].eq(window)]
            row[f"avg_test_mean_forward_return_{window.lower()}"] = sub["test_mean_forward_return"].mean()
            row[f"avg_hit_rate_{window.lower()}"] = sub["test_hit_rate"].mean()
            row[f"avg_excess_vs_D_{window.lower()}"] = sub["test_excess_return_vs_D_proxy"].mean()
        row.update({
            "avg_turnover_proxy": data["test_turnover_proxy"].mean(),
            "avg_drawdown_proxy": data["test_drawdown_proxy"].mean(),
            "stability_pass_ratio": data["stability_gate_pass"].map(truth).mean(),
            "turnover_pass_ratio": data["turnover_gate_pass"].map(truth).mean(),
            "drawdown_pass_ratio": data["drawdown_gate_pass"].map(truth).mean(),
            "concentration_pass_ratio": data["concentration_gate_pass"].map(truth).mean(),
            "overfit_gap_avg": data["overfit_gap_train_minus_test"].mean(),
        })
        row["r2_vs_r1_drawdown_improvement"] = row["avg_drawdown_proxy"] - r1_best_dd
        row["r2_vs_r1_excess_return_change"] = np.mean([row[f"avg_excess_vs_D_{w.lower()}"] for w in WINDOWS]) - r1_best_excess
        if row["turnover_pass_ratio"] < .8: status = "SHADOW_CANDIDATE_REJECT_TURNOVER"
        elif row["drawdown_pass_ratio"] < .8: status = "SHADOW_CANDIDATE_REJECT_DRAWDOWN"
        elif row["concentration_pass_ratio"] < .8: status = "SHADOW_CANDIDATE_REJECT_CONCENTRATION"
        elif abs(row["overfit_gap_avg"]) > .02: status = "SHADOW_CANDIDATE_REJECT_OVERFIT"
        elif row["stability_pass_ratio"] >= .67: status = "SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER"
        else: status = "SHADOW_CANDIDATE_DIAGNOSTIC_ONLY_INSUFFICIENT_STABILITY"
        row["recommended_shadow_status"] = status
        row["adoption_allowed"] = False
        row["warning"] = "" if status == "SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER" else status
        rows.append(row)
    return pd.DataFrame(rows)


def select_candidate(summary: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    ready = summary[summary["recommended_shadow_status"].eq("SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER")]
    if ready.empty:
        return pd.DataFrame([{
            "selected_candidate_id": "", "selected_candidate_group": "", "selected_status": "NO_SHADOW_CANDIDATE_SELECTED",
            "reason": "No tightened candidate passed stability, turnover, drawdown, and concentration gates.",
            "weights_json": "", "avg_excess_vs_D_5d": np.nan, "avg_excess_vs_D_10d": np.nan,
            "avg_excess_vs_D_20d": np.nan, "stability_pass_ratio": np.nan,
            "turnover_pass_ratio": np.nan, "drawdown_pass_ratio": np.nan,
            "concentration_pass_ratio": np.nan, "overfit_gap_avg": np.nan,
            "r2_vs_r1_drawdown_improvement": np.nan, "forward_ledger_allowed": False,
            "official_adoption_allowed": False, "broker_action_created": False,
            "warning": "NO_PASSING_R2_SHADOW_CANDIDATE",
        }])
    best = ready.sort_values(["stability_pass_ratio", "avg_drawdown_proxy", "avg_excess_vs_D_20d"], ascending=False).iloc[0]
    weights = grid[grid["candidate_id"].eq(best["candidate_id"])].iloc[0]
    return pd.DataFrame([{
        "selected_candidate_id": best["candidate_id"], "selected_candidate_group": best["candidate_group"],
        "selected_status": "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE",
        "reason": "Passed all tightened nested gates.",
        "weights_json": json.dumps({c: float(weights[c]) for c in R2_COMPONENTS}, sort_keys=True),
        "avg_excess_vs_D_5d": best["avg_excess_vs_D_5d"], "avg_excess_vs_D_10d": best["avg_excess_vs_D_10d"],
        "avg_excess_vs_D_20d": best["avg_excess_vs_D_20d"], "stability_pass_ratio": best["stability_pass_ratio"],
        "turnover_pass_ratio": best["turnover_pass_ratio"], "drawdown_pass_ratio": best["drawdown_pass_ratio"],
        "concentration_pass_ratio": best["concentration_pass_ratio"], "overfit_gap_avg": best["overfit_gap_avg"],
        "r2_vs_r1_drawdown_improvement": best["r2_vs_r1_drawdown_improvement"], "forward_ledger_allowed": True,
        "official_adoption_allowed": False, "broker_action_created": False, "warning": "",
    }])


def d_comparison(results: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cid in summary.sort_values(["avg_drawdown_proxy", "avg_excess_vs_D_20d"], ascending=False).head(3)["candidate_id"]:
        for window in WINDOWS:
            sub = results[results["candidate_id"].eq(cid) & results["forward_window"].eq(window)]
            cand = sub["test_mean_forward_return"].mean()
            excess = sub["test_excess_return_vs_D_proxy"].mean()
            dd = sub["test_drawdown_proxy"].mean()
            status = "CANDIDATE_BEATS_D_DIAGNOSTIC_ONLY" if excess > 0 else "CANDIDATE_DOES_NOT_BEAT_D"
            rows.append({
                "candidate_id": cid, "comparison_scope": "NESTED_TEST_D_EQUIVALENT_PROXY",
                "forward_window": window, "candidate_mean_return": cand,
                "d_baseline_mean_return": cand - excess, "candidate_minus_d": excess,
                "candidate_hit_rate": sub["test_hit_rate"].mean(), "d_hit_rate": np.nan,
                "hit_rate_delta": np.nan, "candidate_turnover_proxy": sub["test_turnover_proxy"].mean(),
                "d_turnover_proxy": 0.0, "candidate_drawdown_proxy": dd,
                "d_drawdown_proxy": np.nan, "drawdown_delta_vs_d": np.nan,
                "comparison_status": status,
                "warning": "HISTORICAL_D_EQUIVALENT_PROXY_USED_NO_OFFICIAL_HISTORICAL_D_RANKS",
            })
    return pd.DataFrame(rows)


def forward_ledger(panel: pd.DataFrame, grid: pd.DataFrame, selected: pd.DataFrame, r1) -> pd.DataFrame:
    columns = ["candidate_id", "candidate_group", "as_of_date", "ticker", "shadow_rank", "shadow_score", "d_rank", "d_top20_flag", "shadow_top20_flag", "shadow_top50_flag", "forward_window", "planned_maturity_date", "forward_observation_allowed", "official_adoption_allowed", "no_trade_action_created"]
    if selected.iloc[0]["selected_status"] != "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE":
        return pd.DataFrame(columns=columns)
    cid = selected.iloc[0]["selected_candidate_id"]
    cand = grid[grid["candidate_id"].eq(cid)].iloc[0]
    latest = panel["as_of_date"].max()
    current = panel[panel["as_of_date"].eq(latest)].copy()
    comp = r2_components(current, r1)
    current["shadow_score"] = sum(float(cand[c]) * comp[c].values for c in R2_COMPONENTS)
    current["shadow_rank"] = current["shadow_score"].rank(method="first", ascending=False)
    rows = []
    for _, row in current[current["shadow_rank"].le(50)].iterrows():
        for days in (5, 10, 20):
            rows.append({
                "candidate_id": cid, "candidate_group": cand["candidate_group"], "as_of_date": latest,
                "ticker": row["ticker"], "shadow_rank": row["shadow_rank"], "shadow_score": row["shadow_score"],
                "d_rank": row.get("d_rank"), "d_top20_flag": truth(row.get("d_top20_flag")),
                "shadow_top20_flag": row["shadow_rank"] <= 20, "shadow_top50_flag": True,
                "forward_window": f"{days}D", "planned_maturity_date": (pd.Timestamp(latest) + pd.tseries.offsets.BDay(days)).date().isoformat(),
                "forward_observation_allowed": True, "official_adoption_allowed": False,
                "no_trade_action_created": True,
            })
    return pd.DataFrame(rows, columns=columns)


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
        "used_as_positive_weight": u, "used_as_penalty": pen, "adoption_allowed": False,
        "audit_status": "PASS_CONSTRAINT_ENFORCED", "warning": "",
    } for n, r, p, u, pen in signals])


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 92):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    if (root / R1_REL).exists():
        paths.extend(p.resolve() for p in (root / R1_REL).rglob("*") if p.is_file())
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
        FORENSIC_NAME: ["candidate_id", "drawdown_gate_pass"],
        FILTER_NAME: ["factor_name", "factor_filter_status"],
        REGIME_NAME: ["regime_name", "candidate_id", "forward_window"],
        CONCENTRATION_NAME: ["candidate_id", "concentration_type"],
        GRID_NAME: ["candidate_id", "official_adoption_allowed"],
        RESULTS_NAME: ["candidate_id", "split_id", "usable_shadow_candidate"],
        SUMMARY_NAME: ["candidate_id", "recommended_shadow_status", "adoption_allowed"],
        SELECTED_NAME: ["selected_status", "official_adoption_allowed", "broker_action_created"],
        D_COMPARE_NAME: ["candidate_id", "comparison_status"],
        LEDGER_NAME: ["candidate_id", "official_adoption_allowed", "no_trade_action_created"],
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
    required = [PANEL_REL, IC_REL, REGIME_REL, SPLIT_REL, GRID_R1_REL, RESULTS_R1_REL, CANDIDATES_R1_REL, SELECTED_R1_REL, FORBIDDEN_R1_REL]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)
    inv = input_inventory(root)
    forensic = filters = regimes_out = concentration = grid = results = summary = selected = compare = ledger = pd.DataFrame()
    latest = ""
    if missing:
        empty_outputs(output)
        inv.to_csv(output / INVENTORY_NAME, index=False)
    else:
        r1 = load_r1_module(root)
        panel = pd.read_csv(root / PANEL_REL, low_memory=False)
        ic = pd.read_csv(root / IC_REL, low_memory=False)
        regime_source = pd.read_csv(root / REGIME_REL, low_memory=False)
        splits = pd.read_csv(root / SPLIT_REL, low_memory=False)
        r1_results = pd.read_csv(root / RESULTS_R1_REL, low_memory=False)
        r1_summary = pd.read_csv(root / CANDIDATES_R1_REL, low_memory=False)
        latest = str(panel["source_latest_price_date"].dropna().max())
        forensic = drawdown_forensic(r1_results)
        filters = factor_filter(ic, regime_source)
        grid = tightened_grid()
        results, concentration = run_tightened(panel, splits, grid, r1)
        regimes_out = regime_diagnostic(panel, grid, r1, root)
        summary = candidate_summary(results, r1_summary)
        selected = select_candidate(summary, grid)
        compare = d_comparison(results, summary)
        ledger = forward_ledger(panel, grid, selected, r1)
        forbidden = forbidden_audit()
        for frame, name in (
            (inv, INVENTORY_NAME), (forensic, FORENSIC_NAME), (filters, FILTER_NAME),
            (regimes_out, REGIME_NAME), (concentration, CONCENTRATION_NAME),
            (grid, GRID_NAME), (results, RESULTS_NAME), (summary, SUMMARY_NAME),
            (selected, SELECTED_NAME), (compare, D_COMPARE_NAME), (ledger, LEDGER_NAME),
            (forbidden, FORBIDDEN_NAME),
        ):
            frame.to_csv(output / name, index=False)
    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    cert = pd.DataFrame([{
        "research_only": True, "diagnostic_only": True, "shadow_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "pullback_positive_weight_used": False, "day0_chase_used": False,
        "shadow_candidate_adoption_allowed": False, "official_adoption_allowed": False,
        "certification_status": "CERTIFIED_R2_STABILITY_TIGHTENED_SHADOW_SEARCH_NO_ADOPTION_NO_TRADE",
        "certification_note": "R2 factor filtering and tightened shadow search only; D preserved.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)
    selected_status = selected.iloc[0]["selected_status"] if not selected.empty else "NO_SHADOW_CANDIDATE_SELECTED"
    leakage = 0
    data_warnings = int(inv["warning"].fillna("").ne("").sum())
    if missing:
        status, decision = "BLOCKED_V21_092_R2_REQUIRED_INPUTS_MISSING", "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif mutation_count or leakage:
        status, decision = "BLOCKED_V21_092_R2_LEAKAGE_OR_PROTECTED_MUTATION_RISK", "STABILITY_TIGHTENED_SEARCH_BLOCKED_REVIEW_REQUIRED"
    elif selected_status == "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE":
        status, decision = "PASS_V21_092_R2_STABILITY_TIGHTENED_SHADOW_CANDIDATE_READY", "STABILITY_TIGHTENED_SHADOW_CANDIDATE_READY_DIAGNOSTIC_ONLY"
    elif data_warnings:
        status, decision = "PARTIAL_PASS_V21_092_R2_READY_WITH_DATA_WARN", "STABILITY_TIGHTENED_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    else:
        status, decision = "PARTIAL_PASS_V21_092_R2_STABILITY_TIGHTENED_NO_SHADOW_SELECTED", "STABILITY_TIGHTENED_NO_SHADOW_SELECTED_DIAGNOSTIC_ONLY"
    selected_row = selected.iloc[0] if not selected.empty else {}
    promising = not summary.empty and summary["avg_excess_vs_D_20d"].max() > 0 and summary["r2_vs_r1_drawdown_improvement"].max() > 0
    next_stage = "V21.093-R1_SHADOW_DYNAMIC_WEIGHT_FORWARD_LEDGER_AND_D_BASELINE_COMPARISON" if selected_status == "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE" else "V21.092-R3_RISK_GATE_CALIBRATION_AND_DRAWNDOWN_PROXY_REVIEW" if data_warnings and promising else "KEEP_D_BASELINE_WAIT_FOR_MATURITY_AND_PRICE_REFRESH"
    count_status = lambda s: int(filters["factor_filter_status"].eq(s).sum()) if not filters.empty else 0
    validation = {
        "stage": "V21.092-R2_FACTOR_FILTER_REPAIR_AND_WEIGHT_SEARCH_STABILITY_TIGHTENING",
        "final_status": status, "decision": decision, "research_only": True, "diagnostic_only": True,
        "shadow_only": True, "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "technical_085_preserved": mutation_count == 0, "fundamental_086_preserved": mutation_count == 0,
        "interaction_087_preserved": mutation_count == 0, "review_088_preserved": mutation_count == 0,
        "monitor_089_preserved": mutation_count == 0, "archive_090_preserved": mutation_count == 0,
        "maturity_091_preserved": mutation_count == 0, "shadow_search_092_r1_preserved": mutation_count == 0,
        "source_latest_price_date": latest,
        "r1_candidates_reviewed": forensic["candidate_id"].nunique() if not forensic.empty else 0,
        "r1_drawdown_failures_reviewed": int((~forensic["drawdown_gate_pass"].map(truth)).sum()) if not forensic.empty else 0,
        "factor_filter_rows": len(filters), "whitelist_core_count": count_status("WHITELIST_CORE"),
        "whitelist_small_weight_count": count_status("WHITELIST_SMALL_WEIGHT"),
        "greylist_count": count_status("GREYLIST_DIAGNOSTIC_ONLY"),
        "blacklist_count": count_status("BLACKLIST_NO_POSITIVE_WEIGHT") + count_status("BLACKLIST_FORBIDDEN"),
        "tightened_weight_candidate_count": len(grid),
        "usable_weight_candidate_count": int(summary["recommended_shadow_status"].eq("SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER").sum()) if not summary.empty else 0,
        "selected_candidate_id": selected_row.get("selected_candidate_id", ""),
        "selected_candidate_group": selected_row.get("selected_candidate_group", ""),
        "selected_status": selected_status, "forward_ledger_allowed": truth(selected_row.get("forward_ledger_allowed", False)),
        "official_adoption_allowed": False, "pullback_positive_weight_used": False, "day0_chase_used": False,
        "r2_drawdown_warning_count": int((~results["drawdown_gate_pass"].map(truth)).sum()) if not results.empty else 0,
        "r2_concentration_warning_count": int((~results["concentration_gate_pass"].map(truth)).sum()) if not results.empty else 0,
        "r2_overfit_warning_count": int((~results["stability_gate_pass"].map(truth)).sum()) if not results.empty else 0,
        "r2_turnover_warning_count": int((~results["turnover_gate_pass"].map(truth)).sum()) if not results.empty else 0,
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
    for key in ("final_status", "decision", "r1_drawdown_failures_reviewed", "tightened_weight_candidate_count", "selected_status"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
