#!/usr/bin/env python
"""Research-only V21.068-R1 weight perturbation backtest harness."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STAGE = "V21.068-R1_WEIGHT_PERTURBATION_BACKTEST_HARNESS"
OUT_REL = Path("outputs/v21/weight_perturbation")
R3_VALIDATION_NAME = "V21_067_R3_VALIDATION_SUMMARY.csv"
UNIVERSE_NAME = "V21_068_R1_PERTURBATION_UNIVERSE.csv"
GRID_NAME = "V21_068_R1_WEIGHT_PERTURBATION_GRID.csv"
RANKINGS_NAME = "V21_068_R1_PERTURBATION_RANKINGS.csv"
METRICS_NAME = "V21_068_R1_PERTURBATION_EVALUATION_METRICS.csv"
PAIRWISE_NAME = "V21_068_R1_PAIRWISE_VS_CURRENT_D.csv"
RECOMMENDATION_NAME = "V21_068_R1_WEIGHT_CANDIDATE_RECOMMENDATION.csv"
VALIDATION_NAME = "V21_068_R1_VALIDATION_SUMMARY.csv"
EVAL_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/random_backtests/weight_search/"
    "V21_060_R4_WEIGHT_GRID_ROW_LEVEL_RESULTS.csv"
)

PERTURBATIONS = [
    ("P00_CURRENT_D", 0.60, 0.40, True),
    ("P01_BASE_075_MOM_025", 0.75, 0.25, False),
    ("P02_BASE_070_MOM_030", 0.70, 0.30, False),
    ("P03_BASE_065_MOM_035", 0.65, 0.35, False),
    ("P04_BASE_060_MOM_040", 0.60, 0.40, False),
    ("P05_BASE_055_MOM_045", 0.55, 0.45, False),
    ("P06_BASE_050_MOM_050", 0.50, 0.50, False),
    ("P07_BASE_045_MOM_055", 0.45, 0.55, False),
]
WINDOWS = ("5D", "10D", "20D")
BUCKETS = ("TOP20", "TOP50", "ALL_ELIGIBLE")

UNIVERSE_COLUMNS = [
    "run_id", "generated_at_utc", "source_ranking_path",
    "source_ranking_hash", "ticker", "original_rank",
    "original_final_score", "eligible_flag", "exclusion_reason",
    "base_score_raw", "momentum_score_raw", "base_contribution",
    "momentum_contribution", "fundamental_score_raw", "technical_score_raw",
    "strategy_score_raw", "risk_score_raw", "market_regime_score_raw",
    "data_trust_score_raw", "technical__rsi", "technical__kdj",
    "technical__macd", "technical__bb", "technical__ma20",
    "technical__ma50", "technical__ema", "technical__volume",
    "technical__volatility", "technical__relative_strength",
    "technical__breakout", "technical__pullback", "risk__overheat",
    "regime__qqq_ma50_state", "risk__liquidity_penalty",
    "liquidity_percentile_0_1", "liquidity_warning_flag",
    "diagnostic_component_not_in_original_score_flag",
    "explainability_status_r3",
]
GRID_COLUMNS = [
    "run_id", "perturbation_id", "perturbation_type", "base_weight",
    "momentum_weight", "fundamental_weight_delta", "technical_weight_delta",
    "strategy_weight_delta", "risk_weight_delta",
    "market_regime_weight_delta", "data_trust_weight_delta",
    "technical_subfactor_delta_map", "diagnostic_qqq_ma50_used_in_score",
    "diagnostic_liquidity_used_in_score", "normalized_weight_sum",
    "is_current_d", "research_only", "warning",
]
RANKING_COLUMNS = [
    "run_id", "perturbation_id", "ticker", "original_rank",
    "original_final_score", "perturbation_score", "perturbation_rank",
    "rank_delta_vs_current_d", "score_delta_vs_current_d", "eligible_flag",
    "exclusion_reason", "base_weight", "momentum_weight",
    "base_component_used", "momentum_component_used",
    "family_component_used", "technical_subfactor_component_used",
    "reconstruction_status", "diagnostic_qqq_ma50_state",
    "diagnostic_liquidity_penalty", "diagnostic_low_liquidity_warning",
    "overheat_warning", "bb_extension_warning", "warning",
]
METRIC_COLUMNS = [
    "run_id", "perturbation_id", "perturbation_type",
    "evaluation_source_path", "evaluation_source_hash", "evaluation_mode",
    "forward_maturity_status", "top_n", "window", "observation_count",
    "mean_return", "median_return", "hit_rate", "excess_vs_qqq",
    "excess_vs_spy", "excess_vs_soxx", "excess_vs_current_d", "rank_ic",
    "decile_spread", "turnover_vs_current_d", "top_n_overlap_vs_current_d",
    "avg_rank_delta_vs_current_d", "max_rank_delta_vs_current_d",
    "sector_concentration_proxy", "momentum_led_ratio", "base_led_ratio",
    "overheat_warning_ratio", "bb_extension_warning_ratio",
    "low_liquidity_warning_ratio", "qqq_ma50_supportive_ratio",
    "risk_warning_ratio", "data_trust_warning_ratio",
    "evaluation_quality", "warning",
]
PAIRWISE_COLUMNS = [
    "run_id", "perturbation_id", "compared_to", "top_n", "window",
    "observation_count", "perturbation_mean_return", "current_d_mean_return",
    "mean_return_delta", "perturbation_median_return",
    "current_d_median_return", "median_return_delta",
    "perturbation_hit_rate", "current_d_hit_rate", "hit_rate_delta",
    "perturbation_excess_vs_qqq", "current_d_excess_vs_qqq",
    "excess_vs_qqq_delta", "turnover_vs_current_d",
    "top_n_overlap_vs_current_d", "concentration_delta",
    "risk_warning_delta", "low_liquidity_warning_delta",
    "overheat_warning_delta", "result_classification",
    "adoption_candidate_flag", "warning",
]
RECOMMENDATION_COLUMNS = [
    "run_id", "perturbation_id", "recommendation_rank",
    "recommendation_status", "base_weight", "momentum_weight",
    "evidence_score", "return_score", "stability_score", "risk_score",
    "concentration_score", "maturity_score", "turnover_penalty",
    "overfit_warning", "recommended_action", "reason", "adoption_allowed",
    "shadow_forward_allowed", "official_adoption_allowed",
]


def utc_now() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def discover_r3(root: Path, override: Path | None = None) -> tuple[Path, pd.Series, Path, Path]:
    candidates = (
        [override if override and override.is_absolute() else root / override]
        if override else
        sorted(
            (root / "outputs/v21/explainability").rglob(R3_VALIDATION_NAME),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )
    for path in candidates:
        try:
            row = pd.read_csv(path).iloc[0]
        except (OSError, ValueError, IndexError):
            continue
        if not str(row.get("final_status", "")).startswith(("PASS_", "PARTIAL_PASS_")):
            continue
        if not truth(row.get("source_ranking_hash_verified")) or not truth(row.get("research_only")):
            continue
        if truth(row.get("official_mutation")) or truth(row.get("protected_outputs_modified")):
            continue
        ledger = root / str(row.get("repaired_ledger_path", ""))
        source = root / str(row.get("source_ranking_path", ""))
        if ledger.is_file() and source.is_file():
            return path.resolve(), row, ledger.resolve(), source.resolve()
    raise FileNotFoundError("Valid V21.067-R3 artifacts not found")


def protected_files(root: Path, output_dir: Path, explicit: list[Path]) -> list[Path]:
    paths = {path.resolve() for path in explicit if path.is_file()}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output_dir.resolve() in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if any(token in text for token in (
                "official", "broker", "protected", "forward_observation_ledger",
                "066a_d_latest_ranking", "060_r5_d_weight_optimized_ranking",
            )):
                paths.add(path.resolve())
    return sorted(paths)


def snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path): sha256(path) for path in paths if path.is_file()}


def universe_frame(
    ledger: pd.DataFrame, run_id: str, generated_at: str,
    source_path: str, source_hash: str,
) -> pd.DataFrame:
    aliases = {
        "original_rank": "rank",
        "original_final_score": "final_score",
        "fundamental_score_raw": "repaired_fundamental_score_raw",
        "technical_score_raw": "repaired_technical_score_raw",
        "strategy_score_raw": "repaired_strategy_score_raw",
        "risk_score_raw": "repaired_risk_score_raw",
        "market_regime_score_raw": "repaired_market_regime_score_raw",
        "data_trust_score_raw": "repaired_data_trust_score_raw",
    }
    output = pd.DataFrame(index=ledger.index)
    output["run_id"] = run_id
    output["generated_at_utc"] = generated_at
    output["source_ranking_path"] = source_path
    output["source_ranking_hash"] = source_hash
    for column in UNIVERSE_COLUMNS:
        if column in output:
            continue
        source = aliases.get(column, column)
        output[column] = ledger[source] if source in ledger else pd.NA
    return output.reindex(columns=UNIVERSE_COLUMNS)


def grid_frame(run_id: str) -> pd.DataFrame:
    rows = []
    for perturbation_id, base, momentum, current in PERTURBATIONS:
        rows.append({
            "run_id": run_id, "perturbation_id": perturbation_id,
            "perturbation_type": "BASE_MOMENTUM_WEIGHT_GRID",
            "base_weight": base, "momentum_weight": momentum,
            "fundamental_weight_delta": 0, "technical_weight_delta": 0,
            "strategy_weight_delta": 0, "risk_weight_delta": 0,
            "market_regime_weight_delta": 0, "data_trust_weight_delta": 0,
            "technical_subfactor_delta_map": "",
            "diagnostic_qqq_ma50_used_in_score": False,
            "diagnostic_liquidity_used_in_score": False,
            "normalized_weight_sum": base + momentum,
            "is_current_d": current, "research_only": True,
            "warning": "QQQ_MA50_AND_LIQUIDITY_DIAGNOSTIC_ONLY",
        })
    return pd.DataFrame(rows).reindex(columns=GRID_COLUMNS)


def rank_perturbations(universe: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = pd.to_numeric(universe["base_score_raw"], errors="coerce")
    momentum = pd.to_numeric(universe["momentum_score_raw"], errors="coerce")
    original_score = pd.to_numeric(universe["original_final_score"], errors="coerce")
    original_rank = pd.to_numeric(universe["original_rank"], errors="coerce")
    eligible = universe["eligible_flag"].map(truth)
    for _, perturbation in grid.iterrows():
        score = base * float(perturbation["base_weight"]) + momentum * float(perturbation["momentum_weight"])
        score = score.where(eligible)
        rank = score.rank(method="first", ascending=False)
        frame = pd.DataFrame({
            "run_id": universe["run_id"],
            "perturbation_id": perturbation["perturbation_id"],
            "ticker": universe["ticker"], "original_rank": original_rank,
            "original_final_score": original_score, "perturbation_score": score,
            "perturbation_rank": rank,
            "rank_delta_vs_current_d": original_rank - rank,
            "score_delta_vs_current_d": score - original_score,
            "eligible_flag": universe["eligible_flag"],
            "exclusion_reason": universe["exclusion_reason"],
            "base_weight": perturbation["base_weight"],
            "momentum_weight": perturbation["momentum_weight"],
            "base_component_used": base * float(perturbation["base_weight"]),
            "momentum_component_used": momentum * float(perturbation["momentum_weight"]),
            "family_component_used": False,
            "technical_subfactor_component_used": False,
            "reconstruction_status": np.where(
                perturbation["perturbation_id"] == "P00_CURRENT_D",
                np.where((score - original_score).abs() <= 1e-8, "PASS", "WARN"),
                "NOT_CONTROL",
            ),
            "diagnostic_qqq_ma50_state": universe["regime__qqq_ma50_state"],
            "diagnostic_liquidity_penalty": universe["risk__liquidity_penalty"],
            "diagnostic_low_liquidity_warning": universe["liquidity_warning_flag"],
            "overheat_warning": universe["risk__overheat"],
            "bb_extension_warning": pd.to_numeric(universe["technical__bb"], errors="coerce").ge(1),
            "warning": "RAW_D_BASE_MOMENTUM_SCORE_CONVENTION;DIAGNOSTICS_EXCLUDED_FROM_SCORE",
        })
        rows.append(frame)
    return pd.concat(rows, ignore_index=True).reindex(columns=RANKING_COLUMNS)


def load_evaluation(path: Path, source_date: str) -> tuple[pd.DataFrame, str | None]:
    required = [
        "batch_id", "sampled_as_of_date", "momentum_weight", "top_n_bucket",
        "forward_window", "ticker", "rank", "score", "base_score",
        "momentum_score", "net_position_return", "benchmark_spy_return",
        "benchmark_qqq_return", "benchmark_smh_return", "point_in_time_valid",
        "research_only",
    ]
    chunks = []
    for chunk in pd.read_csv(path, usecols=lambda column: column in required, chunksize=250000, low_memory=False):
        if not set(required).issubset(chunk.columns):
            return pd.DataFrame(), "EVALUATION_SCHEMA_MISSING"
        weight = pd.to_numeric(chunk["momentum_weight"], errors="coerce")
        keep = (
            weight.isin([0.25, 0.30, 0.35, 0.40])
            & chunk["forward_window"].astype(str).isin(WINDOWS)
            & chunk["top_n_bucket"].astype(str).isin(("TOP20", "TOP50"))
            & chunk["point_in_time_valid"].map(truth)
            & chunk["research_only"].map(truth)
        )
        filtered = chunk[keep].copy()
        if not filtered.empty:
            chunks.append(filtered)
    if not chunks:
        return pd.DataFrame(), "NO_USABLE_EVALUATION_ROWS"
    frame = pd.concat(chunks, ignore_index=True)
    dates = pd.to_datetime(frame["sampled_as_of_date"], errors="coerce", utc=True)
    source_ts = pd.Timestamp(source_date, tz="UTC")
    if dates.notna().any() and (dates > source_ts).all():
        return pd.DataFrame(), "FUTURE_DATED_EVALUATION_LABELS"
    frame = frame[dates.isna() | (dates <= source_ts)].copy()
    return frame, None


def safe_corr(left: pd.Series, right: pd.Series) -> float:
    joined = pd.concat([pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")], axis=1).dropna()
    if len(joined) <= 2:
        return np.nan
    left_rank = joined.iloc[:, 0].rank(method="average")
    right_rank = joined.iloc[:, 1].rank(method="average")
    return float(left_rank.corr(right_rank))


def evaluate(
    run_id: str, grid: pd.DataFrame, current_rankings: pd.DataFrame,
    evaluation: pd.DataFrame, evaluation_path: Path | None, root: Path,
) -> pd.DataFrame:
    source_hash = sha256(evaluation_path) if evaluation_path and evaluation_path.is_file() else ""
    source_rel = rel(root, evaluation_path) if evaluation_path else ""
    weight_map = dict(zip(grid["perturbation_id"], grid["momentum_weight"]))
    current_weight = 0.40
    current_universe = current_rankings[current_rankings["perturbation_id"] == "P00_CURRENT_D"]
    rows = []
    for perturbation_id, momentum_weight in weight_map.items():
        for bucket in BUCKETS:
            for window in WINDOWS:
                subset = evaluation[
                    np.isclose(pd.to_numeric(evaluation.get("momentum_weight"), errors="coerce"), momentum_weight)
                    & evaluation.get("forward_window", pd.Series(dtype=str)).astype(str).eq(window)
                    & evaluation.get("top_n_bucket", pd.Series(dtype=str)).astype(str).eq(bucket)
                ] if not evaluation.empty and bucket != "ALL_ELIGIBLE" else pd.DataFrame()
                current = evaluation[
                    np.isclose(pd.to_numeric(evaluation.get("momentum_weight"), errors="coerce"), current_weight)
                    & evaluation.get("forward_window", pd.Series(dtype=str)).astype(str).eq(window)
                    & evaluation.get("top_n_bucket", pd.Series(dtype=str)).astype(str).eq(bucket)
                ] if not evaluation.empty and bucket != "ALL_ELIGIBLE" else pd.DataFrame()
                returns = pd.to_numeric(subset.get("net_position_return"), errors="coerce")
                qqq = pd.to_numeric(subset.get("benchmark_qqq_return"), errors="coerce")
                spy = pd.to_numeric(subset.get("benchmark_spy_return"), errors="coerce")
                soxx = pd.to_numeric(subset.get("benchmark_smh_return"), errors="coerce")
                current_returns = pd.to_numeric(current.get("net_position_return"), errors="coerce")
                observed = int(returns.notna().sum()) if isinstance(returns, pd.Series) else 0
                selected_now = current_rankings[
                    (current_rankings["perturbation_id"] == perturbation_id)
                    & current_rankings["eligible_flag"].map(truth)
                ]
                cutoff = 20 if bucket == "TOP20" else 50 if bucket == "TOP50" else len(selected_now)
                selected_now = selected_now.nsmallest(cutoff, "perturbation_rank")
                current_now = current_universe[current_universe["eligible_flag"].map(truth)].nsmallest(cutoff, "perturbation_rank")
                overlap = len(set(selected_now["ticker"]) & set(current_now["ticker"])) / max(cutoff, 1)
                rank_delta = pd.to_numeric(selected_now["rank_delta_vs_current_d"], errors="coerce").abs()
                rows.append({
                    "run_id": run_id, "perturbation_id": perturbation_id,
                    "perturbation_type": "BASE_MOMENTUM_WEIGHT_GRID",
                    "evaluation_source_path": source_rel,
                    "evaluation_source_hash": source_hash,
                    "evaluation_mode": "RANDOM_ASOF_PIT_VALIDATION_WEIGHT_GRID" if observed else "CURRENT_UNIVERSE_DIAGNOSTICS_ONLY",
                    "forward_maturity_status": "CURRENT_D_FORWARD_PENDING_BACKTEST_AVAILABLE" if observed else "INSUFFICIENT_WEIGHT_MATCHED_EVIDENCE",
                    "top_n": bucket, "window": window, "observation_count": observed,
                    "mean_return": returns.mean() if observed else np.nan,
                    "median_return": returns.median() if observed else np.nan,
                    "hit_rate": (returns > 0).mean() if observed else np.nan,
                    "excess_vs_qqq": (returns - qqq).mean() if observed else np.nan,
                    "excess_vs_spy": (returns - spy).mean() if observed else np.nan,
                    "excess_vs_soxx": (returns - soxx).mean() if observed else np.nan,
                    "excess_vs_current_d": returns.mean() - current_returns.mean() if observed and current_returns.notna().any() else np.nan,
                    "rank_ic": safe_corr(subset.get("score", pd.Series(dtype=float)), returns) if observed else np.nan,
                    "decile_spread": np.nan,
                    "turnover_vs_current_d": 1 - overlap,
                    "top_n_overlap_vs_current_d": overlap,
                    "avg_rank_delta_vs_current_d": rank_delta.mean(),
                    "max_rank_delta_vs_current_d": rank_delta.max(),
                    "sector_concentration_proxy": np.nan,
                    "momentum_led_ratio": (
                        pd.to_numeric(selected_now["momentum_component_used"], errors="coerce")
                        >= pd.to_numeric(selected_now["base_component_used"], errors="coerce")
                    ).mean(),
                    "base_led_ratio": (
                        pd.to_numeric(selected_now["base_component_used"], errors="coerce")
                        > pd.to_numeric(selected_now["momentum_component_used"], errors="coerce")
                    ).mean(),
                    "overheat_warning_ratio": selected_now["overheat_warning"].map(truth).mean(),
                    "bb_extension_warning_ratio": selected_now["bb_extension_warning"].map(truth).mean(),
                    "low_liquidity_warning_ratio": selected_now["diagnostic_low_liquidity_warning"].map(truth).mean(),
                    "qqq_ma50_supportive_ratio": selected_now["diagnostic_qqq_ma50_state"].astype(str).str.contains("ABOVE|RISK_ON", case=False, regex=True).mean(),
                    "risk_warning_ratio": selected_now["overheat_warning"].map(truth).mean(),
                    "data_trust_warning_ratio": np.nan,
                    "evaluation_quality": "HIGH_RANDOM_ASOF_VALIDATION" if observed else "INSUFFICIENT_EVIDENCE",
                    "warning": "" if observed else "NO_MATCHED_BACKTEST_WEIGHT_OR_ALL_ELIGIBLE_LABELS",
                })
    return pd.DataFrame(rows).reindex(columns=METRIC_COLUMNS)


def pairwise(run_id: str, metrics: pd.DataFrame) -> pd.DataFrame:
    current = metrics[metrics["perturbation_id"] == "P00_CURRENT_D"].set_index(["top_n", "window"])
    rows = []
    for _, row in metrics.iterrows():
        control = current.loc[(row["top_n"], row["window"])]
        observed = int(row["observation_count"])
        mean_delta = row["mean_return"] - control["mean_return"] if observed else np.nan
        median_delta = row["median_return"] - control["median_return"] if observed else np.nan
        hit_delta = row["hit_rate"] - control["hit_rate"] if observed else np.nan
        qqq_delta = row["excess_vs_qqq"] - control["excess_vs_qqq"] if observed else np.nan
        risk_delta = row["risk_warning_ratio"] - control["risk_warning_ratio"]
        if not observed:
            classification = "INSUFFICIENT_EVIDENCE"
        elif mean_delta > 0 and median_delta >= 0 and hit_delta >= 0 and risk_delta <= 0.05:
            classification = "IMPROVES_RETURN_AND_STABILITY"
        elif mean_delta > 0:
            classification = "IMPROVES_RETURN_BUT_RISKIER"
        elif mean_delta >= -1e-12 and row["turnover_vs_current_d"] <= 0.10:
            classification = "STABLE_BUT_NO_RETURN_IMPROVEMENT"
        else:
            classification = "WORSE_THAN_CURRENT_D"
        rows.append({
            "run_id": run_id, "perturbation_id": row["perturbation_id"],
            "compared_to": "P00_CURRENT_D", "top_n": row["top_n"],
            "window": row["window"], "observation_count": observed,
            "perturbation_mean_return": row["mean_return"],
            "current_d_mean_return": control["mean_return"],
            "mean_return_delta": mean_delta,
            "perturbation_median_return": row["median_return"],
            "current_d_median_return": control["median_return"],
            "median_return_delta": median_delta,
            "perturbation_hit_rate": row["hit_rate"],
            "current_d_hit_rate": control["hit_rate"], "hit_rate_delta": hit_delta,
            "perturbation_excess_vs_qqq": row["excess_vs_qqq"],
            "current_d_excess_vs_qqq": control["excess_vs_qqq"],
            "excess_vs_qqq_delta": qqq_delta,
            "turnover_vs_current_d": row["turnover_vs_current_d"],
            "top_n_overlap_vs_current_d": row["top_n_overlap_vs_current_d"],
            "concentration_delta": np.nan, "risk_warning_delta": risk_delta,
            "low_liquidity_warning_delta": row["low_liquidity_warning_ratio"] - control["low_liquidity_warning_ratio"],
            "overheat_warning_delta": row["overheat_warning_ratio"] - control["overheat_warning_ratio"],
            "result_classification": classification,
            "adoption_candidate_flag": False,
            "warning": "RESEARCH_ONLY_NO_ADOPTION",
        })
    return pd.DataFrame(rows).reindex(columns=PAIRWISE_COLUMNS)


def recommendations(run_id: str, grid: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, perturbation in grid.iterrows():
        subset = pairs[
            (pairs["perturbation_id"] == perturbation["perturbation_id"])
            & pairs["top_n"].isin(("TOP20", "TOP50"))
        ]
        sufficient = subset["observation_count"].gt(0)
        improved = subset["result_classification"].eq("IMPROVES_RETURN_AND_STABILITY").sum()
        return_score = pd.to_numeric(subset["mean_return_delta"], errors="coerce").mean()
        stability = pd.to_numeric(subset["top_n_overlap_vs_current_d"], errors="coerce").mean()
        risk = -pd.to_numeric(subset["risk_warning_delta"], errors="coerce").mean()
        turnover = pd.to_numeric(subset["turnover_vs_current_d"], errors="coerce").mean()
        evidence = sufficient.mean()
        shadow = bool(
            sufficient.all() and improved >= 2
            and (turnover if pd.notna(turnover) else 1) <= 0.25
            and pd.to_numeric(subset["risk_warning_delta"], errors="coerce").max() <= 0.05
        )
        score = (
            (return_score if pd.notna(return_score) else -1) * 100
            + (stability if pd.notna(stability) else 0)
            + (risk if pd.notna(risk) else 0)
            + evidence - (turnover if pd.notna(turnover) else 1)
        )
        rows.append({
            "run_id": run_id, "perturbation_id": perturbation["perturbation_id"],
            "recommendation_rank": 0,
            "recommendation_status": "SHADOW_FORWARD_CANDIDATE" if shadow else "INSUFFICIENT_OR_MIXED_EVIDENCE",
            "base_weight": perturbation["base_weight"],
            "momentum_weight": perturbation["momentum_weight"],
            "evidence_score": evidence, "return_score": return_score,
            "stability_score": stability, "risk_score": risk,
            "concentration_score": np.nan, "maturity_score": 0,
            "turnover_penalty": turnover,
            "overfit_warning": "RANDOM_ASOF_REUSE_REQUIRES_FRESH_SHADOW_VALIDATION",
            "recommended_action": "WAIT_FOR_MATURED_FORWARD_OR_SHADOW_ONLY",
            "reason": f"IMPROVED_RETURN_AND_STABILITY_CELLS={improved}",
            "adoption_allowed": False, "shadow_forward_allowed": shadow,
            "official_adoption_allowed": False, "_score": score,
        })
    output = pd.DataFrame(rows).sort_values(["_score", "perturbation_id"], ascending=[False, True])
    output["recommendation_rank"] = range(1, len(output) + 1)
    return output.drop(columns="_score").reindex(columns=RECOMMENDATION_COLUMNS)


def write_blocked(
    root: Path, output_dir: Path, generated_at: str, status: str,
    reason: str, paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in (
        (UNIVERSE_NAME, UNIVERSE_COLUMNS), (GRID_NAME, GRID_COLUMNS),
        (RANKINGS_NAME, RANKING_COLUMNS), (METRICS_NAME, METRIC_COLUMNS),
        (PAIRWISE_NAME, PAIRWISE_COLUMNS),
        (RECOMMENDATION_NAME, RECOMMENDATION_COLUMNS),
    ):
        target = output_dir / name
        if not target.exists():
            pd.DataFrame(columns=columns).to_csv(target, index=False)
    paths = paths or {}
    result = {
        "stage": STAGE, "final_status": status,
        "decision": "BLOCKED_REVIEW_R3_SOURCE_OR_EVALUATION_INPUTS",
        "generated_at_utc": generated_at,
        "r3_validation_path": paths.get("r3_validation", ""),
        "r3_repaired_ledger_path": paths.get("r3_ledger", ""),
        "source_ranking_path": paths.get("source", ""),
        "source_ranking_hash": paths.get("hash", ""),
        "source_ranking_hash_verified": False,
        "perturbation_universe_path": rel(root, output_dir / UNIVERSE_NAME),
        "perturbation_grid_path": rel(root, output_dir / GRID_NAME),
        "perturbation_rankings_path": rel(root, output_dir / RANKINGS_NAME),
        "perturbation_evaluation_metrics_path": rel(root, output_dir / METRICS_NAME),
        "pairwise_vs_current_d_path": rel(root, output_dir / PAIRWISE_NAME),
        "weight_candidate_recommendation_path": rel(root, output_dir / RECOMMENDATION_NAME),
        "ranking_rows": 0, "perturbation_universe_rows": 0,
        "perturbation_count": 0, "current_d_reconstruction_max_error": "",
        "current_d_reconstruction_avg_error": "",
        "evaluation_sources_found_count": 0, "matured_forward_available": False,
        "backtest_evaluation_available": False,
        "random_asof_evaluation_available": False,
        "top_candidate_perturbation_id": "",
        "top_candidate_recommendation_status": "",
        "shadow_forward_candidate_count": 0,
        "official_adoption_allowed": False, "current_d_preserved": False,
        "ranking_mutation": False, "official_mutation": False,
        "protected_outputs_modified": False, "forward_ledger_mutation": False,
        "research_only": True, "pass_gate": False,
        "validation_warning": reason,
    }
    pd.DataFrame([result]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return result


def run_stage(
    root: Path, r3_validation_override: Path | None = None,
    output_override: Path | None = None, evaluation_override: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id, generated_at = utc_now()
    try:
        r3_path, r3, ledger_path, source_path = discover_r3(root, r3_validation_override)
    except FileNotFoundError as exc:
        return write_blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_068_R1_MISSING_R3_OR_SOURCE_RANKING", str(exc),
        )
    paths = {
        "r3_validation": rel(root, r3_path), "r3_ledger": rel(root, ledger_path),
        "source": rel(root, source_path), "hash": str(r3["source_ranking_hash"]),
    }
    actual_hash = sha256(source_path)
    if actual_hash != str(r3["source_ranking_hash"]):
        return write_blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_068_R1_SOURCE_HASH_MISMATCH",
            "Source ranking SHA-256 mismatch", paths,
        )
    source = pd.read_csv(source_path, low_memory=False)
    ledger = pd.read_csv(ledger_path, low_memory=False)
    protected = protected_files(root, output_dir, [r3_path, ledger_path, source_path])
    before = snapshot(protected)
    universe = universe_frame(ledger, run_id, generated_at, rel(root, source_path), actual_hash)
    grid = grid_frame(run_id)
    rankings = rank_perturbations(universe, grid)
    universe.to_csv(output_dir / UNIVERSE_NAME, index=False)
    grid.to_csv(output_dir / GRID_NAME, index=False)
    rankings.to_csv(output_dir / RANKINGS_NAME, index=False)

    source_date = str(source["latest_price_date"].dropna().astype(str).max())[:10]
    evaluation_path = evaluation_override.resolve() if evaluation_override else (root / EVAL_REL).resolve()
    evaluation = pd.DataFrame()
    evaluation_error = "EVALUATION_SOURCE_MISSING"
    if evaluation_path.is_file():
        evaluation, evaluation_error = load_evaluation(evaluation_path, source_date)
    if evaluation_error == "FUTURE_DATED_EVALUATION_LABELS":
        return write_blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_068_R1_SCORE_RECONSTRUCTION_OR_EVALUATION_RISK",
            evaluation_error, paths,
        )
    metrics = evaluate(
        run_id, grid, rankings, evaluation,
        evaluation_path if evaluation_path.is_file() else None, root,
    )
    pairs = pairwise(run_id, metrics)
    recommendation = recommendations(run_id, grid, pairs)
    metrics.to_csv(output_dir / METRICS_NAME, index=False)
    pairs.to_csv(output_dir / PAIRWISE_NAME, index=False)
    recommendation.to_csv(output_dir / RECOMMENDATION_NAME, index=False)

    after = snapshot(protected)
    changed = [path for path, value in before.items() if after.get(path) != value]
    control = rankings[
        (rankings["perturbation_id"] == "P00_CURRENT_D")
        & rankings["eligible_flag"].map(truth)
    ]
    errors = pd.to_numeric(control["score_delta_vs_current_d"], errors="coerce").abs()
    integrity = (
        len(universe) == len(source)
        and len(rankings) == len(source) * len(grid)
        and grid["perturbation_id"].eq("P00_CURRENT_D").any()
        and errors.notna().all()
    )
    evidence_found = int(evaluation_path.is_file() and not evaluation.empty)
    top = recommendation.iloc[0]
    partial_evidence = (
        not evidence_found
        or not recommendation["shadow_forward_allowed"].map(truth).any()
        or metrics["observation_count"].eq(0).any()
    )
    pass_gate = integrity and evidence_found > 0 and not changed
    if changed:
        status = "BLOCKED_V21_068_R1_MUTATION_RISK"
        decision = "BLOCKED_REVIEW_R3_SOURCE_OR_EVALUATION_INPUTS"
    elif not integrity or not evidence_found:
        status = "BLOCKED_V21_068_R1_SCORE_RECONSTRUCTION_OR_EVALUATION_RISK"
        decision = "BLOCKED_REVIEW_R3_SOURCE_OR_EVALUATION_INPUTS"
    elif partial_evidence:
        status = "PARTIAL_PASS_V21_068_R1_WEIGHT_PERTURBATION_READY_WITH_EVIDENCE_WARNINGS"
        decision = "WEIGHT_PERTURBATION_READY_WITH_EVIDENCE_WARNINGS_RESEARCH_ONLY"
    else:
        status = "PASS_V21_068_R1_WEIGHT_PERTURBATION_BACKTEST_READY"
        decision = "WEIGHT_PERTURBATION_BACKTEST_READY_RESEARCH_ONLY"
    result = {
        "stage": STAGE, "final_status": status, "decision": decision,
        "generated_at_utc": generated_at,
        "r3_validation_path": rel(root, r3_path),
        "r3_repaired_ledger_path": rel(root, ledger_path),
        "source_ranking_path": rel(root, source_path),
        "source_ranking_hash": actual_hash, "source_ranking_hash_verified": True,
        "perturbation_universe_path": rel(root, output_dir / UNIVERSE_NAME),
        "perturbation_grid_path": rel(root, output_dir / GRID_NAME),
        "perturbation_rankings_path": rel(root, output_dir / RANKINGS_NAME),
        "perturbation_evaluation_metrics_path": rel(root, output_dir / METRICS_NAME),
        "pairwise_vs_current_d_path": rel(root, output_dir / PAIRWISE_NAME),
        "weight_candidate_recommendation_path": rel(root, output_dir / RECOMMENDATION_NAME),
        "ranking_rows": len(source), "perturbation_universe_rows": len(universe),
        "perturbation_count": len(grid),
        "current_d_reconstruction_max_error": errors.max(),
        "current_d_reconstruction_avg_error": errors.mean(),
        "evaluation_sources_found_count": evidence_found,
        "matured_forward_available": False,
        "backtest_evaluation_available": evidence_found > 0,
        "random_asof_evaluation_available": evidence_found > 0,
        "top_candidate_perturbation_id": top["perturbation_id"],
        "top_candidate_recommendation_status": top["recommendation_status"],
        "shadow_forward_candidate_count": int(recommendation["shadow_forward_allowed"].map(truth).sum()),
        "official_adoption_allowed": False, "current_d_preserved": True,
        "ranking_mutation": False, "official_mutation": False,
        "protected_outputs_modified": bool(changed),
        "forward_ledger_mutation": False, "research_only": True,
        "pass_gate": pass_gate, "protected_modified_paths": "|".join(changed),
        "evaluation_warning": evaluation_error or "CURRENT_D_FORWARD_PENDING",
    }
    pd.DataFrame([result]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--r3-validation-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--evaluation-source", type=Path)
    args = parser.parse_args()
    result = run_stage(
        args.root, args.r3_validation_path, args.output_dir, args.evaluation_source
    )
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"PERTURBATION_COUNT={result['perturbation_count']}")
    print(f"CURRENT_D_RECONSTRUCTION_MAX_ERROR={result['current_d_reconstruction_max_error']}")
    print(f"CURRENT_D_RECONSTRUCTION_AVG_ERROR={result['current_d_reconstruction_avg_error']}")
    print(f"EVALUATION_SOURCES_FOUND_COUNT={result['evaluation_sources_found_count']}")
    print(f"MATURED_FORWARD_AVAILABLE={result['matured_forward_available']}")
    print(f"TOP_CANDIDATE_PERTURBATION_ID={result['top_candidate_perturbation_id']}")
    print(f"SHADOW_FORWARD_CANDIDATE_COUNT={result['shadow_forward_candidate_count']}")
    print(f"VALIDATION_SUMMARY={(args.output_dir or OUT_REL) / VALIDATION_NAME}")
    return 1 if str(result["final_status"]).startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
