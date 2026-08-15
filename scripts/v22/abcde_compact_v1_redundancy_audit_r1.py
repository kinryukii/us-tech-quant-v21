"""Outcome-blind structural redundancy audit for frozen ABCDE_COMPACT_V1 ranks.

This script reads only the canonical daily rank history.  It never reads a
target, payoff, or forward return, and it does not alter production artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


AUDIT_ID = "ABCDE_COMPACT_V1_REDUNDANCY_AUDIT_R1"
SOURCE_DATASET = "ABCDE_COMPACT_V1_DAILY_HISTORY_R1"
DEFAULT_SOURCE_ROOT = Path(r"D:\us-tech-quant-data\canonical\v22") / SOURCE_DATASET
DEFAULT_RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / AUDIT_ID
STRATEGIES = (
    "A1_CONTROL",
    "B_STATIC_MOMENTUM",
    "C_DYNAMIC_MOMENTUM",
    "D_WEIGHT_OPTIMIZED_REFERENCE",
    "E_R1_DEFENSIVE_REFERENCE",
)
STRATEGY_CODES = dict(zip(STRATEGIES, "ABCDE", strict=True))
REQUIRED_COLUMNS = ("signal_date", "strategy_name", "ticker", "raw_score", "rank", "universe_size")
IDENTITY_COLUMNS = ("model_version", "schema_version")
ALLOWED_COLUMNS = REQUIRED_COLUMNS + IDENTITY_COLUMNS
STRATEGY_ALIAS_MAP: dict[str, str] = {}

# Pre-registered before data aggregation: do not tune these using results.
HIGH_SPEARMAN_MIN = 0.95
HIGH_TOP20_OVERLAP_MIN = 0.80
HIGH_TOP50_OVERLAP_MIN = 0.85
NEAR_SPEARMAN_MIN = 0.90
NEAR_TOP20_OVERLAP_MIN = 0.70
TOP_COUNTS = (20, 50)


class AuditError(RuntimeError):
    """A structural integrity error that must stop the research audit."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, newline="\n") as handle:
        handle.write(text)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def atomic_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, newline="\n") as handle:
        frame.to_csv(handle, index=False, lineterminator="\n", float_format="%.12g")
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary_path, index=False, engine="pyarrow", compression="zstd")
    os.replace(temporary_path, path)


