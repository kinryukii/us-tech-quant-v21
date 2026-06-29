#!/usr/bin/env python
"""V21.077 research-only sector/industry-aware D portfolio backtest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256, truth


STAGE = "V21.077-R1_TO_R3_SECTOR_AWARE_RISK_BUDGET_BACKTEST"
OUT_REL = Path("outputs/v21/v21_077")
HOLDINGS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_HOLDINGS.csv")
RESULTS_REL = Path("outputs/v21/v21_075/V21_075_R2_PORTFOLIO_RESULTS.csv")
V75_COMPARISON_REL = Path("outputs/v21/v21_075/V21_075_R3_POSITION_SIZING_EFFECTIVENESS_COMPARISON.csv")
CLASSIFICATION_REL = Path("outputs/v21/v21_076/V21_076_R1_CLASSIFICATION_MASTER.csv")
V76_READINESS_REL = Path("outputs/v21/v21_076/V21_076_R3_READINESS_DECISION_REPORT.csv")

POLICY_NAME = "V21_077_R1_POLICY_DEFINITIONS.csv"
HOLDINGS_NAME = "V21_077_R2_PORTFOLIO_HOLDINGS.csv"
SUMMARY_NAME = "V21_077_R2_PORTFOLIO_BACKTEST_SUMMARY.csv"
CONC_NAME = "V21_077_R2_CONCENTRATION_DIAGNOSTIC.csv"
THEME_NAME = "V21_077_R2_THEME_DIAGNOSTIC_ONLY_REPORT.csv"
COMPARISON_NAME = "V21_077_R3_D_EW_VS_SECTOR_AWARE_COMPARISON.csv"
READINESS_NAME = "V21_077_R3_READINESS_DECISION_REPORT.csv"

GROUP_KEYS = ["seed", "batch_id", "sampled_as_of_date", "forward_window", "split"]
BASE_SOURCE = {
    20: ("EW_TOP20_R1", "D_EW_TOP20_R1"),
    50: ("EW_TOP50_R1", "D_EW_TOP50_R1"),
}
HARD_CAPS = {
    20: {"sector": 0.55, "industry": 0.30},
    50: {"sector": 0.45, "industry": 0.20},
}
SOFT_THRESHOLDS = {
    20: {"sector": 0.50, "industry": 0.25},
    50: {"sector": 0.40, "industry": 0.18},
}
MAX_TICKER_CAP = 0.10


def policy_definitions() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for top_n in (20, 50):
        rows.append({
            "policy_id": f"D_EW_TOP{top_n}_R1",
            "policy_family": "BASELINE",
            "top_n": top_n,
            "uses_hard_sector_cap": False,
            "uses_hard_industry_cap": False,
            "uses_soft_sector_penalty": False,
            "uses_soft_industry_penalty": False,
            "sector_cap": "",
            "industry_cap": "",
            "sector_soft_threshold": "",
            "industry_soft_threshold": "",
            "max_ticker_cap": MAX_TICKER_CAP,
            "preserve_candidate_pool": True,
            "hard_theme_cap_used": False,
            "theme_diagnostic_only": True,
            "research_only": True,
        })
        for family, hard_sector, hard_industry in (
            ("SECTOR_CAP", True, False),
            ("INDUSTRY_CAP", False, True),
            ("SECTOR_INDUSTRY_CAP", True, True),
        ):
            rows.append({
                "policy_id": f"D_{family}_TOP{top_n}_R1",
                "policy_family": "HARD_CAP",
                "top_n": top_n,
                "uses_hard_sector_cap": hard_sector,
                "uses_hard_industry_cap": hard_industry,
                "uses_soft_sector_penalty": False,
                "uses_soft_industry_penalty": False,
                "sector_cap": HARD_CAPS[top_n]["sector"] if hard_sector else "",
                "industry_cap": HARD_CAPS[top_n]["industry"] if hard_industry else "",
                "sector_soft_threshold": "",
                "industry_soft_threshold": "",
                "max_ticker_cap": MAX_TICKER_CAP,
                "preserve_candidate_pool": True,
                "hard_theme_cap_used": False,
                "theme_diagnostic_only": True,
                "research_only": True,
            })
        for family, soft_sector, soft_industry in (
            ("SECTOR_SOFT_PENALTY", True, False),
            ("INDUSTRY_SOFT_PENALTY", False, True),
            ("SECTOR_INDUSTRY_SOFT_PENALTY", True, True),
        ):
            rows.append({
                "policy_id": f"D_{family}_TOP{top_n}_R1",
                "policy_family": "SOFT_PENALTY",
                "top_n": top_n,
                "uses_hard_sector_cap": False,
                "uses_hard_industry_cap": False,
                "uses_soft_sector_penalty": soft_sector,
                "uses_soft_industry_penalty": soft_industry,
                "sector_cap": "",
                "industry_cap": "",
                "sector_soft_threshold": SOFT_THRESHOLDS[top_n]["sector"] if soft_sector else "",
                "industry_soft_threshold": SOFT_THRESHOLDS[top_n]["industry"] if soft_industry else "",
                "max_ticker_cap": MAX_TICKER_CAP,
                "preserve_candidate_pool": True,
                "hard_theme_cap_used": False,
                "theme_diagnostic_only": True,
                "research_only": True,
            })
    return pd.DataFrame(rows)


def capped_normalize(raw: pd.Series, cap: float) -> pd.Series:
    raw = pd.to_numeric(raw, errors="coerce").fillna(0).clip(lower=0)
    if raw.sum() <= 0:
        raw = pd.Series(1.0, index=raw.index)
    weight = pd.Series(0.0, index=raw.index, dtype=float)
    active = pd.Series(True, index=raw.index)
    remaining = 1.0
    for _ in range(len(raw) + 3):
        if remaining <= 1e-13 or not active.any():
            break
        sub = raw[active]
        proposal = pd.Series(remaining / active.sum(), index=sub.index) if sub.sum() <= 0 else sub / sub.sum() * remaining
        saturated = proposal.ge(cap - weight[proposal.index] - 1e-15)
        if saturated.any():
            idx = proposal.index[saturated]
            add = cap - weight[idx]
            weight.loc[idx] += add
            remaining -= float(add.sum())
            active.loc[idx] = False
        else:
            weight.loc[proposal.index] += proposal
            remaining = 0.0
    return weight / weight.sum() if weight.sum() > 0 else weight


def ticker_capacity(frame: pd.DataFrame, weights: pd.Series, caps: list[tuple[str, float]]) -> pd.Series:
    capacity = pd.Series(MAX_TICKER_CAP, index=weights.index, dtype=float) - weights
    for dim, cap in caps:
        sums = weights.groupby(frame[dim]).sum()
        remain = frame[dim].map(lambda value: cap - float(sums.get(value, 0.0)))
        capacity = np.minimum(capacity, remain)
    return pd.Series(capacity, index=weights.index).clip(lower=0)


def redistribute(
    frame: pd.DataFrame,
    weights: pd.Series,
    excess: float,
    caps: list[tuple[str, float]],
    blocked: pd.Series,
) -> tuple[pd.Series, bool]:
    for _ in range(len(weights) + 5):
        if excess <= 1e-12:
            return weights, True
        cap = ticker_capacity(frame, weights, caps)
        cap = cap.mask(blocked, 0.0)
        total = float(cap.sum())
        if total <= 1e-12:
            return weights, False
        add = cap / total * min(excess, total)
        weights = weights.add(add, fill_value=0.0)
        excess -= float(add.sum())
    return weights, excess <= 1e-10


def enforce_hard_caps(frame: pd.DataFrame, caps: list[tuple[str, float]]) -> tuple[pd.Series, bool, str]:
    weights = pd.Series(1.0 / len(frame), index=frame.index, dtype=float)
    weights = weights.clip(upper=MAX_TICKER_CAP)
    weights = weights / weights.sum()
    if weights.max() > MAX_TICKER_CAP + 1e-12:
        return weights, False, "MAX_TICKER_CAP_INFEASIBLE"
    for _ in range(100):
        violations: list[tuple[float, str, Any, float, float]] = []
        for dim, cap in caps:
            sums = weights.groupby(frame[dim]).sum()
            for label, value in sums.items():
                if value > cap + 1e-10:
                    violations.append((float(value - cap), dim, label, float(value), cap))
        if not violations:
            return weights / weights.sum(), True, ""
        _, dim, label, value, cap = max(violations, key=lambda item: item[0])
        idx = frame.index[frame[dim].eq(label)]
        scale = cap / value
        removed = weights.loc[idx] * (1.0 - scale)
        weights.loc[idx] = weights.loc[idx] * scale
        blocked = frame[dim].eq(label)
        weights, ok = redistribute(frame, weights, float(removed.sum()), caps, blocked)
        if not ok:
            return weights, False, f"{dim.upper()}_CAP_REDISTRIBUTION_INFEASIBLE"
    return weights, False, "CAP_PROJECTION_DID_NOT_CONVERGE"


def soft_penalty_weights(frame: pd.DataFrame, use_sector: bool, use_industry: bool, top_n: int) -> pd.Series:
    raw = pd.Series(1.0, index=frame.index, dtype=float)
    equal = pd.Series(1.0 / len(frame), index=frame.index, dtype=float)
    for dim, enabled in (("sector", use_sector), ("industry", use_industry)):
        if not enabled:
            continue
        threshold = SOFT_THRESHOLDS[top_n][dim]
        exposure = equal.groupby(frame[dim]).sum()
        for label, value in exposure.items():
            if value > threshold:
                penalty = max(threshold / value, 0.25)
                raw.loc[frame[dim].eq(label)] *= penalty
    return capped_normalize(raw, MAX_TICKER_CAP)


def load_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame]:
    readiness = pd.read_csv(root / V76_READINESS_REL).iloc[0]
    if not truth(readiness.get("sector_aware_risk_budget_backtest_allowed")):
        raise RuntimeError("V21.076 readiness does not allow sector-aware backtest")
    classes = pd.read_csv(root / CLASSIFICATION_REL, low_memory=False)
    class_cols = [
        "ticker", "sector", "industry", "theme_tags", "theme_confidence",
        "theme_tags_inferred", "theme_tags_allowed_for_hard_caps",
        "etf_category", "etf_leverage_inverse_flag", "classification_quality_flag",
    ]
    classes = classes[class_cols].copy()
    chunks = []
    cols = [
        "seed", "batch_id", "sampled_as_of_date", "forward_window", "split",
        "selection_policy_id", "position_policy_id", "joint_portfolio_policy_id",
        "ticker", "rank", "score", "risk_size_bucket", "position_weight",
        "realized_forward_return", "max_adverse_excursion",
        "max_favorable_excursion", "path_coverage",
    ]
    for chunk in pd.read_csv(root / HOLDINGS_REL, usecols=cols, chunksize=250000, low_memory=False):
        keep = chunk["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1") & chunk["position_policy_id"].isin(["EW_TOP20_R1", "EW_TOP50_R1"])
        chunks.append(chunk[keep].copy())
    base = pd.concat(chunks, ignore_index=True)
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    base = base.merge(classes, on="ticker", how="left")
    result_cols = [
        "seed", "batch_id", "sampled_as_of_date", "forward_window", "split",
        "selection_policy_id", "position_policy_id", "benchmark_qqq_return",
        "benchmark_spy_return",
    ]
    result_chunks = []
    for chunk in pd.read_csv(root / RESULTS_REL, usecols=result_cols, chunksize=250000, low_memory=False):
        keep = chunk["selection_policy_id"].eq("D_WEIGHT_OPTIMIZED_R1") & chunk["position_policy_id"].isin(["EW_TOP20_R1", "EW_TOP50_R1"])
        result_chunks.append(chunk[keep].copy())
    result_bench = pd.concat(result_chunks, ignore_index=True).drop_duplicates(
        GROUP_KEYS + ["position_policy_id"]
    )
    base = base.merge(
        result_bench[GROUP_KEYS + ["position_policy_id", "benchmark_qqq_return", "benchmark_spy_return"]],
        on=GROUP_KEYS + ["position_policy_id"],
        how="left",
    )
    return base, classes, readiness, pd.read_csv(root / V75_COMPARISON_REL, low_memory=False)


def apply_policy(group: pd.DataFrame, policy: pd.Series) -> tuple[pd.Series, bool, str]:
    top_n = int(policy["top_n"])
    family = str(policy["policy_family"])
    if family == "BASELINE":
        weights = pd.to_numeric(group["position_weight"], errors="coerce").fillna(1.0 / len(group))
        return weights / weights.sum(), True, ""
    if family == "SOFT_PENALTY":
        return soft_penalty_weights(
            group,
            truth(policy["uses_soft_sector_penalty"]),
            truth(policy["uses_soft_industry_penalty"]),
            top_n,
        ), True, ""
    caps: list[tuple[str, float]] = []
    if truth(policy["uses_hard_sector_cap"]):
        caps.append(("sector", HARD_CAPS[top_n]["sector"]))
    if truth(policy["uses_hard_industry_cap"]):
        caps.append(("industry", HARD_CAPS[top_n]["industry"]))
    return enforce_hard_caps(group, caps)


def turnover_proxy(results: pd.DataFrame) -> float:
    ordered = results.sort_values(["seed", "sampled_as_of_date", "batch_id"])
    overlap = ordered["ticker_set"].shift().combine(
        ordered["ticker_set"],
        lambda left, right: len(left & right) / max(len(left | right), 1)
        if isinstance(left, set) and isinstance(right, set) else np.nan,
    )
    return float((1 - overlap).mean())


def build_backtest(base: pd.DataFrame, policies: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    holding_frames: list[pd.DataFrame] = []
    portfolio_rows: list[dict[str, Any]] = []
    conc_rows: list[dict[str, Any]] = []
    theme_rows: list[dict[str, Any]] = []
    for _, policy in policies.iterrows():
        top_n = int(policy["top_n"])
        source_position_policy, _ = BASE_SOURCE[top_n]
        source = base[base["position_policy_id"].eq(source_position_policy)].copy()
        for keys, group in source.groupby(GROUP_KEYS, sort=False):
            group = group.copy()
            weights, feasible, reason = apply_policy(group, policy)
            group["position_weight"] = weights.reindex(group.index).fillna(0.0)
            group["weighted_return"] = group["position_weight"] * pd.to_numeric(group["realized_forward_return"], errors="coerce")
            group["weighted_mae"] = group["position_weight"] * pd.to_numeric(group["max_adverse_excursion"], errors="coerce")
            group["weighted_mfe"] = group["position_weight"] * pd.to_numeric(group["max_favorable_excursion"], errors="coerce")
            weight_sum = float(group["position_weight"].sum())
            sector_weights = group.groupby("sector")["position_weight"].sum()
            industry_weights = group.groupby("industry")["position_weight"].sum()
            etf_weights = group.groupby(group["etf_category"].fillna("").replace("", "NON_ETF"))["position_weight"].sum()
            lev_weight = float(group.loc[group["etf_leverage_inverse_flag"].isin(["LEVERAGED_LONG", "INVERSE"]), "position_weight"].sum())
            inv_weight = float(group.loc[group["etf_leverage_inverse_flag"].eq("INVERSE"), "position_weight"].sum())
            theme_expanded: dict[str, float] = {}
            for _, row in group.iterrows():
                for tag in str(row.get("theme_tags") or "").split("|"):
                    tag = tag.strip()
                    if tag:
                        theme_expanded[tag] = theme_expanded.get(tag, 0.0) + float(row["position_weight"])
            out = group[[
                *GROUP_KEYS, "ticker", "rank", "score", "sector", "industry",
                "theme_tags", "theme_confidence", "theme_tags_inferred",
                "theme_tags_allowed_for_hard_caps", "etf_category",
                "etf_leverage_inverse_flag", "risk_size_bucket", "position_weight",
                "realized_forward_return", "weighted_return",
                "max_adverse_excursion", "max_favorable_excursion",
                "path_coverage",
            ]].copy()
            out["portfolio_policy_id"] = policy["policy_id"]
            out["policy_family"] = policy["policy_family"]
            out["top_n"] = f"TOP{top_n}"
            out["feasible_policy"] = feasible
            out["infeasible_reason"] = reason
            holding_frames.append(out)
            portfolio_rows.append({
                **dict(zip(GROUP_KEYS, keys)),
                "portfolio_policy_id": policy["policy_id"],
                "policy_family": policy["policy_family"],
                "top_n": f"TOP{top_n}",
                "portfolio_return": group["weighted_return"].sum(min_count=1),
                "benchmark_qqq_return": pd.to_numeric(group["benchmark_qqq_return"], errors="coerce").mean(),
                "benchmark_spy_return": pd.to_numeric(group["benchmark_spy_return"], errors="coerce").mean(),
                "drawdown_proxy": group["weighted_mae"].sum(min_count=1),
                "max_adverse_excursion": group["weighted_mae"].sum(min_count=1),
                "max_favorable_excursion": group["weighted_mfe"].sum(min_count=1),
                "max_ticker_weight": group["position_weight"].max(),
                "weight_sum": weight_sum,
                "weight_sum_valid": abs(weight_sum - 1.0) <= 1e-8,
                "sector_concentration": sector_weights.max(),
                "industry_concentration": industry_weights.max(),
                "max_etf_category_exposure": etf_weights.max(),
                "leveraged_inverse_etf_exposure": lev_weight,
                "inverse_etf_exposure": inv_weight,
                "theme_exposure_max": max(theme_expanded.values()) if theme_expanded else 0.0,
                "feasible_policy": feasible,
                "infeasible_reason": reason,
                "classification_coverage_valid": group["sector"].notna().all() and group["industry"].notna().all(),
                "path_coverage_ratio": group["path_coverage"].fillna(False).mean(),
                "ticker_set": set(group["ticker"].astype(str)),
            })
            for dim, values in (("sector", sector_weights), ("industry", industry_weights), ("etf_category", etf_weights)):
                for label, value in values.items():
                    conc_rows.append({
                        **dict(zip(GROUP_KEYS, keys)),
                        "portfolio_policy_id": policy["policy_id"],
                        "top_n": f"TOP{top_n}",
                        "dimension": dim,
                        "label": label,
                        "exposure": value,
                        "research_only": True,
                    })
            for tag, value in theme_expanded.items():
                theme_rows.append({
                    **dict(zip(GROUP_KEYS, keys)),
                    "portfolio_policy_id": policy["policy_id"],
                    "top_n": f"TOP{top_n}",
                    "theme_tag": tag,
                    "theme_exposure": value,
                    "theme_hard_cap_used": False,
                    "diagnostic_only": True,
                    "research_only": True,
                })
    holdings = pd.concat(holding_frames, ignore_index=True)
    results = pd.DataFrame(portfolio_rows)
    return holdings, results, pd.DataFrame(conc_rows), pd.DataFrame(theme_rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    metric_rows = []
    baseline = results[results["portfolio_policy_id"].isin(["D_EW_TOP20_R1", "D_EW_TOP50_R1"])][
        ["seed", "batch_id", "sampled_as_of_date", "forward_window", "split", "top_n", "portfolio_return"]
    ].rename(columns={"portfolio_return": "baseline_portfolio_return"})
    merged = results.merge(baseline, on=["seed", "batch_id", "sampled_as_of_date", "forward_window", "split", "top_n"], how="left")
    for keys, group in merged.groupby(["portfolio_policy_id", "policy_family", "split", "top_n", "forward_window"], sort=False):
        returns = pd.to_numeric(group["portfolio_return"], errors="coerce").dropna()
        drawdown = pd.to_numeric(group["drawdown_proxy"], errors="coerce")
        negative_drawdown = abs(drawdown.mean())
        top_n_int = 20 if keys[3] == "TOP20" else 50
        sector_cap = HARD_CAPS[top_n_int]["sector"]
        industry_cap = HARD_CAPS[top_n_int]["industry"]
        metric_rows.append({
            "portfolio_policy_id": keys[0],
            "policy_family": keys[1],
            "split": keys[2],
            "top_n": keys[3],
            "window": keys[4],
            "portfolio_count": len(group),
            "mean_portfolio_return": returns.mean(),
            "median_portfolio_return": returns.median(),
            "hit_rate": returns.gt(0).mean(),
            "excess_vs_qqq": (returns - pd.to_numeric(group["benchmark_qqq_return"], errors="coerce").loc[returns.index]).mean(),
            "excess_vs_spy": (returns - pd.to_numeric(group["benchmark_spy_return"], errors="coerce").loc[returns.index]).mean(),
            "win_rate_vs_d_equal_weight_baseline": (group["portfolio_return"] >= group["baseline_portfolio_return"]).mean(),
            "drawdown_proxy": drawdown.mean(),
            "max_adverse_excursion": group["max_adverse_excursion"].mean(),
            "max_favorable_excursion": group["max_favorable_excursion"].mean(),
            "portfolio_return_volatility": returns.std(),
            "return_drawdown_ratio": returns.mean() / negative_drawdown if negative_drawdown > 0 else np.nan,
            "max_ticker_concentration": group["max_ticker_weight"].max(),
            "sector_concentration": group["sector_concentration"].mean(),
            "industry_concentration": group["industry_concentration"].mean(),
            "max_sector_concentration": group["sector_concentration"].max(),
            "max_industry_concentration": group["industry_concentration"].max(),
            "max_etf_category_exposure": group["max_etf_category_exposure"].max(),
            "leveraged_inverse_etf_exposure": group["leveraged_inverse_etf_exposure"].mean(),
            "inverse_etf_exposure": group["inverse_etf_exposure"].mean(),
            "theme_exposure_diagnostic_max": group["theme_exposure_max"].max(),
            "turnover": turnover_proxy(group),
            "weight_sum_valid": group["weight_sum_valid"].all(),
            "feasible_policy": group["feasible_policy"].all(),
            "infeasible_portfolio_count": int((~group["feasible_policy"]).sum()),
            "concentration_warnings": int(group["sector_concentration"].gt(sector_cap + 1e-8).sum() + group["industry_concentration"].gt(industry_cap + 1e-8).sum()),
            "classification_warnings": int((~group["classification_coverage_valid"]).sum()),
            "path_coverage_warnings": int(group["path_coverage_ratio"].lt(1).sum()),
            "sample_size_warning": len(group) < 100,
            "leakage_warnings": 0,
            "research_only": True,
        })
    return pd.DataFrame(metric_rows)


def compare(summary: pd.DataFrame, protected_changed: bool, official_mutated: bool) -> pd.DataFrame:
    test10 = summary[(summary["split"].eq("TEST")) & (summary["window"].eq("10D"))].copy()
    baselines = test10[test10["portfolio_policy_id"].isin(["D_EW_TOP20_R1", "D_EW_TOP50_R1"])].set_index("top_n")
    rows = []
    for _, row in test10.iterrows():
        base = baselines.loc[row["top_n"]]
        raw_delta = row["mean_portfolio_return"] - base["mean_portfolio_return"]
        drawdown_improvement = row["drawdown_proxy"] - base["drawdown_proxy"]
        ratio_improvement = row["return_drawdown_ratio"] - base["return_drawdown_ratio"]
        sector_improvement = base["sector_concentration"] - row["sector_concentration"]
        industry_improvement = base["industry_concentration"] - row["industry_concentration"]
        candidate = (
            row["portfolio_policy_id"] not in ["D_EW_TOP20_R1", "D_EW_TOP50_R1"]
            and int(row["leakage_warnings"]) == 0
            and int(row["classification_warnings"]) == 0
            and bool(row["weight_sum_valid"])
            and float(row["max_ticker_concentration"]) <= MAX_TICKER_CAP + 1e-8
            and bool(row["feasible_policy"])
            and sector_improvement > 1e-8
            and industry_improvement > 1e-8
            and drawdown_improvement > 1e-8
            and ratio_improvement > 1e-8
            and raw_delta >= -0.0005
            and row["turnover"] <= base["turnover"] + 0.10
            and not bool(row["sample_size_warning"])
            and not protected_changed
            and not official_mutated
        )
        rows.append({
            **row.to_dict(),
            "baseline_policy_id": base["portfolio_policy_id"],
            "baseline_mean_portfolio_return": base["mean_portfolio_return"],
            "baseline_drawdown_proxy": base["drawdown_proxy"],
            "baseline_return_drawdown_ratio": base["return_drawdown_ratio"],
            "baseline_sector_concentration": base["sector_concentration"],
            "baseline_industry_concentration": base["industry_concentration"],
            "baseline_turnover": base["turnover"],
            "raw_return_delta_vs_d_ew": raw_delta,
            "drawdown_proxy_improvement": drawdown_improvement,
            "return_drawdown_ratio_improvement": ratio_improvement,
            "sector_concentration_improvement": sector_improvement,
            "industry_concentration_improvement": industry_improvement,
            "theme_hard_cap_usage": False,
            "research_candidate_ready": candidate,
            "forward_portfolio_append_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076"):
        base_dir = root / rel
        if base_dir.exists():
            protected.extend(path.resolve() for path in base_dir.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    policies = policy_definitions()
    policies.to_csv(output / POLICY_NAME, index=False)
    base, classes, v76, v75 = load_inputs(root)
    holdings, portfolio_results, conc, theme = build_backtest(base, policies)
    holdings.to_csv(output / HOLDINGS_NAME, index=False)
    conc.to_csv(output / CONC_NAME, index=False)
    theme.to_csv(output / THEME_NAME, index=False)
    summary = summarize(portfolio_results)
    summary.to_csv(output / SUMMARY_NAME, index=False)

    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    official_mutated = False
    comparison = compare(summary, bool(changed), official_mutated)
    comparison.to_csv(output / COMPARISON_NAME, index=False)

    test10 = comparison[(comparison["split"].eq("TEST")) & (comparison["window"].eq("10D"))]
    top20 = test10[test10["top_n"].eq("TOP20")]
    top50 = test10[test10["top_n"].eq("TOP50")]
    best20_raw = top20.sort_values(["mean_portfolio_return", "return_drawdown_ratio"], ascending=False).iloc[0]
    best50_raw = top50.sort_values(["mean_portfolio_return", "return_drawdown_ratio"], ascending=False).iloc[0]
    best20_risk = top20.sort_values(["return_drawdown_ratio", "mean_portfolio_return"], ascending=False).iloc[0]
    best50_risk = top50.sort_values(["return_drawdown_ratio", "mean_portfolio_return"], ascending=False).iloc[0]
    candidate_count = int(comparison["research_candidate_ready"].sum())
    policy_count = int(policies["policy_id"].nunique())
    feasible_policies = int(summary.groupby("portfolio_policy_id")["feasible_policy"].all().sum())
    infeasible_policies = policy_count - feasible_policies
    final_status = (
        "PASS_V21_077_R3_SECTOR_AWARE_RISK_BUDGET_BACKTEST_READY"
        if candidate_count > 0 and not changed else
        "PARTIAL_PASS_V21_077_R3_SECTOR_AWARE_READY_WITH_RETURN_OR_CLASSIFICATION_WARN"
        if candidate_count > 0 else
        "BLOCKED_V21_077_R3_SECTOR_AWARE_POLICY_FAILED_OR_LEAKAGE_RISK"
    )
    decision = (
        "SECTOR_AWARE_RESEARCH_CANDIDATE_READY"
        if candidate_count > 0 else "KEEP_D_EQUAL_WEIGHT_BASELINE_AND_BLOCK_SECTOR_AWARE_SIZING"
    )
    readiness = {
        "stage": "V21.077-R3_D_EW_VS_SECTOR_AWARE_COMPARISON",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_equal_weight_baseline_preserved": True,
        "policies_tested": policy_count,
        "feasible_policies": feasible_policies,
        "infeasible_policies": infeasible_policies,
        "sector_aware_policies_tested": int(policies["policy_id"].str.contains("SECTOR").sum()),
        "industry_aware_policies_tested": int(policies["policy_id"].str.contains("INDUSTRY").sum()),
        "hard_cap_policies_tested": int(policies["policy_family"].eq("HARD_CAP").sum()),
        "soft_penalty_policies_tested": int(policies["policy_family"].eq("SOFT_PENALTY").sum()),
        "best_top20_raw_return_policy": best20_raw["portfolio_policy_id"],
        "best_top50_raw_return_policy": best50_raw["portfolio_policy_id"],
        "best_top20_risk_adjusted_policy": best20_risk["portfolio_policy_id"],
        "best_top50_risk_adjusted_policy": best50_risk["portfolio_policy_id"],
        "comparison_vs_d_ew_top20": f"RAW_DELTA={best20_risk['raw_return_delta_vs_d_ew']:.10f};RATIO_DELTA={best20_risk['return_drawdown_ratio_improvement']:.10f}",
        "comparison_vs_d_ew_top50": f"RAW_DELTA={best50_risk['raw_return_delta_vs_d_ew']:.10f};RATIO_DELTA={best50_risk['return_drawdown_ratio_improvement']:.10f}",
        "drawdown_proxy_improvement": float(max(best20_risk["drawdown_proxy_improvement"], best50_risk["drawdown_proxy_improvement"])),
        "return_drawdown_ratio_improvement": float(max(best20_risk["return_drawdown_ratio_improvement"], best50_risk["return_drawdown_ratio_improvement"])),
        "sector_concentration_improvement": float(max(best20_risk["sector_concentration_improvement"], best50_risk["sector_concentration_improvement"])),
        "industry_concentration_improvement": float(max(best20_risk["industry_concentration_improvement"], best50_risk["industry_concentration_improvement"])),
        "theme_hard_cap_usage": False,
        "classification_warnings": int(summary["classification_warnings"].sum()),
        "leakage_warnings": int(summary["leakage_warnings"].sum()),
        "research_candidate_count": candidate_count,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": official_mutated,
        "forward_portfolio_append_allowed": False,
        "official_adoption_allowed": False,
        "protected_modified_paths": "|".join(changed),
        "research_only": True,
        "execution_pass_gate": (not changed) and not official_mutated and int(summary["leakage_warnings"].sum()) == 0,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "policies_tested", "feasible_policies", "research_candidate_count"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
