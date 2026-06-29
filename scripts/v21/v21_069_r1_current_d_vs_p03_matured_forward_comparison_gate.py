#!/usr/bin/env python
"""Maturity-gated current D versus P03 out-of-sample comparison."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STAGE = "V21.069-R1_CURRENT_D_VS_P03_MATURED_FORWARD_COMPARISON_GATE"
OUT_REL = Path("outputs/v21/forward_comparison")
VALIDATION_068 = "V21_068_R1_VALIDATION_SUMMARY.csv"
CANDIDATE_NAME = "V21_069_R1_COMPARISON_CANDIDATE_MAP.csv"
MATURITY_NAME = "V21_069_R1_MATURITY_AVAILABILITY_AUDIT.csv"
COMPARISON_NAME = "V21_069_R1_CURRENT_D_VS_P03_MATURED_FORWARD_COMPARISON.csv"
DECISION_NAME = "V21_069_R1_OOS_DECISION_TABLE.csv"
VALIDATION_NAME = "V21_069_R1_VALIDATION_SUMMARY.csv"
CURRENT_ID = "P00_CURRENT_D"
P03_ID = "P03_BASE_065_MOM_035"
WINDOWS = ("5D", "10D", "20D")

CANDIDATE_COLUMNS = [
    "run_id", "generated_at_utc", "candidate_id",
    "source_perturbation_id", "base_weight", "momentum_weight",
    "candidate_role", "source_ranking_hash", "candidate_available",
    "candidate_row_count", "top20_tickers", "top50_tickers", "warning",
]
MATURITY_COLUMNS = [
    "run_id", "generated_at_utc", "candidate_forward_source_path",
    "candidate_forward_source_hash", "source_lineage", "row_count",
    "matured_row_count", "pending_row_count", "price_missing_count",
    "available_windows", "earliest_observation_date",
    "latest_observation_date", "earliest_maturity_date",
    "latest_maturity_date", "maturity_status",
    "usable_for_current_d_vs_p03", "rejection_reason", "warning",
]
COMPARISON_COLUMNS = [
    "run_id", "generated_at_utc", "comparison_id", "candidate_id",
    "compared_to", "top_n", "window", "observation_count",
    "matured_observation_count", "pending_observation_count",
    "mean_return", "median_return", "hit_rate", "excess_vs_qqq",
    "excess_vs_spy", "excess_vs_soxx", "current_d_mean_return",
    "current_d_median_return", "current_d_hit_rate",
    "current_d_excess_vs_qqq", "mean_return_delta_vs_current_d",
    "median_return_delta_vs_current_d", "hit_rate_delta_vs_current_d",
    "excess_vs_qqq_delta_vs_current_d", "top_n_overlap_vs_current_d",
    "turnover_vs_current_d", "avg_rank_delta_vs_current_d",
    "max_rank_delta_vs_current_d", "overheat_warning_ratio",
    "bb_extension_warning_ratio", "low_liquidity_warning_ratio",
    "qqq_ma50_supportive_ratio", "risk_warning_ratio",
    "evidence_quality", "result_classification", "warning",
]
DECISION_COLUMNS = [
    "run_id", "generated_at_utc", "candidate_id", "compared_to",
    "evidence_status", "matured_windows_available", "top20_result",
    "top50_result", "return_score", "stability_score", "risk_score",
    "liquidity_score", "overheat_score", "turnover_score",
    "benchmark_excess_score", "aggregate_evidence_score",
    "decision_classification", "recommended_action",
    "shadow_forward_allowed", "adoption_allowed",
    "official_adoption_allowed", "reason", "warning",
]


def now_utc() -> tuple[str, str, pd.Timestamp]:
    value = datetime.now(timezone.utc)
    return (
        value.strftime("%Y%m%dT%H%M%SZ"),
        value.isoformat(),
        pd.Timestamp(value),
    )


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


def first_column(columns: list[str], names: tuple[str, ...]) -> str:
    lookup = {str(column).lower(): str(column) for column in columns}
    return next((lookup[name.lower()] for name in names if name.lower() in lookup), "")


def discover_068(
    root: Path, override: Path | None = None
) -> tuple[Path, pd.Series, dict[str, Path]]:
    candidates = (
        [override if override and override.is_absolute() else root / override]
        if override
        else sorted(
            (root / "outputs/v21/weight_perturbation").rglob(VALIDATION_068),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )
    required_fields = {
        "universe": "perturbation_universe_path",
        "grid": "perturbation_grid_path",
        "rankings": "perturbation_rankings_path",
        "metrics": "perturbation_evaluation_metrics_path",
        "pairwise": "pairwise_vs_current_d_path",
        "recommendation": "weight_candidate_recommendation_path",
        "source": "source_ranking_path",
    }
    for path in candidates:
        try:
            row = pd.read_csv(path).iloc[0]
        except (OSError, ValueError, IndexError):
            continue
        checks = (
            str(row.get("final_status", "")).startswith(("PASS_", "PARTIAL_PASS_"))
            and truth(row.get("source_ranking_hash_verified"))
            and truth(row.get("research_only"))
            and truth(row.get("current_d_preserved"))
            and not truth(row.get("ranking_mutation"))
            and not truth(row.get("official_mutation"))
            and not truth(row.get("protected_outputs_modified"))
            and not truth(row.get("forward_ledger_mutation"))
            and not truth(row.get("official_adoption_allowed"))
        )
        if not checks:
            continue
        paths = {name: (root / str(row[field])).resolve() for name, field in required_fields.items()}
        if all(item.is_file() for item in paths.values()):
            return path.resolve(), row, paths
    raise FileNotFoundError("Valid V21.068-R1 inputs not found")


def protected_files(root: Path, output_dir: Path, explicit: list[Path]) -> list[Path]:
    found = {path.resolve() for path in explicit if path.is_file()}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output_dir.resolve() in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if any(token in text for token in (
                "official", "broker", "protected", "forward_observation_ledger",
                "maturity_refresh_ledger", "daily_maturity_monitoring_ledger",
                "066a_d_latest_ranking", "060_r5_d_weight_optimized_ranking",
            )):
                found.add(path.resolve())
    return sorted(found)


def snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path): sha256(path) for path in paths if path.is_file()}


def candidate_map(
    rankings: pd.DataFrame, grid: pd.DataFrame, run_id: str,
    generated_at: str, source_hash: str,
) -> tuple[pd.DataFrame, bool, bool]:
    rows = []
    definitions = (
        ("CURRENT_D_CONTROL", CURRENT_ID, "CURRENT_D_CONTROL", 0.60, 0.40),
        (P03_ID, P03_ID, "OOS_COMPARISON_CANDIDATE", 0.65, 0.35),
    )
    for candidate_id, perturbation_id, role, base, momentum in definitions:
        grid_rows = grid[grid["perturbation_id"] == perturbation_id]
        ranked = rankings[
            (rankings["perturbation_id"] == perturbation_id)
            & rankings["eligible_flag"].map(truth)
        ].sort_values("perturbation_rank")
        weights_valid = (
            not grid_rows.empty
            and np.isclose(float(grid_rows.iloc[0]["base_weight"]), base)
            and np.isclose(float(grid_rows.iloc[0]["momentum_weight"]), momentum)
        )
        available = weights_valid and not ranked.empty
        rows.append({
            "run_id": run_id, "generated_at_utc": generated_at,
            "candidate_id": candidate_id,
            "source_perturbation_id": perturbation_id,
            "base_weight": base, "momentum_weight": momentum,
            "candidate_role": role, "source_ranking_hash": source_hash,
            "candidate_available": available,
            "candidate_row_count": len(ranked),
            "top20_tickers": "|".join(ranked.head(20)["ticker"].astype(str)),
            "top50_tickers": "|".join(ranked.head(50)["ticker"].astype(str)),
            "warning": "" if available else "CANDIDATE_MISSING_OR_WEIGHT_MISMATCH",
        })
    output = pd.DataFrame(rows).reindex(columns=CANDIDATE_COLUMNS)
    return output, truth(output.iloc[0]["candidate_available"]), truth(output.iloc[1]["candidate_available"])


def forward_candidates(root: Path, override: Path | None) -> list[Path]:
    if override:
        return [override.resolve()]
    base = root / "outputs/v21/experiments/momentum_dynamic/d_weight_optimized"
    patterns = (
        "V21_060_R5_D_FORWARD_OBSERVATION_LEDGER.csv",
        "**/V21_062_D_DAILY_MATURITY_MONITORING_LEDGER.csv",
        "**/V21_063_D_MATURITY_REFRESH_LEDGER.csv",
    )
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(path.resolve() for path in base.glob(pattern) if path.is_file())
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def inspect_forward(
    root: Path, path: Path, run_id: str, generated_at: str,
    run_time: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame, bool]:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except (OSError, ValueError):
        return {}, pd.DataFrame(), False
    columns = list(frame.columns)
    variant_col = first_column(columns, ("variant_id", "source_variant", "version_id"))
    date_col = first_column(columns, ("as_of_date", "observation_date"))
    maturity_col = first_column(
        columns, ("scheduled_maturity_date", "target_maturity_date", "maturity_date")
    )
    status_col = first_column(
        columns, ("maturity_status", "refreshed_maturity_status")
    )
    return_col = first_column(
        columns, ("realized_forward_return", "forward_return")
    )
    window_col = first_column(columns, ("forward_window", "window"))
    ticker_col = first_column(columns, ("ticker", "symbol"))
    if not all((date_col, status_col, return_col, window_col, ticker_col)):
        return {}, pd.DataFrame(), False
    if variant_col:
        variant = frame[variant_col].astype(str).str.upper()
        frame = frame[variant.str.contains("D_WEIGHT_OPTIMIZED_R1|V21.060-R5", regex=True)].copy()
    statuses = frame[status_col].astype(str).str.upper()
    returns = pd.to_numeric(frame[return_col], errors="coerce")
    observation_dates = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
    maturity_dates = (
        pd.to_datetime(frame[maturity_col], errors="coerce", utc=True)
        if maturity_col else pd.Series(pd.NaT, index=frame.index)
    )
    matured_mask = (
        statuses.str.contains("MATURED|COMPLETE|PASS", regex=True)
        & ~statuses.str.contains("PENDING|NOT_MATURED", regex=True)
        & returns.notna()
    )
    pending_mask = statuses.str.contains("PENDING|NOT_MATURED", regex=True)
    price_missing = (
        statuses.str.contains("PRICE|MISSING", regex=True)
        | frame.astype(str).apply(
            lambda column: column.str.contains("PRICE.*MISSING|MISSING.*PRICE", case=False, regex=True)
        ).any(axis=1)
    )
    future_matured = matured_mask & (
        (observation_dates.notna() & (observation_dates > run_time))
        | (maturity_dates.notna() & (maturity_dates > run_time))
    )
    matured = frame[matured_mask & ~future_matured].copy()
    matured["_return"] = returns[matured.index]
    matured["_window"] = frame.loc[matured.index, window_col].astype(str)
    matured["_ticker"] = frame.loc[matured.index, ticker_col].astype(str).str.upper().str.strip()
    row = {
        "run_id": run_id, "generated_at_utc": generated_at,
        "candidate_forward_source_path": rel(root, path),
        "candidate_forward_source_hash": sha256(path),
        "source_lineage": "V21.060-R5_D_FORWARD_MATURITY_LINEAGE",
        "row_count": len(frame), "matured_row_count": len(matured),
        "pending_row_count": int(pending_mask.sum()),
        "price_missing_count": int(price_missing.sum()),
        "available_windows": "|".join(sorted(set(matured["_window"]) & set(WINDOWS))),
        "earliest_observation_date": observation_dates.min().date().isoformat() if observation_dates.notna().any() else "",
        "latest_observation_date": observation_dates.max().date().isoformat() if observation_dates.notna().any() else "",
        "earliest_maturity_date": maturity_dates.min().date().isoformat() if maturity_dates.notna().any() else "",
        "latest_maturity_date": maturity_dates.max().date().isoformat() if maturity_dates.notna().any() else "",
        "maturity_status": (
            "FUTURE_DATED_BLOCKED" if future_matured.any()
            else "MATURED_FORWARD_AVAILABLE" if len(matured) and not pending_mask.any()
            else "PARTIAL_MATURED_FORWARD_AVAILABLE" if len(matured)
            else "PRICE_DATA_MISSING" if price_missing.all() and len(frame)
            else "NO_MATURED_FORWARD_AVAILABLE_WAIT"
        ),
        "usable_for_current_d_vs_p03": bool(len(matured)),
        "rejection_reason": (
            "FUTURE_DATED_MATURED_LABEL" if future_matured.any()
            else "" if len(matured)
            else "NO_MATURED_NON_NULL_FORWARD_RETURNS"
        ),
        "warning": "READ_ONLY_FORWARD_LEDGER",
    }
    return row, matured, bool(future_matured.any())


def maturity_audit(
    root: Path, paths: list[Path], run_id: str, generated_at: str,
    run_time: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    rows, matured_frames = [], []
    future_blocked = False
    for path in paths:
        row, matured, future = inspect_forward(
            root, path, run_id, generated_at, run_time
        )
        if row:
            rows.append(row)
        if not matured.empty:
            matured["_source_path"] = rel(root, path)
            matured_frames.append(matured)
        future_blocked |= future
    audit = pd.DataFrame(rows).reindex(columns=MATURITY_COLUMNS)
    matured_all = pd.concat(matured_frames, ignore_index=True) if matured_frames else pd.DataFrame()
    if not matured_all.empty:
        matured_all = matured_all.drop_duplicates(["_ticker", "_window"], keep="last")
    return audit, matured_all, future_blocked


def ratios(rows: pd.DataFrame) -> dict[str, float]:
    if rows.empty:
        return {
            "overheat": np.nan, "bb": np.nan, "liquidity": np.nan,
            "qqq": np.nan, "risk": np.nan,
        }
    return {
        "overheat": rows["overheat_warning"].map(truth).mean(),
        "bb": rows["bb_extension_warning"].map(truth).mean(),
        "liquidity": rows["diagnostic_low_liquidity_warning"].map(truth).mean(),
        "qqq": rows["diagnostic_qqq_ma50_state"].astype(str).str.contains(
            "ABOVE|RISK_ON", case=False, regex=True
        ).mean(),
        "risk": rows["overheat_warning"].map(truth).mean(),
    }


def build_comparison(
    rankings: pd.DataFrame, matured: pd.DataFrame, run_id: str,
    generated_at: str, pending_count: int,
) -> pd.DataFrame:
    rows = []
    current_all = rankings[
        (rankings["perturbation_id"] == CURRENT_ID)
        & rankings["eligible_flag"].map(truth)
    ]
    p03_all = rankings[
        (rankings["perturbation_id"] == P03_ID)
        & rankings["eligible_flag"].map(truth)
    ]
    for top_n, cutoff in (("TOP20", 20), ("TOP50", 50)):
        current = current_all.nsmallest(cutoff, "perturbation_rank")
        p03 = p03_all.nsmallest(cutoff, "perturbation_rank")
        overlap = len(set(current["ticker"]) & set(p03["ticker"])) / cutoff
        diagnostics = ratios(p03)
        for window in WINDOWS:
            labels = matured[matured["_window"] == window].set_index("_ticker")
            current_returns = pd.to_numeric(
                current["ticker"].map(labels["_return"]), errors="coerce"
            ).dropna()
            p03_returns = pd.to_numeric(
                p03["ticker"].map(labels["_return"]), errors="coerce"
            ).dropna()
            if current_returns.empty and p03_returns.empty:
                continue
            mean_delta = p03_returns.mean() - current_returns.mean()
            median_delta = p03_returns.median() - current_returns.median()
            hit_delta = (p03_returns > 0).mean() - (current_returns > 0).mean()
            if mean_delta > 0 and median_delta >= 0 and hit_delta >= 0:
                classification = "IMPROVES_RETURN_AND_STABILITY"
            elif mean_delta > 0:
                classification = "IMPROVES_RETURN_BUT_RISKIER"
            elif mean_delta >= -1e-12:
                classification = "STABLE_BUT_NO_RETURN_IMPROVEMENT"
            else:
                classification = "WORSE_THAN_CURRENT_D"
            rank_delta = pd.to_numeric(p03["rank_delta_vs_current_d"], errors="coerce").abs()
            rows.append({
                "run_id": run_id, "generated_at_utc": generated_at,
                "comparison_id": "CURRENT_D_VS_P03_MATURED_FORWARD",
                "candidate_id": P03_ID, "compared_to": "CURRENT_D_CONTROL",
                "top_n": top_n, "window": window,
                "observation_count": len(p03_returns),
                "matured_observation_count": len(p03_returns),
                "pending_observation_count": pending_count,
                "mean_return": p03_returns.mean(),
                "median_return": p03_returns.median(),
                "hit_rate": (p03_returns > 0).mean(),
                "excess_vs_qqq": np.nan, "excess_vs_spy": np.nan,
                "excess_vs_soxx": np.nan,
                "current_d_mean_return": current_returns.mean(),
                "current_d_median_return": current_returns.median(),
                "current_d_hit_rate": (current_returns > 0).mean(),
                "current_d_excess_vs_qqq": np.nan,
                "mean_return_delta_vs_current_d": mean_delta,
                "median_return_delta_vs_current_d": median_delta,
                "hit_rate_delta_vs_current_d": hit_delta,
                "excess_vs_qqq_delta_vs_current_d": np.nan,
                "top_n_overlap_vs_current_d": overlap,
                "turnover_vs_current_d": 1 - overlap,
                "avg_rank_delta_vs_current_d": rank_delta.mean(),
                "max_rank_delta_vs_current_d": rank_delta.max(),
                "overheat_warning_ratio": diagnostics["overheat"],
                "bb_extension_warning_ratio": diagnostics["bb"],
                "low_liquidity_warning_ratio": diagnostics["liquidity"],
                "qqq_ma50_supportive_ratio": diagnostics["qqq"],
                "risk_warning_ratio": diagnostics["risk"],
                "evidence_quality": "MATURED_FORWARD_PARTIAL_TICKER_COVERAGE",
                "result_classification": classification,
                "warning": "BENCHMARK_RETURNS_UNAVAILABLE_IN_SELECTED_FORWARD_LEDGER",
            })
    return pd.DataFrame(rows).reindex(columns=COMPARISON_COLUMNS)


def result_for(comparison: pd.DataFrame, top_n: str) -> str:
    rows = comparison[comparison["top_n"] == top_n]
    if rows.empty:
        return "WAITING_FOR_MATURED_FORWARD"
    classes = set(rows["result_classification"])
    if classes == {"IMPROVES_RETURN_AND_STABILITY"}:
        return "IMPROVES_RETURN_AND_STABILITY"
    if "WORSE_THAN_CURRENT_D" in classes:
        return "WORSE_OR_MIXED_VS_CURRENT_D"
    return "MIXED_EVIDENCE"


def decision_table(
    comparison: pd.DataFrame, windows: str, run_id: str, generated_at: str
) -> pd.DataFrame:
    if comparison.empty:
        row = {
            "run_id": run_id, "generated_at_utc": generated_at,
            "candidate_id": P03_ID, "compared_to": "CURRENT_D_CONTROL",
            "evidence_status": "NO_MATURED_FORWARD_AVAILABLE_WAIT",
            "matured_windows_available": "", "top20_result": "WAITING_FOR_MATURED_FORWARD",
            "top50_result": "WAITING_FOR_MATURED_FORWARD",
            "return_score": 0, "stability_score": 0, "risk_score": 0,
            "liquidity_score": 0, "overheat_score": 0, "turnover_score": 0,
            "benchmark_excess_score": 0, "aggregate_evidence_score": 0,
            "decision_classification": "WAITING_FOR_MATURED_FORWARD",
            "recommended_action": "WAIT_FOR_MATURED_FORWARD_BEFORE_CURRENT_D_VS_P03_DECISION",
            "shadow_forward_allowed": False, "adoption_allowed": False,
            "official_adoption_allowed": False,
            "reason": "NO_MATURED_D_FORWARD_OBSERVATIONS",
            "warning": "PENDING_OBSERVATIONS_EXCLUDED",
        }
    else:
        top20, top50 = result_for(comparison, "TOP20"), result_for(comparison, "TOP50")
        improved = (
            pd.to_numeric(comparison["mean_return_delta_vs_current_d"], errors="coerce").gt(0).sum()
            + pd.to_numeric(comparison["median_return_delta_vs_current_d"], errors="coerce").gt(0).sum()
            + pd.to_numeric(comparison["hit_rate_delta_vs_current_d"], errors="coerce").gt(0).sum()
        )
        if "WORSE" in top20 and "IMPROVES" in top50:
            classification = "TOP50_IMPROVEMENT_TOP20_DETERIORATION"
        elif top20 == "IMPROVES_RETURN_AND_STABILITY" and top50 == top20:
            classification = "P03_FORWARD_IMPROVEMENT"
        else:
            classification = "KEEP_CURRENT_D"
        shadow = classification == "P03_FORWARD_IMPROVEMENT" and improved >= 2
        row = {
            "run_id": run_id, "generated_at_utc": generated_at,
            "candidate_id": P03_ID, "compared_to": "CURRENT_D_CONTROL",
            "evidence_status": "MATURED_FORWARD_AVAILABLE",
            "matured_windows_available": windows, "top20_result": top20,
            "top50_result": top50,
            "return_score": comparison["mean_return_delta_vs_current_d"].mean(),
            "stability_score": comparison["top_n_overlap_vs_current_d"].mean(),
            "risk_score": -comparison["risk_warning_ratio"].mean(),
            "liquidity_score": -comparison["low_liquidity_warning_ratio"].mean(),
            "overheat_score": -comparison["overheat_warning_ratio"].mean(),
            "turnover_score": -comparison["turnover_vs_current_d"].mean(),
            "benchmark_excess_score": comparison["excess_vs_qqq_delta_vs_current_d"].mean(),
            "aggregate_evidence_score": improved,
            "decision_classification": classification,
            "recommended_action": "KEEP_CURRENT_D" if not shadow else "ALLOW_RESEARCH_SHADOW_FORWARD_ONLY",
            "shadow_forward_allowed": shadow, "adoption_allowed": False,
            "official_adoption_allowed": False,
            "reason": f"POSITIVE_METRIC_CELLS={improved}",
            "warning": "RESEARCH_ONLY_NO_WEIGHT_ADOPTION",
        }
    return pd.DataFrame([row]).reindex(columns=DECISION_COLUMNS)


def blocked(
    root: Path, output_dir: Path, generated_at: str, status: str,
    reason: str, paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in (
        (CANDIDATE_NAME, CANDIDATE_COLUMNS), (MATURITY_NAME, MATURITY_COLUMNS),
        (COMPARISON_NAME, COMPARISON_COLUMNS), (DECISION_NAME, DECISION_COLUMNS),
    ):
        target = output_dir / name
        if not target.exists():
            pd.DataFrame(columns=columns).to_csv(target, index=False)
    paths = paths or {}
    result = {
        "stage": STAGE, "final_status": status,
        "decision": "BLOCKED_REVIEW_068_INPUTS_OR_FORWARD_LINEAGE",
        "generated_at_utc": generated_at,
        "v21_068_r1_validation_path": paths.get("validation", ""),
        "source_ranking_path": paths.get("source", ""),
        "source_ranking_hash": paths.get("hash", ""),
        "source_ranking_hash_verified": False,
        "comparison_candidate_map_path": rel(root, output_dir / CANDIDATE_NAME),
        "maturity_availability_audit_path": rel(root, output_dir / MATURITY_NAME),
        "current_d_vs_p03_comparison_path": rel(root, output_dir / COMPARISON_NAME),
        "oos_decision_table_path": rel(root, output_dir / DECISION_NAME),
        "ranking_rows": 0, "perturbation_ranking_rows": 0,
        "current_d_candidate_available": False, "p03_candidate_available": False,
        "current_d_top20_count": 0, "p03_top20_count": 0,
        "current_d_top50_count": 0, "p03_top50_count": 0,
        "matured_forward_available": False, "matured_forward_source_count": 0,
        "matured_observation_count": 0, "pending_observation_count": 0,
        "available_matured_windows": "",
        "top20_p03_vs_current_d_result": "",
        "top50_p03_vs_current_d_result": "",
        "decision_classification": "BLOCKED",
        "recommended_action": "BLOCKED_REVIEW_068_INPUTS_OR_FORWARD_LINEAGE",
        "shadow_forward_allowed": False, "adoption_allowed": False,
        "official_adoption_allowed": False, "current_d_preserved": False,
        "ranking_mutation": False, "official_mutation": False,
        "protected_outputs_modified": False, "forward_ledger_mutation": False,
        "research_only": True, "pass_gate": False,
        "validation_warning": reason,
    }
    pd.DataFrame([result]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return result


def run_stage(
    root: Path, validation_override: Path | None = None,
    output_override: Path | None = None, forward_override: Path | None = None,
    rankings_override: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id, generated_at, run_time = now_utc()
    try:
        validation_path, validation_068, paths_obj = discover_068(
            root, validation_override
        )
    except FileNotFoundError as exc:
        return blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_069_R1_MISSING_068_INPUTS_OR_CANDIDATES", str(exc),
        )
    paths = {
        "validation": rel(root, validation_path),
        "source": rel(root, paths_obj["source"]),
        "hash": str(validation_068["source_ranking_hash"]),
    }
    actual_hash = sha256(paths_obj["source"])
    if actual_hash != str(validation_068["source_ranking_hash"]):
        return blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_069_R1_SOURCE_HASH_MISMATCH",
            "Source ranking SHA-256 mismatch", paths,
        )
    ranking_path = rankings_override.resolve() if rankings_override else paths_obj["rankings"]
    if not ranking_path.is_file():
        return blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_069_R1_MISSING_068_INPUTS_OR_CANDIDATES",
            "Perturbation rankings missing", paths,
        )
    source = pd.read_csv(paths_obj["source"], low_memory=False)
    grid = pd.read_csv(paths_obj["grid"], low_memory=False)
    rankings = pd.read_csv(ranking_path, low_memory=False)
    candidates, current_available, p03_available = candidate_map(
        rankings, grid, run_id, generated_at, actual_hash
    )
    candidates.to_csv(output_dir / CANDIDATE_NAME, index=False)
    if not current_available or not p03_available:
        result = blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_069_R1_MISSING_068_INPUTS_OR_CANDIDATES",
            "Current D or P03 candidate missing", paths,
        )
        candidates.to_csv(output_dir / CANDIDATE_NAME, index=False)
        result["source_ranking_hash_verified"] = True
        result["current_d_candidate_available"] = current_available
        result["p03_candidate_available"] = p03_available
        pd.DataFrame([result]).to_csv(output_dir / VALIDATION_NAME, index=False)
        return result

    forward_paths = forward_candidates(root, forward_override)
    protected = protected_files(
        root, output_dir,
        [validation_path, *paths_obj.values(), ranking_path, *forward_paths],
    )
    before = snapshot(protected)
    audit, matured, future_blocked = maturity_audit(
        root, forward_paths, run_id, generated_at, run_time
    )
    audit.to_csv(output_dir / MATURITY_NAME, index=False)
    if future_blocked:
        result = blocked(
            root, output_dir, generated_at,
            "BLOCKED_V21_069_R1_FORWARD_LABEL_OR_LINEAGE_RISK",
            "Future-dated matured forward label detected", paths,
        )
        candidates.to_csv(output_dir / CANDIDATE_NAME, index=False)
        audit.to_csv(output_dir / MATURITY_NAME, index=False)
        return result

    pending_count = int(
        pd.to_numeric(audit.get("pending_row_count"), errors="coerce").max()
    ) if not audit.empty else 0
    comparison = build_comparison(
        rankings, matured, run_id, generated_at, pending_count
    ) if not matured.empty else pd.DataFrame(columns=COMPARISON_COLUMNS)
    windows = "|".join(sorted(set(matured.get("_window", pd.Series(dtype=str))) & set(WINDOWS)))
    decision = decision_table(comparison, windows, run_id, generated_at)
    comparison.to_csv(output_dir / COMPARISON_NAME, index=False)
    decision.to_csv(output_dir / DECISION_NAME, index=False)

    after = snapshot(protected)
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    current_rows = rankings[
        (rankings["perturbation_id"] == CURRENT_ID)
        & rankings["eligible_flag"].map(truth)
    ]
    p03_rows = rankings[
        (rankings["perturbation_id"] == P03_ID)
        & rankings["eligible_flag"].map(truth)
    ]
    integrity = (
        len(source) * 2
        == len(rankings[rankings["perturbation_id"].isin((CURRENT_ID, P03_ID))])
    )
    matured_available = not comparison.empty
    decision_row = decision.iloc[0]
    if changed:
        final_status = "BLOCKED_V21_069_R1_MUTATION_RISK"
        final_decision = "BLOCKED_REVIEW_068_INPUTS_OR_FORWARD_LINEAGE"
    elif not integrity:
        final_status = "BLOCKED_V21_069_R1_FORWARD_LABEL_OR_LINEAGE_RISK"
        final_decision = "BLOCKED_REVIEW_068_INPUTS_OR_FORWARD_LINEAGE"
    elif matured_available:
        final_status = "PASS_V21_069_R1_CURRENT_D_VS_P03_MATURED_FORWARD_COMPARISON_READY"
        final_decision = "CURRENT_D_VS_P03_OOS_COMPARISON_READY_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_069_R1_WAITING_FOR_MATURED_FORWARD_OBSERVATIONS"
        final_decision = "WAIT_FOR_MATURED_FORWARD_BEFORE_CURRENT_D_VS_P03_DECISION"
    result = {
        "stage": STAGE, "final_status": final_status,
        "decision": final_decision, "generated_at_utc": generated_at,
        "v21_068_r1_validation_path": rel(root, validation_path),
        "source_ranking_path": rel(root, paths_obj["source"]),
        "source_ranking_hash": actual_hash,
        "source_ranking_hash_verified": True,
        "comparison_candidate_map_path": rel(root, output_dir / CANDIDATE_NAME),
        "maturity_availability_audit_path": rel(root, output_dir / MATURITY_NAME),
        "current_d_vs_p03_comparison_path": rel(root, output_dir / COMPARISON_NAME),
        "oos_decision_table_path": rel(root, output_dir / DECISION_NAME),
        "ranking_rows": len(source), "perturbation_ranking_rows": len(rankings),
        "current_d_candidate_available": current_available,
        "p03_candidate_available": p03_available,
        "current_d_top20_count": min(20, len(current_rows)),
        "p03_top20_count": min(20, len(p03_rows)),
        "current_d_top50_count": min(50, len(current_rows)),
        "p03_top50_count": min(50, len(p03_rows)),
        "matured_forward_available": matured_available,
        "matured_forward_source_count": int(
            pd.to_numeric(audit.get("matured_row_count"), errors="coerce").gt(0).sum()
        ) if not audit.empty else 0,
        "matured_observation_count": len(matured),
        "pending_observation_count": pending_count,
        "available_matured_windows": windows,
        "top20_p03_vs_current_d_result": decision_row["top20_result"],
        "top50_p03_vs_current_d_result": decision_row["top50_result"],
        "decision_classification": decision_row["decision_classification"],
        "recommended_action": decision_row["recommended_action"],
        "shadow_forward_allowed": truth(decision_row["shadow_forward_allowed"]),
        "adoption_allowed": False, "official_adoption_allowed": False,
        "current_d_preserved": True, "ranking_mutation": False,
        "official_mutation": False,
        "protected_outputs_modified": bool(changed),
        "forward_ledger_mutation": False, "research_only": True,
        "pass_gate": bool(integrity and not changed),
        "protected_modified_paths": "|".join(changed),
    }
    pd.DataFrame([result]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--v21-068-validation-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--forward-source", type=Path)
    parser.add_argument("--rankings-source", type=Path)
    args = parser.parse_args()
    result = run_stage(
        args.root, args.v21_068_validation_path, args.output_dir,
        args.forward_source, args.rankings_source,
    )
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"MATURED_FORWARD_AVAILABLE={result['matured_forward_available']}")
    print(f"MATURED_OBSERVATION_COUNT={result['matured_observation_count']}")
    print(f"AVAILABLE_MATURED_WINDOWS={result['available_matured_windows']}")
    print(f"TOP20_P03_VS_CURRENT_D_RESULT={result['top20_p03_vs_current_d_result']}")
    print(f"TOP50_P03_VS_CURRENT_D_RESULT={result['top50_p03_vs_current_d_result']}")
    print(f"RECOMMENDED_ACTION={result['recommended_action']}")
    print(f"VALIDATION_SUMMARY={(args.output_dir or OUT_REL) / VALIDATION_NAME}")
    return 1 if str(result["final_status"]).startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
