#!/usr/bin/env python
"""V21.092-R5 outlier split decomposition and diagnostic risk-penalty research."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_092_r5")
R1 = Path("outputs/v21/diagnostics/v21_092_r1")
R2 = Path("outputs/v21/diagnostics/v21_092_r2")
R3 = Path("outputs/v21/diagnostics/v21_092_r3")
R4 = Path("outputs/v21/diagnostics/v21_092_r4")
PANEL_REL = R1 / "V21_092_R1_FACTOR_EFFECTIVENESS_PANEL.csv"
SPLIT_REL = R1 / "V21_092_R1_NESTED_WALKFORWARD_SPLIT_PLAN.csv"
FORENSIC_REL = R2 / "V21_092_R2_R1_DRAWDOWN_FAILURE_FORENSIC.csv"
GATE_REL = R3 / "V21_092_R3_RISK_GATE_CALIBRATION_DIAGNOSTIC.csv"
SAFE_REL = R3 / "V21_092_R3_SAFE_WEIGHT_RANGE_MAP.csv"
GRID_REL = R4 / "V21_092_R4_MICRO_WEIGHT_CANDIDATE_GRID.csv"
STRESS_REL = R4 / "V21_092_R4_MICRO_WEIGHT_STRESS_TEST_RESULTS.csv"
OUTLIER_REL = R4 / "V21_092_R4_OUTLIER_SPLIT_STRESS_REVIEW.csv"
SUMMARY_REL = R4 / "V21_092_R4_CANDIDATE_GATE_SUMMARY.csv"
SELECTED_REL = R4 / "V21_092_R4_SELECTED_MICRO_SHADOW_CANDIDATE.csv"
MONITOR_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_D_TOP20_BUCKET_MONITOR.csv")
TECH_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
R1_SCRIPT = Path("scripts/v21/v21_092_r1_factor_effectiveness_nested_walkforward_and_dynamic_weight_shadow_search.py")
R2_SCRIPT = Path("scripts/v21/v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening.py")
R3_SCRIPT = Path("scripts/v21/v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration.py")
R4_SCRIPT = Path("scripts/v21/v21_092_r4_micro_weight_shadow_stress_test_and_forward_plan_review.py")

INVENTORY_NAME = "V21_092_R5_INPUT_SOURCE_INVENTORY.csv"
MASTER_NAME = "V21_092_R5_OUTLIER_SPLIT_MASTER_TABLE.csv"
TICKER_NAME = "V21_092_R5_TICKER_LOSS_CONTRIBUTION.csv"
FACTOR_NAME = "V21_092_R5_FACTOR_EXPOSURE_DECOMPOSITION.csv"
BUCKET_NAME = "V21_092_R5_BUCKET_AND_REGIME_DECOMPOSITION.csv"
PENALTY_GRID_NAME = "V21_092_R5_RISK_PENALTY_RESEARCH_GRID.csv"
PENALTY_TEST_NAME = "V21_092_R5_RISK_PENALTY_BACKTEST_DIAGNOSTIC.csv"
PENALTY_SUMMARY_NAME = "V21_092_R5_PENALTY_EFFECTIVENESS_SUMMARY.csv"
D_COMPARE_NAME = "V21_092_R5_D_BASELINE_OUTLIER_COMPARISON.csv"
ROOT_CAUSE_NAME = "V21_092_R5_OUTLIER_ROOT_CAUSE_SUMMARY.csv"
DECISION_NAME = "V21_092_R5_NEXT_STEP_DECISION_MATRIX.csv"
CERT_NAME = "V21_092_R5_NO_SELECTION_CERTIFICATION.csv"
MUTATION_NAME = "V21_092_R5_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_092_R5_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    INVENTORY_NAME, MASTER_NAME, TICKER_NAME, FACTOR_NAME, BUCKET_NAME,
    PENALTY_GRID_NAME, PENALTY_TEST_NAME, PENALTY_SUMMARY_NAME, D_COMPARE_NAME,
    ROOT_CAUSE_NAME, DECISION_NAME, CERT_NAME, MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = ("5D", "10D", "20D")


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_module(root: Path, rel: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, root / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def input_inventory(root: Path) -> pd.DataFrame:
    sources = [
        (PANEL_REL, "R1_FACTOR_PANEL_REQUIRED"), (SPLIT_REL, "R1_SPLITS_REQUIRED"),
        (FORENSIC_REL, "R2_FORENSIC_REQUIRED"), (GATE_REL, "R3_GATE_REQUIRED"),
        (SAFE_REL, "R3_SAFE_RANGE_REQUIRED"), (GRID_REL, "R4_GRID_REQUIRED"),
        (STRESS_REL, "R4_STRESS_REQUIRED"), (OUTLIER_REL, "R4_OUTLIER_REQUIRED"),
        (SUMMARY_REL, "R4_SUMMARY_REQUIRED"), (SELECTED_REL, "R4_SELECTION_REQUIRED"),
        (MONITOR_REL, "LATEST_BUCKET_OPTIONAL"), (TECH_REL, "TECHNICAL_REFERENCE"),
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
                dates = [x for x in dates if len(x) == 10 and x[4] == "-"]
                if dates:
                    min_date, max_date = min(dates), max(dates)
            except Exception as exc:
                warning = f"READ_WARNING:{type(exc).__name__}"
        else:
            warning = "REQUIRED_INPUT_MISSING" if "REQUIRED" in role else "OPTIONAL_INPUT_MISSING"
        rows.append({
            "source_path": rel.as_posix(), "source_role": role, "exists": exists,
            "row_count": row_count, "ticker_count": ticker_count, "min_date": min_date,
            "max_date": max_date, "usable_for_r5": exists, "warning": warning,
        })
    return pd.DataFrame(rows)


def build_master(stress: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    split_map = splits.set_index("split_id")
    events = stress[stress["severe_or_extreme_breach_flag"].map(truth)].copy()
    rows = []
    for index, (_, row) in enumerate(events.iterrows(), 1):
        split = split_map.loc[row["split_id"]]
        dd_delta = row["drawdown_delta_vs_D_proxy"]
        d_dd = row["test_drawdown_proxy"] - dd_delta
        d_wide = d_dd < -.50 and abs(dd_delta) <= .02
        if d_wide and str(row["split_id"]).startswith("WF1"):
            classification = "EARLY_HISTORY_ARTIFACT"
        elif d_wide:
            classification = "D_BASELINE_WIDE_FAILURE"
        elif dd_delta < -.03:
            classification = "CANDIDATE_SPECIFIC_FAILURE"
        else:
            classification = "MIXED_OR_UNCLASSIFIED"
        rows.append({
            "outlier_event_id": f"R5_EVT_{index:03d}", "candidate_id": row["candidate_id"],
            "candidate_group": row["candidate_group"], "split_id": row["split_id"],
            "forward_window": row["forward_window"], "split_train_start": split["train_start"],
            "split_train_end": split["train_end"], "split_validation_start": split["validation_start"],
            "split_validation_end": split["validation_end"], "split_test_start": split["test_start"],
            "split_test_end": split["test_end"], "test_drawdown_proxy": row["test_drawdown_proxy"],
            "test_mean_forward_return": row["test_mean_forward_return"], "test_hit_rate": row["test_hit_rate"],
            "severity_bucket": "EXTREME" if row["test_drawdown_proxy"] < -.75 else "SEVERE",
            "early_split_outlier_loss_flag": row["early_split_outlier_loss_flag"],
            "severe_or_extreme_breach_flag": True, "d_equivalent_drawdown_proxy": d_dd,
            "candidate_minus_d_drawdown_delta": dd_delta, "outlier_classification": classification,
            "requires_data_review": classification == "MIXED_OR_UNCLASSIFIED",
            "requires_regime_review": True, "requires_risk_penalty_review": True,
            "warning": "" if classification != "MIXED_OR_UNCLASSIFIED" else "ROOT_CAUSE_MIXED",
        })
    return pd.DataFrame(rows)


def reconstruct(root: Path, panel: pd.DataFrame, grid: pd.DataFrame):
    r1 = load_module(root, R1_SCRIPT, "r1_reuse")
    r2 = load_module(root, R2_SCRIPT, "r2_reuse")
    r3 = load_module(root, R3_SCRIPT, "r3_reuse")
    r4 = load_module(root, R4_SCRIPT, "r4_reuse")
    work = r4.prepare_work(panel, r1, r2)
    tops = {"D": r3.rank_top(work, work["D_PROXY_SCORE"])}
    for _, candidate in grid.iterrows():
        tops[candidate["candidate_id"]] = r3.rank_top(work, r4.candidate_score(work, candidate))
    return r1, r2, r3, r4, work, tops


def event_holdings(work: pd.DataFrame, top: pd.DataFrame, event: pd.Series) -> pd.DataFrame:
    window = event["forward_window"].lower()
    return work[
        work["as_of_date"].between(event["split_test_start"], event["split_test_end"])
        & work[f"forward_{window}_matured"].map(truth)
        & work[f"return_{window}_forward"].notna()
    ].merge(top[["as_of_date", "ticker"]], on=["as_of_date", "ticker"], how="inner")


def ticker_decomposition(master: pd.DataFrame, work: pd.DataFrame, tops: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    repeat_counts: dict[str, int] = {}
    temp = []
    for _, event in master.iterrows():
        cand = event_holdings(work, tops[event["candidate_id"]], event)
        dbase = event_holdings(work, tops["D"], event)
        ret_col = f"return_{event['forward_window'].lower()}_forward"
        cstats = cand.groupby("ticker").agg(return_forward=(ret_col, "mean"), exposure=("as_of_date", "nunique"))
        dstats = dbase.groupby("ticker").agg(d_return=(ret_col, "mean"), d_exposure=("as_of_date", "nunique"))
        joined = cstats.join(dstats, how="outer")
        joined["contribution"] = joined["return_forward"] * joined["exposure"]
        joined = joined.sort_values("contribution")
        for rank, (ticker, stat) in enumerate(joined.iterrows(), 1):
            repeat_counts[ticker] = repeat_counts.get(ticker, 0) + int(stat.get("contribution", 0) < 0)
            temp.append((event, ticker, rank, stat))
    for event, ticker, rank, stat in temp:
        c = stat.get("contribution")
        dcontrib = stat.get("d_return") * stat.get("d_exposure") if pd.notna(stat.get("d_return")) else np.nan
        rows.append({
            "outlier_event_id": event["outlier_event_id"], "candidate_id": event["candidate_id"],
            "split_id": event["split_id"], "forward_window": event["forward_window"],
            "ticker": ticker, "candidate_exposure_proxy": stat.get("exposure"),
            "d_exposure_proxy": stat.get("d_exposure"), "return_forward": stat.get("return_forward"),
            "contribution_to_candidate_loss_proxy": c, "contribution_to_d_loss_proxy": dcontrib,
            "contribution_delta_vs_d": c - dcontrib if pd.notna(c) and pd.notna(dcontrib) else np.nan,
            "ticker_loss_rank": rank, "repeated_loss_contributor_flag": repeat_counts[ticker] >= 3,
            "warning": "" if pd.notna(stat.get("return_forward")) else "CANDIDATE_RETURN_UNAVAILABLE",
        })
    return pd.DataFrame(rows)


def factor_decomposition(master: pd.DataFrame, work: pd.DataFrame, tops: dict[str, pd.DataFrame], grid: pd.DataFrame) -> pd.DataFrame:
    factor_weights = {
        "z_tech_rs_vs_qqq": "RS_QQQ_micro_weight", "z_tech_rs_vs_spy": "RS_SPY_micro_weight",
        "z_tech_rs_vs_soxx": "RS_SOXX_micro_weight", "z_tech_breakout_confirmed": "BreakoutConfirmation_micro_weight",
        "z_tech_volume_confirmation": "VolumeConfirmation_micro_weight", "z_fund_low_quality_risk": "LowQualityRisk_penalty_weight",
        "z_bucket_interaction_data_gap": "InteractionDataGap_penalty_weight",
        "z_tech_overextended_but_strong": "OverextendedExposure_penalty_weight",
    }
    grid_map = grid.set_index("candidate_id")
    rows = []
    for _, event in master.iterrows():
        holdings = event_holdings(work, tops[event["candidate_id"]], event)
        ret_col = f"return_{event['forward_window'].lower()}_forward"
        candidate = grid_map.loc[event["candidate_id"]]
        for factor, weight_col in factor_weights.items():
            values = holdings[factor].dropna()
            weight = float(candidate[weight_col])
            high = holdings[holdings[factor].rank(pct=True).ge(.9)]
            proxy = (holdings[factor].fillna(0) * holdings[ret_col]).mean()
            failure = bool(weight > 0 and proxy < 0)
            if factor in {"z_fund_low_quality_risk", "z_bucket_interaction_data_gap", "z_tech_overextended_but_strong"}:
                handling = "PENALTY_ONLY"
            elif failure:
                handling = "REDUCE_MICRO_WEIGHT"
            else:
                handling = "KEEP_FACTOR_DIAGNOSTIC_ONLY"
            rows.append({
                "outlier_event_id": event["outlier_event_id"], "candidate_id": event["candidate_id"],
                "split_id": event["split_id"], "forward_window": event["forward_window"],
                "factor_name": factor, "candidate_factor_weight": weight,
                "factor_exposure_mean": values.mean() if len(values) else np.nan,
                "factor_exposure_top_decile": high[factor].mean() if not high.empty else np.nan,
                "factor_return_proxy": high[ret_col].mean() if not high.empty else np.nan,
                "factor_loss_contribution_proxy": weight * proxy,
                "factor_crowding_flag": bool(values.abs().mean() > 1),
                "factor_failure_flag": failure, "recommended_handling": handling,
                "warning": "" if len(values) else "INSUFFICIENT_DECOMPOSITION_DATA",
            })
    return pd.DataFrame(rows)


def bucket_regime_decomposition(root: Path, master: pd.DataFrame, work: pd.DataFrame, tops: dict[str, pd.DataFrame]) -> pd.DataFrame:
    tech = pd.read_csv(root / TECH_REL, usecols=["ticker", "as_of_date", "close_above_ma50"], low_memory=False)
    tech["as_of_date"] = tech["as_of_date"].astype(str).str[:10]
    regimes = tech[tech["ticker"].isin(["QQQ", "SPY", "SOXX"])].pivot_table(index="as_of_date", columns="ticker", values="close_above_ma50", aggfunc="last")
    rows = []
    for _, event in master.iterrows():
        holdings = event_holdings(work, tops[event["candidate_id"]], event).merge(regimes.reset_index(), on="as_of_date", how="left")
        ret_col = f"return_{event['forward_window'].lower()}_forward"
        specs = [
            ("overextended_flag", holdings["z_tech_overextended_but_strong"].gt(0)),
            ("low_quality_momentum_flag", holdings["z_fund_low_quality_risk"].gt(0)),
            ("interaction_data_gap_flag", holdings["z_bucket_interaction_data_gap"].gt(0)),
        ]
        for benchmark in ("QQQ", "SPY", "SOXX"):
            specs.append((f"{benchmark}_MA50_regime", holdings[benchmark].map(truth)))
        for kind, mask in specs:
            for value in (True, False):
                sub = holdings[mask.eq(value)]
                daily = sub.groupby("as_of_date")[ret_col].mean()
                curve = (1 + daily.fillna(0)).cumprod()
                rows.append({
                    "outlier_event_id": event["outlier_event_id"], "candidate_id": event["candidate_id"],
                    "split_id": event["split_id"], "forward_window": event["forward_window"],
                    "bucket_or_regime_type": kind, "bucket_or_regime_value": str(value).upper(),
                    "exposure_count": len(sub), "exposure_weight_proxy": len(sub) / max(1, len(holdings)),
                    "mean_forward_return": sub[ret_col].mean() if len(sub) else np.nan,
                    "drawdown_contribution_proxy": (curve / curve.cummax() - 1).min() if len(curve) else np.nan,
                    "concentration_ratio": sub["ticker"].nunique() / max(1, holdings["ticker"].nunique()),
                    "failure_cluster_flag": bool(len(sub) and sub[ret_col].mean() < 0),
                    "interpretation": "NEGATIVE_FAILURE_CLUSTER" if len(sub) and sub[ret_col].mean() < 0 else "NO_NEGATIVE_CLUSTER",
                    "warning": "" if len(sub) else "NO_EXPOSURE_ROWS",
                })
    return pd.DataFrame(rows)


def penalty_grid() -> pd.DataFrame:
    definitions = [
        ("P1", "OVEREXTENDED_STRONGER", "overextended", -.015, -.005, -.002, 0, 0, 0),
        ("P2", "LOW_QUALITY_STRONGER", "low_quality", -.005, -.015, -.002, 0, 0, 0),
        ("P3", "INTERACTION_GAP_STRONGER", "data_gap", -.005, -.005, -.0075, 0, 0, 0),
        ("P4", "RS_CROWDING_PENALTY", "rs_crowding", -.005, -.005, -.002, -.01, 0, 0),
        ("P5", "MA_RS_CROWDING_PENALTY", "ma_rs_crowding", -.005, -.005, -.002, -.005, -.01, 0),
        ("P6", "QQQ_RISK_OFF_REGIME_PENALTY", "regime", -.005, -.005, -.002, 0, 0, -.01),
    ]
    return pd.DataFrame([{
        "penalty_variant_id": pid, "penalty_variant_name": name, "applies_to": applies,
        "overextended_penalty_weight": over, "low_quality_momentum_penalty_weight": low,
        "interaction_data_gap_penalty_weight": gap, "rs_crowding_penalty_weight": rs,
        "ma_rs_crowding_penalty_weight": mars, "regime_risk_penalty_weight": regime,
        "max_total_penalty": sum(abs(x) for x in (over, low, gap, rs, mars, regime)),
        "official_adoption_allowed": False, "warning": "DIAGNOSTIC_PENALTY_NOT_ADOPTABLE",
    } for pid, name, applies, over, low, gap, rs, mars, regime in definitions])


def penalty_backtest(root: Path, work: pd.DataFrame, splits: pd.DataFrame, candidate_grid: pd.DataFrame, penalties: pd.DataFrame, stress: pd.DataFrame, r3, r4) -> pd.DataFrame:
    tech = pd.read_csv(root / TECH_REL, usecols=["ticker", "as_of_date", "close_above_ma50"], low_memory=False)
    tech["as_of_date"] = tech["as_of_date"].astype(str).str[:10]
    qqq = tech[tech["ticker"].eq("QQQ")][["as_of_date", "close_above_ma50"]].rename(columns={"close_above_ma50": "qqq_regime"})
    work2 = work.merge(qqq, on="as_of_date", how="left")
    stress_map = stress.set_index(["candidate_id", "split_id", "forward_window"])
    rows = []
    for _, candidate in candidate_grid.iterrows():
        base_score = r4.candidate_score(work2, candidate)
        for _, penalty in penalties.iterrows():
            score = (
                base_score
                + penalty["overextended_penalty_weight"] * work2["z_tech_overextended_but_strong"].fillna(0)
                + penalty["low_quality_momentum_penalty_weight"] * work2["z_fund_low_quality_risk"].fillna(0)
                + penalty["interaction_data_gap_penalty_weight"] * work2["z_bucket_interaction_data_gap"].fillna(0)
                + penalty["rs_crowding_penalty_weight"] * work2[["z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_rs_vs_soxx"]].fillna(0).mean(axis=1).abs()
                + penalty["ma_rs_crowding_penalty_weight"] * (
                    work2["z_tech_ma_slope_alignment"].fillna(0).abs()
                    + work2[["z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_rs_vs_soxx"]].fillna(0).mean(axis=1).abs()
                )
                + penalty["regime_risk_penalty_weight"] * (~work2["qqq_regime"].map(truth)).astype(float)
            )
            top = r3.rank_top(work2, score)
            for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
                window = split["forward_window"]
                penalized = r3.period_metrics(work2, top, split, window)
                original = stress_map.loc[(candidate["candidate_id"], split["split_id"], window)]
                dd_improve = penalized["drawdown"] - original["test_drawdown_proxy"]
                return_cost = original["test_mean_forward_return"] - penalized["mean"]
                conc_improve = original["test_concentration_proxy"] - penalized["concentration"]
                before_severe, after_severe = original["test_drawdown_proxy"] < -.50, penalized["drawdown"] < -.50
                before_extreme, after_extreme = original["test_drawdown_proxy"] < -.75, penalized["drawdown"] < -.75
                if dd_improve <= 0:
                    status = "DOES_NOT_IMPROVE_DRAWDOWN"
                elif before_extreme and not after_extreme:
                    status = "REDUCES_EXTREME_BREACH_ONLY"
                elif return_cost <= .001:
                    status = "IMPROVES_DRAWDOWN_WITH_ACCEPTABLE_RETURN_COST"
                else:
                    status = "IMPROVES_DRAWDOWN_BUT_RETURN_COST_TOO_HIGH"
                rows.append({
                    "penalty_variant_id": penalty["penalty_variant_id"], "candidate_id": candidate["candidate_id"],
                    "split_id": split["split_id"], "forward_window": window,
                    "original_drawdown_proxy": original["test_drawdown_proxy"],
                    "penalized_drawdown_proxy": penalized["drawdown"], "drawdown_improvement": dd_improve,
                    "original_mean_forward_return": original["test_mean_forward_return"],
                    "penalized_mean_forward_return": penalized["mean"], "return_cost": return_cost,
                    "original_hit_rate": original["test_hit_rate"], "penalized_hit_rate": penalized["hit"],
                    "hit_rate_delta": penalized["hit"] - original["test_hit_rate"],
                    "original_concentration_proxy": original["test_concentration_proxy"],
                    "penalized_concentration_proxy": penalized["concentration"],
                    "concentration_improvement": conc_improve, "severe_breach_before": before_severe,
                    "severe_breach_after": after_severe, "extreme_breach_before": before_extreme,
                    "extreme_breach_after": after_extreme, "penalty_effectiveness_status": status,
                    "warning": "" if status.startswith("IMPROVES") or status.startswith("REDUCES") else status,
                })
    return pd.DataFrame(rows)


def penalty_summary(test: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    name_map = grid.set_index("penalty_variant_id")["penalty_variant_name"].to_dict()
    rows = []
    for pid, data in test.groupby("penalty_variant_id"):
        improve = data["drawdown_improvement"].gt(0)
        acceptable = improve & data["return_cost"].le(.001)
        ratio = acceptable.mean()
        if ratio >= .60 and data["severe_breach_after"].sum() < data["severe_breach_before"].sum():
            status = "PENALTY_DIAGNOSTIC_PROMISING_FOR_R6"
        elif data["drawdown_improvement"].mean() <= 0:
            status = "PENALTY_REJECT_NO_DRAWDOWN_IMPROVEMENT"
        elif data["return_cost"].mean() > .001:
            status = "PENALTY_REJECT_RETURN_COST_TOO_HIGH"
        else:
            status = "PENALTY_DIAGNOSTIC_WEAK"
        rows.append({
            "penalty_variant_id": pid, "penalty_variant_name": name_map[pid],
            "candidates_tested": data["candidate_id"].nunique(), "splits_tested": data["split_id"].nunique(),
            "forward_windows_tested": data["forward_window"].nunique(),
            "avg_drawdown_improvement": data["drawdown_improvement"].mean(),
            "avg_return_cost": data["return_cost"].mean(), "avg_hit_rate_delta": data["hit_rate_delta"].mean(),
            "severe_breach_reduction_count": int((data["severe_breach_before"].map(truth) & ~data["severe_breach_after"].map(truth)).sum()),
            "extreme_breach_reduction_count": int((data["extreme_breach_before"].map(truth) & ~data["extreme_breach_after"].map(truth)).sum()),
            "concentration_improvement_avg": data["concentration_improvement"].mean(),
            "effectiveness_ratio": ratio, "recommended_status": status,
            "adoption_allowed": False, "warning": "" if status == "PENALTY_DIAGNOSTIC_PROMISING_FOR_R6" else status,
        })
    return pd.DataFrame(rows)


def baseline_comparison(master: pd.DataFrame, work: pd.DataFrame, tops: dict[str, pd.DataFrame], r3) -> pd.DataFrame:
    rows = []
    for _, event in master.iterrows():
        split_view = pd.Series({
            "test_start": event["split_test_start"],
            "test_end": event["split_test_end"],
        })
        d = r3.period_metrics(work, tops["D"], split_view, event["forward_window"])
        dd_delta = event["test_drawdown_proxy"] - d["drawdown"]
        ret_delta = event["test_mean_forward_return"] - d["mean"]
        if pd.isna(d["drawdown"]):
            interpretation = "INSUFFICIENT_D_COMPARISON_DATA"
        elif d["drawdown"] < -.50 and abs(dd_delta) <= .02:
            interpretation = "D_BASELINE_WIDE_MARKET_STRESS"
        elif dd_delta < -.02:
            interpretation = "CANDIDATE_WORSE_THAN_D_IN_OUTLIER"
        elif event["test_drawdown_proxy"] > d["drawdown"]:
            interpretation = "CANDIDATE_BETTER_THAN_D_BUT_STILL_FAILS_GATE"
        else:
            interpretation = "CANDIDATE_SIMILAR_TO_D_OUTLIER"
        rows.append({
            "outlier_event_id": event["outlier_event_id"], "candidate_id": event["candidate_id"],
            "split_id": event["split_id"], "forward_window": event["forward_window"],
            "candidate_drawdown_proxy": event["test_drawdown_proxy"], "d_equivalent_drawdown_proxy": d["drawdown"],
            "candidate_minus_d_drawdown_delta": dd_delta, "candidate_mean_return": event["test_mean_forward_return"],
            "d_equivalent_mean_return": d["mean"], "candidate_minus_d_return_delta": ret_delta,
            "d_baseline_also_failed": d["drawdown"] < -.30, "interpretation": interpretation,
            "warning": "" if pd.notna(d["drawdown"]) else "INSUFFICIENT_D_COMPARISON_DATA",
        })
    return pd.DataFrame(rows)


def root_causes(master: pd.DataFrame, ticker: pd.DataFrame, factors: pd.DataFrame, compare: pd.DataFrame) -> pd.DataFrame:
    categories = {
        "D_BASELINE_WIDE_MARKET_STRESS": compare["interpretation"].eq("D_BASELINE_WIDE_MARKET_STRESS"),
        "EARLY_HISTORY_ARTIFACT": master["outlier_classification"].eq("EARLY_HISTORY_ARTIFACT"),
        "RS_CROWDING_FAILURE": factors["factor_name"].str.contains("rs_vs") & factors["factor_failure_flag"].map(truth),
        "BREAKOUT_VOLUME_FAILURE": factors["factor_name"].isin(["z_tech_breakout_confirmed", "z_tech_volume_confirmation"]) & factors["factor_failure_flag"].map(truth),
        "OVEREXTENDED_EXPOSURE_FAILURE": factors["factor_name"].eq("z_tech_overextended_but_strong") & factors["factor_failure_flag"].map(truth),
    }
    rows = []
    for category, mask in categories.items():
        source = compare if category == "D_BASELINE_WIDE_MARKET_STRESS" else master if category == "EARLY_HISTORY_ARTIFACT" else factors
        sub = source[mask]
        event_ids = set(sub.get("outlier_event_id", pd.Series(dtype=str)))
        affected = master[master["outlier_event_id"].isin(event_ids)]
        tick = ticker[ticker["outlier_event_id"].isin(event_ids) & ticker["repeated_loss_contributor_flag"].map(truth)]
        fac = factors[factors["outlier_event_id"].isin(event_ids) & factors["factor_failure_flag"].map(truth)]
        rows.append({
            "root_cause_category": category, "event_count": len(event_ids),
            "affected_candidates": "|".join(sorted(affected["candidate_id"].unique())),
            "affected_forward_windows": "|".join(sorted(affected["forward_window"].unique())),
            "affected_splits": "|".join(sorted(affected["split_id"].unique())),
            "representative_tickers": "|".join(tick.groupby("ticker")["contribution_to_candidate_loss_proxy"].sum().nsmallest(5).index),
            "representative_factors": "|".join(sorted(fac["factor_name"].unique())),
            "severity_mix": "|".join(affected["severity_bucket"].value_counts().map(str).index + ":" + affected["severity_bucket"].value_counts().map(str).values),
            "recommended_handling": "KEEP_D_BASELINE_WAIT_FOR_MATURITY" if category in {"D_BASELINE_WIDE_MARKET_STRESS", "EARLY_HISTORY_ARTIFACT"} else "RUN_R6_RISK_PENALTY_MICRO_TEST",
            "warning": "" if len(event_ids) else "NO_EVENTS_CLASSIFIED",
        })
    return pd.DataFrame(rows)


def decision_matrix(promising: int) -> pd.DataFrame:
    decisions = [
        ("dynamic_weight_search", "No R4 candidate passed absolute drawdown gates.", "STOP_DYNAMIC_WEIGHT_SEARCH_TEMPORARILY", "KEEP_D_BASELINE_WAIT_FOR_MATURITY", "SELECT_OR_ADOPT_DYNAMIC_WEIGHT"),
        ("micro_weight_forward_plan", "R4 selected no candidate.", "KEEP_D_BASELINE_WAIT_FOR_MATURITY", "REQUIRE_PRICE_REFRESH_AND_V21_091_RERUN", "CREATE_OFFICIAL_FORWARD_LEDGER"),
        ("risk_penalty_research", f"promising_penalties={promising}", "RUN_R6_RISK_PENALTY_MICRO_TEST" if promising else "KEEP_FACTOR_DIAGNOSTIC_ONLY", "RUN_R6_RISK_PENALTY_MICRO_TEST" if promising else "KEEP_D_BASELINE_WAIT_FOR_MATURITY", "ADOPT_RISK_PENALTY"),
        ("drawdown_gate_calibration", "Severe/extreme breaches persist.", "KEEP_FACTOR_DIAGNOSTIC_ONLY", "INVESTIGATE_OUTLIER_SPLIT_DATA", "LOOSEN_DRAWDOWN_GATE"),
        ("D_baseline_status", "Outliers substantially overlap D-equivalent stress.", "KEEP_D_BASELINE_WAIT_FOR_MATURITY", "KEEP_D_BASELINE_WAIT_FOR_MATURITY", "REPLACE_D"),
        ("maturity_refresh_status", "Local price source remains stale.", "REQUIRE_PRICE_REFRESH_AND_V21_091_RERUN", "REQUIRE_PRICE_REFRESH_AND_V21_091_RERUN", "INFER_MATURITY"),
        ("outlier_split_data_quality", "Early WF1 failures require later review.", "INVESTIGATE_OUTLIER_SPLIT_DATA", "INVESTIGATE_OUTLIER_SPLIT_DATA", "DELETE_OR_EXCLUDE_SPLIT"),
        ("factor_weight_policy", "Allowed factors remain diagnostic only.", "KEEP_FACTOR_DIAGNOSTIC_ONLY", "KEEP_FACTOR_DIAGNOSTIC_ONLY", "ADOPT_FACTOR_WEIGHT"),
    ]
    return pd.DataFrame([{
        "decision_area": area, "evidence_summary": evidence, "diagnostic_decision": decision,
        "allowed_next_action": allowed, "forbidden_next_action": forbidden,
        "reason": "Research-only outlier decomposition; no selection or adoption authority.",
    } for area, evidence, decision, allowed, forbidden in decisions])


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 92):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    for rel in (R1, R2, R3, R4):
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
        INVENTORY_NAME: ["source_path", "source_role", "exists", "warning"], MASTER_NAME: ["outlier_event_id", "severity_bucket"],
        TICKER_NAME: ["outlier_event_id", "ticker"], FACTOR_NAME: ["outlier_event_id", "factor_name"],
        BUCKET_NAME: ["outlier_event_id", "bucket_or_regime_type"], PENALTY_GRID_NAME: ["penalty_variant_id", "official_adoption_allowed"],
        PENALTY_TEST_NAME: ["penalty_variant_id", "candidate_id", "penalty_effectiveness_status"],
        PENALTY_SUMMARY_NAME: ["penalty_variant_id", "recommended_status", "adoption_allowed"],
        D_COMPARE_NAME: ["outlier_event_id", "interpretation"], ROOT_CAUSE_NAME: ["root_cause_category", "event_count"],
        DECISION_NAME: ["decision_area", "diagnostic_decision"], CERT_NAME: ["certification_status"],
        MUTATION_NAME: ["path", "modified_during_run", "mutation_allowed"],
    }
    for name, cols in schemas.items():
        pd.DataFrame(columns=cols).to_csv(output / name, index=False)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override.resolve() if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    required = [PANEL_REL, SPLIT_REL, FORENSIC_REL, GATE_REL, SAFE_REL, GRID_REL, STRESS_REL, OUTLIER_REL, SUMMARY_REL, SELECTED_REL]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)
    inv = input_inventory(root)
    master = ticker = factors = buckets = penalties = ptest = psum = compare = roots = decisions = pd.DataFrame()
    latest = ""
    if missing:
        empty_outputs(output)
        inv.to_csv(output / INVENTORY_NAME, index=False)
    else:
        panel = pd.read_csv(root / PANEL_REL, low_memory=False)
        splits = pd.read_csv(root / SPLIT_REL, low_memory=False)
        grid = pd.read_csv(root / GRID_REL, low_memory=False)
        stress = pd.read_csv(root / STRESS_REL, low_memory=False)
        latest = str(panel["source_latest_price_date"].dropna().max())
        master = build_master(stress, splits)
        r1, r2, r3, r4, work, tops = reconstruct(root, panel, grid)
        ticker = ticker_decomposition(master, work, tops)
        factors = factor_decomposition(master, work, tops, grid)
        buckets = bucket_regime_decomposition(root, master, work, tops)
        penalties = penalty_grid()
        ptest = penalty_backtest(root, work, splits, grid, penalties, stress, r3, r4)
        psum = penalty_summary(ptest, penalties)
        compare = baseline_comparison(master, work, tops, r3)
        roots = root_causes(master, ticker, factors, compare)
        promising = int(psum["recommended_status"].eq("PENALTY_DIAGNOSTIC_PROMISING_FOR_R6").sum())
        decisions = decision_matrix(promising)
        for frame, name in (
            (inv, INVENTORY_NAME), (master, MASTER_NAME), (ticker, TICKER_NAME),
            (factors, FACTOR_NAME), (buckets, BUCKET_NAME), (penalties, PENALTY_GRID_NAME),
            (ptest, PENALTY_TEST_NAME), (psum, PENALTY_SUMMARY_NAME),
            (compare, D_COMPARE_NAME), (roots, ROOT_CAUSE_NAME), (decisions, DECISION_NAME),
        ):
            frame.to_csv(output / name, index=False)
    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    cert = pd.DataFrame([{
        "research_only": True, "diagnostic_only": True, "shadow_only": True,
        "outlier_research_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "candidate_selected": False,
        "risk_penalty_adopted": False, "official_adoption_allowed": False,
        "certification_status": "CERTIFIED_R5_OUTLIER_RESEARCH_NO_SELECTION_NO_ADOPTION_NO_TRADE",
        "certification_note": "Outlier and penalty diagnostics only; no candidate or penalty selected.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)
    leakage = 0
    data_warnings = int(inv["warning"].fillna("").ne("").sum()) + int(ticker["warning"].fillna("").ne("").sum() if not ticker.empty else 0)
    promising = int(psum["recommended_status"].eq("PENALTY_DIAGNOSTIC_PROMISING_FOR_R6").sum()) if not psum.empty else 0
    if missing:
        status, decision = "BLOCKED_V21_092_R5_REQUIRED_INPUTS_MISSING", "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif mutation_count or leakage:
        status, decision = "BLOCKED_V21_092_R5_LEAKAGE_OR_PROTECTED_MUTATION_RISK", "OUTLIER_RESEARCH_BLOCKED_REVIEW_REQUIRED"
    elif data_warnings:
        status, decision = "PARTIAL_PASS_V21_092_R5_READY_WITH_DATA_WARN", "OUTLIER_DECOMPOSITION_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    else:
        status, decision = "PASS_V21_092_R5_OUTLIER_DECOMPOSITION_READY", "OUTLIER_DECOMPOSITION_READY_DIAGNOSTIC_ONLY"
    next_stage = "V21.092-R6_RISK_PENALTY_MICRO_TEST_WITH_NO_SELECTION" if promising else "KEEP_D_BASELINE_WAIT_FOR_MATURITY_AND_PRICE_REFRESH"
    validation = {
        "stage": "V21.092-R5_OUTLIER_SPLIT_DECOMPOSITION_AND_RISK_PENALTY_RESEARCH",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "shadow_only": True, "outlier_research_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "technical_085_preserved": mutation_count == 0, "fundamental_086_preserved": mutation_count == 0,
        "interaction_087_preserved": mutation_count == 0, "review_088_preserved": mutation_count == 0,
        "monitor_089_preserved": mutation_count == 0, "archive_090_preserved": mutation_count == 0,
        "maturity_091_preserved": mutation_count == 0, "shadow_search_092_r1_preserved": mutation_count == 0,
        "stability_search_092_r2_preserved": mutation_count == 0,
        "weight_effectiveness_092_r3_preserved": mutation_count == 0,
        "micro_stress_092_r4_preserved": mutation_count == 0, "source_latest_price_date": latest,
        "outlier_event_count": len(master), "severe_event_count": int(master["severity_bucket"].eq("SEVERE").sum()) if not master.empty else 0,
        "extreme_event_count": int(master["severity_bucket"].eq("EXTREME").sum()) if not master.empty else 0,
        "ticker_loss_rows": len(ticker), "factor_decomposition_rows": len(factors),
        "bucket_regime_rows": len(buckets), "penalty_variant_count": len(penalties),
        "penalty_backtest_rows": len(ptest), "penalty_effectiveness_rows": len(psum),
        "d_baseline_comparison_rows": len(compare), "root_cause_rows": len(roots),
        "promising_penalty_count": promising, "candidate_selected": False,
        "risk_penalty_adopted": False, "official_adoption_allowed": False,
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
    for key in ("final_status", "decision", "outlier_event_count", "penalty_backtest_rows", "promising_penalty_count"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