def discover_sources(source_root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    paths = sorted(source_root.glob("abcde_compact_v1_daily_*.parquet"))
    if not paths:
        raise AuditError(f"no frozen daily parquet found under {source_root}")
    baseline_schema: list[dict[str, str]] | None = None
    for path in paths:
        schema = [{"name": field.name, "type": str(field.type)} for field in pq.ParquetFile(path).schema_arrow]
        names = {field["name"] for field in schema}
        missing = set(ALLOWED_COLUMNS) - names
        if missing:
            raise AuditError(f"{path} missing required identity/rank columns: {sorted(missing)}")
        if baseline_schema is None:
            baseline_schema = schema
        elif schema != baseline_schema:
            raise AuditError(f"schema mismatch across frozen source partitions: {path}")
    return paths, baseline_schema or []


def load_and_validate(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_parquet(path, columns=list(ALLOWED_COLUMNS)) for path in paths]
    frame = pd.concat(frames, ignore_index=True)
    return validate_frame(frame)


def validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate an already loaded rank-only frame (also used by focused tests)."""
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    for source, canonical in STRATEGY_ALIAS_MAP.items():
        frame.loc[frame["strategy_name"] == source, "strategy_name"] = canonical
    if frame[list(IDENTITY_COLUMNS)].isna().any().any():
        raise AuditError("null frozen dataset identity")
    if set(frame["model_version"].unique()) != {"ABCDE_COMPACT_V1"}:
        raise AuditError("source model_version is not exactly ABCDE_COMPACT_V1")
    if set(frame["schema_version"].unique()) != {SOURCE_DATASET}:
        raise AuditError(f"source schema_version is not exactly {SOURCE_DATASET}")
    actual_strategies = set(frame["strategy_name"].dropna().unique())
    if actual_strategies != set(STRATEGIES):
        raise AuditError(f"strategy identity is not exactly frozen ABCDE: {sorted(actual_strategies)}")
    duplicate = frame.duplicated(["signal_date", "strategy_name", "ticker"], keep=False)
    if duplicate.any():
        raise AuditError("duplicate (signal_date, strategy_name, ticker) key; refusing to deduplicate")
    if frame[list(REQUIRED_COLUMNS)].isna().any().any():
        raise AuditError("null required rank data")
    if (frame["rank"] < 1).any() or (frame["universe_size"] < 1).any() or (frame["rank"] > frame["universe_size"]).any():
        raise AuditError("invalid rank or universe_size")
    if not np.isfinite(frame["raw_score"].to_numpy(dtype=float)).all():
        raise AuditError("non-finite raw_score")
    return frame.sort_values(["signal_date", "strategy_name", "ticker"], kind="stable").reset_index(drop=True)


def comparable_date_summary(frame: pd.DataFrame) -> tuple[list[pd.Timestamp], int, int]:
    full_comparable: list[pd.Timestamp] = []
    partial_dates = 0
    universe_mismatch_dates = 0
    for signal_date, day in frame.groupby("signal_date", sort=True):
        strategy_sets = {name: set(part["ticker"]) for name, part in day.groupby("strategy_name", sort=False)}
        if set(strategy_sets) != set(STRATEGIES):
            partial_dates += 1
            continue
        if len({frozenset(tickers) for tickers in strategy_sets.values()}) != 1:
            universe_mismatch_dates += 1
            continue
        full_comparable.append(signal_date)
    return full_comparable, partial_dates, universe_mismatch_dates


def top_set(part: pd.DataFrame, count: int) -> set[str]:
    ordered = part.sort_values(["rank", "ticker"], kind="stable")
    return set(ordered.iloc[: min(count, len(ordered))]["ticker"])


def pair_classification(median_spearman: float, median_top20: float, median_top50: float) -> str:
    if median_spearman >= HIGH_SPEARMAN_MIN and median_top20 >= HIGH_TOP20_OVERLAP_MIN and median_top50 >= HIGH_TOP50_OVERLAP_MIN:
        return "HIGH_REDUNDANCY"
    if median_spearman >= NEAR_SPEARMAN_MIN and median_top20 >= NEAR_TOP20_OVERLAP_MIN:
        return "NEAR_REDUNDANT"
    return "DISTINCT_ENOUGH"


def build_pairwise_daily_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for signal_date, day in frame.groupby("signal_date", sort=True):
        by_strategy = {name: part for name, part in day.groupby("strategy_name", sort=False)}
        for left, right in combinations(STRATEGIES, 2):
            if left not in by_strategy or right not in by_strategy:
                continue
            left_frame = by_strategy[left][["ticker", "rank", "raw_score", "universe_size"]].rename(
                columns={"rank": "rank_left", "raw_score": "raw_score_left", "universe_size": "universe_size_left"}
            )
            right_frame = by_strategy[right][["ticker", "rank", "raw_score", "universe_size"]].rename(
                columns={"rank": "rank_right", "raw_score": "raw_score_right", "universe_size": "universe_size_right"}
            )
            common = left_frame.merge(right_frame, on="ticker", how="inner", validate="one_to_one")
            if len(common) < 2:
                raise AuditError(f"fewer than two common tickers for pair {left}/{right} on {signal_date.date()}")
            ranks_left = common["rank_left"].astype(float)
            ranks_right = common["rank_right"].astype(float)
            raw_left = common["raw_score_left"].astype(float)
            raw_right = common["raw_score_right"].astype(float)
            denominator = max(int(common["universe_size_left"].max()), int(common["universe_size_right"].max())) - 1
            denominator = max(denominator, 1)
            left_top20, right_top20 = top_set(by_strategy[left], 20), top_set(by_strategy[right], 20)
            left_top50, right_top50 = top_set(by_strategy[left], 50), top_set(by_strategy[right], 50)
            intersection20, intersection50 = len(left_top20 & right_top20), len(left_top50 & right_top50)
            union20, union50 = len(left_top20 | right_top20), len(left_top50 | right_top50)
            rows.append(
                {
                    "signal_date": signal_date.strftime("%Y-%m-%d"),
                    "left_strategy": left,
                    "right_strategy": right,
                    "pair_code": f"{STRATEGY_CODES[left]}_{STRATEGY_CODES[right]}",
                    "common_ticker_count": len(common),
                    "spearman_rank_correlation": float(ranks_left.corr(ranks_right, method="spearman")),
                    "pearson_raw_score_correlation": float(raw_left.corr(raw_right, method="pearson")),
                    "mean_abs_rank_diff": float((ranks_left - ranks_right).abs().mean()),
                    "normalized_mean_abs_rank_diff": float(((ranks_left - ranks_right).abs() / denominator).mean()),
                    "top20_left_size": len(left_top20),
                    "top20_right_size": len(right_top20),
                    "top20_overlap_denominator": min(len(left_top20), len(right_top20)),
                    "top20_intersection": intersection20,
                    "top20_overlap_ratio": intersection20 / min(len(left_top20), len(right_top20)),
                    "top20_jaccard": intersection20 / union20,
                    "top50_left_size": len(left_top50),
                    "top50_right_size": len(right_top50),
                    "top50_overlap_denominator": min(len(left_top50), len(right_top50)),
                    "top50_intersection": intersection50,
                    "top50_overlap_ratio": intersection50 / min(len(left_top50), len(right_top50)),
                    "top50_jaccard": intersection50 / union50,
                }
            )
    return pd.DataFrame(rows).sort_values(["pair_code", "signal_date"], kind="stable").reset_index(drop=True)


def aggregate_pairwise(daily: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for pair_code, part in daily.groupby("pair_code", sort=True):
        left, right = part.iloc[0][["left_strategy", "right_strategy"]]
        median_spearman = float(part["spearman_rank_correlation"].median())
        median_top20 = float(part["top20_overlap_ratio"].median())
        median_top50 = float(part["top50_overlap_ratio"].median())
        rows.append(
            {
                "pair_code": pair_code,
                "left_strategy": left,
                "right_strategy": right,
                "observation_date_count": int(len(part)),
                "median_spearman": median_spearman,
                "mean_spearman": float(part["spearman_rank_correlation"].mean()),
                "p10_spearman": float(part["spearman_rank_correlation"].quantile(0.10)),
                "p90_spearman": float(part["spearman_rank_correlation"].quantile(0.90)),
                "median_pearson": float(part["pearson_raw_score_correlation"].median()),
                "median_normalized_rank_difference": float(part["normalized_mean_abs_rank_diff"].median()),
                "median_top20_overlap": median_top20,
                "mean_top20_overlap": float(part["top20_overlap_ratio"].mean()),
                "median_top20_jaccard": float(part["top20_jaccard"].median()),
                "median_top50_overlap": median_top50,
                "median_top50_jaccard": float(part["top50_jaccard"].median()),
                "redundancy_classification": pair_classification(median_spearman, median_top20, median_top50),
            }
        )
    return pd.DataFrame(rows).sort_values("pair_code", kind="stable").reset_index(drop=True)


def unique_top20_contribution(frame: pd.DataFrame) -> pd.DataFrame:
    daily_rows: list[dict[str, object]] = []
    for signal_date, day in frame.groupby("signal_date", sort=True):
        by_strategy = {name: part for name, part in day.groupby("strategy_name", sort=False)}
        if set(by_strategy) != set(STRATEGIES):
            continue
        top20 = {name: top_set(part, 20) for name, part in by_strategy.items()}
        for name in STRATEGIES:
            other_union = set().union(*(top20[other] for other in STRATEGIES if other != name))
            unique = top20[name] - other_union
            daily_rows.append(
                {
                    "signal_date": signal_date.strftime("%Y-%m-%d"),
                    "strategy_name": name,
                    "unique_top20_count": len(unique),
                    "unique_top20_ratio": len(unique) / len(top20[name]),
                    "exclusive_vs_any_other_count": len(unique),
                }
            )
    daily = pd.DataFrame(daily_rows)
    summary_rows: list[dict[str, object]] = []
    for name, part in daily.groupby("strategy_name", sort=False):
        values = part["unique_top20_count"]
        summary_rows.append(
            {
                "strategy_name": name,
                "statistic": "SUMMARY",
                "observation_date_count": int(len(part)),
                "mean_unique_top20_count": float(values.mean()),
                "median_unique_top20_count": float(values.median()),
                "p25_unique_top20_count": float(values.quantile(0.25)),
                "p75_unique_top20_count": float(values.quantile(0.75)),
                "max_unique_top20_count": int(values.max()),
                "mean_unique_top20_ratio": float(part["unique_top20_ratio"].mean()),
                "mean_exclusive_vs_any_other_count": float(part["exclusive_vs_any_other_count"].mean()),
            }
        )
    output = pd.concat([daily, pd.DataFrame(summary_rows)], ignore_index=True, sort=False)
    return output.sort_values(["strategy_name", "statistic", "signal_date"], na_position="last", kind="stable").reset_index(drop=True)


def normalized_rank_observations(frame: pd.DataFrame, full_strategy_dates: list[pd.Timestamp]) -> np.ndarray:
    observations: list[np.ndarray] = []
    for signal_date in full_strategy_dates:
        day = frame[frame["signal_date"] == signal_date]
        by_strategy = {name: part.set_index("ticker") for name, part in day.groupby("strategy_name", sort=False)}
        common_tickers = sorted(set.intersection(*(set(by_strategy[name].index) for name in STRATEGIES)))
        if not common_tickers:
            continue
        columns = []
        for name in STRATEGIES:
            part = by_strategy[name].loc[common_tickers]
            ranks = part["rank"].to_numpy(dtype=float)
            universe = part["universe_size"].to_numpy(dtype=float)
            columns.append(1.0 - (ranks - 1.0) / np.maximum(universe - 1.0, 1.0))
        observations.append(np.column_stack(columns))
    if not observations:
        raise AuditError("no five-strategy common observations available for PCA")
    return np.vstack(observations)


def pca_summary(frame: pd.DataFrame, full_strategy_dates: list[pd.Timestamp]) -> tuple[dict[str, object], pd.DataFrame]:
    matrix = normalized_rank_observations(frame, full_strategy_dates)
    standard_deviation = matrix.std(axis=0, ddof=1)
    if np.any(standard_deviation == 0):
        raise AuditError("zero-variance normalized rank column prevents PCA")
    standardized = (matrix - matrix.mean(axis=0)) / standard_deviation
    covariance = standardized.T @ standardized / (len(standardized) - 1)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(-eigenvalues, kind="stable")
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    for column in range(eigenvectors.shape[1]):
        first = eigenvectors[:, column][np.flatnonzero(np.abs(eigenvectors[:, column]) > 1e-12)[0]]
        if first < 0:
            eigenvectors[:, column] *= -1
    explained = eigenvalues / eigenvalues.sum()
    cumulative = np.cumsum(explained)
    dimension = int(np.flatnonzero(cumulative >= 0.95)[0] + 1)
    summary = {
        "pca_type": "UNSUPERVISED_STRUCTURE_ONLY",
        "observation_count": int(len(matrix)),
        "standardization": "per-strategy normalized rank_strength then global mean=0,std=1",
        "rank_strength_formula": "1 - (rank - 1) / max(universe_size - 1, 1)",
        "explained_variance": {f"PC{i + 1}": float(value) for i, value in enumerate(explained)},
        "cumulative_explained_variance": {f"PC1_PC{i + 1}": float(value) for i, value in enumerate(cumulative)},
        "effective_strategy_dimension_95pct": dimension,
        "UNSUPERVISED_PCA_COUNT": 1,
        "MODEL_FIT_COUNT": 0,
    }
    loadings = pd.DataFrame(eigenvectors, index=[STRATEGY_CODES[name] for name in STRATEGIES], columns=[f"PC{i + 1}" for i in range(5)])
    loadings.index.name = "strategy_code"
    return summary, loadings.reset_index()


def clusters_and_representatives(aggregate: pd.DataFrame, daily: pd.DataFrame) -> dict[str, object]:
    high = aggregate[aggregate["redundancy_classification"] == "HIGH_REDUNDANCY"]
    adjacency = {name: set() for name in STRATEGIES}
    for row in high.itertuples(index=False):
        adjacency[row.left_strategy].add(row.right_strategy)
        adjacency[row.right_strategy].add(row.left_strategy)
    components: list[list[str]] = []
    remaining = set(STRATEGIES)
    while remaining:
        start = min(remaining, key=lambda name: STRATEGY_CODES[name])
        stack, component = [start], set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current] - component)
        remaining -= component
        components.append(sorted(component, key=lambda name: STRATEGY_CODES[name]))
    cluster_output: list[dict[str, object]] = []
    for component in components:
        internal = high[high["left_strategy"].isin(component) & high["right_strategy"].isin(component)]
        required_edges = len(component) * (len(component) - 1) // 2
        clique = len(internal) == required_edges
        entry: dict[str, object] = {
            "strategies": component,
            "size": len(component),
            "FULLY_REDUNDANT_CLIQUE_STATUS": "PASS" if clique else "NOT_A_FULLY_REDUNDANT_CLIQUE",
            "CANDIDATE_CANONICAL_REPRESENTATIVE": None,
            "recommendation_status": "RECOMMENDATION_ONLY",
        }
        if len(component) > 1:
            averages: dict[str, float] = {}
            for name in component:
                pair_daily = daily[
                    ((daily["left_strategy"] == name) & daily["right_strategy"].isin(component))
                    | ((daily["right_strategy"] == name) & daily["left_strategy"].isin(component))
                ]
                averages[name] = float(pair_daily["normalized_mean_abs_rank_diff"].mean())
            representative = min(component, key=lambda name: (averages[name], STRATEGY_CODES[name]))
            entry["average_normalized_mean_abs_rank_difference"] = averages
            entry["CANDIDATE_CANONICAL_REPRESENTATIVE"] = representative
        cluster_output.append(entry)
    return {"description": "Descriptive HIGH_REDUNDANCY graph components only; connected membership does not make every pair HIGH_REDUNDANCY.", "clusters": cluster_output}


def classification_and_decision(aggregate: pd.DataFrame) -> tuple[str, str]:
    classes = set(aggregate["redundancy_classification"])
    # Frozen classification rule: only a complete five-node HIGH graph is A;
    # any partial HIGH/NEAR relationship is B; otherwise all views are C.
    if len(aggregate) == 10 and classes == {"HIGH_REDUNDANCY"}:
        return (
            "A_EFFECTIVELY_LOW_DIMENSIONAL_HIGH_REDUNDANCY",
            "FREEZE_CURRENT_ABCDE_AS_HEURISTIC_BENCHMARKS_NO_MORE_LINEAR_WEIGHT_SEARCH",
        )
    if "HIGH_REDUNDANCY" in classes or "NEAR_REDUNDANT" in classes:
        return (
            "B_PARTIALLY_REDUNDANT_MULTIPLE_DISTINCT_VIEWS",
            "FREEZE_CURRENT_ABCDE_AS_HEURISTIC_BENCHMARKS_NO_MORE_LINEAR_WEIGHT_SEARCH",
        )
    return (
        "C_MEANINGFULLY_DISTINCT_FIVE_VIEW_STRUCTURE",
        "FREEZE_CURRENT_WEIGHTS_PENDING_SEPARATE_ECONOMIC_EVIDENCE",
    )


def run_audit(source_root: Path = DEFAULT_SOURCE_ROOT, results_root: Path = DEFAULT_RESULTS_ROOT) -> dict[str, object]:
    paths, schema = discover_sources(source_root)
    source_file_rows = {str(path): int(pq.ParquetFile(path).metadata.num_rows) for path in paths}
    hashes_before = {str(path): sha256(path) for path in paths}
    frame = load_and_validate(paths)
    full_dates, partial_dates, universe_mismatch_dates = comparable_date_summary(frame)
    daily = build_pairwise_daily_metrics(frame)
    aggregate = aggregate_pairwise(daily)
    unique = unique_top20_contribution(frame)
    pca, loadings = pca_summary(frame, [date for date, day in frame.groupby("signal_date", sort=True) if set(day["strategy_name"]) == set(STRATEGIES)])
    cluster_data = clusters_and_representatives(aggregate, daily)
    classification, decision = classification_and_decision(aggregate)
    hashes_after = {str(path): sha256(path) for path in paths}
    mutation_status = "PASS" if hashes_before == hashes_after else "FAIL"
    if mutation_status != "PASS":
        raise AuditError("SOURCE_MUTATION_STATUS=FAIL")

    source_manifest = {
        "audit_id": AUDIT_ID,
        "source_dataset": SOURCE_DATASET,
        "source_root": str(source_root),
        "source_file_count": len(paths),
        "files": [{"path": str(path), "sha256_before": hashes_before[str(path)], "sha256_after": hashes_after[str(path)], "row_count": source_file_rows[str(path)]} for path in paths],
        "row_count": int(len(frame)),
        "date_min": frame["signal_date"].min().strftime("%Y-%m-%d"),
        "date_max": frame["signal_date"].max().strftime("%Y-%m-%d"),
        "unique_date_count": int(frame["signal_date"].nunique()),
        "unique_ticker_count": int(frame["ticker"].nunique()),
        "strategy_count": int(frame["strategy_name"].nunique()),
        "strategy_names": list(STRATEGIES),
        "strategy_alias_map": STRATEGY_ALIAS_MAP,
        "schema": schema,
        "duplicate_key_check": "PASS",
        "full_five_strategy_comparable_date_count": len(full_dates),
        "partial_date_count": partial_dates,
        "universe_mismatch_date_count": universe_mismatch_dates,
        "SOURCE_MUTATION_STATUS": mutation_status,
        "read_contract": "only signal_date,strategy_name,ticker,raw_score,rank,universe_size plus model/schema identity columns",
        "PAYOFF_READ_COUNT": 0,
        "TARGET_READ_COUNT": 0,
    }
    summary = {
        "audit_id": AUDIT_ID,
        "status": "PASS",
        "ABCDE_REDUNDANCY_CLASSIFICATION": classification,
        "ABCDE_REDUNDANCY_DECISION": decision,
        "SOURCE_DATASET": SOURCE_DATASET,
        "SOURCE_FILE_COUNT": len(paths),
        "SOURCE_ROW_COUNT": int(len(frame)),
        "DATE_MIN": source_manifest["date_min"],
        "DATE_MAX": source_manifest["date_max"],
        "DATE_COUNT": source_manifest["unique_date_count"],
        "FULLY_COMPARABLE_DATE_COUNT": len(full_dates),
        "PARTIAL_DATE_COUNT": partial_dates,
        "UNIVERSE_MISMATCH_DATE_COUNT": universe_mismatch_dates,
        "STRATEGY_COUNT": 5,
        "MODEL_FIT_COUNT": 0,
        "UNSUPERVISED_PCA_COUNT": 1,
        "PAYOFF_READ_COUNT": 0,
        "TARGET_READ_COUNT": 0,
        "NEW_ALPHA_FACTOR_COUNT": 0,
        "LINEAR_WEIGHT_SEARCH_COUNT": 0,
        "SOURCE_MUTATION_STATUS": mutation_status,
        "ABCDE_WEIGHT_CHANGE_STATUS": "UNCHANGED",
        "DAILY_CHAIN_CHANGE_STATUS": "UNCHANGED",
        "BROKER_BEHAVIOR_CHANGE_STATUS": "UNCHANGED",
        "ANTI_BLOAT_STATUS": "PASS_ONE_FOCUSED_SCRIPT_ONE_FOCUSED_TEST_EXTERNAL_ARTIFACTS_ONLY",
        "NO_LINEAR_WEIGHT_OPTIMIZATION_AUTHORIZED": True,
        "why_freeze": "ABCDE_COMPACT_V1 is a FROZEN_HEURISTIC_CROSS_SECTIONAL_BENCHMARK, not a validated economic predictor. This outcome-blind audit measures structural diversity only and does not establish economic predictive validity.",
        "pre_registered_thresholds": {
            "HIGH_REDUNDANCY": {"median_daily_spearman_min": HIGH_SPEARMAN_MIN, "median_top20_overlap_min": HIGH_TOP20_OVERLAP_MIN, "median_top50_overlap_min": HIGH_TOP50_OVERLAP_MIN},
            "NEAR_REDUNDANCY": {"median_daily_spearman_min": NEAR_SPEARMAN_MIN, "median_top20_overlap_min": NEAR_TOP20_OVERLAP_MIN},
        },
        "pca": pca,
        "results_root": str(results_root),
    }
    atomic_parquet(daily, results_root / "abcde_pairwise_daily_metrics.parquet")
    atomic_csv(aggregate, results_root / "abcde_pairwise_aggregate.csv")
    atomic_csv(unique, results_root / "abcde_top20_unique_contribution.csv")
    atomic_json(results_root / "abcde_pca_summary.json", pca)
    atomic_csv(loadings, results_root / "abcde_pca_loadings.csv")
    atomic_json(results_root / "abcde_redundancy_clusters.json", cluster_data)
    atomic_json(results_root / "source_manifest.json", source_manifest)
    atomic_json(results_root / "abcde_redundancy_summary.json", summary)
    return {"summary": summary, "aggregate": aggregate, "unique": unique, "clusters": cluster_data}


def console_summary(result: dict[str, object]) -> str:
    summary = result["summary"]
    aggregate = result["aggregate"].set_index("pair_code")
    unique = result["unique"]
    unique_summary = unique[unique["statistic"] == "SUMMARY"].set_index("strategy_name")
    clusters = result["clusters"]["clusters"]
    high = aggregate[aggregate["redundancy_classification"] == "HIGH_REDUNDANCY"].index.tolist()
    near = aggregate[aggregate["redundancy_classification"] == "NEAR_REDUNDANT"].index.tolist()
    distinct = aggregate[aggregate["redundancy_classification"] == "DISTINCT_ENOUGH"].index.tolist()
    representatives = [entry["CANDIDATE_CANONICAL_REPRESENTATIVE"] for entry in clusters if entry["CANDIDATE_CANONICAL_REPRESENTATIVE"]]
    lines = [
        "ABCDE_REDUNDANCY_R1_STATUS=PASS",
        f"ABCDE_REDUNDANCY_CLASSIFICATION={summary['ABCDE_REDUNDANCY_CLASSIFICATION']}",
        f"ABCDE_REDUNDANCY_DECISION={summary['ABCDE_REDUNDANCY_DECISION']}",
        "",
        f"SOURCE_DATASET={summary['SOURCE_DATASET']}", f"SOURCE_FILE_COUNT={summary['SOURCE_FILE_COUNT']}", f"SOURCE_ROW_COUNT={summary['SOURCE_ROW_COUNT']}",
        f"DATE_MIN={summary['DATE_MIN']}", f"DATE_MAX={summary['DATE_MAX']}", f"DATE_COUNT={summary['DATE_COUNT']}",
        f"FULLY_COMPARABLE_DATE_COUNT={summary['FULLY_COMPARABLE_DATE_COUNT']}", "STRATEGY_COUNT=5", "",
    ]
    for pair in aggregate.index:
        lines.append(f"PAIR_{pair}_MEDIAN_SPEARMAN={aggregate.loc[pair, 'median_spearman']:.12g}")
    lines.append("")
    for pair in aggregate.index:
        lines.append(f"PAIR_{pair}_TOP20_OVERLAP={aggregate.loc[pair, 'median_top20_overlap']:.12g}")
    lines.append("")
    for name in STRATEGIES:
        lines.append(f"{STRATEGY_CODES[name]}_MEAN_UNIQUE_TOP20={unique_summary.loc[name, 'mean_unique_top20_count']:.12g}")
    pca = summary["pca"]
    lines.extend(["", f"PCA_PC1_EXPLAINED={pca['explained_variance']['PC1']:.12g}", f"PCA_PC1_PC2_CUMULATIVE={pca['cumulative_explained_variance']['PC1_PC2']:.12g}", f"PCA_PC1_PC2_PC3_CUMULATIVE={pca['cumulative_explained_variance']['PC1_PC3']:.12g}", f"EFFECTIVE_STRATEGY_DIMENSION={pca['effective_strategy_dimension_95pct']}", "", f"HIGH_REDUNDANCY_PAIRS={','.join(high) or 'NONE'}", f"NEAR_REDUNDANCY_PAIRS={','.join(near) or 'NONE'}", f"DISTINCT_PAIRS={','.join(distinct) or 'NONE'}", f"REDUNDANCY_CLUSTERS={json.dumps([entry['strategies'] for entry in clusters], separators=(',', ':'))}", f"CANDIDATE_CANONICAL_REPRESENTATIVES={','.join(representatives) or 'NONE'}", "", "MODEL_FIT_COUNT=0", "UNSUPERVISED_PCA_COUNT=1", "PAYOFF_READ_COUNT=0", "TARGET_READ_COUNT=0", "NEW_ALPHA_FACTOR_COUNT=0", "LINEAR_WEIGHT_SEARCH_COUNT=0", "", f"SOURCE_MUTATION_STATUS={summary['SOURCE_MUTATION_STATUS']}", "ABCDE_WEIGHT_CHANGE_STATUS=UNCHANGED", "DAILY_CHAIN_CHANGE_STATUS=UNCHANGED", "BROKER_BEHAVIOR_CHANGE_STATUS=UNCHANGED", f"ANTI_BLOAT_STATUS={summary['ANTI_BLOAT_STATUS']}", "", "NO_LINEAR_WEIGHT_OPTIMIZATION_AUTHORIZED=true", f"FREEZE_RECOMMENDATION={summary['ABCDE_REDUNDANCY_DECISION']}", "", f"RESULTS_ROOT={summary['results_root']}", f"SUMMARY_PATH={Path(summary['results_root']) / 'abcde_redundancy_summary.json'}"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    args = parser.parse_args()
    result = run_audit(args.source_root, args.results_root)
    print(console_summary(result))


if __name__ == "__main__":
    main()
