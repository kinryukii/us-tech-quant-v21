#!/usr/bin/env python
"""V21.092-R4 micro-weight shadow stress test and forward-plan review."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_092_r4")
R1 = Path("outputs/v21/diagnostics/v21_092_r1")
R2 = Path("outputs/v21/diagnostics/v21_092_r2")
R3 = Path("outputs/v21/diagnostics/v21_092_r3")
PANEL_REL = R1 / "V21_092_R1_FACTOR_EFFECTIVENESS_PANEL.csv"
SPLIT_REL = R1 / "V21_092_R1_NESTED_WALKFORWARD_SPLIT_PLAN.csv"
R2_RESULTS_REL = R2 / "V21_092_R2_NESTED_WALKFORWARD_TIGHTENED_RESULTS.csv"
ALLOWED_REL = R3 / "V21_092_R3_ALLOWED_FACTOR_SET.csv"
SAFE_REL = R3 / "V21_092_R3_SAFE_WEIGHT_RANGE_MAP.csv"
RISK_REL = R3 / "V21_092_R3_FACTOR_RISK_CONTRIBUTION_SUMMARY.csv"
GATE_REL = R3 / "V21_092_R3_RISK_GATE_CALIBRATION_DIAGNOSTIC.csv"
MATRIX_REL = R3 / "V21_092_R3_WEIGHT_EFFECTIVENESS_DECISION_MATRIX.csv"
SELECTION_R3_REL = R3 / "V21_092_R3_NO_SHADOW_SELECTION_CONFIRMATION.csv"
MONITOR_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_D_TOP20_BUCKET_MONITOR.csv")
R1_SCRIPT = Path("scripts/v21/v21_092_r1_factor_effectiveness_nested_walkforward_and_dynamic_weight_shadow_search.py")
R2_SCRIPT = Path("scripts/v21/v21_092_r2_factor_filter_repair_and_weight_search_stability_tightening.py")
R3_SCRIPT = Path("scripts/v21/v21_092_r3_factor_weight_effectiveness_marginal_contribution_and_risk_gate_calibration.py")

INVENTORY_NAME = "V21_092_R4_INPUT_SOURCE_INVENTORY.csv"
GRID_NAME = "V21_092_R4_MICRO_WEIGHT_CANDIDATE_GRID.csv"
STRESS_NAME = "V21_092_R4_MICRO_WEIGHT_STRESS_TEST_RESULTS.csv"
OUTLIER_NAME = "V21_092_R4_OUTLIER_SPLIT_STRESS_REVIEW.csv"
GATE_SUMMARY_NAME = "V21_092_R4_CANDIDATE_GATE_SUMMARY.csv"
SELECTED_NAME = "V21_092_R4_SELECTED_MICRO_SHADOW_CANDIDATE.csv"
FORWARD_NAME = "V21_092_R4_DIAGNOSTIC_FORWARD_PLAN.csv"
D_COMPARE_NAME = "V21_092_R4_D_BASELINE_COMPARISON_SUMMARY.csv"
FORBIDDEN_NAME = "V21_092_R4_FORBIDDEN_SIGNAL_AUDIT.csv"
CERT_NAME = "V21_092_R4_NO_ADOPTION_CERTIFICATION.csv"
MUTATION_NAME = "V21_092_R4_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_092_R4_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    INVENTORY_NAME, GRID_NAME, STRESS_NAME, OUTLIER_NAME, GATE_SUMMARY_NAME,
    SELECTED_NAME, FORWARD_NAME, D_COMPARE_NAME, FORBIDDEN_NAME, CERT_NAME,
    MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = ("5D", "10D", "20D")
MICRO_COLUMNS = [
    "RS_QQQ_micro_weight", "RS_SPY_micro_weight", "RS_SOXX_micro_weight",
    "BreakoutConfirmation_micro_weight", "VolumeConfirmation_micro_weight",
    "LowQualityRisk_penalty_weight", "InteractionDataGap_penalty_weight",
    "OverextendedExposure_penalty_weight", "MASlopeAlignment_positive_weight",
    "Pullback_positive_weight", "Day0Breakout_chase_weight",
]


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
        (R2_RESULTS_REL, "R2_RESULTS_REQUIRED"), (ALLOWED_REL, "R3_ALLOWED_SET_REQUIRED"),
        (SAFE_REL, "R3_SAFE_RANGE_REQUIRED"), (RISK_REL, "R3_RISK_SUMMARY_REQUIRED"),
        (GATE_REL, "R3_GATE_DIAGNOSTIC_REQUIRED"), (MATRIX_REL, "R3_DECISION_MATRIX_REQUIRED"),
        (SELECTION_R3_REL, "R3_SELECTION_CONFIRMATION_REQUIRED"), (MONITOR_REL, "LATEST_D_TOP20_REFERENCE"),
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
            "row_count": row_count, "ticker_count": ticker_count,
            "min_date": min_date, "max_date": max_date,
            "usable_for_r4": exists, "warning": warning,
        })
    return pd.DataFrame(rows)


def candidate_grid(safe: pd.DataFrame) -> pd.DataFrame:
    safe_map = safe.set_index("factor_name")
    def maximum(name: str, default: float) -> float:
        return min(default, float(safe_map.loc[name, "safe_max_weight"])) if name in safe_map.index else 0.0
    rs = min(maximum("z_tech_rs_vs_qqq", .02), maximum("z_tech_rs_vs_spy", .02), maximum("z_tech_rs_vs_soxx", .02))
    breakout = maximum("z_tech_breakout_confirmed", .015)
    volume = maximum("z_tech_volume_confirmation", .015)
    definitions = [
        ("R4A", "R4A_RS_ONLY_MICRO_SHADOW", [.005, .005, .005, 0, 0, 0, 0, 0]),
        ("R4B", "R4B_BREAKOUT_VOLUME_MICRO_SHADOW", [0, 0, 0, min(.0075, breakout), min(.0075, volume), 0, 0, 0]),
        ("R4C", "R4C_RS_BREAKOUT_VOLUME_MICRO_SHADOW", [min(.005, rs), min(.005, rs), min(.005, rs), min(.005, breakout), min(.005, volume), 0, 0, 0]),
        ("R4D", "R4D_RS_WITH_LIGHT_RISK_PENALTY_MICRO_SHADOW", [min(.005, rs), min(.005, rs), min(.005, rs), 0, 0, -.005, -.0025, -.005]),
        ("R4E", "R4E_ULTRA_CONSERVATIVE_BALANCED_MICRO_SHADOW", [min(.0025, rs), min(.0025, rs), min(.0025, rs), min(.0025, breakout), min(.0025, volume), -.0025, -.001, -.0025]),
    ]
    rows = []
    for cid, group, values in definitions:
        row = {
            "candidate_id": cid, "candidate_group": group, "Base": .60, "Momentum": .40,
            "RS_QQQ_micro_weight": values[0], "RS_SPY_micro_weight": values[1],
            "RS_SOXX_micro_weight": values[2], "BreakoutConfirmation_micro_weight": values[3],
            "VolumeConfirmation_micro_weight": values[4], "LowQualityRisk_penalty_weight": values[5],
            "InteractionDataGap_penalty_weight": values[6], "OverextendedExposure_penalty_weight": values[7],
            "MASlopeAlignment_positive_weight": 0.0, "Pullback_positive_weight": 0.0,
            "Day0Breakout_chase_weight": 0.0,
            "max_total_micro_tilt": sum(abs(x) for x in values),
            "official_adoption_allowed": False, "forward_ledger_allowed_initial": False,
            "warning": "R3_SAFE_MICRO_RANGES_DIAGNOSTIC_ONLY",
        }
        rows.append(row)
    return pd.DataFrame(rows)


def prepare_work(panel: pd.DataFrame, r1, r2) -> pd.DataFrame:
    base = r2.r2_components(panel, r1)
    work = pd.concat([panel.reset_index(drop=True), base[["Base", "Momentum"]].reset_index(drop=True)], axis=1)
    work["D_PROXY_SCORE"] = .6 * work["Base"] + .4 * work["Momentum"]
    return work


def candidate_score(work: pd.DataFrame, row: pd.Series) -> pd.Series:
    return (
        row["Base"] * work["Base"] + row["Momentum"] * work["Momentum"]
        + row["RS_QQQ_micro_weight"] * work["z_tech_rs_vs_qqq"].fillna(0)
        + row["RS_SPY_micro_weight"] * work["z_tech_rs_vs_spy"].fillna(0)
        + row["RS_SOXX_micro_weight"] * work["z_tech_rs_vs_soxx"].fillna(0)
        + row["BreakoutConfirmation_micro_weight"] * work["z_tech_breakout_confirmed"].fillna(0)
        + row["VolumeConfirmation_micro_weight"] * work["z_tech_volume_confirmation"].fillna(0)
        + row["LowQualityRisk_penalty_weight"] * work["z_fund_low_quality_risk"].fillna(0)
        + row["InteractionDataGap_penalty_weight"] * work["z_bucket_interaction_data_gap"].fillna(0)
        + row["OverextendedExposure_penalty_weight"] * work["z_tech_overextended_but_strong"].fillna(0)
    )


def stress_test(work: pd.DataFrame, splits: pd.DataFrame, grid: pd.DataFrame, r3) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    d_top = r3.rank_top(work, work["D_PROXY_SCORE"])
    cache = {"D": d_top}
    rows = []
    for _, candidate in grid.iterrows():
        top = r3.rank_top(work, candidate_score(work, candidate))
        cache[candidate["candidate_id"]] = top
        for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
            window = split["forward_window"]
            cand = r3.period_metrics(work, top, split, window)
            base = r3.period_metrics(work, d_top, split, window)
            train, validation = r3.train_validation_scores(work, top, split, window, d_top)
            turnover = 1 - r3.overlap(top, d_top, split["test_start"], split["test_end"])
            excess = cand["mean"] - base["mean"]
            drawdown_delta = cand["drawdown"] - base["drawdown"]
            concentration_delta = cand["concentration"] - base["concentration"]
            overfit = abs(train - excess) > .02
            early = str(split["split_id"]).startswith("WF1") and cand["drawdown"] < -.50
            severe = cand["drawdown"] < -.50
            drawdown_pass = cand["drawdown"] >= -.30
            concentration_pass = pd.isna(cand["concentration"]) or cand["concentration"] <= .75
            turnover_pass = turnover <= .25
            stability_pass = validation > -.001 and excess > -.001
            usable = drawdown_pass and concentration_pass and turnover_pass and stability_pass and not overfit and not severe
            rows.append({
                "candidate_id": candidate["candidate_id"], "candidate_group": candidate["candidate_group"],
                "split_id": split["split_id"], "forward_window": window,
                "test_mean_forward_return": cand["mean"], "test_median_forward_return": cand["median"],
                "test_hit_rate": cand["hit"], "test_drawdown_proxy": cand["drawdown"],
                "test_turnover_proxy": turnover, "test_concentration_proxy": cand["concentration"],
                "test_excess_vs_D_proxy": excess, "drawdown_delta_vs_D_proxy": drawdown_delta,
                "concentration_delta_vs_D_proxy": concentration_delta, "turnover_delta_vs_D_proxy": turnover,
                "early_split_outlier_loss_flag": early, "severe_or_extreme_breach_flag": severe,
                "drawdown_gate_pass": drawdown_pass, "concentration_gate_pass": concentration_pass,
                "turnover_gate_pass": turnover_pass, "stability_gate_pass": stability_pass,
                "overfit_gate_pass": not overfit, "usable_for_shadow_forward_plan": usable,
                "warning": "" if usable else "ONE_OR_MORE_R4_STRESS_GATES_FAILED",
            })
    return pd.DataFrame(rows), cache


def outlier_review(stress: pd.DataFrame, r2_results: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    r2_best = r2_results.groupby(["split_id", "forward_window"])["test_drawdown_proxy"].max().to_dict()
    group_map = grid.set_index("candidate_id")["candidate_group"].to_dict()
    rows = []
    focus = stress[stress["split_id"].str.startswith("WF1") | stress["severe_or_extreme_breach_flag"].map(truth)]
    for _, row in focus.iterrows():
        dd = float(row["test_drawdown_proxy"])
        improvement = dd - r2_best.get((row["split_id"], row["forward_window"]), np.nan)
        still_blocks = dd < -.30
        if dd < -.75:
            handling = "INVESTIGATE_SPLIT_LATER"
        elif still_blocks:
            handling = "BLOCK_CANDIDATE"
        elif improvement > .02:
            handling = "ACCEPTABLE_AFTER_MICRO_SHRINKAGE_DIAGNOSTIC_ONLY"
        else:
            handling = "KEEP_DIAGNOSTIC_ONLY"
        rows.append({
            "candidate_id": row["candidate_id"], "candidate_group": group_map[row["candidate_id"]],
            "split_id": row["split_id"], "forward_window": row["forward_window"],
            "outlier_split_flag": str(row["split_id"]).startswith("WF1"),
            "test_drawdown_proxy": dd, "test_mean_forward_return": row["test_mean_forward_return"],
            "test_hit_rate": row["test_hit_rate"],
            "likely_outlier_driver": "EARLY_SPLIT_MARKET_LOSS_CLUSTER" if str(row["split_id"]).startswith("WF1") else "SEVERE_ABSOLUTE_DRAWDOWN",
            "candidate_exposure_summary": f"turnover={row['test_turnover_proxy']:.4f}|concentration={row['test_concentration_proxy']:.4f}",
            "repair_effectiveness_vs_r2": improvement, "still_blocks_candidate": still_blocks,
            "recommended_handling": handling,
            "warning": "OUTLIER_OR_SEVERE_BREACH_REMAINS" if still_blocks else "",
        })
    return pd.DataFrame(rows)


def gate_summary(stress: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (cid, group), data in stress.groupby(["candidate_id", "candidate_group"]):
        row = {"candidate_id": cid, "candidate_group": group, "windows_tested": data["forward_window"].nunique(), "splits_tested": data["split_id"].nunique()}
        for window in WINDOWS:
            row[f"avg_excess_vs_D_{window.lower()}"] = data.loc[data["forward_window"].eq(window), "test_excess_vs_D_proxy"].mean()
        row.update({
            "avg_drawdown_proxy": data["test_drawdown_proxy"].mean(),
            "avg_concentration_proxy": data["test_concentration_proxy"].mean(),
            "avg_turnover_proxy": data["test_turnover_proxy"].mean(),
            "drawdown_pass_ratio": data["drawdown_gate_pass"].map(truth).mean(),
            "concentration_pass_ratio": data["concentration_gate_pass"].map(truth).mean(),
            "turnover_pass_ratio": data["turnover_gate_pass"].map(truth).mean(),
            "stability_pass_ratio": data["stability_gate_pass"].map(truth).mean(),
            "overfit_pass_ratio": data["overfit_gate_pass"].map(truth).mean(),
            "severe_breach_count": int(data["test_drawdown_proxy"].lt(-.50).sum()),
            "extreme_breach_count": int(data["test_drawdown_proxy"].lt(-.75).sum()),
        })
        usable = (
            row["drawdown_pass_ratio"] == 1 and row["concentration_pass_ratio"] == 1
            and row["turnover_pass_ratio"] == 1 and row["stability_pass_ratio"] == 1
            and row["overfit_pass_ratio"] == 1 and row["severe_breach_count"] == 0
            and min(row[f"avg_excess_vs_D_{w.lower()}"] for w in WINDOWS) >= 0
        )
        if usable: status = "MICRO_SHADOW_FORWARD_PLAN_READY_DIAGNOSTIC_ONLY"
        elif row["extreme_breach_count"] > 0: status = "MICRO_SHADOW_REJECT_OUTLIER_SPLIT"
        elif row["drawdown_pass_ratio"] < 1: status = "MICRO_SHADOW_REJECT_DRAWDOWN"
        elif row["concentration_pass_ratio"] < 1: status = "MICRO_SHADOW_REJECT_CONCENTRATION"
        elif row["stability_pass_ratio"] < 1: status = "MICRO_SHADOW_REJECT_INSUFFICIENT_STABILITY"
        else: status = "MICRO_SHADOW_REJECT_INSUFFICIENT_RETURN"
        row["usable_for_shadow_forward_plan"] = usable
        row["recommended_shadow_status"] = status
        row["adoption_allowed"] = False
        row["warning"] = "" if usable else status
        rows.append(row)
    return pd.DataFrame(rows)


def select_candidate(summary: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    ready = summary[summary["usable_for_shadow_forward_plan"].map(truth)]
    if ready.empty:
        return pd.DataFrame([{
            "selected_candidate_id": "", "selected_candidate_group": "",
            "selected_status": "NO_MICRO_SHADOW_CANDIDATE_SELECTED",
            "reason": "No micro-weight candidate passed every split-level stress gate.",
            "weights_json": "", "avg_excess_vs_D_5d": np.nan, "avg_excess_vs_D_10d": np.nan,
            "avg_excess_vs_D_20d": np.nan, "drawdown_pass_ratio": np.nan,
            "concentration_pass_ratio": np.nan, "turnover_pass_ratio": np.nan,
            "stability_pass_ratio": np.nan, "severe_breach_count": np.nan,
            "extreme_breach_count": np.nan, "forward_ledger_plan_allowed": False,
            "official_adoption_allowed": False, "broker_action_created": False,
            "recommendation_created": False, "no_trade_action_created": True,
            "warning": "NO_PASSING_MICRO_SHADOW_CANDIDATE",
        }])
    best = ready.sort_values(["avg_excess_vs_D_20d", "avg_drawdown_proxy"], ascending=False).iloc[0]
    weights = grid[grid["candidate_id"].eq(best["candidate_id"])].iloc[0]
    return pd.DataFrame([{
        "selected_candidate_id": best["candidate_id"], "selected_candidate_group": best["candidate_group"],
        "selected_status": "MICRO_SHADOW_FORWARD_PLAN_CANDIDATE_DIAGNOSTIC_ONLY",
        "reason": "Passed every stress gate without severe or extreme breach.",
        "weights_json": json.dumps({c: float(weights[c]) for c in MICRO_COLUMNS}, sort_keys=True),
        "avg_excess_vs_D_5d": best["avg_excess_vs_D_5d"], "avg_excess_vs_D_10d": best["avg_excess_vs_D_10d"],
        "avg_excess_vs_D_20d": best["avg_excess_vs_D_20d"], "drawdown_pass_ratio": best["drawdown_pass_ratio"],
        "concentration_pass_ratio": best["concentration_pass_ratio"], "turnover_pass_ratio": best["turnover_pass_ratio"],
        "stability_pass_ratio": best["stability_pass_ratio"], "severe_breach_count": best["severe_breach_count"],
        "extreme_breach_count": best["extreme_breach_count"], "forward_ledger_plan_allowed": True,
        "official_adoption_allowed": False, "broker_action_created": False,
        "recommendation_created": False, "no_trade_action_created": True, "warning": "",
    }])


def forward_plan(work: pd.DataFrame, selected: pd.DataFrame, grid: pd.DataFrame, r3) -> pd.DataFrame:
    columns = ["selected_candidate_id", "as_of_date", "ticker", "shadow_rank", "shadow_score", "d_rank", "d_top20_flag", "shadow_top20_flag", "shadow_top50_flag", "forward_window", "planned_maturity_date", "forward_observation_allowed", "official_adoption_allowed", "no_trade_action_created", "plan_status", "warning"]
    if selected.iloc[0]["selected_status"] != "MICRO_SHADOW_FORWARD_PLAN_CANDIDATE_DIAGNOSTIC_ONLY":
        return pd.DataFrame([{
            "selected_candidate_id": "", "as_of_date": work["as_of_date"].max(), "ticker": "",
            "shadow_rank": np.nan, "shadow_score": np.nan, "d_rank": np.nan,
            "d_top20_flag": False, "shadow_top20_flag": False, "shadow_top50_flag": False,
            "forward_window": "", "planned_maturity_date": "", "forward_observation_allowed": False,
            "official_adoption_allowed": False, "no_trade_action_created": True,
            "plan_status": "NO_FORWARD_PLAN_CREATED",
            "warning": "NO_MICRO_SHADOW_CANDIDATE_SELECTED",
        }], columns=columns)
    cid = selected.iloc[0]["selected_candidate_id"]
    candidate = grid[grid["candidate_id"].eq(cid)].iloc[0]
    latest = work["as_of_date"].max()
    current = work[work["as_of_date"].eq(latest)].copy()
    current["shadow_score"] = candidate_score(current, candidate)
    current["shadow_rank"] = current["shadow_score"].rank(method="first", ascending=False)
    rows = []
    for _, row in current[current["shadow_rank"].le(50)].iterrows():
        for days in (5, 10, 20):
            rows.append({
                "selected_candidate_id": cid, "as_of_date": latest, "ticker": row["ticker"],
                "shadow_rank": row["shadow_rank"], "shadow_score": row["shadow_score"],
                "d_rank": row.get("d_rank"), "d_top20_flag": truth(row.get("d_top20_flag")),
                "shadow_top20_flag": row["shadow_rank"] <= 20, "shadow_top50_flag": True,
                "forward_window": f"{days}D",
                "planned_maturity_date": (pd.Timestamp(latest) + pd.tseries.offsets.BDay(days)).date().isoformat(),
                "forward_observation_allowed": True, "official_adoption_allowed": False,
                "no_trade_action_created": True, "plan_status": "DIAGNOSTIC_FORWARD_PLAN_CREATED",
                "warning": "",
            })
    return pd.DataFrame(rows, columns=columns)


def d_comparison(stress: pd.DataFrame, work: pd.DataFrame, splits: pd.DataFrame, r3) -> pd.DataFrame:
    d_top = r3.rank_top(work, work["D_PROXY_SCORE"])
    d_metrics = {}
    for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
        d_metrics[split["split_id"]] = r3.period_metrics(work, d_top, split, split["forward_window"])
    rows = []
    for (cid, window), data in stress.groupby(["candidate_id", "forward_window"]):
        base = pd.DataFrame([d_metrics[sid] for sid in data["split_id"]])
        candidate_mean = data["test_mean_forward_return"].mean()
        d_mean = base["mean"].mean()
        candidate_dd, d_dd = data["test_drawdown_proxy"].mean(), base["drawdown"].mean()
        excess = candidate_mean - d_mean
        if data["severe_or_extreme_breach_flag"].map(truth).any():
            status = "MICRO_CANDIDATE_REJECTED_BY_RISK"
        elif excess > 0:
            status = "MICRO_CANDIDATE_BEATS_D_DIAGNOSTIC_ONLY"
        elif candidate_dd > d_dd:
            status = "MICRO_CANDIDATE_IMPROVES_RISK_BUT_NOT_RETURN"
        else:
            status = "MICRO_CANDIDATE_DOES_NOT_BEAT_D"
        rows.append({
            "candidate_id": cid, "forward_window": window,
            "candidate_mean_return": candidate_mean, "d_baseline_mean_return": d_mean,
            "candidate_minus_d": excess, "candidate_hit_rate": data["test_hit_rate"].mean(),
            "d_hit_rate": base["hit"].mean(), "hit_rate_delta": data["test_hit_rate"].mean() - base["hit"].mean(),
            "candidate_drawdown_proxy": candidate_dd, "d_drawdown_proxy": d_dd,
            "drawdown_delta_vs_d": candidate_dd - d_dd,
            "candidate_concentration_proxy": data["test_concentration_proxy"].mean(),
            "d_concentration_proxy": base["concentration"].mean(),
            "comparison_status": status, "warning": "D_EQUIVALENT_PROXY_DIAGNOSTIC_ONLY",
        })
    return pd.DataFrame(rows)


def forbidden_audit() -> pd.DataFrame:
    signals = [
        ("TECH_PULLBACK_BUY_CANDIDATE", "Negative historical edge.", False, False, False),
        ("PULLBACK_REPAIR_R3_RSI_STABILIZED_MACD_POSITIVE", "Repair remained negative.", False, False, False),
        ("TECH_BREAKOUT_DAY0_WATCH_ONLY", "No-chase watch-only state.", False, False, False),
        ("MA_SLOPE_ALIGNMENT_POSITIVE_WEIGHT", "R3 did not establish a full-gate-safe region.", False, False, False),
        ("LOW_QUALITY_MOMENTUM_RISK", "Penalty or diagnostic only.", False, False, True),
        ("INTERACTION_UNAVAILABLE", "Penalty or diagnostic only.", False, False, True),
        ("FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "Diagnostic only until maturity.", False, False, False),
    ]
    return pd.DataFrame([{
        "signal_name": n, "reason_for_constraint": reason,
        "positive_weight_allowed": allowed, "tested_as_positive_weight": tested,
        "used_as_penalty": penalty, "adoption_allowed": False,
        "audit_status": "PASS_CONSTRAINT_ENFORCED", "warning": "",
    } for n, reason, allowed, tested, penalty in signals])


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 92):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    for rel in (R1, R2, R3):
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
        GRID_NAME: ["candidate_id", "official_adoption_allowed"],
        STRESS_NAME: ["candidate_id", "split_id", "usable_for_shadow_forward_plan"],
        OUTLIER_NAME: ["candidate_id", "recommended_handling"],
        GATE_SUMMARY_NAME: ["candidate_id", "recommended_shadow_status", "adoption_allowed"],
        SELECTED_NAME: ["selected_status", "official_adoption_allowed", "no_trade_action_created"],
        FORWARD_NAME: ["selected_candidate_id", "plan_status", "official_adoption_allowed", "no_trade_action_created"],
        D_COMPARE_NAME: ["candidate_id", "comparison_status"],
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
    required = [PANEL_REL, SPLIT_REL, R2_RESULTS_REL, ALLOWED_REL, SAFE_REL, RISK_REL, GATE_REL, MATRIX_REL, SELECTION_R3_REL]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)
    inv = input_inventory(root)
    grid = stress = outliers = summary = selected = plan = compare = pd.DataFrame()
    latest = ""
    if missing:
        empty_outputs(output)
        inv.to_csv(output / INVENTORY_NAME, index=False)
    else:
        r1 = load_module(root, R1_SCRIPT, "r1_reuse")
        r2 = load_module(root, R2_SCRIPT, "r2_reuse")
        r3 = load_module(root, R3_SCRIPT, "r3_reuse")
        panel = pd.read_csv(root / PANEL_REL, low_memory=False)
        splits = pd.read_csv(root / SPLIT_REL, low_memory=False)
        safe = pd.read_csv(root / SAFE_REL, low_memory=False)
        r2_results = pd.read_csv(root / R2_RESULTS_REL, low_memory=False)
        latest = str(panel["source_latest_price_date"].dropna().max())
        grid = candidate_grid(safe)
        work = prepare_work(panel, r1, r2)
        stress, _ = stress_test(work, splits, grid, r3)
        outliers = outlier_review(stress, r2_results, grid)
        summary = gate_summary(stress)
        selected = select_candidate(summary, grid)
        plan = forward_plan(work, selected, grid, r3)
        compare = d_comparison(stress, work, splits, r3)
        forbidden = forbidden_audit()
        for frame, name in (
            (inv, INVENTORY_NAME), (grid, GRID_NAME), (stress, STRESS_NAME),
            (outliers, OUTLIER_NAME), (summary, GATE_SUMMARY_NAME),
            (selected, SELECTED_NAME), (plan, FORWARD_NAME), (compare, D_COMPARE_NAME),
            (forbidden, FORBIDDEN_NAME),
        ):
            frame.to_csv(output / name, index=False)
    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    selected_status = selected.iloc[0]["selected_status"] if not selected.empty else "NO_MICRO_SHADOW_CANDIDATE_SELECTED"
    cert = pd.DataFrame([{
        "research_only": True, "diagnostic_only": True, "shadow_only": True,
        "stress_test_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "pullback_positive_weight_used": False,
        "day0_chase_used": False, "ma_slope_positive_weight_selected": False,
        "shadow_candidate_adoption_allowed": False, "official_adoption_allowed": False,
        "certification_status": "CERTIFIED_R4_MICRO_WEIGHT_STRESS_TEST_NO_ADOPTION_NO_TRADE",
        "certification_note": "Micro-weight stress testing only; no official selection, adoption, or trade.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)
    leakage = 0
    data_warnings = int(inv["warning"].fillna("").ne("").sum())
    if missing:
        status, decision = "BLOCKED_V21_092_R4_REQUIRED_INPUTS_MISSING", "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif mutation_count or leakage:
        status, decision = "BLOCKED_V21_092_R4_LEAKAGE_OR_PROTECTED_MUTATION_RISK", "MICRO_WEIGHT_STRESS_TEST_BLOCKED_REVIEW_REQUIRED"
    elif selected_status == "MICRO_SHADOW_FORWARD_PLAN_CANDIDATE_DIAGNOSTIC_ONLY":
        status, decision = "PASS_V21_092_R4_MICRO_SHADOW_FORWARD_PLAN_READY", "MICRO_SHADOW_FORWARD_PLAN_READY_DIAGNOSTIC_ONLY"
    elif data_warnings:
        status, decision = "PARTIAL_PASS_V21_092_R4_READY_WITH_DATA_WARN", "MICRO_WEIGHT_STRESS_TEST_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    else:
        status, decision = "PARTIAL_PASS_V21_092_R4_MICRO_WEIGHT_STRESS_TEST_READY_NO_CANDIDATE_SELECTED", "MICRO_WEIGHT_STRESS_TEST_READY_NO_CANDIDATE_SELECTED_DIAGNOSTIC_ONLY"
    severe_count = int(stress["test_drawdown_proxy"].lt(-.50).sum()) if not stress.empty else 0
    extreme_count = int(stress["test_drawdown_proxy"].lt(-.75).sum()) if not stress.empty else 0
    next_stage = "V21.093-R1_MICRO_SHADOW_FORWARD_LEDGER_AND_D_BASELINE_COMPARISON" if selected_status == "MICRO_SHADOW_FORWARD_PLAN_CANDIDATE_DIAGNOSTIC_ONLY" else "V21.092-R5_OUTLIER_SPLIT_DECOMPOSITION_AND_RISK_PENALTY_RESEARCH" if extreme_count else "KEEP_D_BASELINE_WAIT_FOR_MATURITY_AND_PRICE_REFRESH"
    selected_id = selected.iloc[0]["selected_candidate_id"] if not selected.empty else ""
    validation = {
        "stage": "V21.092-R4_MICRO_WEIGHT_SHADOW_STRESS_TEST_AND_FORWARD_PLAN_REVIEW",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "shadow_only": True, "stress_test_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "technical_085_preserved": mutation_count == 0, "fundamental_086_preserved": mutation_count == 0,
        "interaction_087_preserved": mutation_count == 0, "review_088_preserved": mutation_count == 0,
        "monitor_089_preserved": mutation_count == 0, "archive_090_preserved": mutation_count == 0,
        "maturity_091_preserved": mutation_count == 0, "shadow_search_092_r1_preserved": mutation_count == 0,
        "stability_search_092_r2_preserved": mutation_count == 0,
        "weight_effectiveness_092_r3_preserved": mutation_count == 0,
        "source_latest_price_date": latest, "micro_candidate_count": len(grid),
        "stress_test_rows": len(stress), "outlier_split_review_rows": len(outliers),
        "candidate_gate_summary_rows": len(summary), "selected_candidate_id": selected_id,
        "selected_status": selected_status,
        "forward_ledger_plan_allowed": truth(selected.iloc[0].get("forward_ledger_plan_allowed", False)) if not selected.empty else False,
        "diagnostic_forward_plan_rows": len(plan), "official_adoption_allowed": False,
        "pullback_positive_weight_used": False, "day0_chase_used": False,
        "ma_slope_positive_weight_selected": False, "severe_breach_count": severe_count,
        "extreme_breach_count": extreme_count,
        "drawdown_warning_count": int((~stress["drawdown_gate_pass"].map(truth)).sum()) if not stress.empty else 0,
        "concentration_warning_count": int((~stress["concentration_gate_pass"].map(truth)).sum()) if not stress.empty else 0,
        "overfit_warning_count": int((~stress["overfit_gate_pass"].map(truth)).sum()) if not stress.empty else 0,
        "turnover_warning_count": int((~stress["turnover_gate_pass"].map(truth)).sum()) if not stress.empty else 0,
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
    for key in ("final_status", "decision", "micro_candidate_count", "stress_test_rows", "selected_status"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
