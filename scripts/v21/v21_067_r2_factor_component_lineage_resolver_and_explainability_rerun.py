#!/usr/bin/env python
"""Resolve V21 factor-component lineage and enrich the R1 explanation ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


STAGE = "V21.067-R2_FACTOR_COMPONENT_LINEAGE_RESOLVER_AND_EXPLAINABILITY_RERUN"
OUT_REL = Path("outputs/v21/explainability")
R1_VALIDATION_NAME = "V21_067_R1_VALIDATION_SUMMARY.csv"
R1_LEDGER_NAME = "V21_067_R1_FACTOR_EXPLAINABILITY_LEDGER.csv"
CATALOG_NAME = "V21_067_R2_FACTOR_COMPONENT_LINEAGE_CATALOG.csv"
MAP_NAME = "V21_067_R2_SELECTED_COMPONENT_LINEAGE_MAP.csv"
LEDGER_NAME = "V21_067_R2_FACTOR_EXPLAINABILITY_LEDGER_ENRICHED.csv"
SUMMARY_NAME = "V21_067_R2_TOP_BUCKET_EXPLAINABILITY_SUMMARY_ENRICHED.csv"
MATRIX_NAME = "V21_067_R2_COMPONENT_AVAILABILITY_MATRIX.csv"
VALIDATION_NAME = "V21_067_R2_VALIDATION_SUMMARY.csv"

COMPONENTS = {
    "base_score_raw": ("family", ("base_score_raw", "base_score", "baseline_score")),
    "momentum_score_raw": ("family", ("momentum_score_raw", "momentum_score", "momentum_leadership_score")),
    "fundamental_score_raw": ("family", ("fundamental_score_raw", "fundamental_score", "normalized_fundamental_score")),
    "technical_score_raw": ("family", ("technical_score_raw", "technical_score", "technical_score_normalized", "normalized_technical_score")),
    "strategy_score_raw": ("family", ("strategy_score_raw", "strategy_score", "normalized_strategy_score")),
    "risk_score_raw": ("family", ("risk_score_raw", "risk_score", "exhaustion_risk_score", "normalized_risk_score")),
    "market_regime_score_raw": ("family", ("market_regime_score_raw", "market_regime_score", "regime_score", "normalized_market_regime_score")),
    "data_trust_score_raw": ("family", ("data_trust_score_raw", "data_trust_score", "normalized_data_trust_score")),
    "technical__rsi": ("technical", ("technical__rsi", "rsi_14", "rsi")),
    "technical__kdj": ("technical", ("technical__kdj", "kdj_j", "kdj_k", "kdj_d")),
    "technical__macd": ("technical", ("technical__macd", "macd_hist", "macd_line")),
    "technical__bb": ("technical", ("technical__bb", "bb_position", "bb_width")),
    "technical__ma20": ("technical", ("technical__ma20", "ma20_distance", "price_above_ma20", "ma20")),
    "technical__ma50": ("technical", ("technical__ma50", "ma50_distance", "price_above_ma50", "ma50")),
    "technical__ema": ("technical", ("technical__ema", "ema20_distance", "ema20", "ema")),
    "technical__volume": ("technical", ("technical__volume", "volume_ratio", "volume_ratio_5d_vs_20d", "volume_trend_5")),
    "technical__volatility": ("technical", ("technical__volatility", "volatility_20", "volatility")),
    "technical__relative_strength": ("technical", ("technical__relative_strength", "relative_momentum_score", "excess_return_20d_vs_qqq")),
    "technical__breakout": ("technical", ("technical__breakout", "breakout_status", "breakout_score")),
    "technical__pullback": ("technical", ("technical__pullback", "pullback_status", "pullback_score")),
    "risk__overheat": ("risk", ("risk__overheat", "overheat_extension_score", "overheat_status", "extension_awareness_flag")),
    "risk__volatility_penalty": ("risk", ("risk__volatility_penalty", "volatility_penalty", "volatility_20")),
    "risk__liquidity_penalty": ("risk", ("risk__liquidity_penalty", "liquidity_penalty", "liquidity_risk_score")),
    "regime__qqq_ma50_state": ("regime", ("regime__qqq_ma50_state", "qqq_ma50_state", "qqq_state")),
    "regime__risk_state": ("regime", ("regime__risk_state", "risk_state", "market_regime")),
    "data_trust__warning_flag": ("data_trust", ("data_trust__warning_flag", "data_trust_warning", "data_warning_flag", "price_date_warning", "local_history_gap_flag")),
}
BASE_COMPONENTS = {"base_score_raw", "momentum_score_raw"}
EXPECTED = list(COMPONENTS)
FAMILY_COMPONENTS = [name for name, (kind, _) in COMPONENTS.items() if kind == "family" and name not in BASE_COMPONENTS]
TECHNICAL_COMPONENTS = [name for name, (kind, _) in COMPONENTS.items() if kind == "technical"]
RISK_COMPONENTS = [name for name, (kind, _) in COMPONENTS.items() if kind == "risk"]
REGIME_COMPONENTS = [name for name, (kind, _) in COMPONENTS.items() if kind == "regime"]
TRUST_COMPONENTS = [name for name, (kind, _) in COMPONENTS.items() if kind == "data_trust"]

CATALOG_COLUMNS = [
    "run_id", "generated_at_utc", "candidate_file_path", "candidate_file_hash",
    "file_modified_utc", "row_count", "column_count", "detected_ticker_column",
    "detected_date_column", "detected_rank_column", "detected_score_columns",
    "detected_weight_columns", "detected_family_columns",
    "detected_technical_subfactor_columns", "detected_risk_columns",
    "detected_regime_columns", "detected_data_trust_columns",
    "component_category", "usable_for_merge", "merge_key_type",
    "lineage_confidence", "rejection_reason",
]
MAP_COLUMNS = [
    "run_id", "generated_at_utc", "component_name", "component_type",
    "selected_source_path", "selected_source_hash", "selected_column_name",
    "normalized_output_column_name", "merge_key_type", "coverage_count",
    "coverage_ratio", "null_count", "lineage_confidence", "selection_reason",
    "warning",
]
ENRICHMENT_COLUMNS = [
    "component_lineage_resolved", "component_lineage_quality",
    "component_coverage_ratio", "selected_component_count",
    "selected_family_component_count", "selected_technical_subfactor_count",
    "selected_risk_component_count", "selected_regime_component_count",
    "selected_data_trust_component_count", "component_merge_warning",
    "family_explainability_status", "technical_subfactor_explainability_status",
    "risk_explainability_status", "regime_explainability_status",
    "data_trust_explainability_status",
]
SUMMARY_COLUMNS = [
    "bucket", "row_count", "avg_final_score", "avg_base_contribution",
    "avg_momentum_contribution", "avg_component_coverage_ratio",
    "complete_explainability_count", "partial_explainability_count",
    "family_component_coverage_count", "technical_subfactor_coverage_count",
    "risk_component_coverage_count", "regime_component_coverage_count",
    "data_trust_component_coverage_count", "momentum_led_count",
    "base_led_count", "technical_led_count", "fundamental_led_count",
    "risk_warning_count", "overheat_warning_count",
    "data_trust_warning_count", "regime_headwind_count",
    "top_positive_driver_1", "top_positive_driver_2",
    "top_positive_driver_3", "top_negative_driver_1",
    "top_negative_driver_2", "top_negative_driver_3",
]


def now_utc() -> tuple[str, str]:
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


def first_column(columns: list[str], aliases: tuple[str, ...]) -> str:
    lookup = {str(column).lower(): str(column) for column in columns}
    return next((lookup[name.lower()] for name in aliases if name.lower() in lookup), "")


def discover_r1(root: Path, validation_override: Path | None = None) -> tuple[Path, Path, pd.Series]:
    if validation_override:
        candidates = [validation_override if validation_override.is_absolute() else root / validation_override]
    else:
        candidates = sorted(
            (root / "outputs/v21/explainability").rglob(R1_VALIDATION_NAME),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    for validation_path in candidates:
        try:
            row = pd.read_csv(validation_path).iloc[0]
        except (OSError, ValueError, IndexError):
            continue
        if not str(row.get("final_status", "")).startswith(("PASS_", "PARTIAL_PASS_")):
            continue
        if not as_bool(row.get("research_only")) or as_bool(row.get("official_mutation")):
            continue
        if as_bool(row.get("protected_outputs_modified")):
            continue
        ledger_value = str(row.get("output_ledger_path", "")).strip()
        ledger_path = root / ledger_value if ledger_value else validation_path.parent / R1_LEDGER_NAME
        if ledger_path.is_file():
            return validation_path.resolve(), ledger_path.resolve(), row
    raise FileNotFoundError("Successful research-only V21.067-R1 artifacts not found")


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


def relevant_columns(columns: list[str]) -> dict[str, list[str]]:
    lower = {column: column.lower() for column in columns}
    score = [c for c, value in lower.items() if "score" in value]
    weight = [c for c, value in lower.items() if "weight" in value]
    family = [c for c, value in lower.items() if any(x in value for x in ("fundamental", "technical_score", "strategy", "risk_score", "regime_score", "data_trust"))]
    technical = [c for c, value in lower.items() if any(x in value for x in ("rsi", "kdj", "macd", "bb_", "bollinger", "ma20", "ma50", "ema", "volume", "volatility", "relative_strength", "relative_momentum", "breakout", "pullback"))]
    risk = [c for c, value in lower.items() if any(x in value for x in ("risk", "overheat", "exhaustion", "liquidity", "volatility_penalty"))]
    regime = [c for c, value in lower.items() if any(x in value for x in ("regime", "qqq_state", "qqq_ma50"))]
    trust = [c for c, value in lower.items() if any(x in value for x in ("data_trust", "warning_flag", "history_gap", "price_date_warning", "eligible"))]
    return {"score": score, "weight": weight, "family": family, "technical": technical, "risk": risk, "regime": regime, "trust": trust}


def scan_catalog(
    root: Path, scan_root: Path, run_id: str, generated_at: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows = []
    metadata = []
    if not scan_root.exists():
        return pd.DataFrame(columns=CATALOG_COLUMNS), metadata
    for path in sorted(scan_root.rglob("*.csv")):
        if path.name.startswith("V21_067_R2_"):
            continue
        try:
            header = pd.read_csv(path, nrows=0)
            columns = [str(column) for column in header.columns]
            with path.open("rb") as handle:
                row_count = max(sum(1 for _ in handle) - 1, 0)
        except (OSError, ValueError, UnicodeError):
            continue
        ticker = first_column(columns, ("ticker", "symbol"))
        date = first_column(columns, ("as_of_date", "snapshot_date", "latest_price_date", "date", "observation_date"))
        rank = first_column(columns, ("rank", "final_shadow_rank", "final_rank"))
        detected = relevant_columns(columns)
        matched = {
            component: first_column(columns, aliases)
            for component, (_, aliases) in COMPONENTS.items()
        }
        matched = {component: column for component, column in matched.items() if column}
        categories = sorted({COMPONENTS[name][0] for name in matched})
        usable = bool(ticker and matched)
        confidence = "HIGH" if usable and date else "PARTIAL" if usable else "NONE"
        rejection = "" if usable else "NO_TICKER_OR_RECOGNIZED_COMPONENT_COLUMN"
        stat = path.stat()
        rows.append({
            "run_id": run_id, "generated_at_utc": generated_at,
            "candidate_file_path": rel(root, path),
            "candidate_file_hash": sha256(path),
            "file_modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "row_count": row_count, "column_count": len(columns),
            "detected_ticker_column": ticker, "detected_date_column": date,
            "detected_rank_column": rank,
            "detected_score_columns": "|".join(detected["score"]),
            "detected_weight_columns": "|".join(detected["weight"]),
            "detected_family_columns": "|".join(detected["family"]),
            "detected_technical_subfactor_columns": "|".join(detected["technical"]),
            "detected_risk_columns": "|".join(detected["risk"]),
            "detected_regime_columns": "|".join(detected["regime"]),
            "detected_data_trust_columns": "|".join(detected["trust"]),
            "component_category": "|".join(categories),
            "usable_for_merge": usable,
            "merge_key_type": "TICKER_DATE" if ticker and date else "TICKER" if ticker else "",
            "lineage_confidence": confidence, "rejection_reason": rejection,
        })
        metadata.append({
            "path": path.resolve(), "hash": rows[-1]["candidate_file_hash"],
            "ticker": ticker, "date": date, "matched": matched,
            "modified": stat.st_mtime,
        })
    return pd.DataFrame(rows).reindex(columns=CATALOG_COLUMNS), metadata


def ranking_dates(ranking: pd.DataFrame) -> tuple[dict[str, pd.Timestamp], pd.Timestamp | None]:
    ticker_col = first_column(list(ranking.columns), ("ticker", "symbol"))
    date_col = first_column(list(ranking.columns), ("latest_price_date", "as_of_date", "snapshot_date", "date"))
    if not ticker_col or not date_col:
        return {}, None
    tickers = ranking[ticker_col].astype(str).str.strip().str.upper()
    dates = pd.to_datetime(ranking[date_col], errors="coerce", utc=True)
    mapping = {ticker: date for ticker, date in zip(tickers, dates) if pd.notna(date)}
    return mapping, max(mapping.values(), default=None)


def normalize_value(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        return numeric
    return series.astype("string").replace({"": pd.NA, "nan": pd.NA})


def resolve_candidate(
    meta: dict[str, Any], component: str, tickers: set[str],
    ticker_dates: dict[str, pd.Timestamp], global_date: pd.Timestamp | None,
    cache: dict[Path, pd.DataFrame],
) -> dict[str, Any]:
    path, ticker_col, date_col = meta["path"], meta["ticker"], meta["date"]
    column = meta["matched"][component]
    if path not in cache:
        usecols = list(dict.fromkeys(
            [ticker_col, date_col, *meta["matched"].values()]
            if date_col else [ticker_col, *meta["matched"].values()]
        ))
        try:
            cache[path] = pd.read_csv(path, usecols=usecols, low_memory=False)
        except (OSError, ValueError) as exc:
            return {"usable": False, "reason": f"READ_FAILURE:{exc}"}
    frame = cache[path][
        list(dict.fromkeys([ticker_col, date_col, column] if date_col else [ticker_col, column]))
    ].copy()
    frame["_ticker"] = frame[ticker_col].astype(str).str.strip().str.upper()
    frame = frame[frame["_ticker"].isin(tickers)].copy()
    frame["_value"] = normalize_value(frame[column])
    frame = frame[frame["_value"].notna()]
    if frame.empty:
        return {"usable": False, "reason": "NO_NON_NULL_TARGET_TICKER_COVERAGE"}
    warning = ""
    exact_count = 0
    if date_col:
        frame["_date"] = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
        target = frame["_ticker"].map(ticker_dates)
        if global_date is not None:
            target = target.fillna(global_date)
        future = frame["_date"].notna() & target.notna() & (frame["_date"] > target)
        frame = frame[~future].copy()
        if frame.empty:
            return {"usable": False, "reason": "DATE_MISMATCH_BLOCKED", "date_blocked": True}
        frame["_exact"] = frame["_date"].eq(frame["_ticker"].map(ticker_dates))
        exact_count = int(frame["_exact"].sum())
        frame = frame.sort_values(["_ticker", "_exact", "_date"], ascending=[True, False, False])
        best = frame.groupby("_ticker", sort=False).head(1)
        keys = ["_ticker", "_date"]
        best_keys = best[keys].drop_duplicates()
        contenders = frame.merge(best_keys, on=keys, how="inner")
        ambiguous = contenders.groupby(keys)["_value"].nunique(dropna=True).gt(1).any()
        if ambiguous:
            return {"usable": False, "reason": "COMPONENT_MERGE_AMBIGUITY", "ambiguous": True}
        selected = best.drop_duplicates("_ticker", keep="first")
        merge_key = "TICKER_DATE_EXACT_OR_LATEST_NON_FUTURE"
        confidence = "HIGH" if exact_count == len(selected) else "PARTIAL"
        if confidence == "PARTIAL":
            warning = "LATEST_NON_FUTURE_DATE_USED_FOR_PARTIAL_ROWS"
    else:
        ambiguous = frame.groupby("_ticker")["_value"].nunique(dropna=True).gt(1).any()
        if ambiguous:
            return {"usable": False, "reason": "COMPONENT_MERGE_AMBIGUITY", "ambiguous": True}
        selected = frame.drop_duplicates("_ticker", keep="last")
        merge_key = "TICKER_ONLY"
        confidence = "PARTIAL"
        warning = "TICKER_ONLY_NO_DATE_LINEAGE"
    values = dict(zip(selected["_ticker"], selected["_value"]))
    coverage = len(values)
    return {
        "usable": coverage > 0, "values": values, "coverage": coverage,
        "coverage_ratio": coverage / max(len(tickers), 1),
        "null_count": len(tickers) - coverage, "merge_key": merge_key,
        "confidence": confidence, "warning": warning, "column": column,
        "exact_count": exact_count, "reason": "BEST_DATE_SAFE_COVERAGE",
    }


def select_components(
    root: Path, metadata: list[dict[str, Any]], tickers: set[str],
    ticker_dates: dict[str, pd.Timestamp], global_date: pd.Timestamp | None,
    run_id: str, generated_at: str,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], dict[str, str]]:
    selected: dict[str, dict[str, Any]] = {}
    states: dict[str, str] = {}
    rows = []
    cache: dict[Path, pd.DataFrame] = {}
    for component, (kind, _) in COMPONENTS.items():
        candidates = []
        ambiguous = False
        date_blocked = False
        found = False
        for meta in metadata:
            if component not in meta["matched"]:
                continue
            found = True
            result = resolve_candidate(
                meta, component, tickers, ticker_dates, global_date, cache
            )
            ambiguous |= bool(result.get("ambiguous"))
            date_blocked |= bool(result.get("date_blocked"))
            if result.get("usable"):
                score = (
                    1 if result["confidence"] == "HIGH" else 0,
                    result["exact_count"], result["coverage_ratio"], meta["modified"],
                    rel(root, meta["path"]),
                )
                candidates.append((score, meta, result))
        if candidates:
            _, meta, result = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
            selected[component] = {**result, "meta": meta, "type": kind}
            states[component] = "AVAILABLE_HIGH_CONFIDENCE" if result["confidence"] == "HIGH" else "AVAILABLE_PARTIAL_CONFIDENCE"
            rows.append({
                "run_id": run_id, "generated_at_utc": generated_at,
                "component_name": component, "component_type": kind,
                "selected_source_path": rel(root, meta["path"]),
                "selected_source_hash": meta["hash"],
                "selected_column_name": result["column"],
                "normalized_output_column_name": component,
                "merge_key_type": result["merge_key"],
                "coverage_count": result["coverage"],
                "coverage_ratio": result["coverage_ratio"],
                "null_count": result["null_count"],
                "lineage_confidence": result["confidence"],
                "selection_reason": result["reason"], "warning": result["warning"],
            })
        elif ambiguous:
            states[component] = "AMBIGUOUS_BLOCKED"
        elif date_blocked:
            states[component] = "DATE_MISMATCH_BLOCKED"
        elif found:
            states[component] = "FOUND_BUT_NOT_SELECTED"
        else:
            states[component] = "MISSING"
    return pd.DataFrame(rows).reindex(columns=MAP_COLUMNS), selected, states


def status_for(row: pd.Series, components: list[str]) -> str:
    count = sum(pd.notna(row.get(component)) for component in components)
    return "COMPLETE" if count == len(components) else "PARTIAL" if count else "MISSING"


def numeric(value: Any) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def truthish(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "YES", "Y", "1", "WARNING", "HIGH", "OVERHEAT", "EXTENDED"}


def enriched_drivers(row: pd.Series) -> tuple[list[str], list[str]]:
    positive: list[tuple[float, str]] = []
    negative: list[tuple[float, str]] = []
    for column, label in (
        ("momentum_contribution", "MOMENTUM_STRONG"),
        ("base_contribution", "BASE_SCORE_STRONG"),
        ("fundamental_score_raw", "FUNDAMENTAL_STRONG"),
        ("technical_score_raw", "TECHNICAL_STRONG"),
    ):
        value = numeric(row.get(column))
        if value is not None:
            positive.append((value, label))
    rules = {
        "technical__rsi": ("RSI_SUPPORTIVE", "RSI_OVERHEAT_OR_WEAK", 45, 75),
        "technical__kdj": ("KDJ_SUPPORTIVE", "KDJ_WEAK", 50, 20),
        "technical__macd": ("MACD_SUPPORTIVE", "MACD_WEAK", 0, 0),
        "technical__bb": ("BB_SUPPORTIVE", "BB_EXTENSION_WARNING", 0.35, 1.0),
        "technical__ma20": ("MA_TREND_SUPPORTIVE", "TECHNICAL_WEAK", 0, 0),
        "technical__ma50": ("MA_TREND_SUPPORTIVE", "TECHNICAL_WEAK", 0, 0),
        "technical__volume": ("VOLUME_SUPPORTIVE", "TECHNICAL_WEAK", 1, 0.7),
        "technical__relative_strength": ("RELATIVE_STRENGTH_STRONG", "TECHNICAL_WEAK", 50, 20),
    }
    for column, (good, bad, high, low) in rules.items():
        value = numeric(row.get(column))
        if value is None:
            continue
        if value >= high:
            positive.append((abs(value), good))
        if (column == "technical__rsi" and (value >= 75 or value < 30)) or (
            column != "technical__rsi" and value < low
        ):
            negative.append((abs(value - low), bad))
    for column, label in (
        ("technical__breakout", "BREAKOUT_SUPPORTIVE"),
        ("technical__pullback", "PULLBACK_SETUP_SUPPORTIVE"),
    ):
        value = row.get(column)
        if pd.notna(value) and ("MATCH" in str(value).upper() or truthish(value)):
            positive.append((1, label))
    risk = numeric(row.get("risk_score_raw"))
    if risk is not None and risk >= 40:
        negative.append((risk, "RISK_PENALTY_HIGH"))
    if truthish(row.get("risk__overheat")) or (numeric(row.get("risk__overheat")) or 0) >= 60:
        negative.append((80, "OVERHEAT_WARNING"))
    if (numeric(row.get("risk__volatility_penalty")) or 0) >= 40:
        negative.append((60, "VOLATILITY_WARNING"))
    if (numeric(row.get("risk__liquidity_penalty")) or 0) >= 40:
        negative.append((60, "LIQUIDITY_WARNING"))
    trust_warning = row.get("data_trust__warning_flag")
    if pd.notna(trust_warning):
        if truthish(trust_warning):
            negative.append((70, "DATA_TRUST_WARNING"))
        else:
            positive.append((5, "DATA_TRUST_CLEAN"))
    regime = str(row.get("regime__risk_state", "")).upper()
    qqq = str(row.get("regime__qqq_ma50_state", "")).upper()
    if any(token in regime + qqq for token in ("RISK_OFF", "BELOW")):
        negative.append((70, "REGIME_HEADWIND"))
    elif regime or qqq:
        positive.append((5, "REGIME_SUPPORTIVE"))
    if float(row.get("component_coverage_ratio", 0)) < 0.5:
        negative.append((2, "LOW_COMPONENT_COVERAGE"))
    if row.get("component_lineage_quality") != "COMPLETE":
        negative.append((1, "COMPONENT_LINEAGE_PARTIAL"))
    if "AMBIGU" in str(row.get("component_merge_warning", "")).upper():
        negative.append((100, "COMPONENT_MERGE_AMBIGUITY"))
    positive = sorted(positive, key=lambda item: (-item[0], item[1]))
    negative = sorted(negative, key=lambda item: (-item[0], item[1]))
    return (
        list(dict.fromkeys(label for _, label in positive))[:3],
        list(dict.fromkeys(label for _, label in negative))[:3],
    )


def driver_modes(frame: pd.DataFrame, side: str) -> list[str]:
    values: list[str] = []
    for index in range(1, 4):
        column = f"{side}_driver_{index}"
        values.extend(value for value in frame[column].fillna("").astype(str) if value)
    return [name for name, _ in sorted(Counter(values).items(), key=lambda item: (-item[1], item[0]))[:3]]


def build_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    eligible = ledger[ledger["eligible_flag"].map(as_bool)].sort_values("rank")
    rows = []
    for bucket, frame in (("TOP20", eligible.head(20)), ("TOP50", eligible.head(50)), ("ALL_ELIGIBLE", eligible)):
        pos, neg = driver_modes(frame, "positive"), driver_modes(frame, "negative")
        driver_frame = frame[["positive_driver_1", "positive_driver_2", "positive_driver_3", "negative_driver_1", "negative_driver_2", "negative_driver_3"]]
        contains = lambda label: driver_frame.eq(label).any(axis=1).sum()
        row = {
            "bucket": bucket, "row_count": len(frame),
            "avg_final_score": pd.to_numeric(frame["final_score"], errors="coerce").mean(),
            "avg_base_contribution": pd.to_numeric(frame["base_contribution"], errors="coerce").mean(),
            "avg_momentum_contribution": pd.to_numeric(frame["momentum_contribution"], errors="coerce").mean(),
            "avg_component_coverage_ratio": frame["component_coverage_ratio"].mean(),
            "complete_explainability_count": (frame["component_lineage_quality"] == "COMPLETE").sum(),
            "partial_explainability_count": (frame["component_lineage_quality"] != "COMPLETE").sum(),
            "family_component_coverage_count": (frame["family_explainability_status"] != "MISSING").sum(),
            "technical_subfactor_coverage_count": (frame["technical_subfactor_explainability_status"] != "MISSING").sum(),
            "risk_component_coverage_count": (frame["risk_explainability_status"] != "MISSING").sum(),
            "regime_component_coverage_count": (frame["regime_explainability_status"] != "MISSING").sum(),
            "data_trust_component_coverage_count": (frame["data_trust_explainability_status"] != "MISSING").sum(),
            "momentum_led_count": (pd.to_numeric(frame["momentum_contribution"], errors="coerce") >= pd.to_numeric(frame["base_contribution"], errors="coerce")).sum(),
            "base_led_count": (pd.to_numeric(frame["base_contribution"], errors="coerce") > pd.to_numeric(frame["momentum_contribution"], errors="coerce")).sum(),
            "technical_led_count": contains("TECHNICAL_STRONG"),
            "fundamental_led_count": contains("FUNDAMENTAL_STRONG"),
            "risk_warning_count": contains("RISK_PENALTY_HIGH"),
            "overheat_warning_count": contains("OVERHEAT_WARNING"),
            "data_trust_warning_count": contains("DATA_TRUST_WARNING"),
            "regime_headwind_count": contains("REGIME_HEADWIND"),
        }
        row.update({f"top_positive_driver_{i + 1}": value for i, value in enumerate(pos)})
        row.update({f"top_negative_driver_{i + 1}": value for i, value in enumerate(neg)})
        rows.append(row)
    return pd.DataFrame(rows).reindex(columns=SUMMARY_COLUMNS)


def write_validation(output_dir: Path, validation: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([validation]).to_csv(output_dir / VALIDATION_NAME, index=False)


def blocked_validation(
    root: Path, output_dir: Path, generated_at: str, status: str, reason: str,
    paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    paths = paths or {}
    for name, columns in (
        (CATALOG_NAME, CATALOG_COLUMNS), (MAP_NAME, MAP_COLUMNS),
        (LEDGER_NAME, ENRICHMENT_COLUMNS), (SUMMARY_NAME, SUMMARY_COLUMNS),
        (MATRIX_NAME, ["component_name", "expected", "found", "selected", "selected_source_path", "coverage_ratio", "confidence", "status", "warning"]),
    ):
        target = output_dir / name
        if not target.exists():
            pd.DataFrame(columns=columns).to_csv(target, index=False)
    validation = {
        "stage": STAGE, "final_status": status,
        "decision": "BLOCKED_REVIEW_R1_SOURCE_OR_COMPONENT_LINEAGE",
        "generated_at_utc": generated_at, "r1_validation_path": paths.get("r1_validation", ""),
        "r1_ledger_path": paths.get("r1_ledger", ""), "source_ranking_path": paths.get("source", ""),
        "source_ranking_hash": paths.get("hash", ""), "source_ranking_hash_verified": False,
        "lineage_catalog_path": rel(root, output_dir / CATALOG_NAME),
        "selected_lineage_map_path": rel(root, output_dir / MAP_NAME),
        "enriched_ledger_path": rel(root, output_dir / LEDGER_NAME),
        "enriched_summary_path": rel(root, output_dir / SUMMARY_NAME),
        "component_availability_matrix_path": rel(root, output_dir / MATRIX_NAME),
        "ranking_rows": 0, "r1_ledger_rows": 0, "enriched_ledger_rows": 0,
        "eligible_rows": 0, "excluded_rows": 0,
        "total_candidate_component_files_scanned": 0, "usable_component_files": 0,
        "selected_component_count": 0, "selected_family_component_count": 0,
        "selected_technical_subfactor_count": 0, "selected_risk_component_count": 0,
        "selected_regime_component_count": 0, "selected_data_trust_component_count": 0,
        "complete_explainability_count": 0, "partial_explainability_count": 0,
        "avg_component_coverage_ratio": 0, "top20_avg_component_coverage_ratio": 0,
        "top50_avg_component_coverage_ratio": 0, "ambiguous_component_count": 0,
        "date_mismatch_blocked_count": 0, "missing_expected_component_count": len(EXPECTED),
        "duplicate_ticker_count": 0, "row_count_integrity_pass": False,
        "official_mutation": False, "protected_outputs_modified": False,
        "research_only": True, "pass_gate": False, "validation_warning": reason,
    }
    write_validation(output_dir, validation)
    return validation


def run_stage(
    root: Path, r1_validation_override: Path | None = None,
    output_override: Path | None = None, candidate_root_override: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id, generated_at = now_utc()
    try:
        r1_validation_path, r1_ledger_path, r1 = discover_r1(root, r1_validation_override)
    except FileNotFoundError as exc:
        return blocked_validation(root, output_dir, generated_at, "BLOCKED_V21_067_R2_MISSING_R1_OR_SOURCE_RANKING", str(exc))
    source_path = root / str(r1["source_ranking_path"])
    paths = {
        "r1_validation": rel(root, r1_validation_path), "r1_ledger": rel(root, r1_ledger_path),
        "source": rel(root, source_path), "hash": str(r1["source_ranking_hash"]),
    }
    if not source_path.is_file():
        return blocked_validation(root, output_dir, generated_at, "BLOCKED_V21_067_R2_MISSING_R1_OR_SOURCE_RANKING", "R1 source ranking missing", paths)
    actual_hash = sha256(source_path)
    if actual_hash != str(r1["source_ranking_hash"]):
        return blocked_validation(root, output_dir, generated_at, "BLOCKED_V21_067_R2_SOURCE_HASH_MISMATCH", "R1 source ranking SHA-256 mismatch", paths)

    r1_ledger = pd.read_csv(r1_ledger_path, low_memory=False)
    ranking = pd.read_csv(source_path, low_memory=False)
    ticker_col = first_column(list(ranking.columns), ("ticker", "symbol"))
    if not ticker_col:
        return blocked_validation(root, output_dir, generated_at, "BLOCKED_V21_067_R2_COMPONENT_MERGE_INTEGRITY_RISK", "Source ticker column missing", paths)
    tickers = set(ranking[ticker_col].astype(str).str.strip().str.upper())
    ticker_dates, global_date = ranking_dates(ranking)
    protected = protected_files(root, output_dir, [r1_validation_path, r1_ledger_path, source_path])
    before = snapshot(protected)

    scan_root = candidate_root_override if candidate_root_override else root / "outputs/v21"
    if not scan_root.is_absolute():
        scan_root = root / scan_root
    catalog, metadata = scan_catalog(root, scan_root, run_id, generated_at)
    catalog.to_csv(output_dir / CATALOG_NAME, index=False)
    lineage_map, selected, states = select_components(
        root, metadata, tickers, ticker_dates, global_date, run_id, generated_at
    )
    lineage_map.to_csv(output_dir / MAP_NAME, index=False)

    ambiguous_count = sum(status == "AMBIGUOUS_BLOCKED" for status in states.values())
    date_blocked_count = sum(status == "DATE_MISMATCH_BLOCKED" for status in states.values())
    if ambiguous_count:
        matrix = pd.DataFrame([
            {
                "component_name": name, "expected": True,
                "found": states[name] != "MISSING", "selected": name in selected,
                "selected_source_path": rel(root, selected[name]["meta"]["path"]) if name in selected else "",
                "coverage_ratio": selected[name]["coverage_ratio"] if name in selected else 0,
                "confidence": selected[name]["confidence"] if name in selected else "",
                "status": states[name], "warning": selected[name]["warning"] if name in selected else states[name],
            } for name in EXPECTED
        ])
        matrix.to_csv(output_dir / MATRIX_NAME, index=False)
        result = blocked_validation(root, output_dir, generated_at, "BLOCKED_V21_067_R2_COMPONENT_MERGE_INTEGRITY_RISK", "Duplicate same-key conflicting component values", paths)
        result.update({
            "source_ranking_hash_verified": True, "ranking_rows": len(ranking),
            "r1_ledger_rows": len(r1_ledger), "ambiguous_component_count": ambiguous_count,
            "total_candidate_component_files_scanned": len(catalog),
            "usable_component_files": int(catalog["usable_for_merge"].map(as_bool).sum()) if not catalog.empty else 0,
        })
        write_validation(output_dir, result)
        return result

    enriched = r1_ledger.copy()
    enriched["ticker"] = enriched["ticker"].astype(str).str.strip().str.upper()
    for column in (
        "positive_driver_1", "positive_driver_2", "positive_driver_3",
        "negative_driver_1", "negative_driver_2", "negative_driver_3",
        "explainability_quality", "primary_ranking_reason",
    ):
        if column in enriched.columns:
            enriched[column] = enriched[column].astype("object")
    for component, selection in selected.items():
        enriched[component] = enriched["ticker"].map(selection["values"])
    for component in EXPECTED:
        if component not in enriched.columns:
            enriched[component] = pd.NA
    selected_non_base = [name for name in selected if name not in BASE_COMPONENTS]
    enriched["component_coverage_ratio"] = enriched[EXPECTED].notna().sum(axis=1) / len(EXPECTED)
    enriched["selected_component_count"] = enriched[EXPECTED].notna().sum(axis=1)
    for column, names in (
        ("selected_family_component_count", FAMILY_COMPONENTS),
        ("selected_technical_subfactor_count", TECHNICAL_COMPONENTS),
        ("selected_risk_component_count", RISK_COMPONENTS),
        ("selected_regime_component_count", REGIME_COMPONENTS),
        ("selected_data_trust_component_count", TRUST_COMPONENTS),
    ):
        enriched[column] = enriched[names].notna().sum(axis=1)
    enriched["family_explainability_status"] = enriched.apply(lambda row: status_for(row, FAMILY_COMPONENTS), axis=1)
    enriched["technical_subfactor_explainability_status"] = enriched.apply(lambda row: status_for(row, TECHNICAL_COMPONENTS), axis=1)
    enriched["risk_explainability_status"] = enriched.apply(lambda row: status_for(row, RISK_COMPONENTS), axis=1)
    enriched["regime_explainability_status"] = enriched.apply(lambda row: status_for(row, REGIME_COMPONENTS), axis=1)
    enriched["data_trust_explainability_status"] = enriched.apply(lambda row: status_for(row, TRUST_COMPONENTS), axis=1)
    enriched["component_lineage_resolved"] = enriched["selected_component_count"] > 2
    enriched["component_lineage_quality"] = enriched.apply(
        lambda row: "COMPLETE" if int(row["selected_component_count"]) == len(EXPECTED) else "PARTIAL",
        axis=1,
    )
    warnings = [selection["warning"] for selection in selected.values() if selection["warning"]]
    enriched["component_merge_warning"] = "|".join(sorted(set(warnings)))
    for index, row in enriched.iterrows():
        positive, negative = enriched_drivers(row)
        for number in range(3):
            enriched.at[index, f"positive_driver_{number + 1}"] = positive[number] if number < len(positive) else ""
            enriched.at[index, f"negative_driver_{number + 1}"] = negative[number] if number < len(negative) else ""
        enriched.at[index, "explainability_quality"] = row["component_lineage_quality"]
        enriched.at[index, "primary_ranking_reason"] = (
            "ENRICHED_COMPONENT_LINEAGE_PARTIAL" if row["component_lineage_quality"] != "COMPLETE"
            else "ENRICHED_COMPONENT_LINEAGE_COMPLETE"
        )
    enriched.to_csv(output_dir / LEDGER_NAME, index=False)
    summary = build_summary(enriched)
    summary.to_csv(output_dir / SUMMARY_NAME, index=False)

    matrix_rows = []
    for name in EXPECTED:
        selection = selected.get(name)
        matrix_rows.append({
            "component_name": name, "expected": True,
            "found": states[name] != "MISSING", "selected": selection is not None,
            "selected_source_path": rel(root, selection["meta"]["path"]) if selection else "",
            "coverage_ratio": selection["coverage_ratio"] if selection else 0,
            "confidence": selection["confidence"] if selection else "",
            "status": states[name], "warning": selection["warning"] if selection else states[name],
        })
    pd.DataFrame(matrix_rows).to_csv(output_dir / MATRIX_NAME, index=False)

    after = snapshot(protected)
    changed = [path for path, value in before.items() if after.get(path) != value]
    duplicate_count = int(enriched["ticker"].duplicated().sum())
    integrity = len(ranking) == len(r1_ledger) == len(enriched) and duplicate_count <= int(r1_ledger["ticker"].duplicated().sum())
    complete_count = int((enriched["component_lineage_quality"] == "COMPLETE").sum())
    partial_count = len(enriched) - complete_count
    top20 = summary[summary["bucket"] == "TOP20"].iloc[0]
    top50 = summary[summary["bucket"] == "TOP50"].iloc[0]
    selected_additional = len(selected_non_base)
    pass_gate = integrity and selected_additional > 0 and not changed
    if changed:
        final_status = "BLOCKED_V21_067_R2_MUTATION_RISK"
        decision = "BLOCKED_REVIEW_R1_SOURCE_OR_COMPONENT_LINEAGE"
    elif not integrity:
        final_status = "BLOCKED_V21_067_R2_COMPONENT_MERGE_INTEGRITY_RISK"
        decision = "BLOCKED_REVIEW_R1_SOURCE_OR_COMPONENT_LINEAGE"
    elif partial_count or len(selected) < len(EXPECTED):
        final_status = "PARTIAL_PASS_V21_067_R2_COMPONENT_LINEAGE_PARTIAL_EXPLAINABILITY_ENRICHED"
        decision = "COMPONENT_LINEAGE_PARTIAL_EXPLAINABILITY_READY_RESEARCH_ONLY"
    else:
        final_status = "PASS_V21_067_R2_COMPONENT_LINEAGE_RESOLVED_EXPLAINABILITY_ENRICHED"
        decision = "COMPONENT_LINEAGE_RESOLVED_EXPLAINABILITY_READY_RESEARCH_ONLY"
    validation = {
        "stage": STAGE, "final_status": final_status, "decision": decision,
        "generated_at_utc": generated_at, "r1_validation_path": rel(root, r1_validation_path),
        "r1_ledger_path": rel(root, r1_ledger_path), "source_ranking_path": rel(root, source_path),
        "source_ranking_hash": actual_hash, "source_ranking_hash_verified": True,
        "lineage_catalog_path": rel(root, output_dir / CATALOG_NAME),
        "selected_lineage_map_path": rel(root, output_dir / MAP_NAME),
        "enriched_ledger_path": rel(root, output_dir / LEDGER_NAME),
        "enriched_summary_path": rel(root, output_dir / SUMMARY_NAME),
        "component_availability_matrix_path": rel(root, output_dir / MATRIX_NAME),
        "ranking_rows": len(ranking), "r1_ledger_rows": len(r1_ledger),
        "enriched_ledger_rows": len(enriched),
        "eligible_rows": int(enriched["eligible_flag"].map(as_bool).sum()),
        "excluded_rows": int((~enriched["eligible_flag"].map(as_bool)).sum()),
        "total_candidate_component_files_scanned": len(catalog),
        "usable_component_files": int(catalog["usable_for_merge"].map(as_bool).sum()) if not catalog.empty else 0,
        "selected_component_count": len(selected),
        "selected_family_component_count": sum(name in selected for name in FAMILY_COMPONENTS),
        "selected_technical_subfactor_count": sum(name in selected for name in TECHNICAL_COMPONENTS),
        "selected_risk_component_count": sum(name in selected for name in RISK_COMPONENTS),
        "selected_regime_component_count": sum(name in selected for name in REGIME_COMPONENTS),
        "selected_data_trust_component_count": sum(name in selected for name in TRUST_COMPONENTS),
        "complete_explainability_count": complete_count,
        "partial_explainability_count": partial_count,
        "avg_component_coverage_ratio": enriched["component_coverage_ratio"].mean(),
        "top20_avg_component_coverage_ratio": top20["avg_component_coverage_ratio"],
        "top50_avg_component_coverage_ratio": top50["avg_component_coverage_ratio"],
        "ambiguous_component_count": ambiguous_count,
        "date_mismatch_blocked_count": date_blocked_count,
        "missing_expected_component_count": sum(states[name] == "MISSING" for name in EXPECTED),
        "duplicate_ticker_count": duplicate_count,
        "row_count_integrity_pass": integrity, "official_mutation": False,
        "protected_outputs_modified": bool(changed), "research_only": True,
        "pass_gate": pass_gate, "protected_modified_paths": "|".join(changed),
    }
    write_validation(output_dir, validation)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--r1-validation-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--candidate-root", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.r1_validation_path, args.output_dir, args.candidate_root)
    print(f"FINAL_STATUS={result['final_status']}")
    print(f"DECISION={result['decision']}")
    print(f"SELECTED_COMPONENT_COUNT={result['selected_component_count']}")
    print(f"SELECTED_TECHNICAL_SUBFACTOR_COUNT={result['selected_technical_subfactor_count']}")
    print(f"AVG_COMPONENT_COVERAGE_RATIO={result['avg_component_coverage_ratio']}")
    print(f"VALIDATION_SUMMARY={(args.output_dir or OUT_REL) / VALIDATION_NAME}")
    return 1 if str(result["final_status"]).startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
