#!/usr/bin/env python
"""Close remaining V21.067 explainability gaps without mutating ranking inputs."""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


STAGE = "V21.067-R3_COMPONENT_GAP_CLOSURE_LIQUIDITY_AND_REGIME_EXPLAINABILITY_REPAIR"
OUT_REL = Path("outputs/v21/explainability")
R2_VALIDATION_NAME = "V21_067_R2_VALIDATION_SUMMARY.csv"
GAP_NAME = "V21_067_R3_COMPONENT_GAP_AUDIT.csv"
QQQ_NAME = "V21_067_R3_QQQ_MA50_REGIME_TICKER_MAP.csv"
LIQUIDITY_NAME = "V21_067_R3_LIQUIDITY_PENALTY_COMPONENT.csv"
LEDGER_NAME = "V21_067_R3_FACTOR_EXPLAINABILITY_LEDGER_REPAIRED.csv"
SUMMARY_NAME = "V21_067_R3_TOP_BUCKET_EXPLAINABILITY_SUMMARY_REPAIRED.csv"
VALIDATION_NAME = "V21_067_R3_VALIDATION_SUMMARY.csv"

FAMILIES = {
    "fundamental_score_raw": ("fundamental_score_raw", "fundamental_score", "normalized_fundamental_score"),
    "technical_score_raw": ("technical_score_raw", "technical_score", "technical_score_normalized", "normalized_technical_score"),
    "strategy_score_raw": ("strategy_score_raw", "strategy_score", "normalized_strategy_score"),
    "risk_score_raw": ("risk_score_raw", "risk_score", "exhaustion_risk_score", "normalized_risk_score"),
    "market_regime_score_raw": ("market_regime_score_raw", "market_regime_score", "regime_score", "normalized_market_regime_score"),
    "data_trust_score_raw": ("data_trust_score_raw", "data_trust_score", "normalized_data_trust_score"),
}
AUDIT_COMPONENTS = [
    *FAMILIES, "risk__liquidity_penalty", "regime__qqq_ma50_state",
    "regime__risk_state", "data_trust__warning_flag",
]
ORIGINAL_EXPECTED = [
    "base_score_raw", "momentum_score_raw", *FAMILIES,
    "technical__rsi", "technical__kdj", "technical__macd", "technical__bb",
    "technical__ma20", "technical__ma50", "technical__ema",
    "technical__volume", "technical__volatility",
    "technical__relative_strength", "technical__breakout",
    "technical__pullback", "risk__overheat",
    "risk__volatility_penalty", "regime__risk_state",
    "data_trust__warning_flag",
]
DIAGNOSTIC_EXPECTED = ["risk__liquidity_penalty", "regime__qqq_ma50_state"]
ALL_EXPECTED = ORIGINAL_EXPECTED + DIAGNOSTIC_EXPECTED

GAP_COLUMNS = [
    "run_id", "generated_at_utc", "component_name", "component_type",
    "r2_status", "r2_coverage_ratio", "gap_type", "repair_attempted",
    "repair_method", "repair_result", "selected_source_path",
    "selected_source_hash", "selected_column_name", "coverage_count",
    "coverage_ratio", "null_count", "confidence", "warning",
]
QQQ_COLUMNS = [
    "ticker", "source_ranking_date", "qqq_regime_source_path",
    "qqq_regime_source_hash", "qqq_regime_date", "qqq_price", "qqq_ma50",
    "regime__qqq_ma50_state", "regime_component_scope",
    "regime_mapping_status", "warning",
]
LIQUIDITY_COLUMNS = [
    "run_id", "generated_at_utc", "ticker", "source_ranking_date",
    "liquidity_source_path", "liquidity_source_hash",
    "liquidity_window_start", "liquidity_window_end",
    "liquidity_observation_count", "avg_dollar_volume",
    "median_dollar_volume", "liquidity_percentile_0_1",
    "risk__liquidity_penalty", "liquidity_warning_flag",
    "liquidity_component_status", "warning",
]
R3_COLUMNS = [
    "repaired_fundamental_score_raw", "repaired_technical_score_raw",
    "repaired_strategy_score_raw", "repaired_risk_score_raw",
    "repaired_market_regime_score_raw", "repaired_data_trust_score_raw",
    "risk__liquidity_penalty", "liquidity_percentile_0_1",
    "liquidity_warning_flag", "regime__qqq_ma50_state",
    "regime__qqq_ma50_component_scope", "component_gap_closure_status",
    "component_coverage_ratio_r2", "component_coverage_ratio_r3",
    "component_coverage_delta", "explainability_status_r3",
    "complete_explainability_reason", "partial_explainability_reason",
    "diagnostic_component_not_in_original_score_flag",
]
SUMMARY_COLUMNS = [
    "bucket", "row_count", "avg_final_score",
    "avg_component_coverage_ratio_r2", "avg_component_coverage_ratio_r3",
    "avg_component_coverage_delta", "complete_explainability_count_r3",
    "partial_explainability_count_r3", "diagnostic_only_component_count",
    "family_component_coverage_count", "technical_subfactor_coverage_count",
    "risk_component_coverage_count", "regime_component_coverage_count",
    "data_trust_component_coverage_count",
    "liquidity_component_available_count", "low_liquidity_warning_count",
    "qqq_ma50_regime_mapped_count", "qqq_ma50_regime_supportive_count",
    "qqq_ma50_regime_headwind_count", "overheat_warning_count",
    "bb_extension_warning_count", "top_positive_driver_1",
    "top_positive_driver_2", "top_positive_driver_3",
    "top_negative_driver_1", "top_negative_driver_2",
    "top_negative_driver_3",
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


def as_bool(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def first_column(columns: list[str], names: tuple[str, ...]) -> str:
    lookup = {str(column).lower(): str(column) for column in columns}
    return next((lookup[name.lower()] for name in names if name.lower() in lookup), "")


def discover_r2(root: Path, override: Path | None = None) -> tuple[Path, pd.Series, dict[str, Path]]:
    candidates = (
        [override if override and override.is_absolute() else root / override]
        if override else
        sorted((root / OUT_REL).rglob(R2_VALIDATION_NAME), key=lambda path: path.stat().st_mtime, reverse=True)
    )
    for path in candidates:
        try:
            row = pd.read_csv(path).iloc[0]
        except (OSError, ValueError, IndexError):
            continue
        if not str(row.get("final_status", "")).startswith(("PASS_", "PARTIAL_PASS_")):
            continue
        if not as_bool(row.get("source_ranking_hash_verified")) or not as_bool(row.get("research_only")):
            continue
        if as_bool(row.get("official_mutation")) or as_bool(row.get("protected_outputs_modified")):
            continue
        paths = {
            "ledger": root / str(row["enriched_ledger_path"]),
            "lineage": root / str(row["selected_lineage_map_path"]),
            "matrix": root / str(row["component_availability_matrix_path"]),
            "source": root / str(row["source_ranking_path"]),
        }
        if all(item.is_file() for item in paths.values()):
            return path.resolve(), row, {key: value.resolve() for key, value in paths.items()}
    raise FileNotFoundError("Valid V21.067-R2 artifacts not found")


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
                "066a_d_latest_ranking", "060_r5_d_weight_optimized_ranking",
            )):
                found.add(path.resolve())
    return sorted(found)


def snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path): sha256(path) for path in paths if path.is_file()}


def source_dates(ranking: pd.DataFrame) -> tuple[str, dict[str, pd.Timestamp]]:
    ticker_col = first_column(list(ranking.columns), ("ticker", "symbol"))
    date_col = first_column(list(ranking.columns), ("latest_price_date", "as_of_date", "date"))
    if not ticker_col or not date_col:
        raise ValueError("Source ranking ticker/date fields unavailable")
    tickers = ranking[ticker_col].astype(str).str.strip().str.upper()
    dates = pd.to_datetime(ranking[date_col], errors="coerce", utc=True)
    mapping = {ticker: date for ticker, date in zip(tickers, dates) if pd.notna(date)}
    return max(mapping.values()).date().isoformat(), mapping


def r2_state(matrix: pd.DataFrame, component: str) -> tuple[str, float]:
    rows = matrix[matrix["component_name"] == component]
    if rows.empty:
        return "MISSING", 0.0
    row = rows.iloc[0]
    return str(row.get("status", "MISSING")), float(pd.to_numeric(row.get("coverage_ratio"), errors="coerce") or 0)


def family_candidates(root: Path, r2_catalog_path: Path | None, override: Path | None) -> list[Path]:
    if override:
        return [override.resolve()]
    paths: set[Path] = set()
    if r2_catalog_path and r2_catalog_path.is_file():
        catalog = pd.read_csv(r2_catalog_path)
        for value in catalog.loc[catalog["detected_family_columns"].fillna("").ne(""), "candidate_file_path"]:
            path = root / str(value)
            if path.is_file():
                paths.add(path.resolve())
    for pattern in (
        "outputs/v21/factors/*TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
        "outputs/v21/shadow_observation/*CURRENT_OBSERVATION_UNIVERSE.csv",
        "outputs/v21/ablation/*JOINED_FACTOR_OUTCOME_ROWS.csv",
        "outputs/v21/recalibration/*JOINED_OUTCOME_ROWS.csv",
    ):
        paths.update(path.resolve() for path in root.glob(pattern) if path.is_file())
    return sorted(paths)


def resolve_families(
    root: Path, candidates: list[Path], tickers: set[str],
    ticker_dates: dict[str, pd.Timestamp],
) -> tuple[dict[str, dict[str, Any]], int, int]:
    outputs: dict[str, dict[str, Any]] = {}
    ambiguous_count = 0
    date_blocked = 0
    for component, aliases in FAMILIES.items():
        options = []
        for path in candidates:
            try:
                columns = [str(column) for column in pd.read_csv(path, nrows=0).columns]
            except (OSError, ValueError):
                continue
            ticker_col = first_column(columns, ("ticker", "symbol"))
            date_col = first_column(columns, ("as_of_date", "snapshot_date", "date", "latest_price_date"))
            value_col = first_column(columns, aliases)
            if not ticker_col or not value_col:
                continue
            usecols = list(dict.fromkeys([ticker_col, value_col, date_col] if date_col else [ticker_col, value_col]))
            frame = pd.read_csv(path, usecols=usecols, low_memory=False)
            frame["_ticker"] = frame[ticker_col].astype(str).str.strip().str.upper()
            frame = frame[frame["_ticker"].isin(tickers)].copy()
            frame["_value"] = pd.to_numeric(frame[value_col], errors="coerce")
            frame = frame[frame["_value"].notna()]
            if frame.empty:
                continue
            warning = ""
            exact = 0
            if date_col:
                frame["_date"] = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
                frame["_target"] = frame["_ticker"].map(ticker_dates)
                future = frame["_date"].notna() & frame["_target"].notna() & (frame["_date"] > frame["_target"])
                frame = frame[~future].copy()
                if frame.empty:
                    date_blocked += 1
                    continue
                frame["_exact"] = frame["_date"].eq(frame["_target"])
                exact = int(frame["_exact"].sum())
                frame = frame.sort_values(["_ticker", "_exact", "_date"], ascending=[True, False, False])
                best = frame.groupby("_ticker", sort=False).head(1)
                contenders = frame.merge(best[["_ticker", "_date"]].drop_duplicates(), on=["_ticker", "_date"])
                if contenders.groupby(["_ticker", "_date"])["_value"].nunique().gt(1).any():
                    ambiguous_count += 1
                    continue
                selected = best.drop_duplicates("_ticker")
                confidence = "HIGH" if exact == len(selected) else "PARTIAL"
                if confidence == "PARTIAL":
                    warning = "LATEST_NON_FUTURE_DATE_USED"
            else:
                if frame.groupby("_ticker")["_value"].nunique().gt(1).any():
                    ambiguous_count += 1
                    continue
                selected = frame.drop_duplicates("_ticker", keep="last")
                confidence = "PARTIAL"
                warning = "TICKER_ONLY_SOURCE"
            values = dict(zip(selected["_ticker"], selected["_value"]))
            options.append((
                (1 if confidence == "HIGH" else 0, exact, len(values), path.stat().st_mtime),
                {
                    "values": values, "path": path, "hash": sha256(path),
                    "column": value_col, "coverage": len(values),
                    "coverage_ratio": len(values) / max(len(tickers), 1),
                    "confidence": confidence, "warning": warning,
                    "exact_count": exact,
                },
            ))
        if options:
            outputs[component] = sorted(options, key=lambda item: item[0], reverse=True)[0][1]
    return outputs, ambiguous_count, date_blocked


def resolve_qqq(
    root: Path, ranking: pd.DataFrame, source_date: str, override: Path | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = (
        [override.resolve()] if override else
        sorted((root / "outputs/v21").rglob("*QQQ*MA50*LEDGER.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    )
    source_ts = pd.Timestamp(source_date, tz="UTC")
    ticker_col = first_column(list(ranking.columns), ("ticker", "symbol"))
    tickers = ranking[ticker_col].astype(str).str.strip().str.upper()
    for path in candidates:
        try:
            frame = pd.read_csv(path, low_memory=False)
        except (OSError, ValueError):
            continue
        columns = list(frame.columns)
        date_col = first_column(columns, ("observation_date", "as_of_date", "date"))
        state_col = first_column(columns, ("qqq_state", "qqq_ma50_state", "regime__qqq_ma50_state"))
        price_col = first_column(columns, ("qqq_price", "close"))
        ma_col = first_column(columns, ("qqq_ma50", "ma50"))
        if not date_col or not state_col:
            continue
        frame["_date"] = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
        if frame["_date"].notna().any() and (frame["_date"] > source_ts).all():
            return pd.DataFrame(columns=QQQ_COLUMNS), {"status": "FUTURE_BLOCKED", "path": path}
        valid = frame[frame["_date"].notna() & (frame["_date"] <= source_ts)].sort_values("_date")
        if valid.empty:
            continue
        latest_date = valid["_date"].max()
        latest = valid[valid["_date"] == latest_date]
        if latest[state_col].astype(str).nunique() > 1:
            return pd.DataFrame(columns=QQQ_COLUMNS), {"status": "AMBIGUOUS", "path": path}
        row = latest.iloc[-1]
        mapped = pd.DataFrame({
            "ticker": tickers,
            "source_ranking_date": source_date,
            "qqq_regime_source_path": rel(root, path),
            "qqq_regime_source_hash": sha256(path),
            "qqq_regime_date": latest_date.date().isoformat(),
            "qqq_price": row.get(price_col, pd.NA) if price_col else pd.NA,
            "qqq_ma50": row.get(ma_col, pd.NA) if ma_col else pd.NA,
            "regime__qqq_ma50_state": str(row[state_col]),
            "regime_component_scope": "MARKET_WIDE_MAPPED_TO_TICKER_UNIVERSE",
            "regime_mapping_status": "MAPPED_NON_FUTURE_VALIDATED",
            "warning": "DIAGNOSTIC_NOT_IN_ORIGINAL_D_SCORE",
        })
        return mapped.reindex(columns=QQQ_COLUMNS), {
            "status": "MAPPED", "path": path, "hash": sha256(path),
            "column": state_col, "date": latest_date, "coverage": len(mapped),
        }
    return pd.DataFrame(columns=QQQ_COLUMNS), {"status": "UNAVAILABLE"}


def liquidity_source(root: Path, override: Path | None) -> Path | None:
    if override:
        return override.resolve()
    candidates = [
        root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
        root / "inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv",
    ]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def compute_liquidity(
    root: Path, ranking: pd.DataFrame, source_date: str, run_id: str,
    generated_at: str, override: Path | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = liquidity_source(root, override)
    if not path:
        return pd.DataFrame(columns=LIQUIDITY_COLUMNS), {"status": "UNAVAILABLE"}
    columns = [str(column) for column in pd.read_csv(path, nrows=0).columns]
    ticker_col = first_column(columns, ("ticker", "symbol"))
    date_col = first_column(columns, ("as_of_date", "date", "price_date"))
    price_col = first_column(columns, ("adjusted_close", "close"))
    volume_col = first_column(columns, ("volume",))
    if not all((ticker_col, date_col, price_col, volume_col)):
        return pd.DataFrame(columns=LIQUIDITY_COLUMNS), {"status": "UNAVAILABLE", "path": path}
    frame = pd.read_csv(path, usecols=[ticker_col, date_col, price_col, volume_col], low_memory=False)
    frame["_ticker"] = frame[ticker_col].astype(str).str.strip().str.upper()
    tickers = set(ranking[first_column(list(ranking.columns), ("ticker", "symbol"))].astype(str).str.strip().str.upper())
    frame = frame[frame["_ticker"].isin(tickers)].copy()
    frame["_date"] = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
    source_ts = pd.Timestamp(source_date, tz="UTC")
    if frame["_date"].notna().any() and (frame["_date"] > source_ts).all():
        return pd.DataFrame(columns=LIQUIDITY_COLUMNS), {"status": "FUTURE_BLOCKED", "path": path}
    frame = frame[frame["_date"].notna() & (frame["_date"] <= source_ts)]
    frame["_price"] = pd.to_numeric(frame[price_col], errors="coerce")
    frame["_volume"] = pd.to_numeric(frame[volume_col], errors="coerce")
    frame = frame[(frame["_price"] > 0) & (frame["_volume"] >= 0)]
    frame = frame.sort_values(["_ticker", "_date"]).groupby("_ticker", group_keys=False).tail(20)
    frame["_dollar_volume"] = frame["_price"] * frame["_volume"]
    grouped = frame.groupby("_ticker").agg(
        liquidity_window_start=("_date", "min"),
        liquidity_window_end=("_date", "max"),
        liquidity_observation_count=("_dollar_volume", "count"),
        avg_dollar_volume=("_dollar_volume", "mean"),
        median_dollar_volume=("_dollar_volume", "median"),
    ).reset_index()
    grouped = grouped[grouped["liquidity_observation_count"] >= 5].copy()
    if grouped.empty:
        return pd.DataFrame(columns=LIQUIDITY_COLUMNS), {"status": "UNAVAILABLE", "path": path}
    grouped["liquidity_percentile_0_1"] = grouped["median_dollar_volume"].rank(pct=True, method="average")
    grouped["risk__liquidity_penalty"] = (1 - grouped["liquidity_percentile_0_1"]) * 100
    grouped["liquidity_warning_flag"] = grouped["liquidity_percentile_0_1"] <= 0.10
    grouped["run_id"] = run_id
    grouped["generated_at_utc"] = generated_at
    grouped["ticker"] = grouped["_ticker"]
    grouped["source_ranking_date"] = source_date
    grouped["liquidity_source_path"] = rel(root, path)
    grouped["liquidity_source_hash"] = sha256(path)
    grouped["liquidity_window_start"] = grouped["liquidity_window_start"].dt.date.astype(str)
    grouped["liquidity_window_end"] = grouped["liquidity_window_end"].dt.date.astype(str)
    grouped["liquidity_component_status"] = "AVAILABLE_DIAGNOSTIC_ONLY"
    grouped["warning"] = "DIAGNOSTIC_NOT_IN_ORIGINAL_D_SCORE"
    result = grouped.reindex(columns=LIQUIDITY_COLUMNS)
    return result, {
        "status": "AVAILABLE", "path": path, "hash": sha256(path),
        "column": "DERIVED_ADJUSTED_CLOSE_X_VOLUME_20D",
        "coverage": len(result), "coverage_ratio": len(result) / max(len(tickers), 1),
    }


def updated_drivers(row: pd.Series) -> tuple[list[str], list[str]]:
    positive: list[tuple[float, str]] = []
    negative: list[tuple[float, str]] = []
    existing_positive = [str(row.get(f"positive_driver_{i}", "")) for i in range(1, 4)]
    existing_negative = [str(row.get(f"negative_driver_{i}", "")) for i in range(1, 4)]
    for index, label in enumerate(existing_positive):
        if label and label != "nan":
            positive.append((30 - index, label))
    for index, label in enumerate(existing_negative):
        if label and label != "nan" and label != "COMPONENT_LINEAGE_PARTIAL":
            negative.append((30 - index, label))
    liquidity = pd.to_numeric(pd.Series([row.get("liquidity_percentile_0_1")]), errors="coerce").iloc[0]
    penalty = pd.to_numeric(pd.Series([row.get("risk__liquidity_penalty")]), errors="coerce").iloc[0]
    if pd.notna(liquidity) and liquidity >= 0.75:
        positive.append((50, "LIQUIDITY_STRONG"))
    if pd.notna(liquidity) and liquidity <= 0.10:
        negative.append((80, "LOW_LIQUIDITY_WARNING"))
    if pd.notna(penalty) and penalty >= 80:
        negative.append((70, "HIGH_LIQUIDITY_PENALTY"))
    qqq = str(row.get("regime__qqq_ma50_state", "")).upper()
    if "ABOVE" in qqq or "RISK_ON" in qqq:
        positive.append((45, "QQQ_MA50_REGIME_SUPPORTIVE"))
    elif qqq:
        negative.append((75, "QQQ_MA50_REGIME_HEADWIND"))
    else:
        negative.append((5, "REGIME_COMPONENT_UNAVAILABLE"))
    if row.get("explainability_status_r3") != "COMPLETE_EXPLAINABILITY":
        negative.append((4, "COMPONENT_LINEAGE_PARTIAL"))
        negative.append((3, "FAMILY_SCORE_LINEAGE_PARTIAL"))
    if pd.isna(penalty):
        negative.append((2, "LIQUIDITY_COMPONENT_UNAVAILABLE"))
    positive = sorted(positive, key=lambda item: (-item[0], item[1]))
    negative = sorted(negative, key=lambda item: (-item[0], item[1]))
    return (
        list(dict.fromkeys(label for _, label in positive))[:3],
        list(dict.fromkeys(label for _, label in negative))[:3],
    )


def driver_modes(frame: pd.DataFrame, side: str) -> list[str]:
    values = []
    for index in range(1, 4):
        values.extend(value for value in frame[f"{side}_driver_{index}"].fillna("").astype(str) if value)
    return [name for name, _ in sorted(Counter(values).items(), key=lambda item: (-item[1], item[0]))[:3]]


def make_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    eligible = ledger[ledger["eligible_flag"].map(as_bool)].sort_values("rank")
    rows = []
    for bucket, frame in (("TOP20", eligible.head(20)), ("TOP50", eligible.head(50)), ("ALL_ELIGIBLE", eligible)):
        drivers = frame[[f"{side}_driver_{i}" for side in ("positive", "negative") for i in range(1, 4)]]
        count = lambda label: int(drivers.eq(label).any(axis=1).sum())
        positive, negative = driver_modes(frame, "positive"), driver_modes(frame, "negative")
        row = {
            "bucket": bucket, "row_count": len(frame),
            "avg_final_score": pd.to_numeric(frame["final_score"], errors="coerce").mean(),
            "avg_component_coverage_ratio_r2": frame["component_coverage_ratio_r2"].mean(),
            "avg_component_coverage_ratio_r3": frame["component_coverage_ratio_r3"].mean(),
            "avg_component_coverage_delta": frame["component_coverage_delta"].mean(),
            "complete_explainability_count_r3": (frame["explainability_status_r3"] == "COMPLETE_EXPLAINABILITY").sum(),
            "partial_explainability_count_r3": (frame["explainability_status_r3"] != "COMPLETE_EXPLAINABILITY").sum(),
            "diagnostic_only_component_count": frame["diagnostic_component_not_in_original_score_flag"].map(as_bool).sum(),
            "family_component_coverage_count": frame[[f"repaired_{name}" for name in FAMILIES]].notna().any(axis=1).sum(),
            "technical_subfactor_coverage_count": frame[[name for name in ORIGINAL_EXPECTED if name.startswith("technical__")]].notna().any(axis=1).sum(),
            "risk_component_coverage_count": frame[["risk__overheat", "risk__volatility_penalty", "risk__liquidity_penalty"]].notna().any(axis=1).sum(),
            "regime_component_coverage_count": frame[["regime__risk_state", "regime__qqq_ma50_state"]].notna().any(axis=1).sum(),
            "data_trust_component_coverage_count": frame[["data_trust__warning_flag"]].notna().any(axis=1).sum(),
            "liquidity_component_available_count": frame["risk__liquidity_penalty"].notna().sum(),
            "low_liquidity_warning_count": frame["liquidity_warning_flag"].map(as_bool).sum(),
            "qqq_ma50_regime_mapped_count": frame["regime__qqq_ma50_state"].notna().sum(),
            "qqq_ma50_regime_supportive_count": count("QQQ_MA50_REGIME_SUPPORTIVE"),
            "qqq_ma50_regime_headwind_count": count("QQQ_MA50_REGIME_HEADWIND"),
            "overheat_warning_count": count("OVERHEAT_WARNING"),
            "bb_extension_warning_count": count("BB_EXTENSION_WARNING"),
        }
        row.update({f"top_positive_driver_{i + 1}": value for i, value in enumerate(positive)})
        row.update({f"top_negative_driver_{i + 1}": value for i, value in enumerate(negative)})
        rows.append(row)
    return pd.DataFrame(rows).reindex(columns=SUMMARY_COLUMNS)


def blocked(
    root: Path, output_dir: Path, generated_at: str, status: str,
    reason: str, paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in (
        (GAP_NAME, GAP_COLUMNS), (QQQ_NAME, QQQ_COLUMNS),
        (LIQUIDITY_NAME, LIQUIDITY_COLUMNS), (LEDGER_NAME, R3_COLUMNS),
        (SUMMARY_NAME, SUMMARY_COLUMNS),
    ):
        target = output_dir / name
        if not target.exists():
            pd.DataFrame(columns=columns).to_csv(target, index=False)
    paths = paths or {}
    validation = {
        "stage": STAGE, "final_status": status,
        "decision": "BLOCKED_REVIEW_R2_SOURCE_OR_COMPONENT_GAPS",
        "generated_at_utc": generated_at,
        "r2_validation_path": paths.get("r2_validation", ""),
        "r2_enriched_ledger_path": paths.get("r2_ledger", ""),
        "source_ranking_path": paths.get("source", ""),
        "source_ranking_hash": paths.get("hash", ""),
        "source_ranking_hash_verified": False,
        "component_gap_audit_path": rel(root, output_dir / GAP_NAME),
        "qqq_ma50_regime_ticker_map_path": rel(root, output_dir / QQQ_NAME),
        "liquidity_penalty_component_path": rel(root, output_dir / LIQUIDITY_NAME),
        "repaired_ledger_path": rel(root, output_dir / LEDGER_NAME),
        "repaired_summary_path": rel(root, output_dir / SUMMARY_NAME),
        "ranking_rows": 0, "r2_enriched_rows": 0, "r3_repaired_rows": 0,
        "eligible_rows": 0, "excluded_rows": 0,
        "r2_avg_component_coverage_ratio": 0, "r3_avg_component_coverage_ratio": 0,
        "component_coverage_delta": 0, "r2_top20_avg_component_coverage_ratio": 0,
        "r3_top20_avg_component_coverage_ratio": 0,
        "r2_top50_avg_component_coverage_ratio": 0,
        "r3_top50_avg_component_coverage_ratio": 0,
        "r3_complete_explainability_count": 0, "r3_partial_explainability_count": 0,
        "current_date_family_lineage_resolved_count": 0,
        "current_date_family_lineage_partial_count": 0,
        "qqq_ma50_regime_mapped_count": 0, "qqq_ma50_regime_unavailable_count": 0,
        "liquidity_component_available_count": 0,
        "liquidity_component_unavailable_count": 0,
        "low_liquidity_warning_count": 0, "ambiguous_component_count": 0,
        "date_mismatch_blocked_count": 0,
        "missing_expected_component_count": len(ALL_EXPECTED),
        "diagnostic_component_not_in_original_score_count": 0,
        "duplicate_ticker_count": 0, "row_count_integrity_pass": False,
        "official_mutation": False, "protected_outputs_modified": False,
        "research_only": True, "pass_gate": False, "validation_warning": reason,
    }
    pd.DataFrame([validation]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return validation


def run_stage(
    root: Path, r2_validation_override: Path | None = None,
    output_override: Path | None = None, qqq_override: Path | None = None,
    liquidity_override: Path | None = None, family_override: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id, generated_at = utc_now()
    try:
        r2_validation_path, r2, paths_obj = discover_r2(root, r2_validation_override)
    except FileNotFoundError as exc:
        return blocked(root, output_dir, generated_at, "BLOCKED_V21_067_R3_MISSING_R2_OR_SOURCE_RANKING", str(exc))
    paths = {
        "r2_validation": rel(root, r2_validation_path),
        "r2_ledger": rel(root, paths_obj["ledger"]),
        "source": rel(root, paths_obj["source"]),
        "hash": str(r2["source_ranking_hash"]),
    }
    actual_hash = sha256(paths_obj["source"])
    if actual_hash != str(r2["source_ranking_hash"]):
        return blocked(root, output_dir, generated_at, "BLOCKED_V21_067_R3_SOURCE_HASH_MISMATCH", "Source ranking SHA-256 mismatch", paths)
    ranking = pd.read_csv(paths_obj["source"], low_memory=False)
    r2_ledger = pd.read_csv(paths_obj["ledger"], low_memory=False)
    lineage = pd.read_csv(paths_obj["lineage"], low_memory=False)
    matrix = pd.read_csv(paths_obj["matrix"], low_memory=False)
    source_date, ticker_dates = source_dates(ranking)
    ticker_col = first_column(list(ranking.columns), ("ticker", "symbol"))
    tickers = set(ranking[ticker_col].astype(str).str.strip().str.upper())
    catalog_path = root / str(r2.get("lineage_catalog_path", ""))
    protected = protected_files(
        root, output_dir,
        [r2_validation_path, *paths_obj.values(), catalog_path],
    )
    before = snapshot(protected)

    candidates = family_candidates(root, catalog_path, family_override)
    family, ambiguous_count, date_blocked_count = resolve_families(root, candidates, tickers, ticker_dates)
    if ambiguous_count:
        return blocked(root, output_dir, generated_at, "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK", "Conflicting same-key family component values", paths)

    qqq_map, qqq_meta = resolve_qqq(root, ranking, source_date, qqq_override)
    if qqq_meta["status"] == "FUTURE_BLOCKED":
        return blocked(root, output_dir, generated_at, "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK", "Future-dated QQQ component would be required", paths)
    if qqq_meta["status"] == "AMBIGUOUS":
        return blocked(root, output_dir, generated_at, "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK", "Ambiguous QQQ regime state", paths)
    qqq_map.to_csv(output_dir / QQQ_NAME, index=False)

    liquidity, liquidity_meta = compute_liquidity(
        root, ranking, source_date, run_id, generated_at, liquidity_override
    )
    if liquidity_meta["status"] == "FUTURE_BLOCKED":
        return blocked(root, output_dir, generated_at, "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK", "Future-dated liquidity data would be required", paths)
    liquidity.to_csv(output_dir / LIQUIDITY_NAME, index=False)

    gap_rows = []
    for component in AUDIT_COMPONENTS:
        r2_status, r2_coverage = r2_state(matrix, component)
        if component in family:
            item = family[component]
            result, method = "RESOLVED" if item["confidence"] == "HIGH" else "PARTIAL", "EXACT_OR_LATEST_NON_FUTURE_TICKER_DATE"
            source_path, source_hash, column = rel(root, item["path"]), item["hash"], item["column"]
            coverage, coverage_ratio, confidence, warning = item["coverage"], item["coverage_ratio"], item["confidence"], item["warning"]
        elif component == "risk__liquidity_penalty" and liquidity_meta["status"] == "AVAILABLE":
            result, method = "AVAILABLE_DIAGNOSTIC_ONLY", "20_SESSION_DOLLAR_VOLUME_CROSS_SECTIONAL_PERCENTILE"
            source_path, source_hash, column = rel(root, liquidity_meta["path"]), liquidity_meta["hash"], liquidity_meta["column"]
            coverage, coverage_ratio, confidence, warning = liquidity_meta["coverage"], liquidity_meta["coverage_ratio"], "HIGH", "NOT_IN_ORIGINAL_D_SCORE"
        elif component == "regime__qqq_ma50_state" and qqq_meta["status"] == "MAPPED":
            result, method = "MAPPED_DIAGNOSTIC_ONLY", "MARKET_WIDE_NON_FUTURE_QQQ_STATE_TICKER_MAP"
            source_path, source_hash, column = rel(root, qqq_meta["path"]), qqq_meta["hash"], qqq_meta["column"]
            coverage, coverage_ratio, confidence, warning = qqq_meta["coverage"], qqq_meta["coverage"] / max(len(tickers), 1), "HIGH", "MARKET_WIDE_NOT_TICKER_SPECIFIC"
        else:
            selected = lineage[lineage["component_name"] == component]
            row = selected.iloc[0] if not selected.empty else {}
            result, method = "UNCHANGED_R2" if not selected.empty else "UNAVAILABLE", "R2_LINEAGE_RETAINED"
            source_path = str(row.get("selected_source_path", ""))
            source_hash = str(row.get("selected_source_hash", ""))
            column = str(row.get("selected_column_name", ""))
            coverage = int(pd.to_numeric(row.get("coverage_count", 0), errors="coerce") or 0)
            coverage_ratio = float(pd.to_numeric(row.get("coverage_ratio", 0), errors="coerce") or 0)
            confidence, warning = str(row.get("lineage_confidence", "")), str(row.get("warning", ""))
        gap_rows.append({
            "run_id": run_id, "generated_at_utc": generated_at,
            "component_name": component,
            "component_type": "family" if component in FAMILIES else component.split("__")[0],
            "r2_status": r2_status, "r2_coverage_ratio": r2_coverage,
            "gap_type": "PARTIAL_LINEAGE" if r2_status.startswith("AVAILABLE") else r2_status,
            "repair_attempted": component in FAMILIES or component in DIAGNOSTIC_EXPECTED,
            "repair_method": method, "repair_result": result,
            "selected_source_path": source_path, "selected_source_hash": source_hash,
            "selected_column_name": column, "coverage_count": coverage,
            "coverage_ratio": coverage_ratio, "null_count": len(tickers) - coverage,
            "confidence": confidence, "warning": warning,
        })
    pd.DataFrame(gap_rows).reindex(columns=GAP_COLUMNS).to_csv(output_dir / GAP_NAME, index=False)

    repaired = r2_ledger.copy()
    repaired["ticker"] = repaired["ticker"].astype(str).str.strip().str.upper()
    for component in FAMILIES:
        repaired_name = f"repaired_{component}"
        repaired[repaired_name] = repaired["ticker"].map(family[component]["values"]) if component in family else repaired.get(component)
    qqq_values = dict(zip(qqq_map["ticker"], qqq_map["regime__qqq_ma50_state"])) if not qqq_map.empty else {}
    repaired["regime__qqq_ma50_state"] = repaired["ticker"].map(qqq_values)
    repaired["regime__qqq_ma50_component_scope"] = (
        "MARKET_WIDE_MAPPED_TO_TICKER_UNIVERSE" if qqq_values else ""
    )
    if not liquidity.empty:
        liq_index = liquidity.set_index("ticker")
        for column in ("risk__liquidity_penalty", "liquidity_percentile_0_1", "liquidity_warning_flag"):
            repaired[column] = repaired["ticker"].map(liq_index[column])
    else:
        for column in ("risk__liquidity_penalty", "liquidity_percentile_0_1", "liquidity_warning_flag"):
            repaired[column] = pd.NA
    repaired["component_coverage_ratio_r2"] = pd.to_numeric(repaired["component_coverage_ratio"], errors="coerce")
    effective = repaired.copy()
    for component in FAMILIES:
        effective[component] = repaired[f"repaired_{component}"].combine_first(repaired[component])
    repaired["component_coverage_ratio_r3"] = effective[ALL_EXPECTED].notna().sum(axis=1) / len(ALL_EXPECTED)
    repaired["component_coverage_delta"] = repaired["component_coverage_ratio_r3"] - repaired["component_coverage_ratio_r2"]
    original_complete = effective[ORIGINAL_EXPECTED].notna().all(axis=1)
    diagnostic_available = effective[DIAGNOSTIC_EXPECTED].notna().any(axis=1)
    repaired["explainability_status_r3"] = original_complete.map(
        {True: "COMPLETE_EXPLAINABILITY", False: "PARTIAL_EXPLAINABILITY"}
    )
    repaired["complete_explainability_reason"] = original_complete.map(
        {True: "ALL_ORIGINAL_SCORING_COMPONENTS_AVAILABLE_OR_ONLY_DIAGNOSTIC_GAPS", False: ""}
    )
    repaired["partial_explainability_reason"] = original_complete.map(
        {True: "", False: "COMPONENT_LINEAGE_PARTIAL"}
    )
    repaired["diagnostic_component_not_in_original_score_flag"] = diagnostic_available
    repaired["component_gap_closure_status"] = [
        "DIAGNOSTIC_ONLY_COMPONENT_AVAILABLE" if diagnostic and not complete
        else "COMPLETE_EXPLAINABILITY" if complete
        else "COMPONENT_LINEAGE_PARTIAL"
        for complete, diagnostic in zip(original_complete, diagnostic_available)
    ]
    for column in (
        "positive_driver_1", "positive_driver_2", "positive_driver_3",
        "negative_driver_1", "negative_driver_2", "negative_driver_3",
    ):
        repaired[column] = repaired[column].astype("object")
    for index, row in repaired.iterrows():
        positive, negative = updated_drivers(row)
        for number in range(3):
            repaired.at[index, f"positive_driver_{number + 1}"] = positive[number] if number < len(positive) else ""
            repaired.at[index, f"negative_driver_{number + 1}"] = negative[number] if number < len(negative) else ""
    repaired.to_csv(output_dir / LEDGER_NAME, index=False)
    summary = make_summary(repaired)
    summary.to_csv(output_dir / SUMMARY_NAME, index=False)

    after = snapshot(protected)
    changed = [path for path, value in before.items() if after.get(path) != value]
    duplicate_count = int(repaired["ticker"].duplicated().sum())
    integrity = len(ranking) == len(r2_ledger) == len(repaired) and duplicate_count <= int(r2_ledger["ticker"].duplicated().sum())
    top20 = summary[summary["bucket"] == "TOP20"].iloc[0]
    top50 = summary[summary["bucket"] == "TOP50"].iloc[0]
    complete_count = int((repaired["explainability_status_r3"] == "COMPLETE_EXPLAINABILITY").sum())
    partial_count = len(repaired) - complete_count
    improvement = bool(qqq_values) or not liquidity.empty or any(item["confidence"] == "HIGH" for item in family.values())
    pass_gate = integrity and improvement and not changed
    unresolved_family = sum(item["confidence"] != "HIGH" for item in family.values()) + (len(FAMILIES) - len(family))
    if changed:
        status = "BLOCKED_V21_067_R3_MUTATION_RISK"
        decision = "BLOCKED_REVIEW_R2_SOURCE_OR_COMPONENT_GAPS"
    elif not integrity:
        status = "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK"
        decision = "BLOCKED_REVIEW_R2_SOURCE_OR_COMPONENT_GAPS"
    elif unresolved_family or partial_count:
        status = "PARTIAL_PASS_V21_067_R3_COMPONENT_GAP_CLOSURE_READY_WITH_REMAINING_WARNINGS"
        decision = "COMPONENT_GAP_CLOSURE_PARTIAL_READY_FOR_WEIGHT_PERTURBATION_WITH_WARNINGS_RESEARCH_ONLY"
    else:
        status = "PASS_V21_067_R3_COMPONENT_GAP_CLOSURE_READY"
        decision = "COMPONENT_GAP_CLOSURE_READY_FOR_WEIGHT_PERTURBATION_RESEARCH_ONLY"
    validation = {
        "stage": STAGE, "final_status": status, "decision": decision,
        "generated_at_utc": generated_at,
        "r2_validation_path": rel(root, r2_validation_path),
        "r2_enriched_ledger_path": rel(root, paths_obj["ledger"]),
        "source_ranking_path": rel(root, paths_obj["source"]),
        "source_ranking_hash": actual_hash, "source_ranking_hash_verified": True,
        "component_gap_audit_path": rel(root, output_dir / GAP_NAME),
        "qqq_ma50_regime_ticker_map_path": rel(root, output_dir / QQQ_NAME),
        "liquidity_penalty_component_path": rel(root, output_dir / LIQUIDITY_NAME),
        "repaired_ledger_path": rel(root, output_dir / LEDGER_NAME),
        "repaired_summary_path": rel(root, output_dir / SUMMARY_NAME),
        "ranking_rows": len(ranking), "r2_enriched_rows": len(r2_ledger),
        "r3_repaired_rows": len(repaired),
        "eligible_rows": int(repaired["eligible_flag"].map(as_bool).sum()),
        "excluded_rows": int((~repaired["eligible_flag"].map(as_bool)).sum()),
        "r2_avg_component_coverage_ratio": float(r2["avg_component_coverage_ratio"]),
        "r3_avg_component_coverage_ratio": repaired["component_coverage_ratio_r3"].mean(),
        "component_coverage_delta": repaired["component_coverage_delta"].mean(),
        "r2_top20_avg_component_coverage_ratio": float(r2["top20_avg_component_coverage_ratio"]),
        "r3_top20_avg_component_coverage_ratio": top20["avg_component_coverage_ratio_r3"],
        "r2_top50_avg_component_coverage_ratio": float(r2["top50_avg_component_coverage_ratio"]),
        "r3_top50_avg_component_coverage_ratio": top50["avg_component_coverage_ratio_r3"],
        "r3_complete_explainability_count": complete_count,
        "r3_partial_explainability_count": partial_count,
        "current_date_family_lineage_resolved_count": sum(item["confidence"] == "HIGH" for item in family.values()),
        "current_date_family_lineage_partial_count": unresolved_family,
        "qqq_ma50_regime_mapped_count": len(qqq_map),
        "qqq_ma50_regime_unavailable_count": len(ranking) - len(qqq_map),
        "liquidity_component_available_count": len(liquidity),
        "liquidity_component_unavailable_count": len(ranking) - len(liquidity),
        "low_liquidity_warning_count": int(liquidity["liquidity_warning_flag"].map(as_bool).sum()) if not liquidity.empty else 0,
        "ambiguous_component_count": ambiguous_count,
        "date_mismatch_blocked_count": date_blocked_count,
        "missing_expected_component_count": int(effective[ALL_EXPECTED].isna().all(axis=0).sum()),
        "diagnostic_component_not_in_original_score_count": int(repaired["diagnostic_component_not_in_original_score_flag"].map(as_bool).sum()),
        "duplicate_ticker_count": duplicate_count, "row_count_integrity_pass": integrity,
        "official_mutation": False, "protected_outputs_modified": bool(changed),
        "research_only": True, "pass_gate": pass_gate,
        "protected_modified_paths": "|".join(changed),
    }
    pd.DataFrame([validation]).to_csv(output_dir / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--r2-validation-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--qqq-source", type=Path)
    parser.add_argument("--liquidity-source", type=Path)
    parser.add_argument("--family-source", type=Path)
    args = parser.parse_args()
    result = run_stage(
        args.root, args.r2_validation_path, args.output_dir,
        args.qqq_source, args.liquidity_source, args.family_source,
    )
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"R2_AVG_COMPONENT_COVERAGE_RATIO={result['r2_avg_component_coverage_ratio']}")
    print(f"R3_AVG_COMPONENT_COVERAGE_RATIO={result['r3_avg_component_coverage_ratio']}")
    print(f"R3_COMPLETE/PARTIAL={result['r3_complete_explainability_count']}/{result['r3_partial_explainability_count']}")
    print(f"QQQ_MA50_MAPPED_COUNT={result['qqq_ma50_regime_mapped_count']}")
    print(f"LIQUIDITY_AVAILABLE_COUNT={result['liquidity_component_available_count']}")
    print(f"MISSING_EXPECTED_COMPONENT_COUNT={result['missing_expected_component_count']}")
    print(f"VALIDATION_SUMMARY={(args.output_dir or OUT_REL) / VALIDATION_NAME}")
    return 1 if str(result["final_status"]).startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
